from __future__ import annotations

import copy
import hashlib
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VERIFIER_PATH = ROOT / "scripts/verify-uniswap-v3-npm-liquidity-v2.py"
SPEC = importlib.util.spec_from_file_location("uniswap_v3_npm_liquidity_v2", VERIFIER_PATH)
assert SPEC is not None and SPEC.loader is not None
VERIFIER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VERIFIER
SPEC.loader.exec_module(VERIFIER)


class NpmLiquidityV2Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.wasm2wat = VERIFIER.WRITER.resolve_wasm2wat(None)
        cls.sources = VERIFIER.load_sources(ROOT, recompute_wat=True, wasm2wat=cls.wasm2wat)
        cls.contract = VERIFIER.verify_contract(ROOT, sources=cls.sources, recompute_wat=False)
        cls.expected_errors = (
            VERIFIER.VerificationError,
            VERIFIER.FIELD.VerificationError,
            VERIFIER.WRITER.VerificationError,
        )

    def assert_contract_rejected(self, value: dict[str, object]) -> None:
        with self.assertRaises(self.expected_errors):
            VERIFIER.verify_contract(ROOT, value, sources=self.sources, recompute_wat=False)

    def handler_proofs(self):
        for proof in self.contract["mapping_proofs"]:
            for key in VERIFIER.HANDLERS:
                yield proof, key, proof["handler_proofs"][key]

    def test_01_committed_contract_is_deterministic(self) -> None:
        self.assertEqual(self.contract, VERIFIER.expected_contract_from_sources(self.sources))
        self.assertEqual((ROOT / VERIFIER.CONTRACT_PATH).read_text(), VERIFIER.render(self.contract))

    def test_02_exact_scope_and_independent_union_denominators(self) -> None:
        scope = self.contract["scope"]
        self.assertEqual((scope["segment_binding_count"], scope["unique_npm_wasm_count"]), (8, 6))
        self.assertEqual((scope["independent_handler_field_outcome_count"], scope["independent_handler_required_absent_overlay_count"]), (4784, 528))
        self.assertEqual((scope["derived_paired_union_field_outcome_count"], scope["derived_paired_union_required_absent_overlay_count"]), (2392, 264))

    def test_03_each_handler_and_union_has_exact_299_partition(self) -> None:
        expected = {
            "field_outcome_count": 299,
            "classified_stored_target_count": 38,
            "saved_target_stored_no_setter_count": 0,
            "derived_query_field_count": 13,
            "outside_store_target_closure_count": 248,
            "required_absent_overlay_count": 33,
        }
        for segment in self.contract["segments"]:
            for key in VERIFIER.HANDLERS:
                self.assertEqual(segment["handler_surfaces"][key]["semantic_surface"]["field_outcome_summary"], expected)
            self.assertEqual(segment["paired_union_surface"]["semantic_surface"]["field_outcome_summary"], expected)

    def test_04_unique_six_physical_totals_are_exact(self) -> None:
        self.assertEqual(
            self.contract["aggregate_counts"]["unique_six_physical_totals"],
            {
                "increase": VERIFIER._counts(559, 2555, 625, 1328, 174, 132, 20, 18, 0, 0, 12, 2, 222, 262, 200),
                "decrease": VERIFIER._counts(559, 2557, 631, 1328, 174, 132, 20, 18, 0, 0, 12, 2, 224, 264, 202),
                "paired_union": VERIFIER._counts(565, 2789, 631, 1360, 180, 144, 24, 18, 0, 0, 12, 2, 224, 264, 202),
            },
        )

    def test_05_eight_binding_weighted_physical_totals_are_exact(self) -> None:
        self.assertEqual(
            self.contract["aggregate_counts"]["eight_binding_weighted_physical_totals"],
            {
                "increase": VERIFIER._counts(771, 3379, 859, 1682, 218, 198, 26, 24, 0, 0, 16, 2, 280, 338, 262),
                "decrease": VERIFIER._counts(771, 3381, 867, 1682, 218, 198, 26, 24, 0, 0, 16, 2, 282, 340, 264),
                "paired_union": VERIFIER._counts(779, 3683, 867, 1714, 224, 216, 30, 24, 0, 0, 16, 2, 282, 340, 264),
            },
        )

    def test_06_handler_semantic_denominators_are_separate_and_exact(self) -> None:
        for _mapping, _key, proof in self.handler_proofs():
            semantic = proof["semantic_invocation_contract"]
            self.assertEqual((semantic["lexical_semantic_field_invocation_count"], semantic["distinct_semantic_field_count"]), (43, 38))
            self.assertEqual((semantic["maximum_expanded_existing_position_field_invocation_count"], semantic["maximum_expanded_new_position_field_invocation_count"]), (26, 48))
            self.assertEqual([item["field_invocation_count"] for item in semantic["lexical_semantic_invocation_ledger"]], [17, 3, 2, 16, 5])

    def test_07_union_is_a_set_union_not_handler_composition(self) -> None:
        for proof in self.contract["mapping_proofs"]:
            union = proof["paired_union_proof"]
            self.assertEqual((union["lexical_site_edge_union_field_invocation_count"], union["handler_attributed_lexical_field_invocation_count"]), (46, 86))
            self.assertFalse(union["sequential_composition_claimed"])
            self.assertFalse(union["event_order_claimed"])

    def test_08_nine_relation_paths_and_shared_transaction_caveats_are_bound(self) -> None:
        expected = {
            ("Position", "pool"), ("Position", "token0"), ("Position", "token1"),
            ("Position", "tickLower"), ("Position", "tickUpper"), ("Position", "transaction"),
            ("PositionSnapshot", "pool"), ("PositionSnapshot", "position"),
            ("PositionSnapshot", "transaction"),
        }
        for _mapping, _key, proof in self.handler_proofs():
            self.assertEqual({(item["entity"], item["field"]) for item in proof["relation_field_authority"]}, expected)
            shared = proof["shared_transaction_contract"]
            self.assertEqual((shared["new_position_invocation_count"], shared["existing_position_invocation_count"]), (2, 1))
            self.assertEqual(
                (shared["hit_field_effect_count"], shared["miss_field_effect_count"]),
                (4, 5),
            )
            self.assertEqual(
                (shared["hit_store_set_count"], shared["miss_store_set_count"]),
                (1, 1),
            )
            self.assertFalse(shared["intra_handler_visibility_between_store_set_and_later_store_get_proven"])
            self.assertFalse(shared["shared_transaction_last_writer_complete"])

    def test_09_transaction_reads_remain_independent_but_writes_are_unconditional(self) -> None:
        for _mapping, _key, proof in self.handler_proofs():
            paths = proof["path_contract"]
            self.assertEqual(paths["accepted_existing_position"]["store_set_orders"], [["Position", "Transaction", "PositionSnapshot"]])
            self.assertEqual(paths["accepted_new_position"]["store_set_orders"], [["Transaction", "Position", "Transaction", "PositionSnapshot"]])
            self.assertFalse(paths["transaction_store_get_visibility_between_the_two_new_path_calls_proven"])

    def test_10_success_and_update_revert_effect_counts_are_exact(self) -> None:
        for _mapping, _key, proof in self.handler_proofs():
            paths = proof["path_contract"]
            self.assertEqual(
                paths["accepted_existing_position"]["field_effect_counts"],
                {
                    "fee_refresh_success_transaction_hit": 25,
                    "fee_refresh_success_transaction_miss": 26,
                    "fee_refresh_revert_transaction_hit": 23,
                    "fee_refresh_revert_transaction_miss": 24,
                },
            )
            self.assertEqual(
                paths["accepted_new_position"]["field_effect_counts"],
                {
                    "fee_refresh_success_zero_transaction_misses": 46,
                    "fee_refresh_success_one_transaction_miss": 47,
                    "fee_refresh_success_two_transaction_misses": 48,
                    "fee_refresh_revert_zero_transaction_misses": 44,
                    "fee_refresh_revert_one_transaction_miss": 45,
                    "fee_refresh_revert_two_transaction_misses": 46,
                },
            )
            self.assertEqual(paths["update_fee_vars_revert"]["setter_count"], 0)
            self.assertTrue(paths["update_fee_vars_revert"]["caller_continues_to_position_save_and_snapshot"])

    def test_11_try_revert_factory_fatal_excluded_and_trap_prefixes_are_distinct(self) -> None:
        for _mapping, _key, proof in self.handler_proofs():
            paths = proof["path_contract"]
            self.assertTrue(paths["try_positions_revert"]["normal_return"])
            self.assertEqual((paths["try_positions_revert"]["contract_call_count"], paths["try_positions_revert"]["store_set_count"]), (1, 0))
            self.assertTrue(paths["factory_get_pool_fatal"]["fatal_before_any_schema_constructor_setter_or_store_set"])
            self.assertEqual(paths["factory_get_pool_fatal"]["contract_call_count_before_fatal"], 2)
            self.assertEqual(paths["excluded_pool_guard"]["new_path_field_effect_counts"], [21, 22])
            self.assertEqual(paths["excluded_pool_guard"]["new_path_store_orders"], [["Transaction"]])
            self.assertFalse(paths["trap_prefixes"]["post_fatal_execution_modeled"])

    def test_12_token_missing_or_null_profiles_stop_at_exact_prefix(self) -> None:
        for mapping, _key, proof in self.handler_proofs():
            token = proof["path_contract"]["token_branch"]
            self.assertEqual((token["existing_position_schema_field_effect_count_before_stop"], token["new_position_schema_field_effect_counts_before_stop"]), (0, [21, 22]))
            self.assertEqual(token["new_position_store_orders_before_stop"], [["Transaction"]])
            if mapping["generation"].startswith("legacy"):
                self.assertTrue(token["legacy_missing_token_is_a_fatal_prefix"])
                self.assertFalse(token["current_null_token_is_a_normal_early_return_prefix"])
            else:
                self.assertFalse(token["legacy_missing_token_is_a_fatal_prefix"])
                self.assertTrue(token["current_null_token_is_a_normal_early_return_prefix"])

    def test_13_historical_guards_are_profile_specific(self) -> None:
        for mapping, _key, proof in self.handler_proofs():
            guard = proof["path_contract"]["historical_block_guard"]
            observed = proof["semantic_invocation_contract"]["historical_guard"]
            if mapping["profile_id"] == "legacy-no-block-guard":
                self.assertFalse(guard["present"])
                self.assertIsNone(observed)
            else:
                self.assertTrue(guard["present"])
                self.assertEqual(guard["block"], 14317993)
                self.assertEqual(observed["comparison_model"], guard["model"])

    def test_14_current_decrease_null_liquidity_abort_is_not_increase_or_legacy(self) -> None:
        for mapping, key, proof in self.handler_proofs():
            branch = proof["path_contract"]["decrease_null_liquidity_branch"]
            present = key == "decrease" and mapping["generation"].startswith("current")
            self.assertEqual(branch["present_as_explicit_abort_only_in_current_generation"], present)
            self.assertEqual(bool(proof["semantic_invocation_contract"]["handler_prefix_call_indexes"]["null_liquidity_abort"]), present)
            if present:
                self.assertEqual(branch["existing_position_schema_field_effect_count_before_fatal"], 0)
                self.assertEqual(branch["new_position_schema_field_effect_counts_before_fatal"], [21, 22])
                self.assertEqual(branch["new_position_store_orders_before_fatal"], [["Transaction"]])
            else:
                self.assertIsNone(branch["existing_position_schema_field_effect_count_before_fatal"])
                self.assertEqual(branch["new_position_schema_field_effect_counts_before_fatal"], [])
                self.assertEqual(branch["new_position_store_orders_before_fatal"], [])

    def test_15_handler_setter_orders_and_numeric_result_flow_are_distinct(self) -> None:
        for _mapping, key, proof in self.handler_proofs():
            semantic = proof["semantic_invocation_contract"]
            self.assertEqual(semantic["handler_setter_keys"], VERIFIER.HANDLERS[key]["field_keys"])
            self.assertTrue(semantic["numeric_operator_result_reaches_liquidity_setter"])
            self.assertFalse(semantic["numeric_operator_meaning_complete"])

    def test_16_legacy_decrease_params_alias_is_physical_only(self) -> None:
        for mapping, key, proof in self.handler_proofs():
            semantic = proof["semantic_invocation_contract"]
            expected = mapping["generation"].startswith("legacy") and key == "decrease"
            self.assertEqual(semantic["legacy_decrease_uses_increase_liquidity_params_symbols"], expected)
            self.assertFalse(semantic["legacy_params_alias_meaning_complete"])

    def test_17_gas_used_generation_split_is_structural_only(self) -> None:
        for mapping, _key, proof in self.handler_proofs():
            gas = proof["path_contract"]["transaction_gas_used"]
            self.assertIn("gasLimit getter result" if mapping["generation"].startswith("legacy") else "literal zero", gas["structural_source"])
            self.assertFalse(gas["numeric_meaning_complete"])

    def test_18_constructor_id_effects_distinguish_generations(self) -> None:
        for mapping, _key, proof in self.handler_proofs():
            constructors = proof["semantic_invocation_contract"]["semantic_constructor_invocations"]
            self.assertEqual([item["entity_authority"] for item in constructors], ["Position", "Transaction", "PositionSnapshot"])
            expected = "constructor_carried" if mapping["generation"].startswith("legacy") else "explicit_generic_id_set"
            self.assertEqual({item["id_effect_class"] for item in constructors}, {expected})

    def test_19_indirect_table_remove_unset_and_store_targets_are_closed(self) -> None:
        for mapping in self.contract["mapping_proofs"]:
            for proof in [*mapping["handler_proofs"].values(), mapping["paired_union_proof"]]:
                sites = proof["schema_api_sites"]
                expected = [] if mapping["generation"].startswith("legacy") else ["~lib/@graphprotocol/graph-ts/common/value/Value#displayData~anonymous|0"]
                self.assertEqual(sites["executable_call_indirect_targets"], expected)
                self.assertEqual((sites["store_removes"], sites["schema_unsets"]), ([], []))
                self.assertEqual(proof["reachable_closure_summary"]["physical_store_set_target_count"], 3)

    def test_19b_all_six_transaction_helpers_bind_the_exact_control_boundary(self) -> None:
        for mapping in self.contract["mapping_proofs"]:
            helper = mapping["handler_proofs"]["increase"]["shared_transaction_contract"]["retained_wat_control_contract"]
            legacy = mapping["generation"].startswith("legacy")
            self.assertEqual(
                (helper["store_null_branch"]["function_line_start"], helper["store_null_branch"]["function_line_end"]),
                (10, 17) if legacy else (10, 38),
            )
            self.assertEqual(helper["store_null_branch"]["guarded_effect_fields"], ["id"])
            self.assertEqual(
                [item["site"]["function_line_index"] for item in helper["unconditional_field_effects"]],
                [22, 27, 34, 41] if legacy else [58, 78, 97, 117],
            )
            self.assertEqual(helper["unconditional_store_set"]["function_line_index"], 43 if legacy else 165)
            self.assertTrue(helper["unconditional_store_set"]["outside_store_null_branch"])
            self.assertEqual(
                helper["id_effect"]["effect_model"],
                "constructor_carried" if legacy else "explicit_generic_id_set",
            )

    def test_20_direct_schemas_match_the_exact_299_field_catalog(self) -> None:
        self.assertEqual(len(self.contract["direct_schema_bindings"]), 3)
        self.assertEqual({item["field_count"] for item in self.contract["direct_schema_bindings"]}, {299})
        self.assertEqual(len({item["field_catalog_sha256"] for item in self.contract["direct_schema_bindings"]}), 1)

    def test_21_all_twenty_eight_axes_have_both_handlers_and_union_diffs(self) -> None:
        self.assertEqual(len(self.contract["segment_diffs"]), 28)
        for diff in self.contract["segment_diffs"]:
            self.assertEqual(set(diff["handler_diffs"]), set(VERIFIER.HANDLERS))
            for nested in [*diff["handler_diffs"].values(), diff["paired_union_diff"]]:
                self.assertTrue(nested["recursive_semantic_diff_paths"])
                self.assertTrue(nested["recursive_provenance_diff_paths"])
            self.assertFalse(diff["graph_oracle_compared"])

    def test_22_all_eight_within_segment_handler_diffs_are_nonempty(self) -> None:
        self.assertEqual(len(self.contract["within_segment_handler_diffs"]), 8)
        for diff in self.contract["within_segment_handler_diffs"]:
            self.assertTrue(diff["recursive_semantic_diff_paths"])
            self.assertTrue(diff["recursive_provenance_diff_paths"])
            self.assertFalse(diff["event_order_compared"])
            self.assertFalse(diff["store_persistence_compared"])

    def test_23_required_absence_overlay_is_11_12_10_on_every_surface(self) -> None:
        expected = {"Collect": 11, "Flash": 12, "TickHourData": 10}
        for segment in self.contract["segments"]:
            surfaces = [
                *(segment["handler_surfaces"][key]["semantic_surface"] for key in VERIFIER.HANDLERS),
                segment["paired_union_surface"]["semantic_surface"],
            ]
            for surface in surfaces:
                outcomes = surface["field_outcomes"]
                observed = {entity: sum(item["entity"] == entity and item["required_absent_overlay"] for item in outcomes) for entity in expected}
                self.assertEqual(observed, expected)

    def test_23b_only_exact_classified_fields_have_setter_paths(self) -> None:
        derived_transaction_fields = {"mints", "burns", "swaps", "flashed", "collects"}
        for segment in self.contract["segments"]:
            surfaces = [
                *(segment["handler_surfaces"][key]["semantic_surface"] for key in VERIFIER.HANDLERS),
                segment["paired_union_surface"]["semantic_surface"],
            ]
            for surface in surfaces:
                for outcome in surface["field_outcomes"]:
                    paths = outcome["setter_before_matching_save_paths"]
                    self.assertEqual(bool(paths), outcome["classified_stored_target"])
                    if outcome["entity"] == "Transaction" and outcome["field"] in derived_transaction_fields:
                        self.assertTrue(outcome["derived_query_field"])
                        self.assertEqual(paths, [])
                    if outcome["entity"] == "Transaction" and outcome["field"] == "id":
                        self.assertTrue(all("store-miss-id-effect" in path for path in paths))
                    if outcome["entity"] == "Transaction" and outcome["field"] in {"blockNumber", "timestamp", "gasUsed", "gasPrice"}:
                        self.assertTrue(all("store-hit-or-miss-unconditional-effect" in path for path in paths))

    def test_24_no_setter_persistence_runtime_history_or_issue_gate_is_promoted(self) -> None:
        self.assertTrue(all(self.contract["truth_boundary"][key] is False for key in VERIFIER.FALSE_FLAGS))
        self.assertFalse(self.contract["scope"]["issue_acceptance_checkbox_completed"])
        for _mapping, _key, proof in self.handler_proofs():
            self.assertFalse(proof["path_contract"]["accepted_existing_position"]["position_fields_without_setter_are_preserved_or_unchanged"])

    def test_25_missing_segment_or_handler_fails_closed(self) -> None:
        missing_segment = copy.deepcopy(self.contract)
        missing_segment["segments"].pop()
        self.assert_contract_rejected(missing_segment)
        missing_handler = copy.deepcopy(self.contract)
        del missing_handler["mapping_proofs"][0]["handler_proofs"]["decrease"]
        self.assert_contract_rejected(missing_handler)

    def test_26_physical_body_count_and_union_digest_mutations_fail_closed(self) -> None:
        mutated = copy.deepcopy(self.contract)
        handler = mutated["mapping_proofs"][0]["handler_proofs"]["increase"]
        handler["reachable_function_bodies"].pop()
        handler["reachable_closure_summary"]["direct_call_count"] += 1
        mutated["mapping_proofs"][0]["paired_union_proof"]["reachable_function_set_sha256"] = "0" * 64
        self.assert_contract_rejected(mutated)

    def test_27_hidden_indirect_remove_or_unset_target_fails_closed(self) -> None:
        mutated = copy.deepcopy(self.contract)
        union = mutated["mapping_proofs"][-1]["paired_union_proof"]
        union["schema_api_sites"]["executable_call_indirect_targets"].append("hidden.store.writer")
        union["schema_api_sites"]["store_removes"].append({"target": "store.remove"})
        union["schema_api_sites"]["schema_unsets"].append({"target": "Position#unset:owner"})
        self.assert_contract_rejected(mutated)

    def test_28_relation_visibility_preservation_and_numeric_overclaims_fail_closed(self) -> None:
        mutated = copy.deepcopy(self.contract)
        proof = mutated["mapping_proofs"][0]["handler_proofs"]["increase"]
        proof["relation_field_authority"][0]["imported_value_semantics_complete"] = True
        proof["shared_transaction_contract"]["intra_handler_visibility_between_store_set_and_later_store_get_proven"] = True
        proof["path_contract"]["accepted_existing_position"]["position_fields_without_setter_are_preserved_or_unchanged"] = True
        mutated["truth_boundary"]["increase_liquidity_arithmetic_semantics_complete"] = True
        self.assert_contract_rejected(mutated)

    def test_29_revert_fatal_token_guard_and_store_order_inversions_fail_closed(self) -> None:
        mutated = copy.deepcopy(self.contract)
        paths = mutated["mapping_proofs"][0]["handler_proofs"]["decrease"]["path_contract"]
        paths["try_positions_revert"]["normal_return"] = False
        paths["factory_get_pool_fatal"]["post_fatal_execution_modeled"] = True
        paths["token_branch"]["new_position_schema_field_effect_counts_before_stop"] = [0]
        paths["accepted_new_position"]["store_set_orders"] = [["Position", "Transaction", "PositionSnapshot"]]
        self.assert_contract_rejected(mutated)

    def test_30_guard_null_abort_and_legacy_alias_mutations_fail_closed(self) -> None:
        mutated = copy.deepcopy(self.contract)
        legacy = next(item for item in mutated["mapping_proofs"] if item["profile_id"] == "legacy-block-guard")
        legacy["handler_proofs"]["decrease"]["semantic_invocation_contract"]["historical_guard"]["block"] = 1
        legacy["handler_proofs"]["decrease"]["semantic_invocation_contract"]["legacy_decrease_uses_increase_liquidity_params_symbols"] = False
        current = next(item for item in mutated["mapping_proofs"] if item["generation"].startswith("current"))
        current["handler_proofs"]["decrease"]["path_contract"]["decrease_null_liquidity_branch"]["present_as_explicit_abort_only_in_current_generation"] = False
        self.assert_contract_rejected(mutated)

    def test_31_handler_union_order_composition_and_last_writer_promotions_fail_closed(self) -> None:
        mutated = copy.deepcopy(self.contract)
        mutated["mapping_proofs"][0]["paired_union_proof"]["sequential_composition_claimed"] = True
        mutated["segments"][0]["paired_union_surface"]["semantic_surface"]["handler_event_order_complete"] = True
        mutated["truth_boundary"]["shared_transaction_last_writer_complete"] = True
        self.assert_contract_rejected(mutated)

    def test_32_partition_overlay_and_diff_deletions_fail_closed(self) -> None:
        mutated = copy.deepcopy(self.contract)
        outcomes = mutated["segments"][0]["handler_surfaces"]["increase"]["semantic_surface"]["field_outcomes"]
        outcomes[0]["path_qualified_category"] = VERIFIER.CATEGORY_OUTSIDE
        mutated["segment_diffs"].pop()
        mutated["within_segment_handler_diffs"].pop()
        self.assert_contract_rejected(mutated)

    def test_33_duplicate_json_keys_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="npm-liquidity-v2-json-") as temporary:
            path = Path(temporary) / "duplicate.json"
            path.write_text('{"field": 1, "field": 2}\n')
            with self.assertRaises(VERIFIER.VerificationError):
                VERIFIER.load_json(path)

    def test_34_compile_valid_mutations_of_both_handlers_are_rejected(self) -> None:
        ancestry = self.sources["direct"]["ancestry_v2"]
        cid = "QmYWR79pUmVbQ42JkvB24D6AKCGtdo4UG78ZSewmFxwQdR"
        base_artifact = next(item for item in ancestry["artifacts"] if item["cid"] == cid)
        inventory = next(item for item in ancestry["mapping_writer_inventories"] if item["cid"] == cid)
        original = ROOT / base_artifact["path"]
        wat = VERIFIER.WRITER.run_wasm2wat(self.wasm2wat, original).decode()
        _memory, functions, _targets, _exports = VERIFIER.WRITER.parse_wat(wat)
        wat2wasm = self.wasm2wat.with_name("wat2wasm")
        self.assertTrue(wat2wasm.is_file())
        for handler_name in (VERIFIER.HANDLERS["increase"]["function"], VERIFIER.HANDLERS["decrease"]["function"]):
            lines = wat.splitlines()
            handler = functions[handler_name]
            lines.insert(handler.start_line - 1 + len(handler.lines) - 1, "    nop")
            with tempfile.TemporaryDirectory(prefix="npm-liquidity-v2-wat-") as temporary:
                wat_path = Path(temporary) / "mutated.wat"
                wasm_path = Path(temporary) / "mutated.wasm"
                wat_path.write_text("\n".join(lines) + "\n")
                completed = subprocess.run([str(wat2wasm), "--debug-names", str(wat_path), "-o", str(wasm_path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                artifact = copy.deepcopy(base_artifact)
                artifact.update(path=str(wasm_path), bytes=wasm_path.stat().st_size, sha256=hashlib.sha256(wasm_path.read_bytes()).hexdigest())
                with self.assertRaises(self.expected_errors):
                    VERIFIER.prove_mapping(ROOT, self.wasm2wat, inventory, artifact)

    def test_34b_transaction_setters_moved_under_null_branch_are_rejected(self) -> None:
        ancestry = self.sources["direct"]["ancestry_v2"]
        cid = "QmYWR79pUmVbQ42JkvB24D6AKCGtdo4UG78ZSewmFxwQdR"
        artifact = next(item for item in ancestry["artifacts"] if item["cid"] == cid)
        wat = VERIFIER.WRITER.run_wasm2wat(self.wasm2wat, ROOT / artifact["path"]).decode()
        memory, functions, _targets, _exports = VERIFIER.WRITER.parse_wat(wat)
        function = functions["src/utils/index/loadTransaction"]
        store_callsites = VERIFIER.WRITER.extract_store_set_callsites(functions, memory)
        original = VERIFIER._transaction_helper_contract(function, memory, "legacy-generated-setters", store_callsites)
        self.assertEqual(original["store_hit"]["field_effect_count"], 4)
        lines = list(function.lines)
        branch_end = lines.pop(17)
        lines.insert(42, branch_end)
        mutated = VERIFIER.WRITER.WatFunction(function.name, function.start_line, tuple(lines), function.function_index)
        with self.assertRaises(self.expected_errors):
            VERIFIER._transaction_helper_contract(mutated, memory, "legacy-generated-setters", store_callsites)

    def test_35_two_in_memory_regenerations_are_byte_identical(self) -> None:
        first = VERIFIER.render(VERIFIER.expected_contract_from_sources(self.sources))
        second = VERIFIER.render(VERIFIER.expected_contract_from_sources(self.sources))
        self.assertEqual(first, second)
        self.assertEqual(hashlib.sha256(first.encode()).hexdigest(), hashlib.sha256(second.encode()).hexdigest())

    def test_36_cli_verifier_passes_with_exact_wabt(self) -> None:
        completed = subprocess.run([sys.executable, str(VERIFIER_PATH), "--wasm2wat", str(self.wasm2wat)], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("8 bindings, 6 WASMs, 4784 independent outcomes, 28 diffs", completed.stdout)


if __name__ == "__main__":
    unittest.main()
