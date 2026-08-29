#!/usr/bin/env python3
"""Fail-closed verification for the host-only joint Uniswap V3 NPM reducer."""

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


CONTRACT_PATH = Path("uniswap-v3/npm-handler-reducer/contract-v1.json")
CONTRACT_SHA256 = "6f46d5cca49506c3ee0622351324ccb62a459916f0e41f3772fe021e0e185dd6"
OVERLAY = Path("uniswap-v3/npm-handler-reducer")
SEMANTICS_SHA256 = "86cf89d8ffe66ac9f4aeda468988306ccc9dca1dbfd2641f132f12529207b143"
REDUCER_SOURCE_SHA256 = "49f5302181c48fb25268bf64c6a53038c4b1f2dc891cd6180cbd94b602239a7b"
REDUCER_TEST_HARNESS_SHA256 = "3af8fa1b569c4fb25062bb7383f29ed088d7ea01b05e1afa3d0144bd7a0bf7e6"
README_SHA256 = "7459e4577c98125ba2ece4879f61e7868eb7d3ad52b4090467283a8b0fc6118f"
POSITION_REDUCER_SHA256 = "3099c3f08208cf46ce68df3433dd5b757436a3a7e315daec3f0d96bf242185c1"
TRANSACTION_REDUCER_SHA256 = "c9f355d141720dfda4347b4ef6cb5350a96803db31cf4770f035b5efca9def7f"
WRITER_RUNTIME_SHA256 = "765806bf19fca7695ef4d97f557593e4f791759589fe55c20f18c6523a5d07ca"
WRITER_SOURCE_SHA256 = "259481724561d5aa725c17f90b5a19ea93ad6f7cd6074cf2cb8a8661c39f81c4"
WRITER_DESCRIPTOR_SHA256 = "22b899f9eeffc8dcfb608eea7ab93884a1756897aba62dc7107507c50a4ac3f0"
WRITER_PROTO_SHA256 = "f87b4bc718349bae2ff8fe799e4a4dadbb507240b7b6e9bc8d7a199299e33c59"
PROFILE_SHA256 = "2b6635c061a7a0bfce39430c71c41dacc1567f095fe41134e890a697aa27f823"
MATRIX_SHA256 = "7f6d1a34a8c885fe5ddcd81895818ba7ae8a0d736d541b881c1cc7cd54275161"
EXECUTION_ORDER_SHA256 = "241e970cfcec4d76610b29a10141d3bff2512d80454a6308594f3db23621cde2"
POSITION_SEMANTICS_SHA256 = "f449c4612413f381486de25c8045ea9d46899942b5d78ab12e477a77b261dec0"
TRANSACTION_SEMANTICS_SHA256 = "83268d10f0ef3008d6d30fc3b6fd304fd46a067866b4284344fe468397878246"
EXPECTED_RUNTIME_DELTA = {
    "configs/npm-handler-reducer-v1.json",
    "src/npm_handler_reducer.rs",
    "tests/npm_handler_reducer.rs",
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


def source_contract(path: str, version: str, digest: str) -> dict[str, object]:
    return {"path": path, "contract_version": version, "sha256": digest}


def expected_truth() -> dict[str, bool]:
    return {
        "all_eight_npm_segments_executable": True,
        "backfill_ready": False,
        "boundary_state_continuity_complete": False,
        "combined_handler_order_implemented": False,
        "diagnostic_only": True,
        "dynamic_datasource_stage_order_implemented": False,
        "failed_handler_poi_error_stream_semantics_certified": False,
        "full_npm_handler_semantics": False,
        "graph_node_execution_order_supplement_bound": True,
        "graph_out_replaced": False,
        "graph_execution_trace_complete": False,
        "joint_npm_entity_state_modeled": True,
        "live_calls_added": False,
        "logical_oracle_complete": False,
        "npm_handler_entity_atomicity_modeled": True,
        "npm_normal_return_orphan_transaction_modeled": True,
        "npm_transaction_entity_effects_modeled": True,
        "physical_parity_complete": False,
        "physical_entity_vid_semantics_certified": False,
        "post_fatal_execution_modeled": False,
        "poi_parity_complete": False,
        "pool_cross_component_execution_order_certified": False,
        "pool_transaction_writers_audited": False,
        "production_ready": False,
        "runtime_consumes_execution_order_contract": False,
        "runtime_population_complete": False,
        "shared_transaction_last_writer_semantics_certified": False,
        "stores_added": False,
        "substreams_handler_added": False,
        "checkpoint_or_graph_block_success_authorized": False,
        "target_runtime_identity_bound": False,
        "writer_runtime_consumes_this_matrix": False,
    }


def load_writer_verifier(root: Path):
    path = root / "scripts/verify-uniswap-v3-writer-runtime.py"
    spec = importlib.util.spec_from_file_location("uniswap_v3_writer_runtime_verifier", path)
    require(spec is not None and spec.loader is not None, "writer verifier cannot be imported")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def expected_repository_artifacts() -> dict[str, tuple[str, str | None, str]]:
    return {
        "readme": ("uniswap-v3/npm-handler-reducer/README.md", None, README_SHA256),
        "reducer_contract": (
            "uniswap-v3/npm-handler-reducer/npm-handler-reducer-v1.json",
            "uniswap-v3-npm-handler-reducer/v1",
            SEMANTICS_SHA256,
        ),
        "reducer_source": (
            "uniswap-v3/npm-handler-reducer/src/npm_handler_reducer.rs",
            None,
            REDUCER_SOURCE_SHA256,
        ),
        "reducer_test_harness": (
            "uniswap-v3/npm-handler-reducer/tests/npm_handler_reducer.rs",
            None,
            REDUCER_TEST_HARNESS_SHA256,
        ),
        "position_reducer": (
            "uniswap-v3/position-reducer/contract-v1.json",
            "uniswap-v3-position-reducer-runtime/v1",
            POSITION_REDUCER_SHA256,
        ),
        "transaction_reducer": (
            "uniswap-v3/transaction-reducer/contract-v1.json",
            "uniswap-v3-transaction-reducer-runtime/v1",
            TRANSACTION_REDUCER_SHA256,
        ),
        "writer_runtime": (
            "uniswap-v3/writer-runtime/contract-v1.json",
            "uniswap-v3-writer-runtime/v1",
            WRITER_RUNTIME_SHA256,
        ),
        "source_writer_contract": (
            "uniswap-v3/graft-ancestry/v2/writer-compatibility.json",
            "uniswap-v3-writer-compatibility/v3",
            WRITER_SOURCE_SHA256,
        ),
        "segment_profiles": (
            "uniswap-v3/writer-runtime/segment-profiles-v1.json",
            "uniswap-v3-writer-runtime-segment-profiles/v1",
            PROFILE_SHA256,
        ),
        "segment_matrix": (
            "uniswap-v3/segment-writer-matrix/v1/contract.json",
            "uniswap-v3-segment-writer-matrix/v1",
            MATRIX_SHA256,
        ),
        "execution_order": (
            "uniswap-v3/execution-order/v1/contract.json",
            "uniswap-v3-execution-order/v1",
            EXECUTION_ORDER_SHA256,
        ),
    }


def load_contract(root: Path) -> dict[str, object]:
    path = root / CONTRACT_PATH
    require(path.is_file(), "joint NPM reducer runtime contract missing")
    require(sha256(path) == CONTRACT_SHA256, "joint NPM reducer runtime contract raw digest drift")
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
        "joint NPM reducer runtime contract",
    )
    require(
        (contract["format_version"], contract["contract_version"], contract["mode"])
        == (1, "uniswap-v3-npm-handler-reducer-runtime/v1", "host-diagnostic-only"),
        "unsupported joint NPM reducer runtime contract",
    )
    require(
        contract["ordered_materialization"]
        == [
            source_contract(
                "uniswap-v3/writer-runtime/contract-v1.json",
                "uniswap-v3-writer-runtime/v1",
                WRITER_RUNTIME_SHA256,
            ),
            source_contract(
                "uniswap-v3/npm-handler-reducer/npm-handler-reducer-v1.json",
                "uniswap-v3-npm-handler-reducer/v1",
                SEMANTICS_SHA256,
            ),
        ],
        "joint NPM reducer materialization order drift",
    )
    expected_artifacts = expected_repository_artifacts()
    require(set(contract["repository_artifacts"]) == set(expected_artifacts), "repository artifact set drift")
    for name, (relative, version, digest) in expected_artifacts.items():
        artifact = contract["repository_artifacts"][name]
        exact_keys(artifact, {"path", "sha256"} | ({"contract_version"} if version else set()), f"artifact {name}")
        require(artifact["path"] == relative, f"repository artifact path drift: {name}")
        require(artifact["sha256"] == digest, f"repository artifact pinned digest drift: {name}")
        if version:
            require(artifact["contract_version"] == version, f"repository artifact version drift: {name}")
        require(sha256(root / relative) == digest, f"repository artifact content drift: {name}")
    require(
        contract["materialized_runtime_artifacts"]
        == {
            "configs/npm-handler-reducer-v1.json": SEMANTICS_SHA256,
            "src/lib.rs": "91a2330a1a1016ab00fae61e8d25fde244591159ab4efd848ecc08b2623aca63",
            "src/npm_handler_reducer.rs": REDUCER_SOURCE_SHA256,
            "tests/npm_handler_reducer.rs": REDUCER_TEST_HARNESS_SHA256,
        },
        "materialized joint NPM artifact inventory drift",
    )
    require(
        contract["producer_contract"]
        == {
            "writer_runtime_sha256": WRITER_RUNTIME_SHA256,
            "writer_descriptor_sha256": WRITER_DESCRIPTOR_SHA256,
            "writer_proto_sha256": WRITER_PROTO_SHA256,
            "source_writer_contract_sha256": WRITER_SOURCE_SHA256,
            "segment_profiles_sha256": PROFILE_SHA256,
            "segment_matrix_sha256": MATRIX_SHA256,
            "execution_order_contract_sha256": EXECUTION_ORDER_SHA256,
            "position_reducer_contract_sha256": POSITION_REDUCER_SHA256,
            "transaction_reducer_contract_sha256": TRANSACTION_REDUCER_SHA256,
            "segment_count": 8,
            "npm_profile_count": 5,
            "writer_protobuf_changed": False,
        },
        "joint NPM producer contract drift",
    )
    require(
        contract["reducer_contract"]
        == {
            "state_entities": ["Transaction", "Position", "PositionSnapshot"],
            "event_loop_count": 1,
            "event_scratch": "joint clone-on-write Transaction, Position, PositionSnapshot state",
            "new_position_save_order": [
                "Transaction:PositionCreation",
                "Position",
                "Transaction:PositionSnapshot",
                "PositionSnapshot",
            ],
            "existing_position_save_order": [
                "Position",
                "Transaction:PositionSnapshot",
                "PositionSnapshot",
            ],
            "new_position_transaction_load_count": 2,
            "existing_position_transaction_load_count": 1,
            "normal_return_orphan_cases": 2,
            "duplicate_transaction_saves_observable": True,
            "legacy_gas_used_source": "transaction gas_limit exposed as event.transaction.gasUsed",
            "current_gas_used_source": "hardcoded zero",
            "receipt_gas_used_used": False,
            "fatal_projection_scope": "final persisted NPM Transaction, Position, and PositionSnapshot user entities only",
            "outcome_scope": "consumed NPM WriterEvents prefix; omitted_event_count reports the unprocessed reducer suffix",
            "post_fatal_execution_modeled": False,
            "nonfatal_state_restore_scope": "failing handler scratch",
            "position_lookup_token_and_exclusion_inputs_shared": True,
            "independent_reducer_output_union_used": False,
            "flash_in_scope": False,
            "physical_vid_and_poi_error_stream_effects_modeled": False,
        },
        "joint NPM reducer execution summary drift",
    )
    require(
        contract["package_contract"]
        == {
            "module_count": 23,
            "diagnostic_module": "map_writer_events",
            "diagnostic_consumers": [],
            "npm_handler_reducer_substreams_module": False,
            "graph_out_output": "proto:sf.substreams.entity.v1.EntityChanges",
            "manifests_changed_from_writer_runtime": False,
            "protobuf_descriptors_changed_from_writer_runtime": False,
            "shared_wasm_binary_count": 1,
            "wasm_identical_to_writer_runtime": True,
            "packages_identical_to_writer_runtime": True,
            "writer_package_verifier_inherited": True,
        },
        "joint NPM package contract drift",
    )
    require(contract["truth_boundary"] == expected_truth(), "joint NPM runtime truth boundary promoted")
    return contract


def load_semantics(root: Path) -> dict[str, object]:
    path = root / OVERLAY / "npm-handler-reducer-v1.json"
    require(path.is_file(), "joint NPM semantics missing")
    require(sha256(path) == SEMANTICS_SHA256, "joint NPM semantics raw digest drift")
    semantics = json.loads(path.read_text())
    exact_keys(
        semantics,
        {
            "format_version",
            "contract_version",
            "mode",
            "source_position_reducer",
            "source_transaction_reducer",
            "source_writer_contract",
            "source_segment_profiles",
            "source_segment_matrix",
            "source_writer_runtime",
            "source_execution_order",
            "network_contracts",
            "execution_contract",
            "npm_profiles",
            "segments",
            "truth_boundary",
        },
        "joint NPM semantics",
    )
    require(
        (semantics["format_version"], semantics["contract_version"], semantics["mode"])
        == (1, "uniswap-v3-npm-handler-reducer/v1", "host-diagnostic-only"),
        "unsupported joint NPM semantics",
    )
    require(
        semantics["source_position_reducer"]
        == source_contract(
            "uniswap-v3/position-reducer/contract-v1.json",
            "uniswap-v3-position-reducer-runtime/v1",
            POSITION_REDUCER_SHA256,
        ),
        "Position reducer binding drift",
    )
    require(
        semantics["source_transaction_reducer"]
        == source_contract(
            "uniswap-v3/transaction-reducer/contract-v1.json",
            "uniswap-v3-transaction-reducer-runtime/v1",
            TRANSACTION_REDUCER_SHA256,
        ),
        "Transaction reducer binding drift",
    )
    require(semantics["source_writer_runtime"]["sha256"] == WRITER_RUNTIME_SHA256, "writer binding drift")
    require(
        semantics["source_writer_runtime"]["writer_descriptor_sha256"] == WRITER_DESCRIPTOR_SHA256,
        "writer descriptor binding drift",
    )
    require(semantics["source_writer_contract"]["sha256"] == WRITER_SOURCE_SHA256, "writer source drift")
    require(semantics["source_segment_profiles"]["sha256"] == PROFILE_SHA256, "profile binding drift")
    require(semantics["source_segment_matrix"]["sha256"] == MATRIX_SHA256, "matrix binding drift")
    require(
        semantics["source_execution_order"]
        == {
            "path": "uniswap-v3/execution-order/v1/contract.json",
            "contract_version": "uniswap-v3-execution-order/v1",
            "raw_sha256": EXECUTION_ORDER_SHA256,
        },
        "execution-order binding drift",
    )
    execution = semantics["execution_contract"]
    require(execution["new_position_transaction_loads"] == 2, "new Position load count drift")
    require(execution["existing_position_transaction_loads"] == 1, "existing Position load count drift")
    require(len(execution["normal_return_orphans"]) == 2, "orphan case set drift")
    require("receipt gas is excluded" in execution["transaction_metadata"], "receipt gas exclusion drift")
    require(
        execution["historical_guard_order"].startswith("before Position identity calls, Transaction saves"),
        "historical guard order drift",
    )
    require(
        execution["fatal_error"]
        == "final persisted NPM user-entity projection shortcut: return the exact block-baseline Transaction, Position, and PositionSnapshot state at the first fatal error; this is not a Graph execution stop",
        "fatal user-entity projection boundary drift",
    )
    require(
        execution["post_fatal_execution"]
        == "intentionally not modeled: Graph continues remaining runnable triggers and breadth-first dynamic stages and may encounter a later retryable failure that aborts before the block transaction; otherwise the fatal transaction filters user modifications to PoI, passes persisted data sources and deterministic errors, advances the failed block pointer, and stops the deployment",
        "post-fatal Graph execution boundary drift",
    )
    require(
        execution["transaction_save_observability"].startswith(
            "every attempted helper call in the modeled event prefix through the first fatal error"
        ),
        "attempted-save prefix boundary drift",
    )
    require(
        execution["physical_side_effect_scope"].startswith("final persisted NPM user-entity projection only"),
        "physical side-effect boundary drift",
    )
    require(semantics["truth_boundary"] == expected_truth(), "joint NPM semantic truth boundary promoted")
    require(len(semantics["segments"]) == 8, "joint NPM reducer requires eight segments")
    require(len(semantics["npm_profiles"]) == 5, "joint NPM reducer requires five profiles")
    return semantics


def verify_upstream_projection_bindings(root: Path, semantics: dict[str, object]) -> None:
    position_path = root / "uniswap-v3/position-reducer/position-reducer-v1.json"
    transaction_path = root / "uniswap-v3/transaction-reducer/transaction-reducer-v1.json"
    require(sha256(position_path) == POSITION_SEMANTICS_SHA256, "Position semantics drift")
    require(sha256(transaction_path) == TRANSACTION_SEMANTICS_SHA256, "Transaction semantics drift")
    position = json.loads(position_path.read_text())
    transaction = json.loads(transaction_path.read_text())
    common_post_fatal_execution = (
        "intentionally not modeled: Graph continues remaining runnable triggers and breadth-first dynamic stages "
        "and may encounter a later retryable failure that aborts before the block transaction; otherwise the fatal "
        "transaction filters user modifications to PoI, passes persisted data sources and deterministic errors, "
        "advances the failed block pointer, and stops the deployment"
    )
    require(
        semantics["execution_contract"]["post_fatal_execution"]
        == position["execution_contract"]["post_fatal_execution"]
        == transaction["execution_contract"]["post_fatal_execution"]
        == common_post_fatal_execution,
        "shared post-fatal execution projection drift",
    )
    require(
        position["execution_contract"]["fatal_error"]
        == "final persisted Position and PositionSnapshot user-entity projection shortcut: return the exact block baseline at the first fatal error; this is not a Graph execution stop",
        "Position fatal projection boundary drift",
    )
    require(
        transaction["execution_contract"]["fatal_error_entity_state"]
        == "final persisted NPM Transaction and relation user-entity projection shortcut: return the exact block baseline at the first fatal error; this is not a Graph execution stop",
        "Transaction fatal projection boundary drift",
    )
    for name, upstream in (("Position", position), ("Transaction", transaction)):
        truth = upstream["truth_boundary"]
        require(truth["graph_execution_trace_complete"] is False, f"{name} Graph trace gate promoted")
        require(truth["post_fatal_execution_modeled"] is False, f"{name} post-fatal execution gate promoted")
        require(
            truth["checkpoint_or_graph_block_success_authorized"] is False,
            f"{name} checkpoint/Graph-success gate promoted",
        )
    require(semantics["network_contracts"] == position["network_contracts"], "network contract projection drift")
    require(semantics["npm_profiles"] == position["npm_profiles"], "NPM profile projection drift")
    for joint, position_segment, transaction_segment in zip(
        semantics["segments"], position["segments"], transaction["segments"], strict=True
    ):
        for field in (
            "network",
            "start_block_inclusive",
            "end_block_inclusive",
            "segment_id",
            "semantic_contract_sha256",
            "npm_profile_id",
            "nonfatal_errors",
            "historical_guard_effective",
        ):
            require(joint[field] == position_segment[field], f"Position segment projection drift: {field}")
        for field in (
            "network",
            "start_block_inclusive",
            "end_block_inclusive",
            "segment_id",
            "semantic_contract_sha256",
            "npm_profile_id",
            "api_version",
            "stored_gas_used_mode",
            "nonfatal_errors",
            "historical_guard_effective",
        ):
            require(joint[field] == transaction_segment[field], f"Transaction segment projection drift: {field}")


def verify_execution_order(root: Path) -> None:
    path = root / "uniswap-v3/execution-order/v1/contract.json"
    require(sha256(path) == EXECUTION_ORDER_SHA256, "execution-order supplement drift")
    contract = json.loads(path.read_text())
    dynamic = contract["execution_model"]["dynamic_data_sources"]
    rollback = contract["execution_model"]["handler_rollback"]
    require(dynamic["stage_scope"] == "stage_local", "dynamic stage scope drift")
    require(dynamic["raw_global_flattening"] is False, "raw-global dynamic order was promoted")
    require(dynamic["creation_log_ordinal_gate"] is False, "creation-log ordinal gate was promoted")
    require(rollback["entity_changes_discarded_on_deterministic_error"] is True, "logical rollback drift")
    require(rollback["vid_sequence_rewinds_on_handler_rollback"] is False, "VID rollback was promoted")
    truth = contract["truth_boundary"]
    for field in (
        "target_runtime_identity_bound",
        "combined_handler_order_implemented",
        "runtime_consumes_contract",
        "physical_parity_complete",
        "poi_parity_complete",
        "backfill_allowed",
        "production_ready",
    ):
        require(truth[field] is False, f"execution-order gate promoted: {field}")


def verify_overlay_static(root: Path) -> None:
    expected_files = {
        "README.md",
        "contract-v1.json",
        "npm-handler-reducer-v1.json",
        "src/npm_handler_reducer.rs",
        "tests/npm_handler_reducer.rs",
    }
    files = {
        path.relative_to(root / OVERLAY).as_posix()
        for path in (root / OVERLAY).rglob("*")
        if path.is_file()
    }
    require(files == expected_files, f"joint NPM overlay file set drift: {sorted(files)}")
    source = (root / OVERLAY / "src/npm_handler_reducer.rs").read_text()
    require(
        re.search(
            rf'const REDUCER_CONTRACT_SHA256: &str\s*=\s*"{SEMANTICS_SHA256}";',
            source,
        )
        is not None,
        "embedded semantic digest drift",
    )
    compact_source = re.sub(r"\s+", "", source)
    for required in (
        "letmutscratch=working.clone();",
        "letnew_identity=!state.positions.contains_key(token_id);",
        "TransactionLoadSite::PositionCreation",
        "state.positions.insert(token_id.to_owned(),position.clone());",
        "TransactionLoadSite::PositionSnapshot",
        "state.snapshots.insert(snapshot.id.clone(),snapshot);",
        "state:baseline",
        "working=scratch;",
        "BlockDisposition::ModeledNpmUserEntityProjectionComplete",
        "BlockDisposition::FatalNpmUserEntityProjection",
        "authorizes_graph_block_or_checkpoint_success",
        "fatal_projection_outcomes_are_only_modeled_prefix_not_graph_execution_trace",
        "modeled_and_fatal_block_dispositions_never_authorize_graph_or_checkpoint_success",
        "graph_execution_trace_complete:false",
        "post_fatal_execution_modeled:false",
        "checkpoint_or_graph_block_success_authorized:false",
    ):
        require(required in compact_source, f"joint event-loop evidence missing: {required}")
    position_save = compact_source.index("state.positions.insert(token_id.to_owned(),position.clone());")
    snapshot_load = compact_source.index("TransactionLoadSite::PositionSnapshot", position_save)
    snapshot_save = compact_source.index("state.snapshots.insert(snapshot.id.clone(),snapshot);", snapshot_load)
    require(position_save < snapshot_load < snapshot_save, "Position/snapshot save order drift")
    for forbidden in (
        "reduce_position_block(",
        "reduce_transaction_block(",
        "PositionLookupPlan",
        "TokenAvailability",
        "#[substreams::handlers",
        "StoreSet",
        "StoreAdd",
        "pub fn graph_out",
        "BlockDisposition::Fatal {",
        "BlockDisposition::Committed",
        "BlockDisposition::FatalUserEntityProjection",
    ):
        require(forbidden not in source, f"forbidden runtime/independent reducer linkage: {forbidden}")
    harness = (root / OVERLAY / "tests/npm_handler_reducer.rs").read_text()
    require(
        harness
        == "//! Host-only integration harness for the disconnected joint NPM reducer.\n\n"
        "pub use substreams_uniswap_v3::pb;\n\n"
        '#[path = "../src/npm_handler_reducer.rs"]\n'
        "mod npm_handler_reducer;\n",
        "joint NPM integration harness drift",
    )
    materializer = (root / "scripts/materialize-uniswap-v3-npm-handler-reducer.sh").read_text()
    for required in (
        "resolve-materialization-destination.py",
        "materialize-uniswap-v3-writer-runtime.sh",
        "verify-uniswap-v3-npm-handler-reducer.py",
        "src/npm_handler_reducer.rs",
        "configs/npm-handler-reducer-v1.json",
        "tests/npm_handler_reducer.rs",
    ):
        require(required in materializer, f"materializer evidence missing: {required}")


def materialize_expected(root: Path, destination: Path, writer=None) -> None:
    writer = writer or load_writer_verifier(root)
    writer.materialize_expected(root, destination)
    (destination / "tests").mkdir()
    shutil.copy2(root / OVERLAY / "src/npm_handler_reducer.rs", destination / "src/npm_handler_reducer.rs")
    shutil.copy2(
        root / OVERLAY / "npm-handler-reducer-v1.json",
        destination / "configs/npm-handler-reducer-v1.json",
    )
    shutil.copy2(
        root / OVERLAY / "tests/npm_handler_reducer.rs",
        destination / "tests/npm_handler_reducer.rs",
    )


def verify_runtime(root: Path, runtime: Path, contract: dict[str, object], writer) -> Path:
    require(runtime.is_dir(), f"joint NPM reducer runtime missing: {runtime}")
    with tempfile.TemporaryDirectory(prefix="uniswap-v3-npm-handler-expected-") as temporary:
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
        require(delta == EXPECTED_RUNTIME_DELTA, f"joint NPM runtime delta drift: {sorted(delta)}")
        require(set(runtime_files) == set(final_files), "joint NPM runtime file set drift")
        for relative, expected in final_files.items():
            actual = runtime_files[relative]
            require(actual.read_bytes() == expected.read_bytes(), f"joint NPM runtime content drift: {relative}")
            require(
                actual.stat().st_mode & 0o111 == expected.stat().st_mode & 0o111,
                f"joint NPM runtime mode drift: {relative}",
            )
    writer.verify_toolchain(runtime)
    writer.verify_protobuf(runtime)
    for relative, digest in contract["materialized_runtime_artifacts"].items():
        require(sha256(runtime / relative) == digest, f"materialized joint NPM artifact drift: {relative}")
    require("npm_handler_reducer" not in (runtime / "src/lib.rs").read_text(), "joint reducer linked into runtime lib")
    return runtime / "target/wasm32-unknown-unknown/release/substreams_uniswap_v3.wasm"


def verify_writer_runtime(root: Path, writer) -> None:
    writer_contract = writer.load_runtime_contract(root)
    require(writer.CONTRACT_SHA256 == WRITER_RUNTIME_SHA256, "loaded writer verifier digest drift")
    require(sha256(root / "uniswap-v3/writer-runtime/contract-v1.json") == WRITER_RUNTIME_SHA256, "writer runtime drift")
    profiles = writer.load_profiles(root)
    configs = writer.load_configs(root)
    writer.load_manifests(root, configs)
    writer.verify_fixture(root)
    writer.verify_overlay_static(root)
    require(writer_contract["package_contract"]["module_count"] == 23, "writer module count drift")
    require(len(profiles["profiles"]) == 8, "writer segment count drift")


def verify_upstream_reducers(root: Path) -> None:
    for script in (
        "scripts/verify-uniswap-v3-position-reducer.py",
        "scripts/verify-uniswap-v3-transaction-reducer.py",
    ):
        process = subprocess.run(
            [sys.executable, str(root / script), "--root", str(root)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        require(process.returncode == 0, f"upstream reducer verification failed: {script}\n{process.stdout[-4000:]}")


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
        verify_upstream_projection_bindings(root, semantics)
        verify_execution_order(root)
        verify_writer_runtime(root, writer)
        verify_upstream_reducers(root)
        verify_overlay_static(root)
        runtime_wasm = None
        if args.runtime:
            runtime_wasm = verify_runtime(root, args.runtime.resolve(), contract, writer)
        if args.writer_runtime:
            writer_wasm = (
                args.writer_runtime.resolve()
                / "target/wasm32-unknown-unknown/release/substreams_uniswap_v3.wasm"
            )
            require(runtime_wasm.is_file(), "joint NPM reducer WASM missing")
            require(writer_wasm.is_file(), "writer-runtime WASM missing")
            require(runtime_wasm.read_bytes() == writer_wasm.read_bytes(), "joint reducer changed writer WASM")
        if args.mainnet_spkg:
            writer.verify_packages(
                runtime_wasm,
                {
                    "mainnet": args.mainnet_spkg.resolve(),
                    "base": args.base_spkg.resolve(),
                },
            )
        print(
            "verified host-only joint Uniswap V3 NPM entity-state reducer, exact Position/Transaction projections, and conservative gates"
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
        print(f"Uniswap V3 joint NPM reducer verification failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
