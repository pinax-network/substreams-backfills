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
VERIFIER_PATH = ROOT / "scripts/verify-uniswap-v3-npm-collect-v2.py"
SPEC = importlib.util.spec_from_file_location("uniswap_v3_npm_collect_v2", VERIFIER_PATH)
assert SPEC is not None and SPEC.loader is not None
VERIFIER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VERIFIER
SPEC.loader.exec_module(VERIFIER)


class NpmCollectV2Test(unittest.TestCase):
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
                    "setter_path_bearing_outcome_count": 38,
                    "nonclassified_setter_path_outcome_count": 0,
                },
            )

    def test_03_exact_aggregate_physical_counts(self) -> None:
        aggregate = self.contract["aggregate_counts"]
        self.assertEqual(
            aggregate["unique_six_mapping_physical_totals"],
            {
                "function_count": 539,
                "direct_call_count": 2424,
                "direct_target_count": 600,
                "memory_write_count": 1312,
                "generic_setter_site_count": 172,
                "named_setter_invocation_count": 126,
                "store_get_site_count": 17,
                "store_set_site_count": 18,
                "store_remove_site_count": 0,
                "schema_unset_site_count": 0,
                "ethereum_call_site_count": 12,
                "call_indirect_count": 2,
                "abort_call_site_count": 220,
                "unreachable_instruction_count": 259,
                "unreachable_function_count": 197,
            },
        )
        self.assertEqual(
            aggregate["eight_binding_weighted_physical_totals"],
            {
                "function_count": 725,
                "direct_call_count": 3128,
                "direct_target_count": 798,
                "memory_write_count": 1658,
                "generic_setter_site_count": 216,
                "named_setter_invocation_count": 186,
                "store_get_site_count": 21,
                "store_set_site_count": 24,
                "store_remove_site_count": 0,
                "schema_unset_site_count": 0,
                "ethereum_call_site_count": 16,
                "call_indirect_count": 2,
                "abort_call_site_count": 278,
                "unreachable_instruction_count": 333,
                "unreachable_function_count": 257,
            },
        )
        self.assertEqual((aggregate["unique_six_lexical_semantic_field_invocation_count"], aggregate["unique_six_maximum_expanded_new_path_field_invocation_count"]), (250, 280))
        self.assertEqual((aggregate["eight_binding_lexical_semantic_field_invocation_count"], aggregate["eight_binding_maximum_expanded_new_path_field_invocation_count"]), (330, 370))

    def test_04_profile_specific_lexical_and_expanded_counts_are_exact(self) -> None:
        no_amount = "mainnet-no-collect-amounts"
        for proof in self.contract["mapping_proofs"]:
            semantic = proof["semantic_invocation_contract"]
            expected = (40, 45) if proof["profile_id"] == no_amount else (42, 47)
            self.assertEqual((semantic["lexical_semantic_field_invocation_count"], semantic["maximum_expanded_new_position_field_invocation_count"]), expected)
            self.assertEqual(semantic["distinct_semantic_field_count"], 38)

    def test_05_nine_relation_and_transaction_fields_are_exactly_bound(self) -> None:
        expected = {
            ("Position", "pool"),
            ("Position", "token0"),
            ("Position", "token1"),
            ("Position", "tickLower"),
            ("Position", "tickUpper"),
            ("Position", "transaction"),
            ("PositionSnapshot", "pool"),
            ("PositionSnapshot", "position"),
            ("PositionSnapshot", "transaction"),
        }
        for proof in self.contract["mapping_proofs"]:
            relations = proof["relation_field_authority"]
            self.assertEqual({(item["entity"], item["field"]) for item in relations}, expected)
            self.assertTrue(all(item["receiver_and_key_authority_bound"] for item in relations))
            shared = proof["shared_transaction_contract"]
            self.assertEqual((shared["new_position_invocation_count"], shared["existing_position_invocation_count"]), (2, 1))
            self.assertEqual((shared["successful_hit_field_effect_count"], shared["successful_miss_field_effect_count"]), (4, 5))
            self.assertEqual(shared["successful_invocation_transaction_store_set_count_on_hit_or_miss"], 1)
            self.assertTrue(shared["only_id_effect_is_store_miss_conditional"])
            self.assertFalse(shared["intra_handler_visibility_between_store_set_and_later_store_get_proven"])

    def test_06_existing_path_never_claims_no_setter_fields_preserved(self) -> None:
        for proof in self.contract["mapping_proofs"]:
            existing = proof["path_contract"]["accepted_existing_position"]
            self.assertFalse(existing["position_fields_without_setter_are_preserved_or_unchanged"])

    def test_07_transaction_hit_miss_effects_differ_but_store_orders_do_not(self) -> None:
        for proof in self.contract["mapping_proofs"]:
            paths = proof["path_contract"]
            handler_effects = proof["semantic_invocation_contract"]["handler_fee_setter_count"]
            self.assertEqual(
                paths["accepted_existing_position"]["field_effect_counts"],
                {
                    "fee_refresh_success_transaction_hit": handler_effects + 22,
                    "fee_refresh_success_transaction_miss": handler_effects + 23,
                    "fee_refresh_revert_transaction_hit": handler_effects + 20,
                    "fee_refresh_revert_transaction_miss": handler_effects + 21,
                },
            )
            self.assertEqual(
                paths["accepted_new_position"]["field_effect_counts"],
                {
                    "fee_refresh_success_zero_transaction_misses": handler_effects + 43,
                    "fee_refresh_success_one_transaction_miss": handler_effects + 44,
                    "fee_refresh_success_two_transaction_misses": handler_effects + 45,
                    "fee_refresh_revert_zero_transaction_misses": handler_effects + 41,
                    "fee_refresh_revert_one_transaction_miss": handler_effects + 42,
                    "fee_refresh_revert_two_transaction_misses": handler_effects + 43,
                },
            )
            self.assertEqual(paths["accepted_existing_position"]["store_set_orders"], [["Position", "Transaction", "PositionSnapshot"]])
            self.assertEqual(paths["accepted_new_position"]["store_set_orders"], [["Transaction", "Position", "Transaction", "PositionSnapshot"]])
            self.assertFalse(paths["transaction_store_get_visibility_between_the_two_new_path_calls_proven"])

    def test_08_revert_fatal_excluded_and_update_revert_boundaries_are_distinct(self) -> None:
        for proof in self.contract["mapping_proofs"]:
            paths = proof["path_contract"]
            self.assertTrue(paths["try_positions_revert"]["normal_return"])
            self.assertEqual(paths["try_positions_revert"]["contract_call_count"], 1)
            self.assertEqual(paths["try_positions_revert"]["store_set_count"], 0)
            self.assertTrue(paths["factory_get_pool_fatal"]["fatal_before_any_schema_constructor_setter_or_store_set"])
            self.assertEqual(paths["factory_get_pool_fatal"]["contract_call_count_before_fatal"], 2)
            self.assertFalse(paths["factory_get_pool_fatal"]["post_fatal_execution_modeled"])
            excluded = paths["excluded_pool_guard"]
            self.assertEqual(excluded["new_path_field_effect_counts"], {"transaction_hit": 21, "transaction_miss": 22})
            self.assertEqual(excluded["new_path_store_orders"], {"transaction_hit": ["Transaction"], "transaction_miss": ["Transaction"]})
            self.assertTrue(excluded["guard_precedes_handler_amount_update_position_save_and_snapshot"])
            self.assertEqual(paths["update_fee_vars_revert"]["setter_count"], 0)
            self.assertTrue(paths["update_fee_vars_revert"]["caller_continues_to_position_save_and_snapshot"])
            traps = paths["trap_prefixes"]
            self.assertEqual(traps["position_save_trap"]["new_prior_completed_store_order"], ["Transaction"])
            self.assertTrue(traps["position_save_trap"]["new_prefix_has_transaction_save_on_hit_and_miss"])
            self.assertEqual(
                traps["snapshot_pre_transaction_required_getter_trap"]["new_prior_completed_store_order"],
                ["Transaction", "Position"],
            )
            self.assertEqual(
                traps["snapshot_post_transaction_required_getter_or_save_trap"]["new_prior_completed_store_order"],
                ["Transaction", "Position", "Transaction"],
            )
            self.assertEqual(
                traps["load_transaction_incomplete_invocation_trap"]["common_setter_or_save_trap_paths"],
                ["store hit", "store miss"],
            )
            ledgers = paths["ordered_nested_helper_field_ledgers"]
            self.assertEqual(ledgers["new_position_get_position"]["before_load_transaction"], list(VERIFIER.POSITION_FIELDS[:14]))
            self.assertEqual(ledgers["new_position_get_position"]["after_load_transaction"], list(VERIFIER.POSITION_FIELDS[14:]))
            self.assertEqual(ledgers["position_snapshot"]["before_load_transaction"], list(VERIFIER.SNAPSHOT_FIELDS[:13]))
            self.assertEqual(ledgers["position_snapshot"]["after_load_transaction"], list(VERIFIER.SNAPSHOT_FIELDS[13:]))

    def test_09_profile_specific_fee_keys_and_token_branches(self) -> None:
        expected = {
            "mainnet-root-correct-collect": ["collectedFeesToken0", "collectedFeesToken1"],
            "mainnet-second-fee0-overwrite": ["collectedFeesToken0", "collectedFeesToken0"],
            "mainnet-no-collect-amounts": [],
            "base-root-amount0-to-both": ["collectedFeesToken0", "collectedFeesToken1"],
            "current-amount0-to-both": ["collectedFeesToken0", "collectedFeesToken1"],
        }
        for proof in self.contract["mapping_proofs"]:
            semantic = proof["semantic_invocation_contract"]
            self.assertEqual(semantic["handler_fee_setter_keys"], expected[proof["profile_id"]])
            token = proof["path_contract"]["token_branch"]
            if proof["generation"].startswith("current"):
                self.assertTrue(token["current_null_token_continues_with_zero_handler_fee_setters"])
                self.assertEqual(
                    token["current_null_token_fee_refresh_success_field_effect_counts_new"],
                    {"zero_transaction_misses": 43, "one_transaction_miss": 44, "two_transaction_misses": 45},
                )
                self.assertEqual(
                    token["current_null_token_fee_refresh_success_field_effect_counts_existing"],
                    {"transaction_hit": 22, "transaction_miss": 23},
                )
                self.assertEqual(
                    token["current_null_token_store_set_order_new"],
                    ["Transaction", "Position", "Transaction", "PositionSnapshot"],
                )
            else:
                self.assertFalse(token["current_null_token_continues_with_zero_handler_fee_setters"])
                if proof["semantic_invocation_contract"]["handler_fee_setter_count"]:
                    self.assertEqual(
                        token["legacy_missing_token_prefix_field_effect_counts"],
                        {"existing": 0, "new_transaction_hit": 21, "new_transaction_miss": 22},
                    )
                    self.assertEqual(
                        token["legacy_missing_token_prefix_store_orders"],
                        {"existing": [], "new_transaction_hit": ["Transaction"], "new_transaction_miss": ["Transaction"]},
                    )
                else:
                    self.assertEqual(token["legacy_missing_token_prefix_field_effect_counts"], {})

    def test_10_gas_used_generation_split_is_structural_only(self) -> None:
        for proof in self.contract["mapping_proofs"]:
            gas = proof["path_contract"]["transaction_gas_used"]
            if proof["generation"].startswith("legacy"):
                self.assertEqual(gas["api_version"], "0.0.4")
                self.assertIn("gasLimit getter result", gas["structural_source"])
            else:
                self.assertEqual(gas["api_version"], "0.0.7")
                self.assertIn("literal zero", gas["structural_source"])
            self.assertFalse(gas["numeric_meaning_complete"])

    def test_11_collect_exclusion_is_bound_without_a_block_guard(self) -> None:
        for proof in self.contract["mapping_proofs"]:
            paths = proof["path_contract"]
            self.assertTrue(paths["collect_excluded_pool_guard_bound"])
            self.assertFalse(paths["collect_historical_block_guard_present"])
            self.assertFalse(paths["global_absence_of_exclusion_literals_claimed"])

    def test_12_current_zero_named_setters_is_not_zero_writes(self) -> None:
        current = [item for item in self.contract["mapping_proofs"] if item["generation"].startswith("current")]
        self.assertEqual(len(current), 2)
        for proof in current:
            summary = proof["reachable_closure_summary"]
            self.assertEqual(summary["named_setter_invocation_count"], 0)
            self.assertEqual(summary["generic_setter_site_count"], 42)
            self.assertGreater(summary["memory_write_count"], 0)

    def test_13_constructor_id_effects_distinguish_generations(self) -> None:
        for proof in self.contract["mapping_proofs"]:
            constructors = proof["semantic_invocation_contract"]["semantic_constructor_invocations"]
            self.assertEqual([item["entity_authority"] for item in constructors], ["Position", "Transaction", "PositionSnapshot"])
            expected = "constructor_carried" if proof["generation"].startswith("legacy") else "explicit_generic_id_set"
            self.assertEqual({item["id_effect_class"] for item in constructors}, {expected})

    def test_14_indirect_table_is_closed_without_hidden_store_target(self) -> None:
        for proof in self.contract["mapping_proofs"]:
            sites = proof["schema_api_sites"]
            expected = [] if proof["generation"].startswith("legacy") else ["~lib/@graphprotocol/graph-ts/common/value/Value#displayData~anonymous|0"]
            self.assertEqual(sites["executable_call_indirect_targets"], expected)
            self.assertEqual(sites["store_removes"], [])
            self.assertEqual(sites["schema_unsets"], [])
            self.assertEqual(proof["reachable_closure_summary"]["physical_store_set_target_count"], 3)

    def test_15_direct_schema_artifacts_match_all_299_fields(self) -> None:
        self.assertEqual(len(self.contract["direct_schema_bindings"]), 3)
        self.assertEqual({item["field_count"] for item in self.contract["direct_schema_bindings"]}, {299})
        self.assertEqual(len({item["field_catalog_sha256"] for item in self.contract["direct_schema_bindings"]}), 1)

    def test_16_all_twenty_eight_diffs_are_recursive_and_nonempty(self) -> None:
        self.assertEqual(len(self.contract["segment_diffs"]), 28)
        for diff in self.contract["segment_diffs"]:
            self.assertTrue(diff["recursive_semantic_diff_paths"])
            self.assertTrue(diff["recursive_provenance_diff_paths"])
            self.assertFalse(diff["graph_oracle_compared"])

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
        paths["accepted_new_position"]["store_set_orders"] = [["Position", "Transaction", "PositionSnapshot"]]
        self.assert_contract_rejected(mutated)

    def test_24_profile_quirk_token_policy_and_guard_mutations_fail_closed(self) -> None:
        mutated = copy.deepcopy(self.contract)
        overwrite = next(item for item in mutated["mapping_proofs"] if item["profile_id"] == "mainnet-second-fee0-overwrite")
        overwrite["semantic_invocation_contract"]["handler_fee_setter_keys"][1] = "collectedFeesToken1"
        current = next(item for item in mutated["mapping_proofs"] if item["generation"].startswith("current"))
        current["path_contract"]["token_branch"]["current_null_token_continues_with_zero_handler_fee_setters"] = False
        current["path_contract"]["collect_historical_block_guard_present"] = True
        self.assert_contract_rejected(mutated)

    def test_25_shared_transaction_visibility_and_last_writer_promotions_fail_closed(self) -> None:
        mutated = copy.deepcopy(self.contract)
        proof = mutated["mapping_proofs"][0]
        proof["shared_transaction_contract"]["intra_handler_visibility_between_store_set_and_later_store_get_proven"] = True
        proof["shared_transaction_contract"]["shared_transaction_last_writer_complete"] = True
        self.assert_contract_rejected(mutated)

    def test_26_required_absence_overlay_is_exact_and_collect_is_not_synthesized(self) -> None:
        expected = {"Collect": 11, "Flash": 12, "TickHourData": 10}
        for segment in self.contract["segments"]:
            outcomes = segment["semantic_surface"]["field_outcomes"]
            observed = {entity: sum(item["entity"] == entity and item["required_absent_overlay"] for item in outcomes) for entity in expected}
            self.assertEqual(observed, expected)
        self.assertEqual({item["target"] for proof in self.contract["mapping_proofs"] for item in proof["schema_api_sites"]["store_set_targets"]}, {"Position", "PositionSnapshot", "Transaction"})

    def test_27_no_setter_path_and_numeric_overclaims_fail_closed(self) -> None:
        mutated = copy.deepcopy(self.contract)
        outcome = next(item for item in mutated["segments"][0]["semantic_surface"]["field_outcomes"] if item["entity"] == "Position" and item["field"] == "owner")
        outcome["field_value_unchanged_or_preserved_proven"] = True
        mutated["truth_boundary"]["collect_numeric_accumulation_semantics_complete"] = True
        self.assert_contract_rejected(mutated)

    def test_28_runtime_value_history_and_issue_gates_remain_false(self) -> None:
        false_gates = set(VERIFIER.FALSE_FLAGS)
        self.assertTrue(false_gates)
        self.assertTrue(all(self.contract["truth_boundary"][key] is False for key in false_gates))
        self.assertFalse(self.contract["scope"]["issue_acceptance_checkbox_completed"])

    def test_29_duplicate_json_keys_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="npm-collect-v2-json-") as temporary:
            path = Path(temporary) / "duplicate.json"
            path.write_text('{"field": 1, "field": 2}\n')
            with self.assertRaises(VERIFIER.VerificationError):
                VERIFIER.load_json(path)

    def test_30_compile_valid_handler_body_mutation_is_rejected(self) -> None:
        ancestry = self.sources["direct"]["ancestry_v2"]
        cid = "QmYWR79pUmVbQ42JkvB24D6AKCGtdo4UG78ZSewmFxwQdR"
        artifact = copy.deepcopy(next(item for item in ancestry["artifacts"] if item["cid"] == cid))
        inventory = next(item for item in ancestry["mapping_writer_inventories"] if item["cid"] == cid)
        original = ROOT / artifact["path"]
        wat = VERIFIER.WRITER.run_wasm2wat(self.wasm2wat, original).decode()
        memory, functions, _targets, _exports = VERIFIER.WRITER.parse_wat(wat)
        handler = functions["src/mappings/position-manager/handleCollect"]
        lines = wat.splitlines()
        insert_at = handler.start_line - 1 + len(handler.lines) - 1
        lines.insert(insert_at, "    nop")
        wat2wasm = self.wasm2wat.with_name("wat2wasm")
        self.assertTrue(wat2wasm.is_file())
        with tempfile.TemporaryDirectory(prefix="npm-collect-v2-wat-") as temporary:
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

    def test_31_two_independent_in_memory_regenerations_are_byte_identical(self) -> None:
        first = VERIFIER.render(VERIFIER.expected_contract_from_sources(self.sources))
        second = VERIFIER.render(VERIFIER.expected_contract_from_sources(self.sources))
        self.assertEqual(first, second)
        self.assertEqual(hashlib.sha256(first.encode()).hexdigest(), hashlib.sha256(second.encode()).hexdigest())

    def test_32_cli_verifier_passes_with_exact_wabt(self) -> None:
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

    def test_33_all_six_load_transaction_control_boundaries_are_structural(self) -> None:
        hit_ledger = [
            "Transaction.blockNumber",
            "Transaction.timestamp",
            "Transaction.gasUsed",
            "Transaction.gasPrice",
            "Transaction.save",
        ]
        miss_ledger = ["Transaction.id", *hit_ledger]
        self.assertEqual(len(self.contract["mapping_proofs"]), 6)
        for proof in self.contract["mapping_proofs"]:
            control = proof["semantic_invocation_contract"]["load_transaction_hit_or_miss_control_boundary"]
            branch_start, branch_end = control["store_miss_branch_wat_lines"]
            self.assertLess(branch_start, control["id_effect_wat_line"])
            self.assertLess(control["id_effect_wat_line"], branch_end)
            common_lines = [
                control["field_setter_wat_lines"][field]
                for field in VERIFIER.TRANSACTION_COMMON_HIT_OR_MISS_FIELDS
            ]
            self.assertEqual(common_lines, sorted(common_lines))
            self.assertTrue(all(line > branch_end for line in common_lines))
            self.assertGreater(control["transaction_save_wat_line"], common_lines[-1])
            self.assertEqual(control["successful_hit_effect_ledger"], hit_ledger)
            self.assertEqual(control["successful_miss_effect_ledger"], miss_ledger)
            self.assertEqual(
                (control["successful_hit_field_effect_count"], control["successful_miss_field_effect_count"]),
                (4, 5),
            )
            self.assertTrue(control["only_id_effect_is_store_miss_conditional"])
            self.assertTrue(control["common_setters_and_save_are_outside_store_miss_branch"])
            self.assertTrue(control["transaction_save_after_common_setters_on_hit_or_miss"])

    def test_34_classified_setter_paths_are_exact_on_every_segment_surface(self) -> None:
        derived_transaction_fields = {"mints", "burns", "swaps", "flashed", "collects"}
        for segment in self.contract["segments"]:
            outcomes = segment["semantic_surface"]["field_outcomes"]
            self.assertEqual(sum(bool(item["setter_before_matching_save_paths"]) for item in outcomes), 38)
            self.assertTrue(
                all(
                    bool(item["setter_before_matching_save_paths"]) == item["classified_stored_target"]
                    for item in outcomes
                )
            )
            self.assertTrue(
                all(
                    not item["setter_before_matching_save_paths"]
                    for item in outcomes
                    if item["derived_query_field"] or item["outside_npm_collect_store_target_closure"]
                )
            )
            transaction = [item for item in outcomes if item["entity"] == "Transaction"]
            self.assertEqual(
                {item["field"] for item in transaction if item["setter_before_matching_save_paths"]},
                set(VERIFIER.TRANSACTION_FIELDS),
            )
            self.assertEqual(
                {item["field"] for item in transaction if item["derived_query_field"]},
                derived_transaction_fields,
            )
            self.assertTrue(
                all(
                    not item["setter_before_matching_save_paths"]
                    for item in transaction
                    if item["field"] in derived_transaction_fields
                )
            )
        aggregate = self.contract["aggregate_counts"]
        self.assertEqual(aggregate["setter_path_bearing_outcome_count"], 304)
        self.assertEqual(aggregate["nonclassified_setter_path_outcome_count"], 0)
        self.assertEqual(aggregate["derived_transaction_setter_path_outcome_count"], 0)

    def test_35_false_derived_or_missing_classified_setter_paths_fail_closed(self) -> None:
        false_derived = copy.deepcopy(self.contract)
        derived = next(
            item
            for item in false_derived["segments"][0]["semantic_surface"]["field_outcomes"]
            if item["entity"] == "Transaction" and item["field"] == "mints"
        )
        derived["setter_before_matching_save_paths"] = ["invented:loadTransaction-setter"]
        self.assert_contract_rejected(false_derived)

        missing_classified = copy.deepcopy(self.contract)
        stored = next(
            item
            for item in missing_classified["segments"][0]["semantic_surface"]["field_outcomes"]
            if item["entity"] == "Transaction" and item["field"] == "blockNumber"
        )
        stored["setter_before_matching_save_paths"] = []
        self.assert_contract_rejected(missing_classified)

    def test_36_common_transaction_setter_moved_into_miss_branch_is_rejected(self) -> None:
        cid = "QmWxG1yzdQmp4pRDiqKvTZyRrrrZPRUTza6xznjR1wu1sD"
        ancestry = self.sources["direct"]["ancestry_v2"]
        artifact = next(item for item in ancestry["artifacts"] if item["cid"] == cid)
        wat = VERIFIER.WRITER.run_wasm2wat(
            self.wasm2wat,
            ROOT / artifact["path"],
        ).decode()
        memory, functions, _targets, _exports = VERIFIER.WRITER.parse_wat(wat)
        function = functions["src/utils/index/loadTransaction"]
        control = VERIFIER._load_transaction_branch_record(
            cid,
            function,
            memory,
            "current-generic-setters",
        )
        branch_end = control["store_miss_branch_wat_lines"][1] - function.start_line
        block_number_setter = control["field_setter_wat_lines"]["blockNumber"] - function.start_line
        lines = list(function.lines)
        end_instruction = lines.pop(branch_end)
        self.assertEqual(end_instruction.strip(), "end")
        if block_number_setter > branch_end:
            block_number_setter -= 1
        lines.insert(block_number_setter + 1, end_instruction)
        mutated = VERIFIER.WRITER.WatFunction(
            name=function.name,
            start_line=function.start_line,
            lines=tuple(lines),
            function_index=function.function_index,
        )
        with self.assertRaises(VERIFIER.VerificationError):
            VERIFIER._load_transaction_branch_record(
                cid,
                mutated,
                memory,
                "current-generic-setters",
            )


if __name__ == "__main__":
    unittest.main()
