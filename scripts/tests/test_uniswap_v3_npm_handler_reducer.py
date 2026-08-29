#!/usr/bin/env python3
"""Hermetic tests for the host-only joint Uniswap V3 NPM reducer."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VERIFIER_PATH = ROOT / "scripts/verify-uniswap-v3-npm-handler-reducer.py"
SPEC = importlib.util.spec_from_file_location("npm_handler_reducer_verifier", VERIFIER_PATH)
assert SPEC and SPEC.loader
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)
WRITER = VERIFIER.load_writer_verifier(ROOT)


def tree_digest(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(directory.rglob("*")):
        relative = path.relative_to(directory)
        if not path.is_file() or "target" in relative.parts:
            continue
        digest.update(relative.as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
        digest.update(b"x" if path.stat().st_mode & 0o111 else b"-")
    return digest.hexdigest()


class JointNpmReducerContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = VERIFIER.load_contract(ROOT)
        cls.semantics = VERIFIER.load_semantics(ROOT)

    def test_exact_upstream_runtime_matrix_and_execution_bindings(self) -> None:
        self.assertEqual(
            self.semantics["source_position_reducer"]["sha256"],
            VERIFIER.POSITION_REDUCER_SHA256,
        )
        self.assertEqual(
            self.semantics["source_transaction_reducer"]["sha256"],
            VERIFIER.TRANSACTION_REDUCER_SHA256,
        )
        self.assertEqual(
            self.semantics["source_writer_runtime"]["sha256"],
            VERIFIER.WRITER_RUNTIME_SHA256,
        )
        self.assertEqual(
            self.semantics["source_writer_runtime"]["writer_descriptor_sha256"],
            VERIFIER.WRITER_DESCRIPTOR_SHA256,
        )
        self.assertEqual(self.semantics["source_segment_matrix"]["sha256"], VERIFIER.MATRIX_SHA256)
        self.assertEqual(
            self.semantics["source_execution_order"]["raw_sha256"],
            VERIFIER.EXECUTION_ORDER_SHA256,
        )
        VERIFIER.verify_upstream_projection_bindings(ROOT, self.semantics)
        VERIFIER.verify_execution_order(ROOT)

    def test_eight_segments_and_five_profiles_are_distinct_truths(self) -> None:
        self.assertEqual(len(self.semantics["segments"]), 8)
        self.assertEqual(len(self.semantics["npm_profiles"]), 5)
        self.assertTrue(self.contract["truth_boundary"]["all_eight_npm_segments_executable"])
        self.assertNotIn("all_eight_npm_profiles_executable", self.contract["truth_boundary"])
        self.assertEqual(
            [item["api_version"] for item in self.semantics["segments"]],
            ["0.0.4"] * 5 + ["0.0.7", "0.0.4", "0.0.7"],
        )
        self.assertEqual(
            [item["stored_gas_used_mode"] for item in self.semantics["segments"]],
            ["transaction-gas-limit"] * 5 + ["zero", "transaction-gas-limit", "zero"],
        )

    def test_joint_scratch_save_order_and_orphan_contract_are_explicit(self) -> None:
        reducer = self.contract["reducer_contract"]
        self.assertEqual(reducer["event_loop_count"], 1)
        self.assertEqual(
            reducer["new_position_save_order"],
            [
                "Transaction:PositionCreation",
                "Position",
                "Transaction:PositionSnapshot",
                "PositionSnapshot",
            ],
        )
        self.assertEqual(
            reducer["existing_position_save_order"],
            ["Position", "Transaction:PositionSnapshot", "PositionSnapshot"],
        )
        self.assertTrue(reducer["duplicate_transaction_saves_observable"])
        self.assertTrue(reducer["position_lookup_token_and_exclusion_inputs_shared"])
        self.assertFalse(reducer["independent_reducer_output_union_used"])
        self.assertEqual(reducer["normal_return_orphan_cases"], 2)

    def test_only_scoped_diagnostic_truth_flags_are_true(self) -> None:
        truth = self.contract["truth_boundary"]
        expected_true = {
            "all_eight_npm_segments_executable",
            "diagnostic_only",
            "graph_node_execution_order_supplement_bound",
            "joint_npm_entity_state_modeled",
            "npm_handler_entity_atomicity_modeled",
            "npm_normal_return_orphan_transaction_modeled",
            "npm_transaction_entity_effects_modeled",
        }
        self.assertEqual({key for key, value in truth.items() if value}, expected_true)
        self.assertFalse(self.contract["reducer_contract"]["flash_in_scope"])
        self.assertFalse(
            self.contract["reducer_contract"]["physical_vid_and_poi_error_stream_effects_modeled"]
        )
        self.assertFalse(truth["graph_execution_trace_complete"])
        self.assertFalse(truth["post_fatal_execution_modeled"])
        self.assertFalse(truth["checkpoint_or_graph_block_success_authorized"])

    def test_fatal_projection_is_explicitly_not_a_complete_graph_trace(self) -> None:
        execution = self.semantics["execution_contract"]
        self.assertIn("final persisted NPM user-entity projection shortcut", execution["fatal_error"])
        self.assertIn("not a Graph execution stop", execution["fatal_error"])
        self.assertIn("Graph continues remaining runnable triggers", execution["post_fatal_execution"])
        self.assertIn("breadth-first dynamic stages", execution["post_fatal_execution"])
        self.assertIn("later retryable failure", execution["post_fatal_execution"])
        self.assertIn("filters user modifications to PoI", execution["post_fatal_execution"])
        self.assertIn("passes persisted data sources and deterministic errors", execution["post_fatal_execution"])
        self.assertIn("modeled event prefix through the first fatal error", execution["transaction_save_observability"])
        reducer = self.contract["reducer_contract"]
        self.assertEqual(
            reducer["fatal_projection_scope"],
            "final persisted NPM Transaction, Position, and PositionSnapshot user entities only",
        )
        self.assertEqual(
            reducer["outcome_scope"],
            "consumed NPM WriterEvents prefix; omitted_event_count reports the unprocessed reducer suffix",
        )
        self.assertFalse(reducer["post_fatal_execution_modeled"])
        for truth in (self.semantics["truth_boundary"], self.contract["truth_boundary"]):
            self.assertFalse(truth["graph_execution_trace_complete"])
            self.assertFalse(truth["post_fatal_execution_modeled"])
            self.assertFalse(truth["checkpoint_or_graph_block_success_authorized"])

    def test_source_is_one_joint_loop_without_runtime_or_independent_reducer_linkage(self) -> None:
        source = (ROOT / VERIFIER.OVERLAY / "src/npm_handler_reducer.rs").read_text()
        for required in (
            "new_and_existing_positions_share_one_ordered_handler_scratch",
            "normal_returns_commit_only_reachable_transaction_writes",
            "legacy_missing_token_discards_staged_transaction_by_fatal_or_nonfatal_policy",
            "fatal_failure_restores_exact_block_baseline_after_successful_and_orphan_events",
            "fatal_projection_outcomes_are_only_modeled_prefix_not_graph_execution_trace",
            "modeled_and_fatal_block_dispositions_never_authorize_graph_or_checkpoint_success",
            "identical_transaction_saves_remain_visible_in_the_ordered_write_trace",
            "current_collect_missing_token0_still_refreshes_and_saves_joint_state",
            "all_five_collect_profiles_execute_and_qmrv_resets_fee0_from_fee1",
            "all_eight_segments_execute_with_exact_api_gas_behavior",
            "projections_retain_position_and_transaction_reducer_contracts",
        ):
            self.assertIn(required, source)
        for forbidden in (
            "reduce_position_block(",
            "reduce_transaction_block(",
            "PositionLookupPlan",
            "TokenAvailability",
            "#[substreams::handlers",
            "rpc::eth_call",
            "StoreSet",
            "StoreAdd",
            "pub fn graph_out",
        ):
            self.assertNotIn(forbidden, source)
        VERIFIER.verify_overlay_static(ROOT)

    def test_metadata_is_host_only_and_writer_proto_is_unchanged(self) -> None:
        source = (ROOT / VERIFIER.OVERLAY / "src/npm_handler_reducer.rs").read_text()
        metadata = source.split("pub struct TransactionMetadata {", 1)[1].split("}", 1)[0]
        self.assertIn("pub gas_limit: String", metadata)
        self.assertIn("pub gas_price: String", metadata)
        self.assertNotIn("receipt", metadata)
        self.assertFalse(self.contract["producer_contract"]["writer_protobuf_changed"])
        self.assertFalse(
            self.contract["package_contract"]["protobuf_descriptors_changed_from_writer_runtime"]
        )
        self.assertEqual(
            self.contract["producer_contract"]["writer_proto_sha256"],
            VERIFIER.WRITER_PROTO_SHA256,
        )

    def test_host_harness_keeps_writer_library_source_exact(self) -> None:
        self.assertFalse((ROOT / VERIFIER.OVERLAY / "runtime.patch").exists())
        with tempfile.TemporaryDirectory(prefix="joint-npm-library-identity-") as temporary:
            writer_runtime = Path(temporary) / "writer"
            joint_runtime = Path(temporary) / "joint"
            WRITER.materialize_expected(ROOT, writer_runtime)
            VERIFIER.materialize_expected(ROOT, joint_runtime, WRITER)
            self.assertEqual(
                (joint_runtime / "src/lib.rs").read_bytes(),
                (writer_runtime / "src/lib.rs").read_bytes(),
            )
            self.assertTrue((joint_runtime / "tests/npm_handler_reducer.rs").is_file())
            self.assertEqual(
                {
                    path.relative_to(joint_runtime).as_posix()
                    for path in joint_runtime.rglob("*")
                    if path.is_file()
                }
                - {
                    path.relative_to(writer_runtime).as_posix()
                    for path in writer_runtime.rglob("*")
                    if path.is_file()
                },
                VERIFIER.EXPECTED_RUNTIME_DELTA,
            )

    def test_materializer_refuses_nonempty_repository_and_symlink_escape_destinations(self) -> None:
        script = ROOT / "scripts/materialize-uniswap-v3-npm-handler-reducer.sh"
        with tempfile.TemporaryDirectory(prefix="joint-npm-nonempty-") as temporary:
            destination = Path(temporary)
            sentinel = destination / "keep.txt"
            sentinel.write_text("preserve\n")
            result = subprocess.run(
                ["bash", str(script), str(destination)],
                env={**os.environ, "PYTHON": sys.executable},
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("destination must be empty", result.stdout)
            self.assertEqual(sentinel.read_text(), "preserve\n")
        forbidden = ROOT / "joint-npm-reducer-forbidden"
        self.assertFalse(forbidden.exists())
        result = subprocess.run(
            ["bash", str(script), str(forbidden)],
            env={**os.environ, "PYTHON": sys.executable},
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("destination must be outside the repository", result.stdout)
        self.assertFalse(forbidden.exists())
        with tempfile.TemporaryDirectory(prefix="joint-npm-symlink-") as temporary:
            link = Path(temporary) / "escape"
            link.symlink_to(ROOT / "uniswap-v3")
            result = subprocess.run(
                ["bash", str(script), str(link)],
                env={**os.environ, "PYTHON": sys.executable},
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("destination must be outside the repository", result.stdout)

    def test_exact_materialization_preserves_frozen_source(self) -> None:
        before = tree_digest(ROOT / "uniswap-v3/source")
        with tempfile.TemporaryDirectory(prefix="joint-npm-materializer-") as temporary:
            destination = Path(temporary) / "runtime"
            subprocess.run(
                ["bash", str(ROOT / "scripts/materialize-uniswap-v3-npm-handler-reducer.sh"), str(destination)],
                env={**os.environ, "PYTHON": sys.executable},
                text=True,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            VERIFIER.verify_runtime(ROOT, destination, self.contract, WRITER)
        self.assertEqual(tree_digest(ROOT / "uniswap-v3/source"), before)

    def test_runtime_verifier_rejects_content_and_file_set_drift(self) -> None:
        for mutation in ("content", "extra"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory(
                prefix="joint-npm-runtime-drift-"
            ) as temporary:
                runtime = Path(temporary) / "runtime"
                VERIFIER.materialize_expected(ROOT, runtime, WRITER)
                if mutation == "content":
                    config = runtime / "configs/npm-handler-reducer-v1.json"
                    config.write_text(config.read_text() + "\n")
                else:
                    (runtime / "unexpected.txt").write_text("drift\n")
                with self.assertRaises(VERIFIER.VerificationError):
                    VERIFIER.verify_runtime(ROOT, runtime, self.contract, WRITER)

    def test_fixed_runtime_and_semantic_digests_reject_self_rehash(self) -> None:
        with tempfile.TemporaryDirectory(prefix="joint-npm-contract-drift-") as temporary:
            root = Path(temporary)
            runtime_contract = root / VERIFIER.CONTRACT_PATH
            runtime_contract.parent.mkdir(parents=True)
            mutated_contract = copy.deepcopy(self.contract)
            mutated_contract["truth_boundary"]["production_ready"] = True
            runtime_contract.write_text(json.dumps(mutated_contract, indent=2) + "\n")
            with self.assertRaisesRegex(VERIFIER.VerificationError, "raw digest drift"):
                VERIFIER.load_contract(root)
        with tempfile.TemporaryDirectory(prefix="joint-npm-semantics-drift-") as temporary:
            root = Path(temporary)
            target = root / VERIFIER.OVERLAY / "npm-handler-reducer-v1.json"
            target.parent.mkdir(parents=True)
            mutated = copy.deepcopy(self.semantics)
            mutated["truth_boundary"]["production_ready"] = True
            target.write_text(json.dumps(mutated, indent=2) + "\n")
            with self.assertRaisesRegex(VERIFIER.VerificationError, "raw digest drift"):
                VERIFIER.load_semantics(root)

    def test_projection_and_execution_order_tamper_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="joint-npm-projection-drift-") as temporary:
            root = Path(temporary)
            for relative in (
                "uniswap-v3/position-reducer/position-reducer-v1.json",
                "uniswap-v3/transaction-reducer/transaction-reducer-v1.json",
            ):
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT / relative).read_bytes())
            semantics = copy.deepcopy(self.semantics)
            semantics["segments"][0]["api_version"] = "0.0.7"
            with self.assertRaisesRegex(VERIFIER.VerificationError, "Transaction segment projection drift"):
                VERIFIER.verify_upstream_projection_bindings(root, semantics)
        with tempfile.TemporaryDirectory(prefix="joint-npm-order-drift-") as temporary:
            root = Path(temporary)
            target = root / "uniswap-v3/execution-order/v1/contract.json"
            target.parent.mkdir(parents=True)
            target.write_bytes((ROOT / "uniswap-v3/execution-order/v1/contract.json").read_bytes() + b"\n")
            with self.assertRaisesRegex(VERIFIER.VerificationError, "execution-order supplement drift"):
                VERIFIER.verify_execution_order(root)

    def test_package_shape_remains_consumerless_writer_graph(self) -> None:
        configs = WRITER.load_configs(ROOT)
        manifests = WRITER.load_manifests(ROOT, configs)
        for network, manifest in manifests.items():
            self.assertEqual(len(manifest["modules"]), 23, network)
            graph_out = next(module for module in manifest["modules"] if module["name"] == "graph_out")
            self.assertEqual(graph_out["output"]["type"], "proto:sf.substreams.entity.v1.EntityChanges")
            self.assertFalse(
                any(
                    item.get("map") == "map_writer_events" or item.get("store") == "map_writer_events"
                    for module in manifest["modules"]
                    for item in module.get("inputs", [])
                )
            )
            self.assertNotIn("map_npm_handler_reducer", {module["name"] for module in manifest["modules"]})

    def test_ci_releases_only_transaction_target_before_joint_materialization(self) -> None:
        workflow = (ROOT / ".github/workflows/ci.yaml").read_text()
        transaction_proof = (
            "      - name: Prove the host-only reducer leaves writer WASM and packages unchanged\n"
        )
        capacity_step = (
            "      - name: Release the NPM Transaction reducer target before joint materialization\n"
        )
        joint_materialization = "      - name: Materialize the host-only joint NPM reducer\n"
        proof_offset = workflow.index(transaction_proof)
        capacity_offset = workflow.index(capacity_step)
        joint_offset = workflow.index(joint_materialization)
        self.assertLess(proof_offset, capacity_offset)
        self.assertLess(capacity_offset, joint_offset)

        capacity_block = workflow[capacity_offset:joint_offset]
        self.assertEqual(
            capacity_block,
            capacity_step
            + "        run: |\n"
            + '          cargo +1.79.0 clean --manifest-path '
            + '"$RUNNER_TEMP/uniswap-v3-transaction-reducer/Cargo.toml"\n'
            + '          test ! -e "$RUNNER_TEMP/uniswap-v3-transaction-reducer/target"\n',
        )
        self.assertEqual(capacity_block.count("cargo +1.79.0 clean --manifest-path"), 1)
        self.assertNotIn("uniswap-v3-writer-runtime", capacity_block)
        self.assertNotIn(
            'clean --manifest-path "$RUNNER_TEMP/uniswap-v3-writer-runtime/Cargo.toml"',
            workflow,
        )
        self.assertEqual(
            workflow.count(
                'cargo +1.79.0 clean --manifest-path '
                '"$RUNNER_TEMP/uniswap-v3-transaction-reducer/Cargo.toml"'
            ),
            1,
        )


if __name__ == "__main__":
    unittest.main()
