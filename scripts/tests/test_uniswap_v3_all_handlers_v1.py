from __future__ import annotations

import copy
import hashlib
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VERIFIER_PATH = ROOT / "scripts/verify-uniswap-v3-all-handlers-v1.py"
SPEC = importlib.util.spec_from_file_location("uniswap_v3_all_handlers_v1", VERIFIER_PATH)
assert SPEC is not None and SPEC.loader is not None
VERIFIER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VERIFIER
SPEC.loader.exec_module(VERIFIER)


class AllHandlersV1Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sources = VERIFIER.load_sources(ROOT, regenerate_components=False)
        cls.expected = VERIFIER.expected_contract_from_sources(ROOT, cls.sources)
        cls.contract = VERIFIER.verify_contract(
            ROOT,
            sources=cls.sources,
            regenerate_components=False,
        )

    def assert_contract_rejected(self, value: dict[str, object]) -> None:
        with self.assertRaises(VERIFIER.VerificationError):
            VERIFIER.verify_against_expected(value, self.expected)

    def cells(self, handler: str):
        for segment in self.contract["segments"]:
            yield from segment["handler_surfaces"][handler]["semantic_surface"]["field_outcomes"]

    def test_01_committed_contract_is_deterministic(self) -> None:
        self.assertEqual(self.contract, self.expected)
        rendered = VERIFIER.render(self.contract)
        self.assertEqual((ROOT / VERIFIER.CONTRACT_PATH).read_text(), rendered)

    def test_02_exact_mixed_canonical_and_provisional_component_roots(self) -> None:
        authority = self.contract["authority_contract"]
        self.assertEqual(authority["implementation_base_commit"], VERIFIER.IMPLEMENTATION_BASE_COMMIT)
        self.assertEqual(authority["implementation_base_tree"], VERIFIER.IMPLEMENTATION_BASE_TREE)
        manifest = self.contract["component_manifest"]
        self.assertEqual(len(manifest), 9)
        self.assertEqual(sum(len(item["handlers"]) for item in manifest), 10)
        self.assertTrue(all(item["parent_matches_selected_predecessor"] for item in manifest))
        self.assertTrue(all(item["reachable_from_implementation_base"] for item in manifest))
        self.assertTrue(self.contract["canonical_reseal_required"])
        self.assertEqual(self.contract["canonical_reseal_order"], ["transfer", "collect", "liquidity", "all-handlers"])
        self.assertEqual(
            {item["component"] for item in manifest if item["canonical_component_commit"]},
            {"factory", "initialize", "flash", "burn", "mint", "swap"},
        )
        self.assertEqual(
            {item["component"] for item in manifest if item["provisional_for_final_publication"]},
            {"transfer", "collect", "liquidity"},
        )

    def test_03_direct_schema_reconstruction_is_exact(self) -> None:
        schema = self.contract["schema_catalog"]
        self.assertEqual(len(schema["field_catalog"]), 299)
        self.assertEqual(len(schema["direct_schema_bindings"]), 3)
        self.assertEqual({item["field_count"] for item in schema["direct_schema_bindings"]}, {299})
        self.assertEqual(schema["summary"]["field_catalog_sha256"], VERIFIER.FIELD_CATALOG_SHA256)
        self.assertEqual((schema["summary"]["stored_field_count"], schema["summary"]["derived_field_count"]), (286, 13))

    def test_04_factory_projection_does_not_widen_issue_77(self) -> None:
        expected = Counter({
            VERIFIER.CATEGORY_SETTER: 59,
            VERIFIER.CATEGORY_NO_SETTER: 1,
            VERIFIER.CATEGORY_OUTSIDE: 226,
            VERIFIER.CATEGORY_DERIVED: 13,
        })
        for segment in self.contract["segments"]:
            records = segment["handler_surfaces"]["factory"]["semantic_surface"]["field_outcomes"]
            self.assertEqual(Counter(item["category"] for item in records), expected)
            tick = next(item for item in records if (item["entity"], item["field"]) == ("Pool", "tick"))
            self.assertEqual(tick["category"], VERIFIER.CATEGORY_NO_SETTER)
            self.assertTrue(tick["required_absent_handler_relative"])
            other = [item for item in records if item["category"] == VERIFIER.CATEGORY_OUTSIDE]
            self.assertTrue(all("outside_factory_60_field_contract" in item["source_native_category"] for item in other))

    def test_05_exact_23920_cell_partition(self) -> None:
        scope = self.contract["scope"]
        self.assertEqual((scope["handler_count"], scope["segment_count"], scope["schema_field_count"]), (10, 8, 299))
        self.assertEqual(scope["field_cell_count"], 23920)
        self.assertEqual(
            self.contract["aggregate_category_counts"],
            {
                VERIFIER.CATEGORY_SETTER: 5326,
                VERIFIER.CATEGORY_NO_SETTER: 1665,
                VERIFIER.CATEGORY_OUTSIDE: 15889,
                VERIFIER.CATEGORY_DERIVED: 1040,
            },
        )

    def test_06_each_handler_segment_is_a_mutually_exclusive_299_partition(self) -> None:
        for segment in self.contract["segments"]:
            for handler in VERIFIER.HANDLERS:
                records = segment["handler_surfaces"][handler]["semantic_surface"]["field_outcomes"]
                self.assertEqual(len(records), 299)
                self.assertEqual(set(item["category"] for item in records) <= set(VERIFIER.CATEGORIES), True)
                self.assertEqual(len({(item["entity"], item["field"]) for item in records}), 299)

    def test_07_initialize_five_no_save_and_three_save_profiles_are_separate(self) -> None:
        vectors = Counter()
        for segment in self.contract["segments"]:
            counts = segment["handler_surfaces"]["initialize"]["semantic_surface"]["category_counts"]
            vectors[tuple(counts[key] for key in VERIFIER.CATEGORIES)] += 1
        self.assertEqual(vectors, Counter({(42, 16, 228, 13): 5, (44, 43, 199, 13): 3}))

    def test_08_aggregate_segment_vectors_preserve_the_initialize_split(self) -> None:
        vectors = Counter(
            tuple(segment["aggregate_category_counts"][key] for key in VERIFIER.CATEGORIES)
            for segment in self.contract["segments"]
        )
        self.assertEqual(vectors, Counter({(665, 198, 1997, 130): 5, (667, 225, 1968, 130): 3}))

    def test_09_required_absence_occurrences_unions_and_population_are_distinct(self) -> None:
        absence = self.contract["overlays"]["required_absence"]
        self.assertEqual(absence["handler_relative_occurrence_count"], 1424)
        self.assertEqual(absence["handler_relative_distinct_union_count"], 272)
        self.assertEqual(absence["population_required_absence_count"], 264)
        self.assertEqual(absence["handler_relative_counts"]["factory"], 8)
        self.assertEqual(absence["handler_relative_counts"]["flash"], 96)
        self.assertTrue(absence["pool_tick_is_factory_handler_local_not_population_absence"])
        self.assertNotIn("Pool.tick", absence["population_required_absence_fields"])

    def test_10_mint_and_swap_nullability_overlays_are_structural_only(self) -> None:
        mint = Counter(value for item in self.cells("mint") for value in item["native_overlays"])
        swap = Counter(value for item in self.cells("swap") for value in item["native_overlays"])
        self.assertEqual((mint["mint_required_field_overlay"], mint["mint_nullable_field_overlay"]), (104, 24))
        self.assertEqual((swap["swap_required_field_overlay"], swap["swap_nullable_field_overlay"]), (112, 8))
        self.assertFalse(self.contract["truth_boundary"]["required_nonempty_certified"])

    def test_10a_repaired_swap_native_taxonomy_is_exact_and_conservative(self) -> None:
        native = Counter(item["source_native_category"] for item in self.cells("swap"))
        self.assertEqual(
            native,
            Counter({
                "stored_field_with_exact_setter_and_lexically_later_same_group_store_receiver_origin_overlap": 1152,
                "stored_field_on_reachable_entity_store_without_exact_schema_setter": 360,
                "stored_field_outside_pool_swap_graph_store_closure": 776,
                "derived_field_without_direct_graph_store_transition": 104,
            }),
        )
        truth = self.contract["truth_boundary"]
        self.assertFalse(truth["uniform_setter_to_matching_store_path_proven"])
        self.assertFalse(truth["uniform_setter_store_common_execution_path_proven"])
        self.assertFalse(truth["uniform_setter_store_branch_correlation_proven"])
        self.assertFalse(truth["uniform_setter_store_receiver_must_alias_proven"])

    def test_10b_repaired_swap_adapter_rejects_missing_conflicting_old_and_promoted_inputs(self) -> None:
        source = self.sources["contracts"]["swap"]["segments"][0]["semantic_surface"]["field_outcomes"]
        setter = copy.deepcopy(next(
            item for item in source
            if item["stored_field_with_exact_setter_and_lexically_later_same_group_store_receiver_origin_overlap"]
        ))
        cases = []
        missing = copy.deepcopy(setter)
        del missing["stored_field_with_exact_setter_and_lexically_later_same_group_store_receiver_origin_overlap"]
        cases.append(missing)
        conflicting = copy.deepcopy(setter)
        conflicting["stored_field_on_reachable_store_without_exact_schema_setter"] = True
        cases.append(conflicting)
        old_label = copy.deepcopy(setter)
        old_label["lexical_static_category"] = "stored_field_with_setter_path_before_matching_store"
        cases.append(old_label)
        wrong_storage = copy.deepcopy(setter)
        wrong_storage["storage"] = "derived"
        cases.append(wrong_storage)
        non_boolean = copy.deepcopy(setter)
        non_boolean["stored_field_outside_pool_swap_store_closure"] = 0
        cases.append(non_boolean)
        for gate in (
            "setter_store_common_execution_path_proven",
            "setter_store_branch_correlation_proven",
            "setter_store_receiver_must_alias_proven",
        ):
            promoted = copy.deepcopy(setter)
            promoted[gate] = True
            cases.append(promoted)
        for index, value in enumerate(cases):
            with self.subTest(index=index):
                with self.assertRaises(VERIFIER.VerificationError):
                    VERIFIER.classify_swap_outcome(value)

    def test_10c_repaired_npm_adapter_rejects_setter_path_category_contradictions(self) -> None:
        source = self.sources["contracts"]["transfer"]["segments"][0]["semantic_surface"]["field_outcomes"]
        setter = copy.deepcopy(next(item for item in source if item["classified_stored_target"]))
        setter["setter_before_matching_save_paths"] = []
        outside = copy.deepcopy(next(item for item in source if item["outside_npm_transfer_store_target_closure"]))
        outside["setter_before_matching_save_paths"] = ["invented-path"]
        conflicting = copy.deepcopy(next(item for item in source if item["derived_query_field"]))
        conflicting["classified_stored_target"] = True
        old_label = copy.deepcopy(next(item for item in source if item["classified_stored_target"]))
        old_label["path_qualified_category"] = "classified_stored_target"
        wrong_storage = copy.deepcopy(next(item for item in source if item["classified_stored_target"]))
        wrong_storage["storage"] = "derived"
        non_boolean = copy.deepcopy(next(item for item in source if item["classified_stored_target"]))
        non_boolean["saved_target_stored_no_setter"] = 0
        for index, value in enumerate((setter, outside, conflicting, old_label, wrong_storage, non_boolean)):
            with self.subTest(index=index):
                with self.assertRaises(VERIFIER.VerificationError):
                    VERIFIER.classify_npm_outcome("transfer", value)

    def test_11_derived_child_occurrences_and_distinct_union_are_exact(self) -> None:
        derived = self.contract["overlays"]["derived"]
        self.assertEqual((derived["handler_relative_derived_cell_count"], derived["handler_relative_child_association_count"]), (1040, 136))
        self.assertEqual(derived["handler_relative_other_derived_count"], 904)
        self.assertEqual(derived["distinct_child_association_field_count_per_segment"], 9)
        self.assertFalse(derived["query_visibility_complete"])

    def test_12_npm_stored_relation_occurrences_and_union_are_exact(self) -> None:
        relations = self.contract["overlays"]["stored_relations"]
        self.assertEqual(relations["handler_relative_occurrence_count"], 264)
        self.assertEqual(relations["handler_relative_counts"], {"transfer": 48, "collect": 72, "increase": 72, "decrease": 72})
        self.assertEqual(relations["distinct_field_count_per_segment"], 9)
        self.assertFalse(relations["imported_value_or_alias_semantics_complete"])

    def test_13_entity_setter_or_direct_write_authority_is_exact(self) -> None:
        authority = self.contract["setter_authority"]
        self.assertEqual(authority["entity_setter_or_direct_write_authority_sets"], VERIFIER.EXPECTED_ENTITY_AUTHORITIES)
        self.assertEqual(authority["entities_without_setter_or_direct_write_authority"], ["Collect", "Flash", "TickHourData"])

    def test_14_transaction_setter_fields_and_repaired_hit_miss_boundary_are_exact(self) -> None:
        transaction = self.contract["setter_authority"]["transaction"]
        self.assertEqual(transaction["setter_or_direct_write_handlers"], ["burn", "collect", "decrease", "increase", "mint", "swap", "transfer"])
        self.assertEqual(transaction["setter_or_direct_write_fields"], ["blockNumber", "gasPrice", "gasUsed", "id", "timestamp"])
        npm = transaction["npm_hit_miss_control_authority"]
        self.assertEqual(npm["retained_control_record_counts"], {"collect": 6, "increase": 6, "decrease": 6})
        self.assertEqual(npm["successful_hit_field_effects"], ["blockNumber", "timestamp", "gasUsed", "gasPrice"])
        self.assertEqual(npm["successful_miss_field_effects"], ["id", "blockNumber", "timestamp", "gasUsed", "gasPrice"])
        self.assertEqual(npm["successful_invocation_transaction_store_set_count_on_hit_or_miss"], 1)
        self.assertTrue(npm["only_id_effect_is_store_miss_conditional"])
        self.assertFalse(npm["intra_handler_store_set_to_later_store_get_visibility_proven"])
        self.assertFalse(npm["cross_handler_last_writer_complete"])

    def test_15_all_manifests_have_the_exact_three_ordered_handler_groups(self) -> None:
        order = self.contract["manifest_handler_order"]
        self.assertEqual(len(order["records"]), 8)
        self.assertEqual(order["factory_datasource_handlers"], ["handlePoolCreated"])
        self.assertEqual(order["npm_datasource_handlers"], ["handleIncreaseLiquidity", "handleDecreaseLiquidity", "handleCollect", "handleTransfer"])
        self.assertEqual(order["pool_dynamic_template_handlers"], ["handleInitialize", "handleSwap", "handleMint", "handleBurn", "handleFlash"])
        self.assertFalse(order["manifest_declaration_is_global_category_schedule"])

    def test_16_execution_order_is_reference_only(self) -> None:
        order = self.contract["execution_order_reference"]
        self.assertEqual(order["graph_node_reference"]["commit"], "77823b5a7adc4eac4abf03202c8dd7cb00dea31d")
        self.assertFalse(order["target_runtime_identity_proven"])
        self.assertFalse(order["store_visibility_or_last_writer_proven"])
        self.assertFalse(self.contract["truth_boundary"]["global_flattened_event_order_proven"])

    def test_17_liquidity_physical_ledger_is_exact_and_not_globally_summed(self) -> None:
        ledger = self.contract["physical_ledgers"]["liquidity"]["projection"]["aggregate_counts"]
        weighted = ledger["eight_binding_weighted_physical_totals"]
        self.assertEqual(weighted["increase"]["function_count"], 771)
        self.assertEqual(weighted["decrease"]["direct_call_count"], 3381)
        self.assertEqual(weighted["paired_union"]["memory_write_count"], 1714)
        self.assertEqual(weighted["paired_union"]["named_setter_invocation_count"], 216)
        self.assertFalse(self.contract["physical_ledgers_globally_summed"])

    def test_18_all_handler_aggregate_and_liquidity_diff_axes_are_exact(self) -> None:
        diffs = self.contract["diffs"]
        self.assertEqual(diffs["per_handler_total_count"], 280)
        self.assertTrue(all(len(records) == 28 for records in diffs["per_handler"].values()))
        self.assertEqual((diffs["aggregate_segment_pair_count"], diffs["aggregate_count_vector_changed_count"]), (28, 15))
        self.assertEqual(diffs["aggregate_identity_or_provenance_only_count"], 13)
        self.assertEqual(diffs["liquidity_within_segment_handler_diff_count"], 8)
        self.assertEqual(diffs["total_records_including_liquidity_within_handler_axis"], 316)

    def test_19_issue_mapping_checks_nothing_and_closes_nothing(self) -> None:
        for issue in self.contract["issue_mapping"].values():
            self.assertEqual(issue["checkboxes_completed_by_this_certificate"], [])
            self.assertFalse(issue["issue_closed"])
        self.assertFalse(self.contract["scope"]["issue_acceptance_checkbox_completed"])

    def test_20_every_no_overclaim_gate_remains_false(self) -> None:
        truth = self.contract["truth_boundary"]
        self.assertTrue(all(truth[key] is False for key in VERIFIER.FALSE_FLAGS))
        self.assertTrue(all(truth[key] is True for key in VERIFIER.TRUE_FLAGS))

    def test_21_component_identity_verifier_test_and_source_root_mutations_fail_closed(self) -> None:
        mutated = copy.deepcopy(self.contract)
        mutated["component_manifest"][0]["commit"] = "0" * 40
        mutated["component_manifest"][1]["verifier_raw_sha256"] = "0" * 64
        mutated["component_manifest"][2]["test_raw_sha256"] = "0" * 64
        mutated["component_manifest"][3]["source_contracts_sha256"] = "0" * 64
        mutated["source_roots"]["segment_field_semantics_v2"]["tree"] = "0" * 40
        self.assert_contract_rejected(mutated)

    def test_22_handler_segment_field_and_category_denominator_mutations_fail_closed(self) -> None:
        mutated = copy.deepcopy(self.contract)
        mutated["segments"].pop()
        del mutated["segments"][0]["handler_surfaces"]["flash"]
        mutated["segments"][1]["handler_surfaces"]["burn"]["semantic_surface"]["field_outcomes"].pop()
        mutated["segments"][2]["handler_surfaces"]["mint"]["semantic_surface"]["field_outcomes"][0]["category"] = VERIFIER.CATEGORY_DERIVED
        self.assert_contract_rejected(mutated)

    def test_23_schema_order_type_storage_and_digest_mutations_fail_closed(self) -> None:
        mutated = copy.deepcopy(self.contract)
        catalog = mutated["schema_catalog"]["field_catalog"]
        catalog[0], catalog[1] = catalog[1], catalog[0]
        catalog[2]["type"] = "Bytes"
        catalog[3]["storage"] = "derived"
        mutated["schema_catalog"]["summary"]["field_catalog_sha256"] = "0" * 64
        self.assert_contract_rejected(mutated)

    def test_24_required_absence_multiplicity_union_and_population_mutations_fail_closed(self) -> None:
        mutated = copy.deepcopy(self.contract)
        absence = mutated["overlays"]["required_absence"]
        absence["handler_relative_occurrence_count"] -= 1
        absence["handler_relative_distinct_union_count"] -= 1
        absence["population_required_absence_fields"].append("Pool.tick")
        self.assert_contract_rejected(mutated)

    def test_25_nullable_child_relation_receiver_and_key_mutations_fail_closed(self) -> None:
        mutated = copy.deepcopy(self.contract)
        mint = next(item for item in mutated["segments"][0]["handler_surfaces"]["mint"]["semantic_surface"]["field_outcomes"] if "mint_nullable_field_overlay" in item["native_overlays"])
        mint["native_overlays"] = []
        burn_child = next(item for item in mutated["segments"][0]["handler_surfaces"]["burn"]["semantic_surface"]["field_outcomes"] if item["child_association"])
        burn_child["child_association"]["child_field"] = "wrong"
        transfer_relation = next(item for item in mutated["segments"][0]["handler_surfaces"]["transfer"]["semantic_surface"]["field_outcomes"] if item["stored_relation_authority"])
        transfer_relation["stored_relation_authority"] = False
        mutated["setter_authority"]["transaction"]["structural_key_model"] = "numeric transaction ordinal"
        self.assert_contract_rejected(mutated)

    def test_26_setter_authority_store_visibility_preservation_and_last_writer_promotions_fail_closed(self) -> None:
        mutated = copy.deepcopy(self.contract)
        mutated["setter_authority"]["entity_setter_or_direct_write_authority_sets"]["Pool"].remove("flash")
        transaction = mutated["setter_authority"]["transaction"]["npm_hit_miss_control_authority"]
        transaction["intra_handler_store_set_to_later_store_get_visibility_proven"] = True
        transaction["cross_handler_last_writer_complete"] = True
        mutated["segments"][0]["handler_surfaces"]["swap"]["semantic_surface"]["no_setter_is_preservation_or_unchanged_claim"] = True
        self.assert_contract_rejected(mutated)

    def test_27_manifest_group_order_and_global_schedule_mutations_fail_closed(self) -> None:
        mutated = copy.deepcopy(self.contract)
        order = mutated["manifest_handler_order"]
        order["npm_datasource_handlers"].reverse()
        order["records"][0]["pool_dynamic_template_handlers"].reverse()
        order["manifest_declaration_is_global_category_schedule"] = True
        self.assert_contract_rejected(mutated)

    def test_28_diff_count_digest_identity_and_multiplicity_mutations_fail_closed(self) -> None:
        mutated = copy.deepcopy(self.contract)
        diffs = mutated["diffs"]
        diffs["per_handler"]["factory"].pop()
        diffs["aggregate"][0]["recursive_diff"]["paths_sha256"] = "0" * 64
        diffs["aggregate"][1]["left_segment_id"] = diffs["aggregate"][1]["right_segment_id"]
        diffs["liquidity_within_segment_handler_diff_count"] = 7
        self.assert_contract_rejected(mutated)

    def test_29_provisional_ancestry_and_reseal_promotions_fail_closed(self) -> None:
        mutated = copy.deepcopy(self.contract)
        mutated["canonical_reseal_required"] = False
        mutated["canonical_reseal_order"] = []
        transfer = next(item for item in mutated["component_manifest"] if item["component"] == "transfer")
        transfer["parent_matches_selected_predecessor"] = False
        transfer["reachable_from_implementation_base"] = False
        transfer["canonical_component_commit"] = True
        transfer["provisional_for_final_publication"] = False
        mutated["truth_boundary"]["all_component_roots_canonical_and_ancestral"] = True
        self.assert_contract_rejected(mutated)

    def test_30_every_false_gate_mutation_is_rejected(self) -> None:
        mutated = copy.deepcopy(self.contract)
        for key in VERIFIER.FALSE_FLAGS:
            mutated["truth_boundary"][key] = True
            with self.subTest(key=key):
                self.assert_contract_rejected(mutated)
            mutated["truth_boundary"][key] = False

    def test_31_every_true_gate_mutation_is_rejected(self) -> None:
        mutated = copy.deepcopy(self.contract)
        for key in VERIFIER.TRUE_FLAGS:
            mutated["truth_boundary"][key] = False
            with self.subTest(key=key):
                self.assert_contract_rejected(mutated)
            mutated["truth_boundary"][key] = True

    def test_32_physical_ledger_edge_store_guard_and_scope_mutations_fail_closed(self) -> None:
        mutated = copy.deepcopy(self.contract)
        mutated["physical_ledgers"]["burn"]["projection"]["scope"]["expanded_handler_to_setter_path_count"] -= 1
        mutated["physical_ledgers"]["swap"]["projection"]["scope"]["expanded_store_path_count"] -= 1
        mutated["physical_ledgers"]["liquidity"]["projection"]["aggregate_counts"]["eight_binding_weighted_physical_totals"]["paired_union"]["call_indirect_count"] = 3
        mutated["component_manifest"][4]["scope_sha256"] = "0" * 64
        self.assert_contract_rejected(mutated)

    def test_33_duplicate_json_keys_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="all-handlers-v1-json-") as temporary:
            candidate = Path(temporary) / "duplicate.json"
            candidate.write_text('{"field": 1, "field": 2}\n')
            with self.assertRaises(VERIFIER.VerificationError):
                VERIFIER.load_json(candidate)

    def test_34_two_in_memory_regenerations_are_byte_identical(self) -> None:
        first = VERIFIER.render(VERIFIER.expected_contract_from_sources(ROOT, self.sources))
        second = VERIFIER.render(VERIFIER.expected_contract_from_sources(ROOT, self.sources))
        self.assertEqual(first, second)
        self.assertEqual(hashlib.sha256(first.encode()).hexdigest(), hashlib.sha256(second.encode()).hexdigest())

    def test_35_quick_cli_verifier_passes_and_reports_provisional_status(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(VERIFIER_PATH), "--skip-component-regeneration"],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("10 handlers x 8 segments x 299 fields = 23920 cells", completed.stdout)
        self.assertIn("canonical reseal required", completed.stdout)


if __name__ == "__main__":
    unittest.main()
