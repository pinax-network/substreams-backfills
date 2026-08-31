#!/usr/bin/env python3
"""Fail-closed verification for the hermetic Uniswap V3 NPM provider executor."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path


OVERLAY = Path("uniswap-v3/npm-provider-executor/v1")
CONTRACT_PATH = OVERLAY / "contract.json"
CONTRACT_SHA256 = "25604086ecfd97c7885fa013e4f6b9e6fb4f65dc4fdc4399f63708f210fc9e1a"
SEMANTICS_SHA256 = "42be28917cbd73c84911084e17e0869f9655c16a4cec50c8a636aa7b9f021bbe"
PLAN_RUNTIME_SHA256 = "8cd45b0c31994332e75bd25ccd515d961fe0de9d93ac30874f5a17c0f35b6c10"
PLAN_SEMANTICS_SHA256 = "2d305149664b4c1e83d31a21a4131e585e44f8f25636d311ff741b9c437eaa3f"
FIELD_SEMANTICS_V1_SHA256 = "4daa777ce2d14edd8a665a6a1239db8fb78957aa091174fd31f81b2c25136d4e"
STALE_PLAN_DOCUMENTATION_SHA256S = (
    "1468ddf23c3c70a28c77e657cabaa1d91dd074c5927f37b7f3f49812471ec9df",
    "6e80d215e6e8fb22a8b1bf69172f973fb065d6a5605e5cdcb7d69298fbed41c9",
)

README_SHA256 = "b18c748ad4ba25a17c928e3d0995de565c6b026cc50c6ce4fe94dd7b4dc6962a"
ELIGIBILITY_SHA256 = "f6059a6911533b1a1639cf8cdf4270d1be25d7523ec80e517d40f9c3cd74e0e6"
PROVENANCE_SHA256 = "4add272dca8386b8175ec594f9b65d69a6c17b01175137f3999f1ad6c92fd963"
SOURCE_SHA256 = "4e508d1ad5fc5d530b13150185054d731d34a273e336de92351dfc52d94a9651"
HARNESS_SHA256 = "26ea60ae60643a6f0bd415559f425ac27b3416a0ce8d08ad3e0bad4d904c1f68"
MATERIALIZER_SHA256 = "03fac5176b554cdf1e42531eb45d5e50f8718143c8dd8f4309ed2084c45b02f0"

EXPECTED_OVERLAY_FILES = {
    "README.md",
    "contract.json",
    "docs/eligibility.md",
    "docs/provenance.md",
    "npm-provider-executor-v1.json",
    "src/npm_provider_executor.rs",
    "tests/npm_provider_executor.rs",
}

EXPECTED_PLAN_DELTA = {
    "configs/npm-provider-executor-v1.json",
    "src/npm_provider_executor.rs",
    "tests/npm_observation_plan.rs",
    "tests/npm_provider_executor.rs",
}


class VerificationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_plan_verifier(root: Path):
    return load_module(
        root / "scripts/verify-uniswap-v3-npm-observation-plan.py",
        "npm_provider_executor_plan_verifier",
    )


def load_field_verifier(root: Path):
    return load_module(
        root / "scripts/verify-uniswap-v3-segment-field-semantics.py",
        "npm_provider_executor_field_verifier",
    )


def expected_truth() -> dict[str, bool]:
    return {
        "host_provider_executor_implemented": True,
        "all_planned_conservative_observations_evaluated": True,
        "post_fatal_reducer_suffix_evaluated": True,
        "phased_provider_order_enforced": True,
        "exact_plan_resolved_frame_key_equality_enforced": True,
        "certified_joint_reducer_invoked_after_preflight": True,
        "canonical_observation_execution_audit_returned": True,
        "all_eight_npm_segment_profiles_exercised": True,
        "live_provider_authority": False,
        "exact_graph_call_trace_complete": False,
        "exact_graph_ordering_complete": False,
        "flash_integration_complete": False,
        "factory_pool_combined_schedule_implemented": False,
        "dynamic_datasource_stage_order_implemented": False,
        "post_fatal_graph_execution_modeled": False,
        "entity_changes_or_block_changes_implemented": False,
        "output_or_store_or_graph_out_implemented": False,
        "package_consumes_executor": False,
        "checkpoint_or_graph_block_success_authorized": False,
        "boundary_state_continuity_complete": False,
        "physical_parity_complete": False,
        "poi_parity_complete": False,
        "backfill_ready": False,
        "production_ready": False,
    }


def expected_dependencies() -> dict[str, dict[str, str]]:
    return {
        "npm_observation_plan_runtime": {
            "path": "uniswap-v3/npm-observation-plan/contract-v1.json",
            "contract_version": "uniswap-v3-npm-observation-plan-runtime/v1",
            "raw_sha256": PLAN_RUNTIME_SHA256,
        },
        "npm_observation_plan_semantics": {
            "path": "uniswap-v3/npm-observation-plan/npm-observation-plan-v1.json",
            "contract_version": "uniswap-v3-npm-observation-plan/v1",
            "raw_sha256": PLAN_SEMANTICS_SHA256,
        },
        "selected_npm_flash_field_semantics_v1": {
            "path": "uniswap-v3/segment-field-semantics/v1/contract.json",
            "contract_version": "uniswap-v3-segment-field-semantics/v1",
            "raw_sha256": FIELD_SEMANTICS_V1_SHA256,
        },
    }


def expected_artifacts() -> dict[str, dict[str, str]]:
    return {
        "readme": {"path": f"{OVERLAY}/README.md", "sha256": README_SHA256},
        "eligibility": {"path": f"{OVERLAY}/docs/eligibility.md", "sha256": ELIGIBILITY_SHA256},
        "provenance": {"path": f"{OVERLAY}/docs/provenance.md", "sha256": PROVENANCE_SHA256},
        "semantics": {"path": f"{OVERLAY}/npm-provider-executor-v1.json", "sha256": SEMANTICS_SHA256},
        "source": {"path": f"{OVERLAY}/src/npm_provider_executor.rs", "sha256": SOURCE_SHA256},
        "harness": {"path": f"{OVERLAY}/tests/npm_provider_executor.rs", "sha256": HARNESS_SHA256},
        "materializer": {
            "path": "scripts/materialize-uniswap-v3-npm-provider-executor.sh",
            "sha256": MATERIALIZER_SHA256,
        },
    }


def load_contract(root: Path) -> dict[str, object]:
    path = root / CONTRACT_PATH
    require(path.is_file(), "provider-executor runtime contract missing")
    require(sha256(path) == CONTRACT_SHA256, "provider-executor runtime contract raw digest drift")
    contract = json.loads(path.read_text())
    require(
        set(contract)
        == {
            "format_version",
            "contract_version",
            "mode",
            "ordered_materialization",
            "direct_dependencies",
            "repository_artifacts",
            "materialized_runtime_artifacts",
            "host_contract",
            "package_contract",
            "truth_boundary",
        },
        "provider-executor runtime field set drift",
    )
    require(contract["format_version"] == 1, "runtime format drift")
    require(
        contract["contract_version"] == "uniswap-v3-npm-provider-executor-runtime/v1",
        "runtime contract version drift",
    )
    require(contract["mode"] == "host-diagnostic-only", "runtime mode drift")
    require(contract["direct_dependencies"] == expected_dependencies(), "direct dependency set drift")
    require(contract["repository_artifacts"] == expected_artifacts(), "repository artifact inventory drift")
    for artifact in expected_artifacts().values():
        require(sha256(root / artifact["path"]) == artifact["sha256"], f"artifact digest drift: {artifact['path']}")
    require(contract["truth_boundary"] == expected_truth(), "runtime truth boundary promoted")
    host = contract["host_contract"]
    require(host["accepted_provider_authority"] == "HermeticFixture", "provider authority widened")
    require(
        host["phase_order"] == ["Position", "Pool", "Token", "Preflight", "Reduction"],
        "provider phase order drift",
    )
    for key in (
        "provider_constructs_observation_keys",
        "provider_payload_in_audit_or_error",
        "substreams_handler",
        "manifest_module",
        "live_provider_adapter",
        "checkpoint_authority",
    ):
        require(host[key] is False, f"host authority promoted: {key}")
    package = contract["package_contract"]
    require(package["module_count"] == 23, "package module count drift")
    for key in (
        "executor_substreams_module",
        "manifests_changed_from_writer_runtime",
        "runtime_protobuf_descriptors_changed_from_writer_runtime",
    ):
        require(package[key] is False, f"package authority promoted: {key}")
    require(package["writer_wasm_identical"] is True, "writer WASM identity weakened")
    require(package["writer_packages_identical"] is True, "writer package identity weakened")
    return contract


def load_semantics(root: Path) -> dict[str, object]:
    path = root / OVERLAY / "npm-provider-executor-v1.json"
    require(path.is_file(), "provider-executor semantics missing")
    require(sha256(path) == SEMANTICS_SHA256, "provider-executor semantic raw digest drift")
    semantics = json.loads(path.read_text())
    require(semantics["format_version"] == 1, "semantic format drift")
    require(semantics["contract_version"] == "uniswap-v3-npm-provider-executor/v1", "semantic version drift")
    require(semantics["mode"] == "host-diagnostic-only", "semantic mode drift")
    require(semantics["direct_dependencies"] == expected_dependencies(), "semantic direct dependency drift")
    require(semantics["truth_boundary"] == expected_truth(), "semantic truth boundary promoted")
    execution = semantics["execution_contract"]
    require(
        execution["phase_order"]
        == [
            "all canonical Position requests",
            "derive the closed plan",
            "all canonical Pool requests",
            "all ordinal-scoped canonical Token requests",
            "exact-key preflight",
            "certified joint reduction",
        ],
        "semantic phase order drift",
    )
    require(execution["audit_name"] == "canonical conservative request-evaluation trace", "audit terminology drift")
    require(
        execution["provider_error_handling"]
        == "provider error payloads are discarded; only a sanitized error kind, phase, "
        "and optional canonical request index appear in the host error",
        "provider error truth boundary drift",
    )
    for key in ("canonical_wire_schema_added", "provider_status_serialized", "provider_error_payload_serialized"):
        require(execution[key] is False, f"provider payload/schema promoted: {key}")
    return semantics


def verify_dependencies(root: Path, plan, field) -> tuple[object, object, object, object]:
    require(plan.CONTRACT_SHA256 == PLAN_RUNTIME_SHA256, "loaded observation-plan runtime digest drift")
    require(plan.SEMANTICS_SHA256 == PLAN_SEMANTICS_SHA256, "loaded observation-plan semantic digest drift")
    plan_contract = plan.load_contract(root)
    plan.load_semantics(root)
    resolved = plan.load_resolved_verifier(root)
    _, joint, writer = plan.verify_upstream(root, resolved)
    plan.verify_proto(root, plan_contract)
    plan.verify_overlay_static(root)
    require(field.raw_sha256(root / field.CONTRACT_PATH) == FIELD_SEMANTICS_V1_SHA256, "field-semantics v1 digest drift")
    field.verify_contract(root)
    provenance = (root / "uniswap-v3/npm-observation-plan/docs/provenance.md").read_text()
    require(PLAN_SEMANTICS_SHA256 in provenance, "observation-plan documentation digest missing")
    for stale in STALE_PLAN_DOCUMENTATION_SHA256S:
        require(stale not in provenance, "stale observation-plan documentation digest retained")
    return resolved, joint, writer, plan_contract


def verify_overlay_static(root: Path) -> None:
    overlay = root / OVERLAY
    files = {path.relative_to(overlay).as_posix() for path in overlay.rglob("*") if path.is_file()}
    require(files == EXPECTED_OVERLAY_FILES, f"provider-executor overlay file set drift: {sorted(files)}")
    require(not (overlay / "evidence").exists(), "eligibility escaped docs directory")
    require(not (overlay / "provenance").exists(), "provenance escaped docs directory")
    source = (overlay / "src/npm_provider_executor.rs").read_text()
    compact = re.sub(r"\s+", "", source)
    for required in (
        "pubtraitNpmObservationProvider",
        "ProviderAuthority::HermeticFixture",
        "pubfnexecute_npm_provider",
        "plan_position_observations(source,initial,call_scope)",
        "complete_observation_plan(position_phase,positions)",
        "preflight_resolved_frame(complete,pools,tokens)",
        "reduce_preflighted_npm_frame(initial,preflighted)",
        "provider.resolve_position(&scope,request)",
        "provider.resolve_pool(&scope,request)",
        "provider.resolve_token(&scope,request)",
        "canonicalconservativerequest-evaluationtrace",
        "Err(_)=>Err(error(ExecutionErrorKind::ProviderError",
        "ProviderResolution::PossibleReorg",
        "ProviderResolution::Unknown",
        "CapturedPositionResult::None",
        "CapturedPoolResult::None",
        "CapturedTokenResult::Missing",
        "audit.canonical_sha256=canonical_audit_sha256(&audit)",
    ):
        require(required in compact, f"provider-executor source evidence missing: {required}")
    position = compact.index("for(index,request)inposition_requests.iter().enumerate()")
    pool = compact.index("for(index,request)inplan.pool_requests.iter().enumerate()")
    token = compact.index("for(index,request)inplan.token_requests.iter().enumerate()")
    preflight = compact.index("letpreflighted=preflight_resolved_frame")
    reducer = compact.index("let(reduction,coverage)=reduce_preflighted_npm_frame")
    require(position < pool < token < preflight < reducer, "provider/reducer phase order drift")
    for forbidden in (
        "#[substreams::handlers",
        "pub fn graph_out",
        "substreams_ethereum::rpc",
        "reqwest",
        "tokio_postgres",
        "sqlx",
        "StoreSet",
        "StoreAdd",
    ):
        require(forbidden not in source, f"forbidden provider-executor linkage: {forbidden}")
    harness = (overlay / "tests/npm_provider_executor.rs").read_text()
    tests = {
        "all_eight_segments_execute_their_selected_profiles",
        "full_suffix_is_evaluated_before_fatal_reducer_projection",
        "repeated_interleaved_and_transfer_only_blocks_use_strict_phase_order",
        "resolved_none_and_missing_are_not_unstable_results",
        "unstable_and_error_results_abort_with_sanitized_identity_only",
        "exact_eip1898_and_number_fallback_scopes_reach_every_request",
        "authority_and_scope_refusals_happen_before_provider_calls",
        "immutable_block_start_identity_drives_derived_token_requests",
        "audit_binds_exact_consumption_maxima_and_is_deterministic",
        "executor_binds_only_selected_v1_and_keeps_broad_authority_false",
    }
    require({name for name in tests if f"fn {name}()" in harness} == tests, "Rust executor test inventory drift")
    materializer = (root / "scripts/materialize-uniswap-v3-npm-provider-executor.sh").read_text()
    for required in (
        "materialize-uniswap-v3-npm-observation-plan.sh",
        'rm "$destination/tests/npm_observation_plan.rs"',
        "npm_provider_executor.rs",
        "npm-provider-executor-v1.json",
        "npm_provider_executor.rs",
        "verify-uniswap-v3-npm-provider-executor.py",
    ):
        require(required in materializer, f"provider-executor materializer evidence missing: {required}")


def materialize_expected(root: Path, destination: Path, plan=None, resolved=None, joint=None, writer=None) -> None:
    plan = plan or load_plan_verifier(root)
    resolved = resolved or plan.load_resolved_verifier(root)
    joint = joint or resolved.load_joint_verifier(root)
    writer = writer or joint.load_writer_verifier(root)
    plan.materialize_expected(root, destination, resolved, joint, writer)
    (destination / "tests/npm_observation_plan.rs").unlink()
    copies = {
        f"{OVERLAY}/src/npm_provider_executor.rs": "src/npm_provider_executor.rs",
        f"{OVERLAY}/npm-provider-executor-v1.json": "configs/npm-provider-executor-v1.json",
        f"{OVERLAY}/tests/npm_provider_executor.rs": "tests/npm_provider_executor.rs",
    }
    for source, target in copies.items():
        shutil.copy2(root / source, destination / target)


def changed_files(baseline: dict[str, Path], candidate: dict[str, Path]) -> set[str]:
    return {
        relative
        for relative in set(baseline) | set(candidate)
        if relative not in baseline
        or relative not in candidate
        or baseline[relative].read_bytes() != candidate[relative].read_bytes()
        or bool(baseline[relative].stat().st_mode & 0o111) != bool(candidate[relative].stat().st_mode & 0o111)
    }


def verify_runtime(root: Path, runtime: Path, contract: dict[str, object], plan, resolved, joint, writer) -> Path:
    require(runtime.is_dir(), f"provider-executor runtime missing: {runtime}")
    with tempfile.TemporaryDirectory(prefix="npm-provider-executor-expected-") as temporary:
        temporary_path = Path(temporary)
        baseline = temporary_path / "plan"
        expected = temporary_path / "executor"
        plan.materialize_expected(root, baseline, resolved, joint, writer)
        materialize_expected(root, expected, plan, resolved, joint, writer)
        baseline_files = writer.non_build_files(baseline)
        expected_files = writer.non_build_files(expected)
        runtime_files = writer.non_build_files(runtime)
        require(
            changed_files(baseline_files, expected_files) == EXPECTED_PLAN_DELTA,
            f"runtime delta from observation plan drift: {sorted(changed_files(baseline_files, expected_files))}",
        )
        require(set(runtime_files) == set(expected_files), "provider-executor runtime file set drift")
        for relative, expected_path in expected_files.items():
            actual = runtime_files[relative]
            require(actual.read_bytes() == expected_path.read_bytes(), f"runtime content drift: {relative}")
            require(
                bool(actual.stat().st_mode & 0o111) == bool(expected_path.stat().st_mode & 0o111),
                f"runtime mode drift: {relative}",
            )
        for relative, baseline_path in baseline_files.items():
            if relative == "tests/npm_observation_plan.rs":
                continue
            require(runtime_files[relative].read_bytes() == baseline_path.read_bytes(), f"plan/writer artifact changed: {relative}")
    for relative, digest in contract["materialized_runtime_artifacts"].items():
        require(sha256(runtime / relative) == digest, f"materialized artifact digest drift: {relative}")
    require(not (runtime / "tests/npm_observation_plan.rs").exists(), "superseded observation-plan harness retained")
    require(not (runtime / "proto/uniswap/npm/plan").exists(), "host-only plan protobuf entered runtime descriptor tree")
    lib = (runtime / "src/lib.rs").read_text()
    require("npm_provider_executor" not in lib, "host-only executor linked into runtime lib")
    return runtime / "target/wasm32-unknown-unknown/release/substreams_uniswap_v3.wasm"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--writer-runtime", type=Path)
    parser.add_argument("--mainnet-spkg", type=Path)
    parser.add_argument("--base-spkg", type=Path)
    parser.add_argument("--writer-mainnet-spkg", type=Path)
    parser.add_argument("--writer-base-spkg", type=Path)
    args = parser.parse_args()
    if bool(args.mainnet_spkg) != bool(args.base_spkg):
        parser.error("--mainnet-spkg and --base-spkg must be passed together")
    if bool(args.writer_mainnet_spkg) != bool(args.writer_base_spkg):
        parser.error("--writer-mainnet-spkg and --writer-base-spkg must be passed together")
    if args.mainnet_spkg and not args.runtime:
        parser.error("package checks require --runtime")
    if args.writer_mainnet_spkg and not args.mainnet_spkg:
        parser.error("writer package comparison requires executor package arguments")
    if args.writer_runtime and not args.runtime:
        parser.error("writer-runtime comparison requires --runtime")

    root = args.root.resolve()
    contract = load_contract(root)
    load_semantics(root)
    plan = load_plan_verifier(root)
    field = load_field_verifier(root)
    resolved, joint, writer, _ = verify_dependencies(root, plan, field)
    verify_overlay_static(root)

    runtime_wasm = None
    if args.runtime is not None:
        runtime_wasm = verify_runtime(root, args.runtime.resolve(), contract, plan, resolved, joint, writer)
    if args.writer_runtime is not None:
        writer_wasm = writer.verify_runtime(
            root,
            args.writer_runtime.resolve(),
            writer.load_runtime_contract(root),
        )
        require(runtime_wasm is not None and runtime_wasm.is_file(), "provider-executor runtime WASM missing")
        require(writer_wasm.is_file(), "writer runtime WASM missing")
        require(runtime_wasm.read_bytes() == writer_wasm.read_bytes(), "provider executor changed writer WASM")
    packages = (args.mainnet_spkg, args.base_spkg)
    writer_packages = (args.writer_mainnet_spkg, args.writer_base_spkg)
    require(all(value is None for value in packages) or all(value is not None for value in packages), "pass both executor packages")
    require(
        all(value is None for value in writer_packages) or all(value is not None for value in writer_packages),
        "pass both writer packages",
    )
    if all(value is not None for value in packages):
        require(runtime_wasm is not None and runtime_wasm.is_file(), "package verification requires built runtime WASM")
        package_map = {"mainnet": args.mainnet_spkg.resolve(), "base": args.base_spkg.resolve()}
        writer_map = None
        if all(value is not None for value in writer_packages):
            writer_map = {
                "mainnet": args.writer_mainnet_spkg.resolve(),
                "base": args.writer_base_spkg.resolve(),
            }
        plan.verify_packages(resolved, writer, runtime_wasm, package_map, writer_map)

    print(
        "verified phased hermetic NPM provider execution, full-suffix evaluation, exact preflight, "
        "canonical conservative request-evaluation audit, and unchanged writer artifacts"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"verification failed: {error}", file=sys.stderr)
        raise SystemExit(1)
