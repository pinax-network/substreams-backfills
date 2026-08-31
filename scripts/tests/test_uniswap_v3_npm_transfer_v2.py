from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VERIFIER_PATH = ROOT / "scripts/verify-uniswap-v3-npm-transfer-v2.py"
SPEC = importlib.util.spec_from_file_location("uniswap_v3_npm_transfer_v2", VERIFIER_PATH)
assert SPEC is not None and SPEC.loader is not None
VERIFIER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VERIFIER
SPEC.loader.exec_module(VERIFIER)


class NpmTransferV2Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.wasm2wat = VERIFIER.WRITER.resolve_wasm2wat(None)
        cls.sources = VERIFIER.load_sources(
            ROOT,
            recompute_wat=True,
            wasm2wat=cls.wasm2wat,
        )
        cls.contract = VERIFIER.verify_contract(
            ROOT,
            sources=cls.sources,
            recompute_wat=False,
        )
        cls.by_cid = {
            item["mapping_cid"]: item for item in cls.contract["mapping_proofs"]
        }
        cls.expected_errors = (
            VERIFIER.VerificationError,
            VERIFIER.FIELD.VerificationError,
            VERIFIER.WRITER.VerificationError,
        )

    def assert_contract_rejected(self, value: dict[str, object]) -> None:
        with self.assertRaises(self.expected_errors):
            VERIFIER.verify_contract(
                ROOT,
                value,
                sources=self.sources,
                recompute_wat=False,
            )

    def test_01_committed_contract_is_deterministic(self) -> None:
        self.assertEqual(
            self.contract,
            VERIFIER.expected_contract_from_sources(self.sources),
        )
        self.assertEqual(
            (ROOT / VERIFIER.CONTRACT_PATH).read_text(),
            VERIFIER.render(self.contract),
        )

    def test_02_exact_population_and_partition(self) -> None:
        scope = self.contract["scope"]
        self.assertEqual((scope["segment_binding_count"], scope["unique_npm_wasm_count"]), (8, 6))
        self.assertEqual(scope["field_outcome_count"], 2392)
        for segment in self.contract["segments"]:
            self.assertEqual(
                segment["semantic_surface"]["field_outcome_summary"],
                {
                    "field_outcome_count": 299,
                    "classified_stored_target_count": 38,
                    "saved_target_stored_no_setter_count": 0,
                    "derived_query_field_count": 13,
                    "outside_store_target_closure_count": 248,
                    "required_absent_overlay_count": 33,
                },
            )

    def test_03_exact_aggregate_physical_counts(self) -> None:
        aggregate = self.contract["aggregate_counts"]
        self.assertEqual(
            aggregate["unique_six_mapping_physical_totals"],
            {
                "function_count": 454,
                "direct_call_count": 2006,
                "direct_target_count": 490,
                "memory_write_count": 1270,
                "generic_setter_site_count": 166,
                "named_setter_invocation_count": 116,
                "store_get_site_count": 12,
                "store_set_site_count": 18,
                "call_indirect_count": 2,
            },
        )
        self.assertEqual(aggregate["eight_binding_lexical_semantic_field_invocation_count"], 312)
        self.assertEqual(aggregate["eight_binding_maximum_expanded_new_path_field_invocation_count"], 352)

    def test_04_six_relation_fields_are_exactly_bound(self) -> None:
        expected = {
            ("Position", "pool"),
            ("Position", "token0"),
            ("Position", "token1"),
            ("Position", "tickLower"),
            ("Position", "tickUpper"),
            ("PositionSnapshot", "pool"),
        }
        for proof in self.contract["mapping_proofs"]:
            relations = proof["relation_field_authority"]
            self.assertEqual({(item["entity"], item["field"]) for item in relations}, expected)
            self.assertTrue(all(item["receiver_and_key_authority_bound"] for item in relations))

    def test_05_existing_path_never_claims_no_setter_fields_preserved(self) -> None:
        for proof in self.contract["mapping_proofs"]:
            existing = proof["path_contract"]["accepted_existing_position"]
            self.assertEqual(len(existing["position_fields_without_a_setter_before_position_save"]), 16)
            self.assertFalse(existing["position_fields_without_setter_are_preserved_or_unchanged"])

    def test_06_store_order_and_double_transaction_save_are_not_collapsed(self) -> None:
        for proof in self.contract["mapping_proofs"]:
            paths = proof["path_contract"]
            self.assertEqual(paths["accepted_existing_position"]["store_set_order"], ["Position", "Transaction", "PositionSnapshot"])
            self.assertEqual(paths["accepted_new_position"]["store_set_order"], ["Transaction", "Position", "Transaction", "PositionSnapshot"])
            self.assertEqual(paths["accepted_new_position"]["expanded_store_set_count"], 4)

    def test_07_revert_and_fatal_boundaries_are_distinct(self) -> None:
        for proof in self.contract["mapping_proofs"]:
            paths = proof["path_contract"]
            self.assertTrue(paths["try_positions_revert"]["normal_return"])
            self.assertEqual(paths["try_positions_revert"]["store_set_count"], 0)
            self.assertTrue(paths["factory_get_pool_fatal"]["fatal_before_any_schema_constructor_setter_or_store_set"])
            self.assertFalse(paths["factory_get_pool_fatal"]["post_fatal_execution_modeled"])

    def test_08_gas_used_generation_split_is_structural_only(self) -> None:
        for proof in self.contract["mapping_proofs"]:
            gas = proof["path_contract"]["transaction_gas_used"]
            if proof["generation"].startswith("legacy"):
                self.assertEqual(gas["api_version"], "0.0.4")
                self.assertIn("gasLimit getter result", gas["structural_source"])
            else:
                self.assertEqual(gas["api_version"], "0.0.7")
                self.assertIn("literal zero", gas["structural_source"])
            self.assertFalse(gas["numeric_meaning_complete"])

    def test_09_no_transfer_exclusion_or_block_guard_is_invented(self) -> None:
        for proof in self.contract["mapping_proofs"]:
            paths = proof["path_contract"]
            self.assertTrue(paths["no_transfer_exclusion_or_historical_block_branch_in_bound_handler_path"])
            self.assertFalse(paths["global_absence_of_exclusion_literals_claimed"])

    def test_10_current_zero_named_setters_is_not_zero_writes(self) -> None:
        current = [item for item in self.contract["mapping_proofs"] if item["generation"].startswith("current")]
        self.assertEqual(len(current), 2)
        for proof in current:
            summary = proof["reachable_closure_summary"]
            self.assertEqual(summary["named_setter_invocation_count"], 0)
            self.assertEqual(summary["generic_setter_site_count"], 39)
            self.assertGreater(summary["memory_write_count"], 0)

    def test_11_constructor_id_effects_distinguish_generations(self) -> None:
        for proof in self.contract["mapping_proofs"]:
            constructors = proof["semantic_invocation_contract"]["semantic_constructor_invocations"]
            self.assertEqual([item["entity_authority"] for item in constructors], ["Position", "Transaction", "PositionSnapshot"])
            expected = "constructor_carried" if proof["generation"].startswith("legacy") else "explicit_generic_id_set"
            self.assertEqual({item["id_effect_class"] for item in constructors}, {expected})

    def test_12_indirect_table_is_closed_without_hidden_store_target(self) -> None:
        for proof in self.contract["mapping_proofs"]:
            sites = proof["schema_api_sites"]
            expected = [] if proof["generation"].startswith("legacy") else ["~lib/@graphprotocol/graph-ts/common/value/Value#displayData~anonymous|0"]
            self.assertEqual(sites["executable_call_indirect_targets"], expected)
            self.assertEqual(sites["store_removes"], [])
            self.assertEqual(sites["schema_unsets"], [])

    def test_13_direct_schema_artifacts_match_all_299_fields(self) -> None:
        self.assertEqual(len(self.contract["direct_schema_bindings"]), 3)
        self.assertEqual({item["field_count"] for item in self.contract["direct_schema_bindings"]}, {299})
        self.assertEqual(len({item["field_catalog_sha256"] for item in self.contract["direct_schema_bindings"]}), 1)

    def test_14_all_twenty_eight_diffs_are_recursive_and_nonempty(self) -> None:
        self.assertEqual(len(self.contract["segment_diffs"]), 28)
        for diff in self.contract["segment_diffs"]:
            self.assertTrue(diff["recursive_semantic_diff_paths"])
            self.assertTrue(diff["recursive_provenance_diff_paths"])
            self.assertFalse(diff["graph_oracle_compared"])

    def test_15_only_classified_stored_fields_have_setter_paths(self) -> None:
        for segment in self.contract["segments"]:
            outcomes = segment["semantic_surface"]["field_outcomes"]
            for outcome in outcomes:
                paths = outcome["setter_before_matching_save_paths"]
                classified = outcome["classified_stored_target"]
                self.assertEqual(bool(paths), classified)
                if outcome["derived_query_field"] or outcome["outside_npm_transfer_store_target_closure"]:
                    self.assertEqual(paths, [])
                if paths:
                    self.assertEqual(outcome["storage"], "stored")

    def test_16_exact_transaction_setter_path_fields_exclude_derived_collections(self) -> None:
        derived_fields = {"mints", "burns", "swaps", "flashed", "collects"}
        for segment in self.contract["segments"]:
            transaction = [
                item for item in segment["semantic_surface"]["field_outcomes"]
                if item["entity"] == "Transaction"
            ]
            self.assertEqual(
                {item["field"] for item in transaction if item["setter_before_matching_save_paths"]},
                set(VERIFIER.TRANSACTION_FIELDS),
            )
            derived = [item for item in transaction if item["storage"] == "derived"]
            self.assertEqual({item["field"] for item in derived}, derived_fields)
            self.assertTrue(all(item["path_qualified_category"] == VERIFIER.CATEGORY_DERIVED for item in derived))
            self.assertTrue(all(not item["setter_before_matching_save_paths"] for item in derived))

    def test_17_missing_segment_fails_closed(self) -> None:
        mutated = copy.deepcopy(self.contract)
        mutated["segments"].pop()
        self.assert_contract_rejected(mutated)

    def test_18_missing_mapping_proof_fails_closed(self) -> None:
        mutated = copy.deepcopy(self.contract)
        mutated["mapping_proofs"].pop()
        self.assert_contract_rejected(mutated)

    def test_19_missing_handler_body_or_call_fails_closed(self) -> None:
        mutated = copy.deepcopy(self.contract)
        mutated["mapping_proofs"][0]["reachable_function_bodies"].pop()
        mutated["mapping_proofs"][0]["direct_call_sites"].pop()
        self.assert_contract_rejected(mutated)

    def test_20_hidden_indirect_target_or_dynamic_store_fails_closed(self) -> None:
        mutated = copy.deepcopy(self.contract)
        proof = mutated["mapping_proofs"][-1]
        proof["schema_api_sites"]["executable_call_indirect_targets"].append("hidden.store.writer")
        proof["schema_api_sites"]["store_removes"].append({"target": "~lib/@graphprotocol/graph-ts/index/store.remove"})
        self.assert_contract_rejected(mutated)

    def test_21_relation_receiver_or_key_overclaim_fails_closed(self) -> None:
        mutated = copy.deepcopy(self.contract)
        relation = mutated["mapping_proofs"][0]["relation_field_authority"][0]
        relation["receiver_and_key_authority_bound"] = False
        relation["imported_value_semantics_complete"] = True
        self.assert_contract_rejected(mutated)

    def test_22_preservation_and_persistence_promotions_fail_closed(self) -> None:
        mutated = copy.deepcopy(self.contract)
        proof = mutated["mapping_proofs"][0]
        proof["path_contract"]["accepted_existing_position"]["position_fields_without_setter_are_preserved_or_unchanged"] = True
        mutated["truth_boundary"]["graph_store_persistence_proven"] = True
        self.assert_contract_rejected(mutated)

    def test_23_revert_fatal_inversion_and_order_collapse_fail_closed(self) -> None:
        mutated = copy.deepcopy(self.contract)
        paths = mutated["mapping_proofs"][0]["path_contract"]
        paths["try_positions_revert"]["normal_return"] = False
        paths["factory_get_pool_fatal"]["fatal_before_any_schema_constructor_setter_or_store_set"] = False
        paths["accepted_new_position"]["store_set_order"] = ["Position", "Transaction", "PositionSnapshot"]
        self.assert_contract_rejected(mutated)

    def test_24_gas_profile_inversion_and_invented_guard_fail_closed(self) -> None:
        mutated = copy.deepcopy(self.contract)
        proof = next(item for item in mutated["mapping_proofs"] if item["generation"].startswith("legacy"))
        proof["path_contract"]["transaction_gas_used"]["api_version"] = "0.0.7"
        proof["path_contract"]["no_transfer_exclusion_or_historical_block_branch_in_bound_handler_path"] = False
        self.assert_contract_rejected(mutated)

    def test_25_runtime_value_history_and_issue_gates_remain_false(self) -> None:
        false_gates = set(VERIFIER.FALSE_FLAGS)
        self.assertTrue(false_gates)
        self.assertTrue(all(self.contract["truth_boundary"][key] is False for key in false_gates))
        self.assertFalse(self.contract["scope"]["issue_acceptance_checkbox_completed"])

    def test_26_derived_transaction_setter_path_overclaim_fails_closed(self) -> None:
        mutated = copy.deepcopy(self.contract)
        outcome = next(
            item
            for item in mutated["segments"][0]["semantic_surface"]["field_outcomes"]
            if item["entity"] == "Transaction" and item["field"] == "mints"
        )
        outcome["setter_before_matching_save_paths"].append("invented:derived-field-setter")
        self.assert_contract_rejected(mutated)

    def test_27_duplicate_json_keys_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="npm-transfer-v2-json-") as temporary:
            path = Path(temporary) / "duplicate.json"
            path.write_text('{"field": 1, "field": 2}\n')
            with self.assertRaises(VERIFIER.VerificationError):
                VERIFIER.load_json(path)

    def test_28_compile_valid_handler_body_mutation_is_rejected(self) -> None:
        ancestry = self.sources["direct"]["ancestry_v2"]
        cid = "QmYWR79pUmVbQ42JkvB24D6AKCGtdo4UG78ZSewmFxwQdR"
        artifact = copy.deepcopy(next(item for item in ancestry["artifacts"] if item["cid"] == cid))
        inventory = next(item for item in ancestry["mapping_writer_inventories"] if item["cid"] == cid)
        original = ROOT / artifact["path"]
        wat = VERIFIER.WRITER.run_wasm2wat(self.wasm2wat, original).decode()
        memory, functions, _targets, _exports = VERIFIER.WRITER.parse_wat(wat)
        handler = functions["src/mappings/position-manager/handleTransfer"]
        lines = wat.splitlines()
        insert_at = handler.start_line - 1 + len(handler.lines) - 1
        lines.insert(insert_at, "    nop")
        wat2wasm = self.wasm2wat.with_name("wat2wasm")
        self.assertTrue(wat2wasm.is_file())
        with tempfile.TemporaryDirectory(prefix="npm-transfer-v2-wat-") as temporary:
            wat_path = Path(temporary) / "mutated.wat"
            wasm_path = Path(temporary) / "mutated.wasm"
            wat_path.write_text("\n".join(lines) + "\n")
            compiled = subprocess.run(
                [str(wat2wasm), "--debug-names", str(wat_path), "-o", str(wasm_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            artifact["path"] = str(wasm_path)
            artifact["bytes"] = wasm_path.stat().st_size
            artifact["sha256"] = hashlib.sha256(wasm_path.read_bytes()).hexdigest()
            with self.assertRaises(self.expected_errors):
                VERIFIER.prove_mapping(ROOT, self.wasm2wat, inventory, artifact)
        self.assertGreater(len(memory), 0)

    def test_29_cli_verifier_passes_with_exact_wabt(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(VERIFIER_PATH), "--wasm2wat", str(self.wasm2wat)],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("8 bindings, 6 WASMs, 2392 outcomes, 28 diffs", completed.stdout)


if __name__ == "__main__":
    unittest.main()
