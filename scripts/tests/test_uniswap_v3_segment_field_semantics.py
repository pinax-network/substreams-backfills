from __future__ import annotations

import copy
import importlib.util
import itertools
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VERIFIER_PATH = ROOT / "scripts/verify-uniswap-v3-segment-field-semantics.py"
SPEC = importlib.util.spec_from_file_location("uniswap_v3_segment_field_semantics", VERIFIER_PATH)
assert SPEC is not None and SPEC.loader is not None
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)


class SegmentFieldSemanticsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = VERIFIER.verify_contract(ROOT)

    def assert_rejected(self, contract: dict[str, object], label: str) -> None:
        with self.assertRaises(VERIFIER.VerificationError, msg=label):
            VERIFIER.verify_contract(ROOT, contract)

    def test_committed_contract_is_exact_deterministic_projection(self) -> None:
        self.assertEqual(self.contract, VERIFIER.expected_contract(ROOT))
        result = subprocess.run(
            [sys.executable, str(VERIFIER_PATH), "--root", str(ROOT)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("8 segments, 28 pairwise diffs, 67 field records", result.stdout)

    def test_field_catalog_is_complete_only_for_the_declared_subset(self) -> None:
        fields = self.contract["field_catalog"]
        conditional = [item for item in fields if item["population_classification"] == "conditional"]
        absent = [item for item in fields if item["population_classification"] == "required_absent"]
        self.assertEqual(len(conditional), 34)
        self.assertEqual(len(absent), 33)
        self.assertTrue(all(item["complete_in_scope"] for item in fields))
        self.assertTrue(all(not item["complete_entity_history"] for item in conditional))
        self.assertTrue(all(item["complete_entity_history"] for item in absent))
        identities = {(item["entity"], item["field"]) for item in fields}
        self.assertEqual(len(identities), 67)
        for entity, field in (
            ("Position", "pool"),
            ("Position", "token0"),
            ("Position", "token1"),
            ("Position", "tickLower"),
            ("Position", "tickUpper"),
            ("PositionSnapshot", "pool"),
        ):
            self.assertNotIn((entity, field), identities)
        self.assertEqual(
            {item["entity"] for item in absent},
            {"Collect", "Flash", "TickHourData"},
        )

    def test_all_eight_segments_and_all_twenty_eight_pairs_are_bound(self) -> None:
        segments = self.contract["segments"]
        self.assertEqual(len(segments), 8)
        ids = [item["segment_id"] for item in segments]
        self.assertEqual(len(set(ids)), 8)
        expected_pairs = set(itertools.combinations(ids, 2))
        actual_pairs = {
            (item["left_segment_id"], item["right_segment_id"])
            for item in self.contract["segment_diffs"]
        }
        self.assertEqual(actual_pairs, expected_pairs)
        self.assertTrue(all(not item["boundary_state_compared"] for item in self.contract["segment_diffs"]))
        self.assertTrue(all(not item["graph_oracle_compared"] for item in self.contract["segment_diffs"]))
        self.assertTrue(all(item["provenance_diff_paths"] for item in self.contract["segment_diffs"]))
        semantic_equal = [item for item in self.contract["segment_diffs"] if item["semantic_equal"]]
        self.assertEqual(len(semantic_equal), 4)
        self.assertTrue(all(not item["semantic_diff_paths"] for item in semantic_equal))
        self.assertTrue(
            all(item["semantic_diff_paths"] for item in self.contract["segment_diffs"] if not item["semantic_equal"])
        )

    def test_exact_npm_profile_gas_error_and_historical_splits_are_retained(self) -> None:
        segments = self.contract["segments"]
        npm_profiles = [item["semantic_surface"]["npm"]["profile_id"] for item in segments]
        self.assertEqual(
            set(npm_profiles),
            {
                "mainnet-root-correct-collect",
                "mainnet-second-fee0-overwrite",
                "mainnet-no-collect-amounts",
                "base-root-amount0-to-both",
                "current-amount0-to-both",
            },
        )
        legacy = [item for item in segments if item["semantic_surface"]["npm"]["api_version"] == "0.0.4"]
        current = [item for item in segments if item["semantic_surface"]["npm"]["api_version"] == "0.0.7"]
        self.assertEqual((len(legacy), len(current)), (6, 2))
        self.assertTrue(all(item["semantic_surface"]["npm"]["stored_gas_used_mode"] == "transaction-gas-limit" for item in legacy))
        self.assertTrue(all(item["semantic_surface"]["npm"]["stored_gas_used_mode"] == "zero" for item in current))
        guarded = [item for item in segments if item["semantic_surface"]["npm"]["historical_guard_effective"]]
        self.assertEqual([item["network"] for item in guarded], ["base"])
        self.assertEqual(guarded[0]["semantic_surface"]["npm"]["historical_guard"]["block"], 14317993)
        self.assertEqual(sum(item["semantic_surface"]["npm"]["nonfatal_errors"] for item in segments), 3)

    def test_contract_calls_order_atomicity_and_failure_semantics_are_exactly_scoped(self) -> None:
        for segment in self.contract["segments"]:
            flash = segment["semantic_surface"]["flash"]
            self.assertEqual(flash["fee_growth_0_calldata"], "f3058399")
            self.assertEqual(flash["fee_growth_1_calldata"], "46141319")
            self.assertEqual(flash["emitted_row_types"], ["Pool"])
            self.assertEqual(flash["synthetic_row_types"], [])
            self.assertIn("only after both calls", flash["atomicity"])
            self.assertIn("before fee1", flash["first_call_failure"])
            self.assertIn("discard fee0", flash["second_call_failure"])
            npm = segment["semantic_surface"]["npm"]
            self.assertEqual(npm["excluded_pool"], "8fe8d9bb8eeba3ed688069c3d6b556c9ca258248")
            self.assertEqual(npm["excluded_pool_handlers"], ["collect", "decrease", "increase"])
            self.assertIn("strictly increasing global ordinal", npm["event_order"])
            self.assertEqual(
                npm["write_order"]["new_position"],
                ["Transaction:PositionCreation", "Position", "Transaction:PositionSnapshot", "PositionSnapshot"],
            )
            self.assertEqual(
                npm["write_order"]["existing_position"],
                ["Position", "Transaction:PositionSnapshot", "PositionSnapshot"],
            )
            self.assertTrue(npm["write_order"]["duplicate_transaction_saves_observable"])
            self.assertIn("invocation-local raw results", npm["graph_call_cache"])
            self.assertIn("remains provisional", npm["provisional_identity"])
            self.assertIn("not modeled", npm["post_fatal_execution"])
            self.assertEqual(
                segment["semantic_surface"]["numeric"],
                {"decimal_significant_digits": 34, "contract_uint_width_bits": 256},
            )

    def test_provenance_closes_selected_store_target_sets_only(self) -> None:
        for segment in self.contract["segments"]:
            provenance = segment["provenance_surface"]
            self.assertEqual(len(provenance["npm_handlers"]), 4)
            for handler in provenance["npm_handlers"]:
                self.assertEqual(
                    handler["reachable_store_set_targets"],
                    ["Position", "PositionSnapshot", "Transaction"],
                )
                self.assertEqual(len(handler["source_handler_record_sha256"]), 64)
            self.assertEqual(provenance["flash_handler"]["reachable_store_set_targets"], ["Pool"])
            self.assertEqual(len(provenance["flash_handler"]["source_handler_record_sha256"]), 64)

    def test_broad_completion_and_backfill_gates_remain_false(self) -> None:
        truth = self.contract["truth_boundary"]
        narrow_true = {
            "all_eight_scoped_segment_contracts_present",
            "all_pairwise_scoped_segment_diffs_present",
            "conditional_field_handler_effect_rules_complete_for_certified_subset",
            "required_absence_field_closure_complete",
            "scoped_historical_exclusions_ordering_and_quirks_bound",
            "scoped_npm_call_and_failure_host_projection_complete",
            "scoped_pool_flash_two_field_host_projection_complete",
            "source_artifact_raw_bytes_bound",
        }
        self.assertEqual({key for key, value in truth.items() if value}, narrow_true)
        for key in (
            "all_manifest_handler_field_semantics_complete",
            "all_stored_fields_exact",
            "backfill_ready",
            "boundary_state_continuity_complete",
            "combined_handler_order_implemented",
            "factory_handler_semantics_complete",
            "full_entity_histories_complete",
            "full_handler_semantics_complete",
            "graph_execution_trace_complete",
            "graph_oracle_complete",
            "logical_parity_complete",
            "physical_parity_complete",
            "poi_parity_complete",
            "pool_non_flash_handler_semantics_complete",
            "post_fatal_execution_modeled",
            "production_ready",
            "required_nonempty_certified",
            "runtime_population_complete",
            "segment_execution_models_decided",
            "target_runtime_identity_bound",
            "writer_runtime_consumes_this_contract",
        ):
            self.assertFalse(truth[key], key)
        self.assertTrue(all(not segment["backfill_allowed"] for segment in self.contract["segments"]))
        self.assertTrue(all(segment["execution_model"] == "undecided" for segment in self.contract["segments"]))

    def test_adversarial_contract_mutations_fail_closed(self) -> None:
        mutations = []

        promoted = copy.deepcopy(self.contract)
        promoted["truth_boundary"]["backfill_ready"] = True
        mutations.append(("promoted readiness", promoted))

        numeric_false_truth_gate = copy.deepcopy(self.contract)
        numeric_false_truth_gate["truth_boundary"]["backfill_ready"] = 0
        mutations.append(("numeric false truth gate", numeric_false_truth_gate))

        numeric_false_segment_gate = copy.deepcopy(self.contract)
        numeric_false_segment_gate["segments"][0]["backfill_allowed"] = 0
        mutations.append(("numeric false segment gate", numeric_false_segment_gate))

        floating_segment_count = copy.deepcopy(self.contract)
        floating_segment_count["scope"]["segment_count"] = 8.0
        mutations.append(("floating segment count", floating_segment_count))

        removed_field = copy.deepcopy(self.contract)
        removed_field["field_catalog"].pop()
        mutations.append(("removed field", removed_field))

        changed_rule = copy.deepcopy(self.contract)
        changed_rule["field_rule_catalog"]["flash.pool.fee_growth_0"]["rule"] = "infer a value"
        mutations.append(("changed rule", changed_rule))

        changed_profile = copy.deepcopy(self.contract)
        changed_profile["segments"][0]["semantic_surface"]["npm"]["profile_id"] = "current-amount0-to-both"
        changed_profile["segments"][0]["semantic_surface_sha256"] = VERIFIER.canonical_sha256(
            changed_profile["segments"][0]["semantic_surface"]
        )
        mutations.append(("self-rehashed semantic mutation", changed_profile))

        removed_diff = copy.deepcopy(self.contract)
        removed_diff["segment_diffs"].pop()
        mutations.append(("removed pairwise diff", removed_diff))

        changed_provenance = copy.deepcopy(self.contract)
        changed_provenance["segments"][0]["provenance_surface"]["pool_mapping_cid"] = "QmFake"
        changed_provenance["segments"][0]["provenance_surface_sha256"] = VERIFIER.canonical_sha256(
            changed_provenance["segments"][0]["provenance_surface"]
        )
        mutations.append(("self-rehashed provenance mutation", changed_provenance))

        for label, mutation in mutations:
            with self.subTest(label=label):
                self.assert_rejected(mutation, label)

    def test_duplicate_json_keys_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="segment-field-semantics-json-") as temporary:
            path = Path(temporary) / "duplicate.json"
            path.write_text('{"format_version": 1, "format_version": 2}\n')
            with self.assertRaisesRegex(VERIFIER.VerificationError, "duplicate JSON key"):
                VERIFIER.load_json_strict(path)


if __name__ == "__main__":
    unittest.main()
