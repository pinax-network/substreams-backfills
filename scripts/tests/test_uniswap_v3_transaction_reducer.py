#!/usr/bin/env python3
"""Hermetic tests for the host-only Uniswap V3 Transaction reducer overlay."""

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
VERIFIER_PATH = ROOT / "scripts/verify-uniswap-v3-transaction-reducer.py"
SPEC = importlib.util.spec_from_file_location("transaction_reducer_verifier", VERIFIER_PATH)
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


class TransactionReducerContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = VERIFIER.load_contract(ROOT)
        cls.semantics = VERIFIER.load_semantics(ROOT)

    def test_exact_writer_runtime_matrix_and_descriptor_bindings(self) -> None:
        self.assertEqual(self.semantics["source_writer_runtime"]["sha256"], VERIFIER.WRITER_RUNTIME_SHA256)
        self.assertEqual(
            self.semantics["source_writer_runtime"]["writer_descriptor_sha256"],
            VERIFIER.WRITER_DESCRIPTOR_SHA256,
        )
        self.assertEqual(self.semantics["source_segment_matrix"]["sha256"], VERIFIER.MATRIX_SHA256)
        self.assertEqual(self.semantics["source_segment_profiles"]["sha256"], VERIFIER.PROFILE_SHA256)

    def test_eight_segments_bind_legacy_and_current_gas_contracts(self) -> None:
        segments = self.semantics["segments"]
        self.assertEqual(len(segments), 8)
        self.assertEqual([item["api_version"] for item in segments], ["0.0.4"] * 5 + ["0.0.7", "0.0.4", "0.0.7"])
        self.assertEqual(
            [item["stored_gas_used_mode"] for item in segments],
            ["transaction-gas-limit"] * 5 + ["zero", "transaction-gas-limit", "zero"],
        )
        self.assertEqual([item["nonfatal_errors"] for item in segments], [False] * 5 + [True, True, True])
        VERIFIER.verify_segment_bindings(ROOT, self.semantics)

    def test_graph_node_v044_binds_transaction_gas_limit_and_excludes_receipt_usage(self) -> None:
        source = self.semantics["source_graph_node_transaction_gas"]
        self.assertEqual(source, VERIFIER.expected_graph_node_transaction_gas_source())
        self.assertEqual(source["legacy_wat_field_offset_bytes"], 20)
        self.assertEqual(source["asc_transaction_field"], "gas_limit")
        self.assertFalse(source["receipt_gas_used_used"])
        self.assertFalse(source["target_runtime_binary_or_source_identity_bound"])
        execution_source = self.semantics["source_execution_order"]
        self.assertEqual(execution_source, VERIFIER.expected_execution_order_source())
        supplement = VERIFIER.load_execution_order(ROOT)
        self.assertFalse(supplement["execution_model"]["dynamic_data_sources"]["raw_global_flattening"])
        self.assertFalse(
            supplement["execution_model"]["handler_rollback"]["vid_sequence_rewinds_on_handler_rollback"]
        )
        self.assertFalse(
            supplement["execution_model"]["proof_of_indexing"]["failed_handler_set_entity_events_physically_erased"]
        )
        VERIFIER.verify_graph_node_source_binding(ROOT, self.semantics)

    def test_helper_count_orphan_and_relation_contracts_are_explicit(self) -> None:
        execution = self.semantics["execution_contract"]
        self.assertEqual(execution["new_position_helper_calls"], 2)
        self.assertEqual(execution["existing_position_helper_calls"], 1)
        self.assertEqual(len(execution["normal_return_orphans"]), 2)
        self.assertIn("first successfully persisted", execution["position_transaction"])
        self.assertIn("current accepted event", execution["snapshot_transaction"])
        self.assertIn("entity-state", execution["deterministic_error_entity_state"])
        self.assertIn("NPM WriterEvents", execution["npm_writer_event_order"])
        self.assertIn("dynamic Pool", execution["pool_cross_component_execution_order"])
        self.assertIn("entity VIDs", execution["physical_graph_node_side_effects"])
        self.assertIn("PoI and error streams", execution["physical_graph_node_side_effects"])
        self.assertIn("final persisted NPM Transaction and relation user-entity projection", execution["fatal_error_entity_state"])
        self.assertIn("Graph continues remaining runnable triggers", execution["post_fatal_execution"])

    def test_pool_shared_transaction_writers_and_all_promotion_gates_remain_false(self) -> None:
        truth = self.contract["truth_boundary"]
        self.assertTrue(truth["diagnostic_only"])
        self.assertFalse(truth["pool_transaction_writers_audited"])
        self.assertFalse(truth["shared_transaction_last_writer_semantics_certified"])
        self.assertFalse(truth["pool_cross_component_execution_order_certified"])
        self.assertFalse(truth["physical_entity_vid_semantics_certified"])
        self.assertFalse(truth["failed_handler_poi_error_stream_semantics_certified"])
        self.assertFalse(truth["graph_execution_trace_complete"])
        self.assertFalse(truth["post_fatal_execution_modeled"])
        self.assertFalse(truth["checkpoint_or_graph_block_success_authorized"])
        self.assertTrue(all(value is False for key, value in truth.items() if key != "diagnostic_only"))
        self.assertFalse(self.contract["reducer_contract"]["pool_shared_transaction_writers_in_scope"])
        self.assertFalse(self.contract["reducer_contract"]["pool_cross_component_execution_order_certified"])
        self.assertTrue(self.contract["reducer_contract"]["entity_state_discard_scope_only"])
        self.assertFalse(self.contract["reducer_contract"]["physical_vid_and_poi_error_stream_effects_modeled"])

    def test_metadata_is_host_input_only_and_writer_descriptor_is_unchanged(self) -> None:
        self.assertTrue(self.contract["reducer_contract"]["transaction_metadata_input_only"])
        self.assertFalse(self.contract["producer_contract"]["writer_protobuf_changed"])
        self.assertFalse(self.contract["package_contract"]["protobuf_descriptors_changed_from_writer_runtime"])
        source = (ROOT / VERIFIER.OVERLAY / "src/transaction_reducer.rs").read_text()
        self.assertIn("pub struct TransactionMetadata", source)
        metadata_body = source.split("pub struct TransactionMetadata {", 1)[1].split("}", 1)[0]
        self.assertIn("pub gas_limit: String", metadata_body)
        self.assertNotIn("pub gas_used", metadata_body)
        self.assertNotIn("receipt", metadata_body)
        self.assertIn("receipt_actual_gas_used", source)
        self.assertIn("transaction_gas_limit", source)
        writer_proto = (ROOT / "uniswap-v3/writer-runtime/runtime.patch").read_text()
        self.assertNotIn("gas_used", writer_proto.split("diff --git a/proto/uniswap/v1/writer.proto", 1)[1].split("diff --git", 1)[0])

    def test_host_harness_leaves_the_runtime_library_source_exact(self) -> None:
        self.assertFalse((ROOT / VERIFIER.OVERLAY / "runtime.patch").exists())
        with tempfile.TemporaryDirectory(prefix="transaction-library-identity-") as temporary:
            writer_runtime = Path(temporary) / "writer"
            transaction_runtime = Path(temporary) / "transaction"
            WRITER.materialize_expected(ROOT, writer_runtime)
            VERIFIER.materialize_expected(ROOT, transaction_runtime, WRITER)
            self.assertEqual(
                (transaction_runtime / "src/lib.rs").read_bytes(),
                (writer_runtime / "src/lib.rs").read_bytes(),
            )
            self.assertTrue((transaction_runtime / "tests/transaction_reducer.rs").is_file())

    def test_ci_cleanup_is_after_package_proofs_and_scoped_to_completed_targets(self) -> None:
        workflow = (ROOT / ".github/workflows/ci.yaml").read_text()
        configured_proof = workflow.index("Pack both configured diagnostic manifests and prove embedded WASM identity")
        position_proof = workflow.index("Prove the host-only reducer cannot change writer packages")
        flash_proof = workflow.index("Prove the host-only Pool Flash reducer cannot change writer packages")
        cleanup = workflow.index("      - name: Release completed reducer build caches before Transaction validation")
        transaction = workflow.index("      - name: Materialize the host-only NPM Transaction reducer")
        self.assertLess(configured_proof, cleanup)
        self.assertLess(position_proof, cleanup)
        self.assertLess(flash_proof, cleanup)
        self.assertLess(cleanup, transaction)

        cleanup_block = workflow[cleanup:transaction]
        self.assertEqual(
            [line.strip() for line in cleanup_block.splitlines() if line.strip()],
            [
                "- name: Release completed reducer build caches before Transaction validation",
                "run: |",
                'cargo +1.79.0 clean --manifest-path "$RUNNER_TEMP/uniswap-v3-configured/Cargo.toml"',
                'cargo +1.79.0 clean --manifest-path "$RUNNER_TEMP/uniswap-v3-position-reducer/Cargo.toml"',
                'cargo +1.79.0 clean --manifest-path "$RUNNER_TEMP/uniswap-v3-flash-reducer/Cargo.toml"',
                'test ! -e "$RUNNER_TEMP/uniswap-v3-configured/target"',
                'test ! -e "$RUNNER_TEMP/uniswap-v3-position-reducer/target"',
                'test ! -e "$RUNNER_TEMP/uniswap-v3-flash-reducer/target"',
            ],
        )

    def test_materializer_refuses_nonempty_and_repository_destinations(self) -> None:
        script = ROOT / "scripts/materialize-uniswap-v3-transaction-reducer.sh"
        with tempfile.TemporaryDirectory(prefix="transaction-nonempty-") as temporary:
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
        forbidden = ROOT / "transaction-reducer-forbidden"
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

    def test_exact_materialization_preserves_frozen_source(self) -> None:
        before = tree_digest(ROOT / "uniswap-v3/source")
        with tempfile.TemporaryDirectory(prefix="transaction-materializer-") as temporary:
            destination = Path(temporary) / "runtime"
            subprocess.run(
                ["bash", str(ROOT / "scripts/materialize-uniswap-v3-transaction-reducer.sh"), str(destination)],
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
                prefix="transaction-runtime-drift-"
            ) as temporary:
                runtime = Path(temporary) / "runtime"
                VERIFIER.materialize_expected(ROOT, runtime, WRITER)
                if mutation == "content":
                    config = runtime / "configs/transaction-reducer-v1.json"
                    config.write_text(config.read_text() + "\n")
                else:
                    (runtime / "unexpected.txt").write_text("drift\n")
                with self.assertRaises(VERIFIER.VerificationError):
                    VERIFIER.verify_runtime(ROOT, runtime, self.contract, WRITER)

    def test_semantics_self_rehash_cannot_escape_fixed_digest(self) -> None:
        with tempfile.TemporaryDirectory(prefix="transaction-semantics-drift-") as temporary:
            root = Path(temporary)
            target = root / VERIFIER.OVERLAY / "transaction-reducer-v1.json"
            target.parent.mkdir(parents=True)
            mutated = copy.deepcopy(self.semantics)
            mutated["truth_boundary"]["production_ready"] = True
            target.write_text(json.dumps(mutated, indent=2) + "\n")
            with self.assertRaisesRegex(VERIFIER.VerificationError, "digest drift"):
                VERIFIER.load_semantics(root)

    def test_execution_order_supplement_is_raw_digest_bound(self) -> None:
        with tempfile.TemporaryDirectory(prefix="transaction-execution-order-drift-") as temporary:
            root = Path(temporary)
            target = root / VERIFIER.EXECUTION_ORDER_PATH
            target.parent.mkdir(parents=True)
            target.write_bytes((ROOT / VERIFIER.EXECUTION_ORDER_PATH).read_bytes() + b"\n")
            with self.assertRaisesRegex(VERIFIER.VerificationError, "raw digest drift"):
                VERIFIER.load_execution_order(root)

    def test_relocked_receipt_gas_semantic_drift_fails_fixed_digest(self) -> None:
        with tempfile.TemporaryDirectory(prefix="transaction-gas-source-drift-") as temporary:
            root = Path(temporary)
            target = root / VERIFIER.OVERLAY / "transaction-reducer-v1.json"
            target.parent.mkdir(parents=True)
            mutated = copy.deepcopy(self.semantics)
            mutated["source_graph_node_transaction_gas"]["asc_transaction_field"] = "receipt.gas_used"
            mutated["source_graph_node_transaction_gas"]["receipt_gas_used_used"] = True
            mutated["segments"][0]["stored_gas_used_mode"] = "receipt-gas-used"
            target.write_text(json.dumps(mutated, indent=2) + "\n")
            with self.assertRaisesRegex(VERIFIER.VerificationError, "digest drift"):
                VERIFIER.load_semantics(root)

    def test_relocked_legacy_zero_and_segment_drop_fail_fixed_digest(self) -> None:
        for mutation in ("legacy-zero", "segment-drop"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory(
                prefix="transaction-semantic-refusal-"
            ) as temporary:
                root = Path(temporary)
                target = root / VERIFIER.OVERLAY / "transaction-reducer-v1.json"
                target.parent.mkdir(parents=True)
                mutated = copy.deepcopy(self.semantics)
                if mutation == "legacy-zero":
                    mutated["execution_contract"]["legacy_stored_gas_used"] = "hardcoded zero"
                    for segment in mutated["segments"]:
                        if segment["api_version"] == "0.0.4":
                            segment["stored_gas_used_mode"] = "zero"
                else:
                    del mutated["segments"][1]
                target.write_text(json.dumps(mutated, indent=2) + "\n")
                with self.assertRaisesRegex(VERIFIER.VerificationError, "digest drift"):
                    VERIFIER.load_semantics(root)

    def test_source_forbids_runtime_and_pool_writer_integration(self) -> None:
        source = (ROOT / VERIFIER.OVERLAY / "src/transaction_reducer.rs").read_text()
        for required in (
            "all_eight_segments_execute_committed_event_with_expected_gas_contract",
            "legacy_and_current_stored_gas_used_distinguish_gas_limit_from_receipt_usage",
            "decrease_success_and_missing_token_fatal_nonfatal_policies",
            "base_root_guard_covers_increase_and_decrease_before_identity",
            "orphan_transaction_then_later_same_token_success_creates_relations",
            "EventKind::Decrease => Event::DecreaseLiquidity",
        ):
            self.assertIn(required, source)
        for forbidden in (
            "#[substreams::handlers",
            "rpc::eth_call",
            "StoreSet",
            "StoreAdd",
            "EntityChanges",
            "handleSwap",
            "handleMint",
            "handleBurn",
        ):
            self.assertNotIn(forbidden, source)

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
            self.assertNotIn("map_transaction_reducer", {module["name"] for module in manifest["modules"]})


if __name__ == "__main__":
    unittest.main()
