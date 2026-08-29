#!/usr/bin/env python3
"""Fail-closed verification for the host-only Uniswap V3 NPM observation plan."""

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


OVERLAY = Path("uniswap-v3/npm-observation-plan")
CONTRACT_PATH = OVERLAY / "contract-v1.json"
CONTRACT_SHA256 = "0ba6d02e3569a11ab1f5c45293e1f33b2d4d7a6f50668bae2e8590d9a65c007e"
SEMANTICS_SHA256 = "6e80d215e6e8fb22a8b1bf69172f973fb065d6a5605e5cdcb7d69298fbed41c9"
RESOLVED_RUNTIME_SHA256 = "c5ad1556273b0c532f8d00e27c257250b596d022dc25dc4f9443c429303c0a1a"
RESOLVED_SEMANTICS_SHA256 = "01f7e87b22f52d84f8bb2fe806e963ecfb9dc196ab29804baee4c156eabbdbd9"
RESOLVED_PROTO_SHA256 = "e4859b67d590b1bcd2ce2d51ef90775c3729002300269a61b49d4bc31df6b299"
RESOLVED_BINDING_SHA256 = "d7979c2e98750c8fa1a5fbe4efcb11d7033e5b12b9c239a13963d20f485f3b66"
RESOLVED_SOURCE_SHA256 = "24fe3e9f7f94f156782394b5fc48407735cad2127ad9eec5bb9572fee35c4650"
RESOLVED_HARNESS_SHA256 = "b549e08bba3bef8ae18f6f0440a01efad0c811b2cfde50652446fd2dfd1a8f94"
SOURCE_RUNTIME_SHA256 = "701e83d3833356cff75ad4455553894e7695fb9f75f03e7c53eaa3da616b57d5"
JOINT_RUNTIME_SHA256 = "6f46d5cca49506c3ee0622351324ccb62a459916f0e41f3772fe021e0e185dd6"
JOINT_SEMANTICS_SHA256 = "86cf89d8ffe66ac9f4aeda468988306ccc9dca1dbfd2641f132f12529207b143"
WRITER_RUNTIME_SHA256 = "765806bf19fca7695ef4d97f557593e4f791759589fe55c20f18c6523a5d07ca"
WRITER_PROFILE_SHA256 = "2b6635c061a7a0bfce39430c71c41dacc1567f095fe41134e890a697aa27f823"
WRITER_COMPATIBILITY_SHA256 = "259481724561d5aa725c17f90b5a19ea93ad6f7cd6074cf2cb8a8661c39f81c4"
SEGMENT_MATRIX_SHA256 = "7f6d1a34a8c885fe5ddcd81895818ba7ae8a0d736d541b881c1cc7cd54275161"
EXECUTION_ORDER_SHA256 = "241e970cfcec4d76610b29a10141d3bff2512d80454a6308594f3db23621cde2"

README_SHA256 = "f1ec3cb87a9dfba8cbef864252927506465cf7cd52c47b5ca52929ff691b0527"
ELIGIBILITY_SHA256 = "fb28b06ed8ba2808a4a167e49e6a59f75e1626943dca8cafaaea41684c9b579d"
PROVENANCE_SHA256 = "6e5556b6e29639a2cb53be897b2b5730bad13f738340a23659eb8ab1466577be"
PROTO_SHA256 = "20f983a984aa732c9ae9950f193428d45d212b168b840964af0823e5fce7092a"
BINDING_SHA256 = "5a69fd0772ca4c2166e37f8afbb00727bbb8a4a5304c3bdd6dcab4db71a819c5"
SOURCE_CODE_SHA256 = "f3f854992b262e87c4fef3fbc660a2b0c2ffa8a87344848a6421b6ad3602dc36"
HARNESS_SHA256 = "8bd218ad3d8fbf2e5cb64232698f8e12c273d45a5eff8dcca05b8250a55180fa"
MATERIALIZER_SHA256 = "85d4b77762f319712ef43baeb1697b4be1272fd217a4da90079f71d725a9bd8c"

EXPECTED_OVERLAY_FILES = {
    "README.md",
    "contract-v1.json",
    "docs/eligibility.md",
    "docs/provenance.md",
    "npm-observation-plan-v1.json",
    "proto/uniswap/npm/plan/v1/npm_observation_plan.proto",
    "src/npm_observation_plan.rs",
    "src/uniswap.npm.plan.v1.rs",
    "tests/npm_observation_plan.rs",
}

EXPECTED_RESOLVED_DELTA = {
    "configs/npm-observation-plan-v1.json",
    "src/npm_observation_plan.rs",
    "src/uniswap.npm.plan.v1.rs",
    "tests/npm_resolved_inputs.rs",
    "tests/npm_observation_plan.rs",
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


def load_resolved_verifier(root: Path):
    return load_module(
        root / "scripts/verify-uniswap-v3-npm-resolved-inputs.py",
        "npm_observation_plan_resolved_verifier",
    )


def expected_truth() -> dict[str, bool]:
    return {
        "host_observation_plan_implemented": True,
        "complete_conservative_npm_request_closure": True,
        "post_fatal_writer_event_suffix_in_plan": True,
        "exact_plan_resolved_frame_key_equality_enforced": True,
        "all_planned_rows_resolved_before_certified_reducer_path": True,
        "all_eight_npm_segment_profiles_bound": True,
        "integrated_provider_executor_added": False,
        "all_required_observations_evaluated": False,
        "exact_graph_call_trace_complete": False,
        "post_fatal_execution_modeled": False,
        "graph_execution_trace_complete": False,
        "factory_pool_combined_schedule_implemented": False,
        "dynamic_datasource_stage_order_implemented": False,
        "entity_changes_or_block_changes_implemented": False,
        "checkpoint_or_graph_block_success_authorized": False,
        "boundary_state_continuity_complete": False,
        "physical_parity_complete": False,
        "poi_parity_complete": False,
        "backfill_ready": False,
        "production_ready": False,
    }


def expected_repository_artifacts() -> dict[str, tuple[str, str, str | None]]:
    return {
        "readme": ("uniswap-v3/npm-observation-plan/README.md", README_SHA256, None),
        "eligibility": (
            "uniswap-v3/npm-observation-plan/docs/eligibility.md",
            ELIGIBILITY_SHA256,
            None,
        ),
        "provenance": (
            "uniswap-v3/npm-observation-plan/docs/provenance.md",
            PROVENANCE_SHA256,
            None,
        ),
        "semantics": (
            "uniswap-v3/npm-observation-plan/npm-observation-plan-v1.json",
            SEMANTICS_SHA256,
            "uniswap-v3-npm-observation-plan/v1",
        ),
        "plan_proto": (
            "uniswap-v3/npm-observation-plan/proto/uniswap/npm/plan/v1/npm_observation_plan.proto",
            PROTO_SHA256,
            None,
        ),
        "plan_binding": (
            "uniswap-v3/npm-observation-plan/src/uniswap.npm.plan.v1.rs",
            BINDING_SHA256,
            None,
        ),
        "plan_source": (
            "uniswap-v3/npm-observation-plan/src/npm_observation_plan.rs",
            SOURCE_CODE_SHA256,
            None,
        ),
        "combined_harness": (
            "uniswap-v3/npm-observation-plan/tests/npm_observation_plan.rs",
            HARNESS_SHA256,
            None,
        ),
        "materializer": (
            "scripts/materialize-uniswap-v3-npm-observation-plan.sh",
            MATERIALIZER_SHA256,
            None,
        ),
        "resolved_input_runtime": (
            "uniswap-v3/npm-resolved-inputs/contract-v1.json",
            RESOLVED_RUNTIME_SHA256,
            "uniswap-v3-npm-resolved-inputs-runtime/v1",
        ),
        "resolved_input_semantics": (
            "uniswap-v3/npm-resolved-inputs/npm-resolved-inputs-v1.json",
            RESOLVED_SEMANTICS_SHA256,
            "uniswap-v3-npm-resolved-inputs/v1",
        ),
        "resolved_input_proto": (
            "uniswap-v3/npm-resolved-inputs/proto/uniswap/npm/inputs/v1/npm_resolved_inputs.proto",
            RESOLVED_PROTO_SHA256,
            None,
        ),
        "resolved_input_binding": (
            "uniswap-v3/npm-resolved-inputs/src/uniswap.npm.inputs.v1.rs",
            RESOLVED_BINDING_SHA256,
            None,
        ),
        "resolved_input_source": (
            "uniswap-v3/npm-resolved-inputs/src/npm_resolved_inputs.rs",
            RESOLVED_SOURCE_SHA256,
            None,
        ),
        "resolved_input_harness": (
            "uniswap-v3/npm-resolved-inputs/tests/npm_resolved_inputs.rs",
            RESOLVED_HARNESS_SHA256,
            None,
        ),
    }


def expected_materialized_artifacts() -> dict[str, str]:
    return {
        "configs/npm-observation-plan-v1.json": SEMANTICS_SHA256,
        "configs/npm-resolved-inputs-v1.json": RESOLVED_SEMANTICS_SHA256,
        "src/lib.rs": "91a2330a1a1016ab00fae61e8d25fde244591159ab4efd848ecc08b2623aca63",
        "src/npm_resolved_inputs.rs": RESOLVED_SOURCE_SHA256,
        "src/uniswap.npm.inputs.v1.rs": RESOLVED_BINDING_SHA256,
        "src/npm_observation_plan.rs": SOURCE_CODE_SHA256,
        "src/uniswap.npm.plan.v1.rs": BINDING_SHA256,
        "tests/npm_observation_plan.rs": HARNESS_SHA256,
    }


def load_contract(root: Path) -> dict[str, object]:
    path = root / CONTRACT_PATH
    require(path.is_file(), "observation-plan runtime contract missing")
    require(sha256(path) == CONTRACT_SHA256, "observation-plan runtime contract raw digest drift")
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
            "protobuf_contract",
            "host_contract",
            "package_contract",
            "truth_boundary",
        },
        "observation-plan runtime contract",
    )
    require(contract["format_version"] == 1, "runtime format drift")
    require(
        contract["contract_version"] == "uniswap-v3-npm-observation-plan-runtime/v1",
        "runtime contract version drift",
    )
    require(contract["mode"] == "host-diagnostic-only", "runtime mode drift")
    require(
        contract["ordered_materialization"]
        == [
            {
                "path": "uniswap-v3/npm-resolved-inputs/contract-v1.json",
                "contract_version": "uniswap-v3-npm-resolved-inputs-runtime/v1",
                "sha256": RESOLVED_RUNTIME_SHA256,
            },
            {
                "path": "uniswap-v3/npm-observation-plan/npm-observation-plan-v1.json",
                "contract_version": "uniswap-v3-npm-observation-plan/v1",
                "sha256": SEMANTICS_SHA256,
            },
        ],
        "ordered materialization drift",
    )
    artifacts = contract["repository_artifacts"]
    require(set(artifacts) == set(expected_repository_artifacts()), "repository artifact inventory drift")
    for name, (relative, digest, version) in expected_repository_artifacts().items():
        expected = {"path": relative, "sha256": digest}
        if version is not None:
            expected["contract_version"] = version
        require(artifacts[name] == expected, f"repository artifact metadata drift: {name}")
        require(sha256(root / relative) == digest, f"repository artifact content drift: {relative}")
    require(
        contract["materialized_runtime_artifacts"] == expected_materialized_artifacts(),
        "materialized artifact inventory drift",
    )
    require(contract["truth_boundary"] == expected_truth(), "runtime truth boundary promoted")
    host = contract["host_contract"]
    for key in (
        "provider_status_serialized",
        "provider_errors_serialized",
        "substreams_handler",
        "manifest_module",
        "database_or_provider_integration",
        "checkpoint_authority",
    ):
        require(host[key] is False, f"host authority promoted: {key}")
    package = contract["package_contract"]
    require(package["module_count"] == 23, "package module count drift")
    for key in (
        "observation_plan_substreams_module",
        "manifests_changed_from_writer_runtime",
        "runtime_protobuf_descriptors_changed_from_writer_runtime",
    ):
        require(package[key] is False, f"package authority promoted: {key}")
    require(package["writer_wasm_identical"] is True, "writer WASM identity weakened")
    require(package["writer_packages_identical"] is True, "writer package identity weakened")
    return contract


def load_semantics(root: Path) -> dict[str, object]:
    path = root / OVERLAY / "npm-observation-plan-v1.json"
    require(path.is_file(), "observation-plan semantics missing")
    require(sha256(path) == SEMANTICS_SHA256, "observation-plan semantic raw digest drift")
    semantics = json.loads(path.read_text())
    require(semantics["format_version"] == 1, "semantic format drift")
    require(
        semantics["contract_version"] == "uniswap-v3-npm-observation-plan/v1",
        "semantic contract version drift",
    )
    require(semantics["mode"] == "host-diagnostic-only", "semantic mode drift")
    expected_bindings = {
        "source_resolved_input_runtime_sha256": RESOLVED_RUNTIME_SHA256,
        "source_resolved_input_semantics_sha256": RESOLVED_SEMANTICS_SHA256,
        "source_npm_source_runtime_sha256": SOURCE_RUNTIME_SHA256,
        "source_npm_handler_reducer_runtime_sha256": JOINT_RUNTIME_SHA256,
        "source_npm_handler_reducer_semantics_sha256": JOINT_SEMANTICS_SHA256,
        "source_writer_runtime_sha256": WRITER_RUNTIME_SHA256,
        "source_writer_profiles_sha256": WRITER_PROFILE_SHA256,
        "source_writer_compatibility_sha256": WRITER_COMPATIBILITY_SHA256,
        "source_segment_matrix_sha256": SEGMENT_MATRIX_SHA256,
        "source_execution_order_sha256": EXECUTION_ORDER_SHA256,
    }
    require(
        {key: semantics.get(key) for key in expected_bindings} == expected_bindings,
        "semantic upstream binding drift",
    )
    require(semantics["truth_boundary"] == expected_truth(), "semantic truth boundary promoted")
    require(semantics["planning_contract"]["provider_failure_payload_serialized"] is False, "failure payload serialized")
    require(semantics["planning_contract"]["provider_status_serialized"] is False, "provider status serialized")
    require(
        semantics["planning_contract"]["multiplicity"]
        == "Position and Pool maximum reducer consumption is exactly one per unique block-scoped cache key; Token maximum consumption is the role count for each ordinal/address key",
        "planned multiplicity contract drift",
    )
    require(
        semantics["preflight_contract"]["resolution"]
        == "the call scope must pass the upstream payload-free Resolved gate before planning and every planned row must pass it before frame construction; PossibleReorg and Unknown abort",
        "resolution-gate contract drift",
    )
    return semantics


def verify_upstream(root: Path, resolved) -> tuple[object, object, object]:
    require(resolved.CONTRACT_SHA256 == RESOLVED_RUNTIME_SHA256, "loaded resolved runtime digest drift")
    require(resolved.SEMANTICS_SHA256 == RESOLVED_SEMANTICS_SHA256, "loaded resolved semantic digest drift")
    source = resolved.load_source_verifier(root)
    joint = resolved.load_joint_verifier(root)
    writer = joint.load_writer_verifier(root)
    resolved.load_contract(root)
    resolved.load_semantics(root)
    resolved.verify_upstream(root, source, joint, writer)
    resolved.verify_proto(root, resolved.load_contract(root))
    resolved.verify_overlay_static(root)
    return source, joint, writer


def verify_proto(root: Path, contract: dict[str, object]) -> None:
    proto = (root / OVERLAY / "proto/uniswap/npm/plan/v1/npm_observation_plan.proto").read_text()
    binding = (root / OVERLAY / "src/uniswap.npm.plan.v1.rs").read_text()
    descriptor = contract["protobuf_contract"]
    require(descriptor["namespace"] == "uniswap.npm.plan.v1", "plan protobuf namespace drift")
    require(descriptor["repository_only"] is True, "plan protobuf repository-only gate drift")
    require(descriptor["copied_into_runtime_proto_directory"] is False, "runtime descriptor gate promoted")
    require(descriptor["provider_status_or_errors_serialized"] is False, "provider payload entered schema contract")
    for item in (
        'import "uniswap/npm/inputs/v1/npm_resolved_inputs.proto";',
        "message NpmObservationPlan",
        "bytes source_frame_sha256 = 1;",
        "bytes planning_state_sha256 = 2;",
        "ResolvedCallScope call_scope = 3;",
        "repeated PositionRequest position_requests = 10;",
        "repeated PoolRequest pool_requests = 11;",
        "repeated TokenRequest token_requests = 12;",
        "uint32 expected_consumption_count = 5;",
        "uint32 expected_consumption_count = 7;",
        "uint32 expected_consumption_count = 4;",
    ):
        require(item in proto, f"plan protobuf evidence missing: {item}")
    for item in (
        "super::super::inputs::v1::ResolvedCallScope",
        "pub struct NpmObservationPlan",
        "pub struct PositionRequest",
        "pub struct PoolRequest",
        "pub struct TokenRequest",
        '#[prost(message, repeated, tag = "10")]',
        '#[prost(message, repeated, tag = "11")]',
        '#[prost(message, repeated, tag = "12")]',
    ):
        require(item in binding, f"plan binding evidence missing: {item}")
    schema = f"{proto}\n{binding}".lower()
    for item in (
        "provider_status =",
        "provider_error =",
        "error_message =",
        "endpoint =",
        "retry_count =",
        "pub provider_status:",
        "pub provider_error:",
        "pub error_message:",
        "pub endpoint:",
        "pub retry_count:",
    ):
        require(item not in schema, f"provider/runtime field entered canonical plan: {item}")


def verify_overlay_static(root: Path) -> None:
    overlay = root / OVERLAY
    files = {path.relative_to(overlay).as_posix() for path in overlay.rglob("*") if path.is_file()}
    require(files == EXPECTED_OVERLAY_FILES, f"observation-plan overlay file set drift: {sorted(files)}")
    source = (overlay / "src/npm_observation_plan.rs").read_text()
    compact = re.sub(r"\s+", "", source)
    for required in (
        "pubfnplan_position_observations(",
        "pubfncomplete_observation_plan(",
        "pubfnpreflight_resolved_frame(",
        "pubfnreduce_preflighted_npm_frame(",
        "call_scope:Gated<CapturedCallScope>",
        "ResolvedPlanningCallScope",
        "call_scope.resolved_value_mut().cloned()",
        "structPreflightedResolvedFrame{frame:NpmResolvedInputs,plan:NpmObservationPlan,}",
        "crate::npm_source_block::validate_npm_source_block(source)",
        "require_exact_position_keys",
        "require_exact_pool_keys",
        "require_exact_token_keys",
        "ensure_consumed_subset",
        "PLANNING_STATE_DOMAIN",
        "POSITION_REASON_FULL_ENVELOPE",
        "POOL_REASON_FULL_ENVELOPE",
        "TOKEN_REASON_FULL_ENVELOPE",
        "post_fatal_writer_event_suffix_in_plan",
        "all_required_observations_evaluated",
        "checkpoint_or_graph_block_success_authorized",
    ):
        require(required in compact, f"planner source evidence missing: {required}")
    require(
        compact.count("expected_consumption_count:1") >= 2,
        "Position/Pool unit cache multiplicity evidence missing",
    )
    require("pubframe:" not in compact and "pubplan:" not in compact, "preflight fields became public")
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
        require(forbidden not in source, f"forbidden planner linkage: {forbidden}")
    overlay_text = "\n".join(path.read_text(errors="replace") for path in overlay.rglob("*") if path.is_file())
    sentinel = "Provider" + "Unavailable"
    require(sentinel not in overlay_text, "provider failure sentinel entered observation-plan overlay")
    harness = (overlay / "tests/npm_observation_plan.rs").read_text()
    expected_tests = {
        "every_segment_selects_its_exact_profile_and_collect_closure",
        "repeated_interleaved_events_are_sorted_deduplicated_and_counted",
        "existing_position_uses_immutable_block_start_identity",
        "resolved_none_closes_position_without_pool_or_token_requests",
        "normal_pipeline_is_canonical_and_consumption_is_audited",
        "fatal_middle_still_resolves_and_audits_the_full_suffix",
        "unresolved_full_envelope_rows_abort_both_stages",
        "exact_key_set_rejects_missing_extra_and_duplicate_rows",
        "call_scope_and_planning_state_drift_fail_closed",
        "possible_reorg_and_unknown_call_scopes_fail_before_planning",
        "plan_bytes_are_stable_across_supplied_position_order",
        "same_token_address_tracks_two_role_consumptions_once",
        "canonical_wire_rejects_unknown_fields_and_never_contains_provider_failures",
        "planning_state_is_canonical_and_rejects_identity_drift",
        "inherited_resolved_adapter_surface_remains_exercised",
        "truth_boundary_keeps_every_broader_authority_false",
        "empty_frames_have_no_requests_and_still_preflight",
        "request_keys_are_unique_after_normalization",
        "planning_projection_ignores_nonposition_state",
        "repeated_event_cache_limits_reject_position_and_pool_overconsumption",
    }
    require(
        {name for name in expected_tests if f"fn {name}()" in harness} == expected_tests,
        "Rust observation-plan test inventory drift",
    )
    materializer = (root / "scripts/materialize-uniswap-v3-npm-observation-plan.sh").read_text()
    for required in (
        "materialize-uniswap-v3-npm-resolved-inputs.sh",
        'rm "$destination/tests/npm_resolved_inputs.rs"',
        "npm_observation_plan.rs",
        "uniswap.npm.plan.v1.rs",
        "npm-observation-plan-v1.json",
        "npm_observation_plan.rs",
        "verify-uniswap-v3-npm-observation-plan.py",
    ):
        require(required in materializer, f"observation-plan materializer evidence missing: {required}")


def materialize_expected(root: Path, destination: Path, resolved=None, joint=None, writer=None) -> None:
    resolved = resolved or load_resolved_verifier(root)
    joint = joint or resolved.load_joint_verifier(root)
    writer = writer or joint.load_writer_verifier(root)
    resolved.materialize_expected(root, destination, joint, writer)
    (destination / "tests/npm_resolved_inputs.rs").unlink()
    copies = {
        "uniswap-v3/npm-observation-plan/src/npm_observation_plan.rs": "src/npm_observation_plan.rs",
        "uniswap-v3/npm-observation-plan/src/uniswap.npm.plan.v1.rs": "src/uniswap.npm.plan.v1.rs",
        "uniswap-v3/npm-observation-plan/npm-observation-plan-v1.json": "configs/npm-observation-plan-v1.json",
        "uniswap-v3/npm-observation-plan/tests/npm_observation_plan.rs": "tests/npm_observation_plan.rs",
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


def verify_runtime(root: Path, runtime: Path, contract: dict[str, object], resolved, joint, writer) -> Path:
    require(runtime.is_dir(), f"observation-plan runtime missing: {runtime}")
    with tempfile.TemporaryDirectory(prefix="npm-observation-plan-expected-") as temporary:
        temporary_path = Path(temporary)
        baseline = temporary_path / "resolved"
        expected = temporary_path / "planned"
        resolved.materialize_expected(root, baseline, joint, writer)
        materialize_expected(root, expected, resolved, joint, writer)
        baseline_files = writer.non_build_files(baseline)
        expected_files = writer.non_build_files(expected)
        runtime_files = writer.non_build_files(runtime)
        require(
            changed_files(baseline_files, expected_files) == EXPECTED_RESOLVED_DELTA,
            f"runtime delta from resolved inputs drift: {sorted(changed_files(baseline_files, expected_files))}",
        )
        require(set(runtime_files) == set(expected_files), "observation-plan runtime file set drift")
        for relative, expected_path in expected_files.items():
            actual = runtime_files[relative]
            require(actual.read_bytes() == expected_path.read_bytes(), f"runtime content drift: {relative}")
            require(
                bool(actual.stat().st_mode & 0o111) == bool(expected_path.stat().st_mode & 0o111),
                f"runtime mode drift: {relative}",
            )
        for relative, baseline_path in baseline_files.items():
            if relative == "tests/npm_resolved_inputs.rs":
                continue
            require(runtime_files[relative].read_bytes() == baseline_path.read_bytes(), f"resolved/writer artifact changed: {relative}")
    for relative, digest in contract["materialized_runtime_artifacts"].items():
        require(sha256(runtime / relative) == digest, f"materialized artifact digest drift: {relative}")
    require(not (runtime / "tests/npm_resolved_inputs.rs").exists(), "superseded resolved harness retained")
    require(not (runtime / "proto/uniswap/npm/plan").exists(), "host-only plan protobuf entered runtime descriptor tree")
    lib = (runtime / "src/lib.rs").read_text()
    require("npm_observation_plan" not in lib, "host-only planner linked into runtime lib")
    return runtime / "target/wasm32-unknown-unknown/release/substreams_uniswap_v3.wasm"


def verify_packages(
    resolved,
    writer,
    runtime_wasm: Path,
    packages: dict[str, Path],
    writer_packages: dict[str, Path] | None,
) -> None:
    resolved.verify_packages(writer, runtime_wasm, packages, writer_packages)


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

    root = args.root.resolve()
    contract = load_contract(root)
    load_semantics(root)
    resolved = load_resolved_verifier(root)
    _, joint, writer = verify_upstream(root, resolved)
    verify_proto(root, contract)
    verify_overlay_static(root)

    runtime_wasm = None
    if args.runtime is not None:
        runtime_wasm = verify_runtime(root, args.runtime.resolve(), contract, resolved, joint, writer)
    package_values = (args.mainnet_spkg, args.base_spkg)
    require(all(value is None for value in package_values) or all(value is not None for value in package_values), "pass both plan packages")
    writer_values = (args.writer_mainnet_spkg, args.writer_base_spkg)
    require(all(value is None for value in writer_values) or all(value is not None for value in writer_values), "pass both writer packages")
    if all(value is not None for value in package_values):
        require(runtime_wasm is not None and runtime_wasm.is_file(), "package verification requires built runtime WASM")
        packages = {"mainnet": args.mainnet_spkg.resolve(), "base": args.base_spkg.resolve()}
        writer_packages = None
        if all(value is not None for value in writer_values):
            writer_packages = {
                "mainnet": args.writer_mainnet_spkg.resolve(),
                "base": args.writer_base_spkg.resolve(),
            }
        verify_packages(resolved, writer, runtime_wasm, packages, writer_packages)

    print(
        "verified staged full-envelope NPM observation closure, exact closed-frame preflight, "
        "consumed-subset audit, and unchanged writer artifacts"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except VerificationError as error:
        print(f"verification failed: {error}", file=sys.stderr)
        raise SystemExit(1)
