#!/usr/bin/env python3
"""Adversarial tests for the Graph Node v0.44 execution-order supplement."""

from __future__ import annotations

import copy
import importlib.util
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VERIFIER_PATH = ROOT / "scripts/verify-uniswap-v3-execution-order.py"
SPEC = importlib.util.spec_from_file_location(
    "uniswap_v3_execution_order_verifier", VERIFIER_PATH
)
assert SPEC and SPEC.loader
VERIFIER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VERIFIER
SPEC.loader.exec_module(VERIFIER)


class UniswapV3ExecutionOrderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = VERIFIER.verify(ROOT)

    def validate_mutation(self, mutate) -> None:
        contract = copy.deepcopy(self.contract)
        mutate(contract)
        VERIFIER.validate_internal_contract(contract, ROOT)

    def test_contract_is_deterministic_and_exactly_binds_both_inputs(self) -> None:
        expected = VERIFIER.build_contract(ROOT)
        self.assertEqual(self.contract, expected)
        self.assertEqual(
            (ROOT / VERIFIER.CONTRACT_PATH).read_text(), VERIFIER.render(expected)
        )
        self.assertEqual(
            self.contract["source_contracts"],
            {
                "writer_v3": {
                    "path": VERIFIER.WRITER_PATH.as_posix(),
                    "contract_version": VERIFIER.WRITER_VERSION,
                    "raw_sha256": VERIFIER.WRITER_RAW_SHA256,
                },
                "segment_matrix_v1": {
                    "path": VERIFIER.MATRIX_PATH.as_posix(),
                    "contract_version": VERIFIER.MATRIX_VERSION,
                    "raw_sha256": VERIFIER.MATRIX_RAW_SHA256,
                },
            },
        )

    def test_graph_node_reference_binds_exact_commit_tree_and_source_files(self) -> None:
        reference = self.contract["graph_node_reference"]
        self.assertEqual(reference["version"], "v0.44.0")
        self.assertEqual(reference["commit"], VERIFIER.GRAPH_NODE_COMMIT)
        self.assertEqual(reference["tree"], VERIFIER.GRAPH_NODE_TREE)
        self.assertEqual(len(reference["source_files"]), 22)
        paths = {item["path"] for item in reference["source_files"]}
        self.assertIn("core/src/subgraph/runner/mod.rs", paths)
        self.assertIn("chain/ethereum/src/data_source.rs", paths)
        self.assertIn("graph/src/components/store/entity_cache.rs", paths)
        self.assertIn("graph/src/components/subgraph/proof_of_indexing/online.rs", paths)
        for item in reference["source_files"]:
            self.assertRegex(item["sha256"], r"^[0-9a-f]{64}$")
            self.assertIn(VERIFIER.GRAPH_NODE_COMMIT, item["immutable_url"])

    def test_initial_pass_is_trigger_major_host_minor_with_bound_host_order(self) -> None:
        stage_one = self.contract["execution_model"]["stage_one"]
        self.assertEqual(stage_one["ordering_scope"], "stage_local")
        self.assertEqual(
            stage_one["handler_order"],
            "for each ordered raw trigger, matching hosts execute in insertion order",
        )
        self.assertIn("successfully instantiated nonduplicate hosts", stage_one["initial_host_order"])
        self.assertIn("manifest order", stage_one["initial_host_order"])
        self.assertIn("creation block then database vid", stage_one["initial_host_order"])

    def test_stage_fixture_rejects_raw_global_flattening(self) -> None:
        fixture = self.contract["fixtures"]["stage_order"]
        exact = VERIFIER.simulate_order_fixture(fixture)
        flattened = VERIFIER.simulate_order_fixture(
            fixture, raw_global_flattening=True
        )
        self.assertEqual(exact["trace"], fixture["expected_trace"])
        self.assertEqual(
            [item["log_index"] for item in exact["trace"]], [10, 20, 3, 4, 1, 1]
        )
        self.assertNotEqual(flattened["trace"], exact["trace"])

        def mutate(contract) -> None:
            dynamic = contract["execution_model"]["dynamic_data_sources"]
            dynamic["stage_scope"] = "raw_global_block"
            dynamic["raw_global_flattening"] = True

        with self.assertRaisesRegex(VERIFIER.VerificationError, "raw-global flattening"):
            self.validate_mutation(mutate)

    def test_stage_fixture_rejects_creation_log_ordinal_gating(self) -> None:
        fixture = self.contract["fixtures"]["stage_order"]
        exact = VERIFIER.simulate_order_fixture(fixture)
        gated = VERIFIER.simulate_order_fixture(
            fixture, creation_log_ordinal_gate=True
        )
        self.assertNotEqual(gated["trace"], exact["trace"])
        self.assertEqual(
            self.contract["execution_model"]["dynamic_data_sources"][
                "activation_scope"
            ],
            "entire_creation_block",
        )

        def mutate(contract) -> None:
            dynamic = contract["execution_model"]["dynamic_data_sources"]
            dynamic["activation_scope"] = "after_creation_log"
            dynamic["creation_log_ordinal_gate"] = True

        with self.assertRaisesRegex(
            VERIFIER.VerificationError, "creation-log ordinal gating"
        ):
            self.validate_mutation(mutate)

    def test_failed_handler_discards_entities_but_does_not_rewind_vid(self) -> None:
        fixture = self.contract["fixtures"]["rollback"]
        exact = VERIFIER.simulate_rollback_fixture(fixture)
        rewound = VERIFIER.simulate_rollback_fixture(
            fixture, rewind_vid_on_error=True
        )
        self.assertEqual(
            exact["persisted_entities_nonfatal"],
            [
                {"entity": "A", "vid_sequence": 100},
                {"entity": "D", "vid_sequence": 103},
                {"entity": "PoI", "vid_sequence": 104},
            ],
        )
        self.assertEqual(rewound["allocations"][-2]["vid_sequence"], 101)
        self.assertEqual(rewound["allocations"][-1]["vid_sequence"], 102)
        self.assertNotEqual(rewound["allocations"], exact["allocations"])

        def mutate(contract) -> None:
            contract["execution_model"]["handler_rollback"][
                "vid_sequence_rewinds_on_handler_rollback"
            ] = True

        with self.assertRaisesRegex(VERIFIER.VerificationError, "VID rollback"):
            self.validate_mutation(mutate)

    def test_poi_retains_set_entity_events_and_appends_redaction_count(self) -> None:
        fixture = self.contract["fixtures"]["rollback"]
        exact = VERIFIER.simulate_rollback_fixture(fixture)
        erased = VERIFIER.simulate_rollback_fixture(
            fixture, erase_failed_poi_events=True
        )
        self.assertEqual(exact["poi_events"], fixture["expected_poi_events"])
        self.assertIn({"type": "SetEntity", "entity": "B"}, exact["poi_events"])
        self.assertIn(
            {"type": "DeterministicError", "redacted_events": 2},
            exact["poi_events"],
        )
        self.assertNotEqual(erased["poi_events"], exact["poi_events"])

        def mutate(contract) -> None:
            poi = contract["execution_model"]["proof_of_indexing"]
            poi["failed_handler_set_entity_events_physically_erased"] = True
            poi["redaction_encoding"] = "delete attempted events"

        with self.assertRaisesRegex(VERIFIER.VerificationError, "PoI erasure"):
            self.validate_mutation(mutate)

    def test_poi_boundary_is_raw_trigger_group_not_each_mapping_handler(self) -> None:
        poi = self.contract["execution_model"]["proof_of_indexing"]
        self.assertEqual(
            poi["handler_boundary"],
            "once per runnable raw trigger before its ordered hosted mapping handlers",
        )
        self.assertNotIn("failing mapping handler", poi["handler_boundary"])
        self.assertEqual(
            self.contract["fixtures"]["rollback"]["scope"],
            "one hosted mapping handler per runnable raw trigger",
        )

    def test_fatal_and_nonfatal_transactions_keep_distinct_channels(self) -> None:
        rollback = self.contract["fixtures"]["rollback"]
        fatal = rollback["fatal_transaction"]
        self.assertEqual(
            fatal["entity_modifications"],
            [{"entity": "PoI", "vid_sequence": 104}],
        )
        self.assertTrue(fatal["persisted_dynamic_data_sources_passed"])
        self.assertTrue(fatal["deterministic_errors_passed"])
        self.assertTrue(fatal["failed_block_pointer_advanced"])
        self.assertTrue(fatal["deployment_stops_after_transaction"])
        nonfatal = rollback["nonfatal_transaction"]
        self.assertEqual(nonfatal["persisted_user_entities"], ["A", "D"])
        self.assertEqual(
            nonfatal["poi_entity_modification"],
            {"entity": "PoI", "vid_sequence": 104},
        )
        self.assertTrue(nonfatal["block_transaction_accepted_and_pointer_advanced"])
        self.assertEqual(
            nonfatal["continuation_after_transaction_acceptance"],
            "conditional_on_no_fail_fast_cancellation",
        )

    def test_truth_promotion_and_graph_source_drift_are_rejected(self) -> None:
        for flag in (
            "target_runtime_identity_bound",
            "combined_handler_order_implemented",
            "runtime_consumes_contract",
            "same_path_order_machine_proven",
            "physical_parity_complete",
            "poi_parity_complete",
            "backfill_allowed",
            "production_ready",
        ):
            with self.subTest(flag=flag), self.assertRaisesRegex(
                VERIFIER.VerificationError, "truth boundary"
            ):
                self.validate_mutation(
                    lambda contract, flag=flag: contract["truth_boundary"].__setitem__(
                        flag, True
                    )
                )

        with self.assertRaisesRegex(VERIFIER.VerificationError, "Graph Node source"):
            self.validate_mutation(
                lambda contract: contract["graph_node_reference"]["source_files"][0].__setitem__(
                    "sha256", "0" * 64
                )
            )

    def test_raw_source_contract_drift_is_rejected_before_generation(self) -> None:
        for mutated, expected_error in (
            (VERIFIER.WRITER_PATH, "writer-v3 raw SHA-256 drift"),
            (VERIFIER.MATRIX_PATH, "segment-matrix-v1 raw SHA-256 drift"),
        ):
            with self.subTest(mutated=mutated), tempfile.TemporaryDirectory(
                prefix="execution-order-source-drift-"
            ) as temp:
                root = Path(temp)
                for relative in (VERIFIER.WRITER_PATH, VERIFIER.MATRIX_PATH):
                    target = root / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(ROOT / relative, target)
                target = root / mutated
                target.write_bytes(target.read_bytes() + b"\n")
                with self.assertRaisesRegex(
                    VERIFIER.VerificationError, expected_error
                ):
                    VERIFIER.build_contract(root)


if __name__ == "__main__":
    unittest.main()
