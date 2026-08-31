#!/usr/bin/env python3
"""Fail-closed verification for host-only resolved Uniswap V3 NPM inputs."""

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


OVERLAY = Path("uniswap-v3/npm-resolved-inputs")
CONTRACT_PATH = OVERLAY / "contract-v1.json"
CONTRACT_SHA256 = "5df1d6f5d6852ff8aea9ef6b054be786d0df78021e6ed271439f744a330cfc1f"
SEMANTICS_SHA256 = "01f7e87b22f52d84f8bb2fe806e963ecfb9dc196ab29804baee4c156eabbdbd9"
SOURCE_RUNTIME_SHA256 = "701e83d3833356cff75ad4455553894e7695fb9f75f03e7c53eaa3da616b57d5"
SOURCE_SEMANTICS_SHA256 = "267dfc6b7240c36cdf345553e02a4f7b5332fa70548349bc6ef4b3075b4fcb4b"
SOURCE_PROTO_SHA256 = "bd394a11de37449710f0fd7dc10eac4e7f4ad299141a9fd54ec156980246fe1e"
SOURCE_VALIDATOR_SHA256 = "5dac40f6f81223b0e373eb69e12a652754bc92879c0da28244ba80849b95c177"
SOURCE_BINDING_SHA256 = "0dba8501e790d4efd0cda3cf64c9eddbca01cb9ce90da3931568224b38c7be3d"
JOINT_RUNTIME_SHA256 = "6f46d5cca49506c3ee0622351324ccb62a459916f0e41f3772fe021e0e185dd6"
JOINT_SEMANTICS_SHA256 = "86cf89d8ffe66ac9f4aeda468988306ccc9dca1dbfd2641f132f12529207b143"
JOINT_SOURCE_SHA256 = "49f5302181c48fb25268bf64c6a53038c4b1f2dc891cd6180cbd94b602239a7b"
WRITER_RUNTIME_SHA256 = "765806bf19fca7695ef4d97f557593e4f791759589fe55c20f18c6523a5d07ca"
WRITER_PROFILE_SHA256 = "2b6635c061a7a0bfce39430c71c41dacc1567f095fe41134e890a697aa27f823"
WRITER_COMPATIBILITY_SHA256 = "259481724561d5aa725c17f90b5a19ea93ad6f7cd6074cf2cb8a8661c39f81c4"
WRITER_PROTO_SHA256 = "f87b4bc718349bae2ff8fe799e4a4dadbb507240b7b6e9bc8d7a199299e33c59"
SEGMENT_MATRIX_SHA256 = "7f6d1a34a8c885fe5ddcd81895818ba7ae8a0d736d541b881c1cc7cd54275161"
EXECUTION_ORDER_SHA256 = "241e970cfcec4d76610b29a10141d3bff2512d80454a6308594f3db23621cde2"

README_SHA256 = "6531c8cd98f713da1f036f8bbfbba212163ff34a9acf2ac2a072838aee872845"
ELIGIBILITY_SHA256 = "ffa5dc51a669ba8a4b8d548bb3c24c9588260fb3f0a21c7b7173129605460bb2"
PROVENANCE_SHA256 = "89537d2fe898d0e487a1fccad4f54482766e51df2cd6613801e0a07520419dd4"
PROTO_SHA256 = "e4859b67d590b1bcd2ce2d51ef90775c3729002300269a61b49d4bc31df6b299"
BINDING_SHA256 = "d7979c2e98750c8fa1a5fbe4efcb11d7033e5b12b9c239a13963d20f485f3b66"
SOURCE_CODE_SHA256 = "01a836f7dc71b87e980f313b8cc61d1eb5529b7cbe3e590706ed8d2b0a8586c3"
HARNESS_SHA256 = "b549e08bba3bef8ae18f6f0440a01efad0c811b2cfde50652446fd2dfd1a8f94"
MATERIALIZER_SHA256 = "47273f52c892c7e491974e16a1199105516d1ef27f910d08b32a9a3a17e7227f"

EXPECTED_OVERLAY_FILES = {
    "README.md",
    "contract-v1.json",
    "docs/eligibility.md",
    "docs/provenance.md",
    "npm-resolved-inputs-v1.json",
    "proto/uniswap/npm/inputs/v1/npm_resolved_inputs.proto",
    "src/npm_resolved_inputs.rs",
    "src/uniswap.npm.inputs.v1.rs",
    "tests/npm_resolved_inputs.rs",
}

EXPECTED_RUNTIME_DELTA = {
    "configs/npm-source-block-v1.json",
    "configs/npm-resolved-inputs-v1.json",
    "src/npm_source_block.rs",
    "src/uniswap.npm.source.v1.rs",
    "src/npm_resolved_inputs.rs",
    "src/uniswap.npm.inputs.v1.rs",
    "tests/npm_handler_reducer.rs",
    "tests/npm_resolved_inputs.rs",
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


def load_source_verifier(root: Path):
    return load_module(root / "scripts/verify-uniswap-v3-npm-source-block.py", "npm_resolved_source_verifier")


def load_joint_verifier(root: Path):
    return load_module(root / "scripts/verify-uniswap-v3-npm-handler-reducer.py", "npm_resolved_joint_verifier")


def expected_truth() -> dict[str, bool]:
    return {
        "all_eight_npm_segments_executable": True,
        "diagnostic_only": True,
        "host_resolved_input_frame_implemented": True,
        "integrated_host_engine_added": False,
        "post_fatal_execution_modeled": False,
        "all_required_observations_evaluated": False,
        "graph_execution_trace_complete": False,
        "checkpoint_or_graph_block_success_authorized": False,
        "boundary_state_continuity_complete": False,
        "physical_parity_complete": False,
        "physical_entity_vid_semantics_certified": False,
        "poi_parity_complete": False,
        "dynamic_datasource_stage_order_implemented": False,
        "runtime_population_complete": False,
        "shared_transaction_last_writer_semantics_certified": False,
        "backfill_ready": False,
        "production_ready": False,
    }


def expected_repository_artifacts() -> dict[str, tuple[str, str, str | None]]:
    return {
        "readme": ("uniswap-v3/npm-resolved-inputs/README.md", README_SHA256, None),
        "eligibility": ("uniswap-v3/npm-resolved-inputs/docs/eligibility.md", ELIGIBILITY_SHA256, None),
        "provenance": ("uniswap-v3/npm-resolved-inputs/docs/provenance.md", PROVENANCE_SHA256, None),
        "semantics": (
            "uniswap-v3/npm-resolved-inputs/npm-resolved-inputs-v1.json",
            SEMANTICS_SHA256,
            "uniswap-v3-npm-resolved-inputs/v1",
        ),
        "input_proto": (
            "uniswap-v3/npm-resolved-inputs/proto/uniswap/npm/inputs/v1/npm_resolved_inputs.proto",
            PROTO_SHA256,
            None,
        ),
        "input_binding": (
            "uniswap-v3/npm-resolved-inputs/src/uniswap.npm.inputs.v1.rs",
            BINDING_SHA256,
            None,
        ),
        "input_source": (
            "uniswap-v3/npm-resolved-inputs/src/npm_resolved_inputs.rs",
            SOURCE_CODE_SHA256,
            None,
        ),
        "combined_harness": (
            "uniswap-v3/npm-resolved-inputs/tests/npm_resolved_inputs.rs",
            HARNESS_SHA256,
            None,
        ),
        "materializer": (
            "scripts/materialize-uniswap-v3-npm-resolved-inputs.sh",
            MATERIALIZER_SHA256,
            None,
        ),
        "npm_source_runtime": (
            "uniswap-v3/npm-source-block/contract-v1.json",
            SOURCE_RUNTIME_SHA256,
            "uniswap-v3-npm-source-block-runtime/v1",
        ),
        "npm_source_semantics": (
            "uniswap-v3/npm-source-block/npm-source-block-v1.json",
            SOURCE_SEMANTICS_SHA256,
            "uniswap-v3-npm-source-block/v1",
        ),
        "npm_source_proto": (
            "uniswap-v3/npm-source-block/proto/uniswap/npm/source/v1/npm_source_block.proto",
            SOURCE_PROTO_SHA256,
            None,
        ),
        "npm_source_validator": (
            "uniswap-v3/npm-source-block/runtime/src/npm_source_block.rs",
            SOURCE_VALIDATOR_SHA256,
            None,
        ),
        "npm_source_binding": (
            "uniswap-v3/npm-source-block/runtime/src/pb/uniswap.npm.source.v1.rs",
            SOURCE_BINDING_SHA256,
            None,
        ),
        "joint_reducer_runtime": (
            "uniswap-v3/npm-handler-reducer/contract-v1.json",
            JOINT_RUNTIME_SHA256,
            "uniswap-v3-npm-handler-reducer-runtime/v1",
        ),
        "joint_reducer_semantics": (
            "uniswap-v3/npm-handler-reducer/npm-handler-reducer-v1.json",
            JOINT_SEMANTICS_SHA256,
            "uniswap-v3-npm-handler-reducer/v1",
        ),
    }


def expected_materialized_artifacts() -> dict[str, str]:
    return {
        "configs/npm-handler-reducer-v1.json": JOINT_SEMANTICS_SHA256,
        "configs/npm-source-block-v1.json": SOURCE_SEMANTICS_SHA256,
        "configs/npm-resolved-inputs-v1.json": SEMANTICS_SHA256,
        "src/lib.rs": "91a2330a1a1016ab00fae61e8d25fde244591159ab4efd848ecc08b2623aca63",
        "src/npm_handler_reducer.rs": JOINT_SOURCE_SHA256,
        "src/npm_source_block.rs": SOURCE_VALIDATOR_SHA256,
        "src/uniswap.npm.source.v1.rs": SOURCE_BINDING_SHA256,
        "src/npm_resolved_inputs.rs": SOURCE_CODE_SHA256,
        "src/uniswap.npm.inputs.v1.rs": BINDING_SHA256,
        "tests/npm_resolved_inputs.rs": HARNESS_SHA256,
    }


def load_contract(root: Path) -> dict[str, object]:
    path = root / CONTRACT_PATH
    require(path.is_file(), "resolved-input runtime contract missing")
    require(sha256(path) == CONTRACT_SHA256, "resolved-input runtime contract raw digest drift")
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
            "adapter_contract",
            "package_contract",
            "truth_boundary",
        },
        "resolved-input runtime contract",
    )
    require(
        (contract["format_version"], contract["contract_version"], contract["mode"])
        == (1, "uniswap-v3-npm-resolved-inputs-runtime/v1", "host-diagnostic-only"),
        "unsupported resolved-input runtime contract",
    )
    require(
        contract["ordered_materialization"]
        == [
            {
                "path": "uniswap-v3/npm-source-block/contract-v1.json",
                "contract_version": "uniswap-v3-npm-source-block-runtime/v1",
                "sha256": SOURCE_RUNTIME_SHA256,
            },
            {
                "path": "uniswap-v3/npm-handler-reducer/contract-v1.json",
                "contract_version": "uniswap-v3-npm-handler-reducer-runtime/v1",
                "sha256": JOINT_RUNTIME_SHA256,
            },
            {
                "path": "uniswap-v3/npm-resolved-inputs/npm-resolved-inputs-v1.json",
                "contract_version": "uniswap-v3-npm-resolved-inputs/v1",
                "sha256": SEMANTICS_SHA256,
            },
        ],
        "resolved-input materialization order drift",
    )
    artifacts = expected_repository_artifacts()
    require(set(contract["repository_artifacts"]) == set(artifacts), "repository artifact inventory drift")
    for name, (relative, digest, version) in artifacts.items():
        expected = {"path": relative, "sha256": digest}
        if version is not None:
            expected["contract_version"] = version
        require(contract["repository_artifacts"][name] == expected, f"repository artifact binding drift: {name}")
        require(sha256(root / relative) == digest, f"repository artifact content drift: {name}")
    require(
        contract["materialized_runtime_artifacts"] == expected_materialized_artifacts(),
        "materialized artifact table drift",
    )
    require(contract["truth_boundary"] == expected_truth(), "resolved-input truth boundary promoted")
    return contract


def load_semantics(root: Path) -> dict[str, object]:
    path = root / OVERLAY / "npm-resolved-inputs-v1.json"
    require(sha256(path) == SEMANTICS_SHA256, "resolved-input semantic contract raw digest drift")
    semantics = json.loads(path.read_text())
    exact_keys(
        semantics,
        {
            "format_version",
            "contract_version",
            "mode",
            "source_npm_source_runtime_sha256",
            "source_npm_source_semantics_sha256",
            "source_npm_source_proto_sha256",
            "source_npm_source_validator_sha256",
            "source_npm_source_binding_sha256",
            "source_npm_handler_reducer_runtime_sha256",
            "source_npm_handler_reducer_semantics_sha256",
            "source_writer_runtime_sha256",
            "source_writer_profiles_sha256",
            "source_writer_compatibility_sha256",
            "source_writer_proto_sha256",
            "source_segment_matrix_sha256",
            "source_execution_order_sha256",
            "mapping_contract",
            "replay_contract",
            "determinism_contract",
            "initial_blocks",
            "truth_boundary",
        },
        "resolved-input semantic contract",
    )
    require(
        (semantics["format_version"], semantics["contract_version"], semantics["mode"])
        == (1, "uniswap-v3-npm-resolved-inputs/v1", "host-diagnostic-only"),
        "unsupported resolved-input semantic contract",
    )
    expected_bindings = {
        "source_npm_source_runtime_sha256": SOURCE_RUNTIME_SHA256,
        "source_npm_source_semantics_sha256": SOURCE_SEMANTICS_SHA256,
        "source_npm_source_proto_sha256": SOURCE_PROTO_SHA256,
        "source_npm_source_validator_sha256": SOURCE_VALIDATOR_SHA256,
        "source_npm_source_binding_sha256": SOURCE_BINDING_SHA256,
        "source_npm_handler_reducer_runtime_sha256": JOINT_RUNTIME_SHA256,
        "source_npm_handler_reducer_semantics_sha256": JOINT_SEMANTICS_SHA256,
        "source_writer_runtime_sha256": WRITER_RUNTIME_SHA256,
        "source_writer_profiles_sha256": WRITER_PROFILE_SHA256,
        "source_writer_compatibility_sha256": WRITER_COMPATIBILITY_SHA256,
        "source_writer_proto_sha256": WRITER_PROTO_SHA256,
        "source_segment_matrix_sha256": SEGMENT_MATRIX_SHA256,
        "source_execution_order_sha256": EXECUTION_ORDER_SHA256,
    }
    for key, digest in expected_bindings.items():
        require(semantics[key] == digest, f"semantic upstream binding drift: {key}")
    require(semantics["initial_blocks"] == {"mainnet": 12_369_651, "base": 1_371_713}, "initial-block drift")
    require(semantics["truth_boundary"] == expected_truth(), "semantic truth boundary promoted")
    mapping = semantics["mapping_contract"]
    require(mapping["source_recomputed"] is False, "source recomputation gate promoted")
    require(mapping["writer_events_supplied_separately"] is False, "separate WriterEvents gate promoted")
    require(mapping["raw_block_consumed"] is False, "raw Block gate promoted")
    require(mapping["chain_config_consumed"] is False, "ChainConfig gate promoted")
    require(mapping["external_failure_text_serialized"] is False, "failure-text serialization gate promoted")
    return semantics


def verify_upstream(root: Path, source, joint, writer) -> None:
    require(source.CONTRACT_SHA256 == SOURCE_RUNTIME_SHA256, "loaded source verifier digest drift")
    require(source.SEMANTICS_SHA256 == SOURCE_SEMANTICS_SHA256, "loaded source semantics digest drift")
    source.load_contract(root)
    source.load_semantics(root)
    source.verify_upstream(root)
    source.verify_proto(root)
    source.verify_static_source(root)
    require(joint.CONTRACT_SHA256 == JOINT_RUNTIME_SHA256, "loaded joint verifier digest drift")
    require(joint.SEMANTICS_SHA256 == JOINT_SEMANTICS_SHA256, "loaded joint semantics digest drift")
    joint_semantics = joint.load_semantics(root)
    joint.load_contract(root)
    joint.verify_upstream_projection_bindings(root, joint_semantics)
    joint.verify_execution_order(root)
    joint.verify_writer_runtime(root, writer)
    require(sha256(root / "uniswap-v3/writer-runtime/segment-profiles-v1.json") == WRITER_PROFILE_SHA256, "writer profiles drift")
    require(sha256(root / "uniswap-v3/graft-ancestry/v2/writer-compatibility.json") == WRITER_COMPATIBILITY_SHA256, "writer compatibility drift")
    require(sha256(root / "uniswap-v3/segment-writer-matrix/v1/contract.json") == SEGMENT_MATRIX_SHA256, "segment matrix drift")
    require(sha256(root / "uniswap-v3/execution-order/v1/contract.json") == EXECUTION_ORDER_SHA256, "execution order drift")


def verify_proto(root: Path, contract: dict[str, object]) -> None:
    proto = (root / OVERLAY / "proto/uniswap/npm/inputs/v1/npm_resolved_inputs.proto").read_text()
    generated = (root / OVERLAY / "src/uniswap.npm.inputs.v1.rs").read_text()
    descriptor = contract["protobuf_contract"]
    require(descriptor["namespace"] == "uniswap.npm.inputs.v1", "protobuf namespace drift")
    require(descriptor["repository_only"] is True, "protobuf repository-only gate drift")
    require(descriptor["copied_into_runtime_proto_directory"] is False, "runtime protobuf gate promoted")
    required = (
        'import "uniswap/npm/source/v1/npm_source_block.proto";',
        "uniswap.npm.source.v1.NpmSourceBlock source = 1;",
        "ResolvedCallScope call_scope = 2;",
        "bytes eip1898_hash = 1;",
        "uint64 block_number_fallback = 2;",
        "PositionValue value = 3;",
        "ResolvedNone none = 4;",
        "bytes pool = 5;",
        "TokenFound found = 3;",
        "ResolvedNone missing = 4;",
    )
    for item in required:
        require(item in proto, f"resolved-input protobuf field drift: {item}")
    require("super::super::source::v1::NpmSourceBlock" in generated, "nested source binding drift")
    require("::prost::Oneof" in generated, "resolved oneof binding missing")
    sentinel = "Provider" + "Unavailable"
    require(sentinel not in proto and sentinel not in generated, "unstable sentinel entered protobuf schema/binding")
    legacy_null = "Position" + "NullKind"
    require(legacy_null not in proto and legacy_null not in generated, "legacy null taxonomy entered protobuf")


def verify_overlay_static(root: Path) -> None:
    files = {
        path.relative_to(root / OVERLAY).as_posix()
        for path in (root / OVERLAY).rglob("*")
        if path.is_file()
    }
    require(files == EXPECTED_OVERLAY_FILES, f"resolved-input overlay file set drift: {sorted(files)}")
    source = (root / OVERLAY / "src/npm_resolved_inputs.rs").read_text()
    compact = re.sub(r"\s+", "", source)
    correct_base_factory = "0x33,0x12,0x8a,0x8f,0xc1,0x78,0x69,0x89,0x7d,0xce,0x68,0xed,0x02,0x6d,0x69,0x46,0x21,0xf6,0xfd,0xfd"
    wrong_base_factory = "0x33,0x12,0x8a,0x8f,0xc1,0x78,0x69,0x89,0x7d,0xce,0x68,0xed,0x02,0x6d,0x69,0x46,0x21,0xf6,0xdf,0xd0"
    require(correct_base_factory in compact, "exact Base Factory literal missing")
    require(wrong_base_factory not in compact, "transposed Base Factory literal restored")
    require("pubfnmap_resolved_npm_inputs(source:&NpmSourceBlock," in compact, "source-only mapper signature drift")
    for required in (
        "ResolutionGate::Resolved",
        "ResolutionGate::PossibleReorg",
        "ResolutionGate::Unknown",
        "crate::npm_source_block::validate_npm_source_block(source)",
        "source:Some(source.clone())",
        "validate_frame(&frame)",
        "FailurePhase::None",
        "source_frame_authorizes_graph_block_or_checkpoint_success",
        "resolved_input_frame_authorizes_graph_block_or_checkpoint_success",
        "reducer_disposition_authorizes_graph_block_or_checkpoint_success",
        "post_fatal_execution_modeled",
        "all_required_observations_evaluated",
        "graph_execution_trace_complete",
        "checkpoint_or_graph_block_success_authorized",
    ):
        require(required in compact, f"resolved-input source evidence missing: {required}")
    for forbidden in (
        "substreams_ethereum::pb::eth::v2::Block",
        "ChainConfig",
        "extract_writer_events",
        "Position" + "NullKind",
        "#[substreams::handlers",
        "pub fn graph_out",
        "StoreSet",
        "StoreAdd",
    ):
        require(forbidden not in source, f"forbidden adapter linkage: {forbidden}")
    sentinel = "Provider" + "Unavailable"
    overlay_text = "\n".join(path.read_text(errors="replace") for path in (root / OVERLAY).rglob("*") if path.is_file())
    require(sentinel not in overlay_text, "unstable sentinel entered resolved-input overlay")
    harness = (root / OVERLAY / "tests/npm_resolved_inputs.rs").read_text()
    expected_tests = {
        "source_to_resolved_adapter_to_joint_reducer_is_end_to_end",
        "every_resolved_value_none_zero_found_and_missing_variant_is_canonical",
        "possible_reorg_and_unknown_abort_every_observation_class",
        "fatal_middle_unresolved_or_malformed_later_observation_aborts_before_reducer",
        "nested_source_canonical_unknown_field_and_drift_are_rejected",
        "source_input_normal_and_fatal_authorities_are_independently_false",
        "exact_initial_blocks_and_both_call_scope_variants_replay_empty_frames",
        "source_transactions_are_reused_without_raw_block_recomputation",
        "exact_upstream_bindings_are_compile_time_visible",
    }
    require({name for name in expected_tests if f"fn {name}()" in harness} == expected_tests, "Rust test inventory drift")
    materializer = (root / "scripts/materialize-uniswap-v3-npm-resolved-inputs.sh").read_text()
    for required in (
        "materialize-uniswap-v3-npm-handler-reducer.sh",
        'rm "$destination/tests/npm_handler_reducer.rs"',
        "runtime/src/npm_source_block.rs",
        "runtime/src/pb/uniswap.npm.source.v1.rs",
        "npm-source-block-v1.json",
        "npm_resolved_inputs.rs",
        "uniswap.npm.inputs.v1.rs",
        "npm_resolved_inputs.rs",
        "verify-uniswap-v3-npm-resolved-inputs.py",
    ):
        require(required in materializer, f"materializer evidence missing: {required}")


def materialize_expected(root: Path, destination: Path, joint=None, writer=None) -> None:
    joint = joint or load_joint_verifier(root)
    writer = writer or joint.load_writer_verifier(root)
    joint.materialize_expected(root, destination, writer)
    (destination / "tests/npm_handler_reducer.rs").unlink()
    copies = {
        "uniswap-v3/npm-source-block/runtime/src/npm_source_block.rs": "src/npm_source_block.rs",
        "uniswap-v3/npm-source-block/runtime/src/pb/uniswap.npm.source.v1.rs": "src/uniswap.npm.source.v1.rs",
        "uniswap-v3/npm-source-block/npm-source-block-v1.json": "configs/npm-source-block-v1.json",
        "uniswap-v3/npm-resolved-inputs/src/npm_resolved_inputs.rs": "src/npm_resolved_inputs.rs",
        "uniswap-v3/npm-resolved-inputs/src/uniswap.npm.inputs.v1.rs": "src/uniswap.npm.inputs.v1.rs",
        "uniswap-v3/npm-resolved-inputs/npm-resolved-inputs-v1.json": "configs/npm-resolved-inputs-v1.json",
        "uniswap-v3/npm-resolved-inputs/tests/npm_resolved_inputs.rs": "tests/npm_resolved_inputs.rs",
    }
    for source, target in copies.items():
        shutil.copy2(root / source, destination / target)


def verify_runtime(root: Path, runtime: Path, contract: dict[str, object], joint, writer) -> Path:
    require(runtime.is_dir(), f"resolved-input runtime missing: {runtime}")
    with tempfile.TemporaryDirectory(prefix="npm-resolved-input-expected-") as temporary:
        temporary_path = Path(temporary)
        baseline = temporary_path / "writer"
        expected = temporary_path / "resolved"
        joint_runtime = temporary_path / "joint"
        joint.materialize_expected(root, joint_runtime, writer)
        writer.materialize_expected(root, baseline)
        materialize_expected(root, expected, joint, writer)
        baseline_files = writer.non_build_files(baseline)
        joint_files = writer.non_build_files(joint_runtime)
        expected_files = writer.non_build_files(expected)
        runtime_files = writer.non_build_files(runtime)
        delta = {
            relative
            for relative in set(baseline_files) | set(expected_files)
            if relative not in baseline_files
            or relative not in expected_files
            or baseline_files[relative].read_bytes() != expected_files[relative].read_bytes()
        }
        require(
            delta
            == (EXPECTED_RUNTIME_DELTA - {"tests/npm_handler_reducer.rs"})
            | {"configs/npm-handler-reducer-v1.json", "src/npm_handler_reducer.rs"},
            f"runtime delta from writer drift: {sorted(delta)}",
        )
        joint_delta = {
            relative
            for relative in set(joint_files) | set(expected_files)
            if relative not in joint_files
            or relative not in expected_files
            or joint_files[relative].read_bytes() != expected_files[relative].read_bytes()
        }
        require(joint_delta == EXPECTED_RUNTIME_DELTA, f"runtime delta from joint reducer drift: {sorted(joint_delta)}")
        require(set(runtime_files) == set(expected_files), "resolved-input runtime file set drift")
        for relative, expected_path in expected_files.items():
            actual = runtime_files[relative]
            require(actual.read_bytes() == expected_path.read_bytes(), f"resolved-input runtime content drift: {relative}")
            require(
                actual.stat().st_mode & 0o111 == expected_path.stat().st_mode & 0o111,
                f"resolved-input runtime mode drift: {relative}",
            )
        for relative, baseline_path in baseline_files.items():
            require(runtime_files[relative].read_bytes() == baseline_path.read_bytes(), f"writer artifact changed: {relative}")
    writer.verify_toolchain(runtime)
    writer.verify_protobuf(runtime)
    for relative, digest in contract["materialized_runtime_artifacts"].items():
        require(sha256(runtime / relative) == digest, f"materialized artifact drift: {relative}")
    require(sha256(runtime / "proto/uniswap/v1/writer.proto") == WRITER_PROTO_SHA256, "writer protobuf changed")
    require(not (runtime / "proto/uniswap/npm").exists(), "host-only protobuf entered runtime descriptor tree")
    lib = (runtime / "src/lib.rs").read_text()
    require("npm_resolved_inputs" not in lib and "npm_source_block" not in lib, "host-only adapter linked into runtime lib")
    return runtime / "target/wasm32-unknown-unknown/release/substreams_uniswap_v3.wasm"


def verify_packages(
    writer,
    runtime_wasm: Path,
    packages: dict[str, Path],
    writer_packages: dict[str, Path] | None,
) -> None:
    writer.verify_packages(runtime_wasm, packages)
    if writer_packages is not None:
        for network in ("mainnet", "base"):
            require(
                packages[network].read_bytes() == writer_packages[network].read_bytes(),
                f"resolved-input materialization changed {network} writer package",
            )


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
    if (args.writer_mainnet_spkg or args.writer_base_spkg) and not args.mainnet_spkg:
        parser.error("writer package comparison requires adapter package arguments")
    if args.writer_runtime and not args.runtime:
        parser.error("writer-runtime comparison requires --runtime")
    try:
        root = args.root.resolve()
        source = load_source_verifier(root)
        joint = load_joint_verifier(root)
        writer = joint.load_writer_verifier(root)
        contract = load_contract(root)
        load_semantics(root)
        verify_upstream(root, source, joint, writer)
        verify_proto(root, contract)
        verify_overlay_static(root)
        runtime_wasm = None
        if args.runtime:
            runtime_wasm = verify_runtime(root, args.runtime.resolve(), contract, joint, writer)
        if args.writer_runtime:
            writer_wasm = writer.verify_runtime(
                root,
                args.writer_runtime.resolve(),
                writer.load_runtime_contract(root),
            )
            require(runtime_wasm is not None and runtime_wasm.is_file(), "resolved-input runtime WASM missing")
            require(writer_wasm.is_file(), "writer runtime WASM missing")
            require(runtime_wasm.read_bytes() == writer_wasm.read_bytes(), "resolved-input adapter changed writer WASM")
        if args.mainnet_spkg:
            require(runtime_wasm is not None, "resolved-input runtime WASM missing for package checks")
            writer_packages = None
            if args.writer_mainnet_spkg:
                writer_packages = {
                    "mainnet": args.writer_mainnet_spkg.resolve(),
                    "base": args.writer_base_spkg.resolve(),
                }
            verify_packages(
                writer,
                runtime_wasm,
                {"mainnet": args.mainnet_spkg.resolve(), "base": args.base_spkg.resolve()},
                writer_packages,
            )
        print(
            "verified complete NpmSourceBlock embedding, resolved-only observations, unstable-resolution refusal, exact joint delegation, and unchanged writer artifacts"
        )
        return 0
    except (VerificationError, OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
        print(f"Uniswap V3 resolved NPM input verification failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
