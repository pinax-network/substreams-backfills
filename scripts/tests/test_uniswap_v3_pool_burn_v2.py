from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[2]
VERIFIER_PATH = ROOT / "scripts/verify-uniswap-v3-pool-burn-v2.py"
SPEC = importlib.util.spec_from_file_location(
    "uniswap_v3_pool_burn_v2",
    VERIFIER_PATH,
)
assert SPEC is not None and SPEC.loader is not None
VERIFIER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VERIFIER
SPEC.loader.exec_module(VERIFIER)

Mutation = tuple[str, Callable[[list[str], dict[str, Any]], None]]


class PoolBurnV2Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sources = VERIFIER.load_sources(ROOT, recompute_wat=True)
        cls.contract = VERIFIER.verify_contract(
            ROOT,
            sources=cls.sources,
            recompute_wat=False,
        )
        cls.contexts = cls.sources["contexts"]
        cls.by_profile = {
            context["profile"]["profile_id"]: context
            for context in cls.contexts.values()
        }
        cls.parent_by_cid = {
            item["mapping_cid"]: item
            for item in cls.sources["burn_contract"]["mapping_proofs"]
        }
        cls.field_catalog = cls.sources["field_catalog"]
        wasm2wat = next(iter(cls.contexts.values()))["wasm2wat"]
        cls.wasm2wat = VERIFIER.BURN.INITIALIZE.resolve_tool(wasm2wat, "wasm2wat")
        cls.wat2wasm = VERIFIER.BURN.INITIALIZE.resolve_tool(
            wasm2wat.with_name("wat2wasm"),
            "wat2wasm",
        )
        cls.expected_errors = tuple(
            dict.fromkeys((VERIFIER.VerificationError, *VERIFIER.UPSTREAM_ERRORS))
        )

    @staticmethod
    def replace(lines: list[str], index: int, instruction: str) -> None:
        indent = lines[index][: len(lines[index]) - len(lines[index].lstrip())]
        closing = (
            ")"
            if lines[index].rstrip().endswith(")")
            and not instruction.rstrip().endswith(")")
            else ""
        )
        lines[index] = f"{indent}{instruction}{closing}"

    def function_by_suffix(self, context: dict[str, Any], suffix: str) -> Any:
        matches = [
            function
            for name, function in context["functions"].items()
            if name.endswith(suffix)
        ]
        self.assertEqual(len(matches), 1, suffix)
        return matches[0]

    def roundtrip(
        self,
        context: dict[str, Any],
        mutations: list[Mutation],
    ) -> dict[str, Any]:
        replacements: list[tuple[int, int, list[str]]] = []
        for function_name, mutate in mutations:
            function = context["functions"][function_name]
            lines = list(function.lines)
            mutate(lines, context)
            replacements.append((function.start_line - 1, len(function.lines), lines))
        wat_lines = context["wat_text"].splitlines()
        for start, length, replacement in sorted(replacements, reverse=True):
            wat_lines[start : start + length] = replacement
        with tempfile.TemporaryDirectory(prefix="pool-burn-v2-wat-") as temporary:
            wat = Path(temporary) / "fixture.wat"
            wasm = Path(temporary) / "fixture.wasm"
            wat.write_text("\n".join(wat_lines) + "\n")
            compiled = subprocess.run(
                [str(self.wat2wasm), "--debug-names", str(wat), "-o", str(wasm)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            regenerated = VERIFIER.WRITER.run_wasm2wat(self.wasm2wat, wasm).decode()
        memory, functions, indirect_targets, exports = VERIFIER.WRITER.parse_wat(
            regenerated
        )
        handler = VERIFIER.WRITER.resolve_handler(
            functions,
            exports,
            VERIFIER.HANDLER_EXPORT,
        )
        return {
            **context,
            "memory": memory,
            "functions": functions,
            "indirect_targets": tuple(indirect_targets),
            "exports": exports,
            "handler": handler,
            "wat_text": regenerated,
        }

    def assert_wat_rejected(
        self,
        context: dict[str, Any],
        mutations: list[Mutation],
    ) -> None:
        changed = self.roundtrip(context, mutations)
        with self.assertRaises(self.expected_errors):
            VERIFIER.prove_complete_context(
                changed,
                self.parent_by_cid[context["mapping_cid"]],
                self.field_catalog,
            )

    def rehash_segment_surfaces(self, contract: dict[str, Any]) -> None:
        for segment in contract["segments"]:
            segment["semantic_surface_sha256"] = VERIFIER.canonical_sha256(
                segment["semantic_surface"]
            )
            segment["provenance_surface_sha256"] = VERIFIER.canonical_sha256(
                segment["provenance_surface"]
            )
        contract["segment_diffs"] = VERIFIER.build_segment_diffs(
            contract["segments"]
        )

    def assert_contract_rejected(
        self,
        contract: dict[str, Any],
        *,
        rehash: bool = False,
    ) -> None:
        if rehash:
            self.rehash_segment_surfaces(contract)
        with self.assertRaises(self.expected_errors):
            VERIFIER.verify_contract(
                ROOT,
                contract,
                sources=self.sources,
                recompute_wat=False,
            )

    def test_01_committed_contract_is_deterministic(self) -> None:
        self.assertEqual(
            self.contract,
            VERIFIER.expected_contract_from_sources(self.sources),
        )
        self.assertEqual(
            (self.contract["format_version"], self.contract["contract_version"]),
            (1, "uniswap-v3-pool-burn/v2"),
        )
        result = subprocess.run(
            [
                sys.executable,
                str(VERIFIER_PATH),
                "--root",
                str(ROOT),
                "--wasm2wat",
                str(self.wasm2wat),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("8 segments, 2392 field outcomes, 28 diffs", result.stdout)
        self.assertIn("no issue checkbox completed", result.stdout)

    def test_02_exact_scope_denominators(self) -> None:
        scope = self.contract["scope"]
        expected = {
            "segment_count": 8,
            "mapping_count": 8,
            "schema_field_count_per_segment": 299,
            "field_outcome_count": 2392,
            "selected_pool_tvl_setter_before_same_pool_save_outcome_count": 16,
            "other_stored_field_with_setter_path_outcome_count": 976,
            "reachable_store_without_setter_path_outcome_count": 504,
            "derived_child_association_setter_path_outcome_count": 40,
            "other_derived_without_direct_or_child_setter_path_outcome_count": 64,
            "stored_field_outside_burn_store_closure_outcome_count": 792,
            "required_absent_overlay_count": 264,
            "physical_typed_map_set_site_count": 622,
            "physical_site_to_invocation_edge_count": 1208,
            "lexical_schema_field_invocation_count": 1176,
            "expanded_handler_to_setter_path_count": 1560,
            "physical_store_set_site_count": 96,
            "expanded_store_path_count": 136,
            "unique_stored_setter_field_count_per_segment": 124,
            "pairwise_recursive_diff_count": 28,
            "legacy_profile_count": 6,
            "modern_profile_count": 2,
        }
        self.assertEqual(
            {key: scope[key] for key in expected},
            expected,
        )

    def test_03_every_scope_denominator_fails_closed(self) -> None:
        denominator_keys = [
            key
            for key, value in self.contract["scope"].items()
            if type(value) is int
        ]
        self.assertEqual(len(denominator_keys), 21)
        for key in denominator_keys:
            with self.subTest(key=key):
                changed = copy.deepcopy(self.contract)
                changed["scope"][key] -= 1
                self.assert_contract_rejected(changed)

    def test_04_categories_are_mutually_exclusive_and_complete(self) -> None:
        boolean_keys = (
            "selected_pool_tvl_setter_before_same_pool_save",
            "other_stored_field_with_setter_path_before_matching_store",
            "stored_field_on_reachable_store_without_setter_path",
            "derived_field_with_child_association_setter_path",
            "derived_field_without_direct_or_child_setter_path",
            "stored_field_outside_burn_store_closure",
        )
        category_totals: Counter[str] = Counter()
        for segment in self.contract["segments"]:
            outcomes = segment["semantic_surface"]["field_outcomes"]
            summary = segment["semantic_surface"]["field_outcome_summary"]
            self.assertEqual(len(outcomes), 299)
            self.assertEqual(
                len({(item["entity"], item["field"]) for item in outcomes}),
                299,
            )
            self.assertEqual(
                (
                    summary["selected_pool_tvl_setter_before_same_pool_save_count"],
                    summary["other_stored_field_with_setter_path_count"],
                    summary["reachable_store_without_setter_path_count"],
                    summary["derived_child_association_setter_path_count"],
                    summary["other_derived_without_direct_or_child_setter_path_count"],
                    summary["stored_field_outside_burn_store_closure_count"],
                    summary["required_absent_overlay_count"],
                ),
                (2, 122, 63, 5, 8, 99, 33),
            )
            for item in outcomes:
                self.assertEqual(sum(item[key] for key in boolean_keys), 1)
                category_totals[item["path_qualified_category"]] += 1
        self.assertEqual(
            category_totals,
            Counter(
                {
                    VERIFIER.CATEGORY_SELECTED: 16,
                    VERIFIER.CATEGORY_OTHER_SETTER: 976,
                    VERIFIER.CATEGORY_NO_SETTER: 504,
                    VERIFIER.CATEGORY_DERIVED_CHILD: 40,
                    VERIFIER.CATEGORY_DERIVED_OTHER: 64,
                    VERIFIER.CATEGORY_OUTSIDE: 792,
                }
            ),
        )

    def test_05_no_setter_and_derived_boundaries_do_not_overclaim(self) -> None:
        expected_associations = set(VERIFIER.DERIVED_CHILD_ASSOCIATIONS)
        for segment in self.contract["segments"]:
            outcomes = segment["semantic_surface"]["field_outcomes"]
            no_setter = [
                item
                for item in outcomes
                if item["stored_field_on_reachable_store_without_setter_path"]
            ]
            self.assertEqual(len(no_setter), 63)
            for item in no_setter:
                self.assertTrue(item["no_reachable_schema_api_setter_path_bound"])
                self.assertFalse(item["loaded_field_preservation_proven"])
                self.assertFalse(item["field_value_unchanged_proven"])
                self.assertFalse(item["field_value_semantics_complete"])
            derived = {
                (item["entity"], item["field"])
                for item in outcomes
                if item["derived_field_with_child_association_setter_path"]
            }
            self.assertEqual(derived, expected_associations)
            self.assertTrue(
                all(
                    not item["graph_store_persistence_proven"]
                    for item in outcomes
                )
            )

    def test_06_required_absence_is_an_independent_overlay(self) -> None:
        expected = Counter({"Collect": 11, "Flash": 12, "TickHourData": 10})
        for segment in self.contract["segments"]:
            outcomes = segment["semantic_surface"]["field_outcomes"]
            absent = [item for item in outcomes if item["required_absent_overlay"]]
            self.assertEqual(Counter(item["entity"] for item in absent), expected)
            self.assertEqual(len(absent), 33)
            self.assertTrue(all(item["static_required_absence_bound"] for item in absent))
            self.assertTrue(
                all(
                    item["path_qualified_category"] == VERIFIER.CATEGORY_OUTSIDE
                    for item in absent
                )
            )

    def test_07_lexical_physical_expanded_and_store_ledgers_are_separate(self) -> None:
        totals = Counter()
        for proof in self.contract["mapping_proofs"]:
            closure = proof["schema_api_invocation_closure"]
            inventory = proof["reachable_inventory"]
            store = proof["store_closure"]
            generation = proof["control_generation"]
            self.assertEqual(closure["lexical_field_invocation_count"], 147)
            self.assertEqual(closure["physical_site_to_invocation_edge_count"], 151)
            self.assertEqual(closure["nullable_branch_alternative_count"], 4)
            self.assertEqual(
                Counter(
                    (item["entity"], item["field"])
                    for item in closure["physical_site_to_invocation_edges"]
                    if item["nullable_branch_alternative"]
                ),
                Counter(VERIFIER.NULLABLE_FIELD_IDENTITIES),
            )
            self.assertEqual(closure["expanded_handler_to_setter_path_count"], 195)
            self.assertEqual(closure["unique_stored_setter_field_count"], 124)
            self.assertEqual(closure["unclassified_physical_typed_map_set_site_count"], 0)
            self.assertIn("distinct denominators", closure["physical_vs_semantic_ledger_warning"])
            self.assertEqual(
                inventory["physical_typed_map_set_site_count"],
                149 if generation == "modern" else 54,
            )
            self.assertEqual(store["physical_store_set_site_count"], 12)
            self.assertEqual(store["expanded_store_path_count"], 17)
            self.assertEqual(store["reachable_store_targets"], list(VERIFIER.STORE_TARGETS))
            totals.update(
                functions=inventory["reachable_function_count"],
                calls=inventory["direct_callsite_count"],
                writes=inventory["direct_memory_write_site_count"],
                physical_setters=inventory["physical_typed_map_set_site_count"],
                indirect=inventory["reachable_call_indirect_count"],
            )
        self.assertEqual(
            totals,
            Counter(
                functions=1240,
                calls=7084,
                writes=2048,
                physical_setters=622,
                indirect=2,
            ),
        )

    def test_08_helper_multiplicity_and_unique_field_denominators_are_exact(self) -> None:
        expected_multiplicity = {
            group: len(paths) for group, paths in VERIFIER.PATH_IDS.items()
        }
        expected_entity_counts = {
            "Burn": 15,
            "Factory": 3,
            "Pool": 6,
            "PoolDayData": 20,
            "PoolHourData": 20,
            "Tick": 4,
            "TickDayData": 12,
            "Token": 3,
            "TokenDayData": 14,
            "TokenHourData": 14,
            "Transaction": 5,
            "UniswapDayData": 8,
        }
        catalog_by_identity = {
            (item["entity"], item["field"]): item for item in self.field_catalog
        }
        for proof in self.contract["mapping_proofs"]:
            fanout = proof["helper_fanout"]
            closure = proof["schema_api_invocation_closure"]
            self.assertEqual(
                fanout["expanded_multiplicity_by_group"],
                expected_multiplicity,
            )
            self.assertEqual(
                closure["unique_stored_setter_entity_counts"],
                expected_entity_counts,
            )
            self.assertEqual(
                len(closure["unique_stored_setter_fields"]),
                124,
            )
            self.assertTrue(
                all(
                    catalog_by_identity[(item["entity"], item["field"])][
                        "storage"
                    ]
                    == "stored"
                    for item in closure["unique_stored_setter_fields"]
                )
            )

    def test_09_modern_and_legacy_guard_boundaries_are_exact(self) -> None:
        for proof in self.contract["mapping_proofs"]:
            ordering = proof["ordering_and_guards"]
            outer = ordering["outer_two_token_guard"]
            nested = ordering["nested_two_tick_guard"]
            self.assertTrue(ordering["handler_tick_setters_precede_tick_helper_calls"])
            self.assertFalse(ordering["imported_numeric_semantics_complete"])
            self.assertFalse(ordering["imported_comparator_semantics_complete"])
            self.assertFalse(ordering["contract_call_value_semantics_complete"])
            self.assertFalse(ordering["graph_store_persistence_proven"])
            if proof["control_generation"] == "modern":
                self.assertTrue(outer["all_handler_effect_callsites_inside_guard"])
                self.assertTrue(outer["missing_either_token_skips_entire_effect_body"])
                self.assertEqual(nested["tick_helper_control_depth"], 2)
                self.assertTrue(nested["missing_either_tick_skips_tick_and_tick_day_effects"])
            else:
                self.assertFalse(outer["all_handler_effect_callsites_inside_guard"])
                self.assertFalse(outer["missing_either_token_skips_entire_effect_body"])
                self.assertEqual(nested["tick_helper_control_depth"], 0)
                self.assertFalse(nested["missing_either_tick_skips_tick_and_tick_day_effects"])

    def test_10_all_28_recursive_diffs_reproduce(self) -> None:
        by_id = {item["segment_id"]: item for item in self.contract["segments"]}
        self.assertEqual(len(self.contract["segment_diffs"]), 28)
        for diff in self.contract["segment_diffs"]:
            left = by_id[diff["left_segment_id"]]
            right = by_id[diff["right_segment_id"]]
            self.assertEqual(
                diff["recursive_semantic_diff_paths"],
                VERIFIER.json_diff_paths(
                    left["semantic_surface"],
                    right["semantic_surface"],
                ),
            )
            self.assertEqual(
                diff["recursive_provenance_diff_paths"],
                VERIFIER.json_diff_paths(
                    left["provenance_surface"],
                    right["provenance_surface"],
                ),
            )
            self.assertFalse(diff["complete_entity_histories_compared"])
            self.assertFalse(diff["boundary_state_compared"])

    def test_11_only_scoped_truths_are_promoted(self) -> None:
        truth = self.contract["truth_boundary"]
        self.assertEqual(
            {key for key, value in truth.items() if value},
            set(VERIFIER.TRUE_FLAGS),
        )
        self.assertEqual(
            {key for key, value in truth.items() if not value},
            set(VERIFIER.FALSE_FLAGS),
        )
        for segment in self.contract["segments"]:
            self.assertEqual(segment["execution_model"], "undecided")
            self.assertFalse(segment["backfill_allowed"])
            self.assertFalse(segment["semantic_surface"]["complete_entity_history"])
            self.assertFalse(segment["semantic_surface"]["pool_burn_semantics_complete"])
        self.assertFalse(self.contract["scope"]["issue_acceptance_checkbox_completed"])

    def test_12_edge_multiplicity_nullable_receiver_key_and_store_mutations_fail_closed(self) -> None:
        mutations: list[dict[str, Any]] = []
        changed = copy.deepcopy(self.contract)
        changed["mapping_proofs"][0]["schema_api_invocation_closure"][
            "physical_site_to_invocation_edges"
        ][0]["site_relative_wat_line"] += 1
        mutations.append(changed)
        changed = copy.deepcopy(self.contract)
        changed["mapping_proofs"][0]["helper_fanout"][
            "expanded_multiplicity_by_group"
        ]["updateTokenDayData"] = 1
        mutations.append(changed)
        changed = copy.deepcopy(self.contract)
        edge = next(
            item
            for item in changed["mapping_proofs"][0]["schema_api_invocation_closure"][
                "physical_site_to_invocation_edges"
            ]
            if item["nullable_branch_alternative"]
        )
        edge["nullable_branch_alternative"] = False
        mutations.append(changed)
        changed = copy.deepcopy(self.contract)
        invocation = changed["mapping_proofs"][0]["schema_api_invocation_closure"][
            "lexical_field_invocations"
        ][0]
        invocation["receiver_context_bound_by_exact_caller_and_store_path"] = False
        mutations.append(changed)
        changed = copy.deepcopy(self.contract)
        changed["mapping_proofs"][0]["schema_api_invocation_closure"][
            "lexical_field_invocations"
        ][0]["field"] = "notAField"
        mutations.append(changed)
        changed = copy.deepcopy(self.contract)
        changed["mapping_proofs"][0]["store_closure"]["reachable_store_targets"][0] = "Mint"
        mutations.append(changed)
        for ordinal, changed in enumerate(mutations):
            with self.subTest(ordinal=ordinal):
                self.assert_contract_rejected(changed)

    def test_13_guard_category_preservation_truth_and_diff_mutations_fail_closed(self) -> None:
        mutations: list[dict[str, Any]] = []
        changed = copy.deepcopy(self.contract)
        modern = next(
            item
            for item in changed["mapping_proofs"]
            if item["control_generation"] == "modern"
        )
        modern["ordering_and_guards"]["outer_two_token_guard"][
            "all_handler_effect_callsites_inside_guard"
        ] = False
        mutations.append(changed)
        changed = copy.deepcopy(self.contract)
        outcome = changed["segments"][0]["semantic_surface"]["field_outcomes"][0]
        outcome["path_qualified_category"] = VERIFIER.CATEGORY_SELECTED
        outcome["stored_field_on_reachable_store_without_setter_path"] = False
        outcome["selected_pool_tvl_setter_before_same_pool_save"] = True
        mutations.append(changed)
        changed = copy.deepcopy(self.contract)
        no_setter = next(
            item
            for item in changed["segments"][0]["semantic_surface"]["field_outcomes"]
            if item["stored_field_on_reachable_store_without_setter_path"]
        )
        no_setter["loaded_field_preservation_proven"] = True
        mutations.append(changed)
        changed = copy.deepcopy(self.contract)
        changed["truth_boundary"]["backfill_ready"] = True
        mutations.append(changed)
        changed = copy.deepcopy(self.contract)
        changed["segment_diffs"].pop()
        mutations.append(changed)
        for ordinal, changed in enumerate(mutations):
            with self.subTest(ordinal=ordinal):
                self.assert_contract_rejected(changed, rehash=ordinal in {1, 2})

    def test_14_direct_schema_catalog_identity_shape_and_absence_fail_closed(self) -> None:
        records = copy.deepcopy(self.sources["schema_records"])
        catalog = copy.deepcopy(self.field_catalog)
        summary = VERIFIER.validate_field_catalog(catalog, records)
        self.assertFalse(summary["catalog_order_matches_direct_schema"])
        reversed_catalog = list(reversed(catalog))
        self.assertFalse(
            VERIFIER.validate_field_catalog(reversed_catalog, records)[
                "catalog_order_matches_direct_schema"
            ]
        )
        mutations: list[tuple[list[dict[str, Any]], list[dict[str, str]]]] = []
        changed_catalog = copy.deepcopy(catalog)
        changed_catalog.pop()
        mutations.append((changed_catalog, records))
        changed_catalog = copy.deepcopy(catalog)
        changed_catalog[0]["field"] = changed_catalog[1]["field"]
        mutations.append((changed_catalog, records))
        changed_records = copy.deepcopy(records)
        changed_records[0]["type"] = "String!"
        mutations.append((catalog, changed_records))
        changed_catalog = copy.deepcopy(catalog)
        absent = next(
            item
            for item in changed_catalog
            if item["population_classification"] == "required_absent"
        )
        absent["population_classification"] = "conditional"
        mutations.append((changed_catalog, records))
        for ordinal, (changed_catalog, changed_records) in enumerate(mutations):
            with self.subTest(ordinal=ordinal):
                with self.assertRaises(VERIFIER.VerificationError):
                    VERIFIER.validate_field_catalog(changed_catalog, changed_records)

    def test_15_parent_store_and_guard_evidence_mutations_fail_closed(self) -> None:
        context = self.by_profile["modern-base"]
        parent = self.parent_by_cid[context["mapping_cid"]]
        mutations = []
        changed = copy.deepcopy(parent)
        changed["persistence_and_effect_closure"]["direct_pool_save_count"] = 2
        mutations.append(changed)
        changed = copy.deepcopy(parent)
        changed["persistence_and_effect_closure"]["transitive_store_evidence"][
            "reachable_store_set_targets"
        ][0] = "Mint"
        mutations.append(changed)
        changed = copy.deepcopy(parent)
        changed["token_loads_and_presence_control"][
            "selected_update_guard_start_index"
        ] += 500
        mutations.append(changed)
        for ordinal, changed in enumerate(mutations):
            with self.subTest(ordinal=ordinal):
                with self.assertRaises(self.expected_errors):
                    VERIFIER.prove_complete_context(
                        context,
                        changed,
                        self.field_catalog,
                    )

    def test_16_compile_valid_receiver_key_and_store_authority_mutations_fail_closed(self) -> None:
        context = self.by_profile["legacy-mainnet-root"]
        handler = context["handler"]
        selected_index = next(
            index
            for index, line in enumerate(handler.lines)
            if (VERIFIER.BURN.call_name(line) or "").endswith(
                "schema/Pool#set:totalValueLockedToken0"
            )
        )
        self.assert_wat_rejected(
            context,
            [
                (
                    handler.name,
                    lambda lines, _context: self.replace(
                        lines,
                        selected_index - 4,
                        "i32.const 0",
                    ),
                )
            ],
        )

        helper = self.function_by_suffix(context, "updatePoolDayData")
        date_index = next(
            index
            for index, line in enumerate(helper.lines)
            if (VERIFIER.BURN.call_name(line) or "").endswith(
                "schema/PoolDayData#set:date"
            )
        )
        pool_target = next(
            VERIFIER.BURN.call_name(line)
            for line in helper.lines
            if (VERIFIER.BURN.call_name(line) or "").endswith(
                "schema/PoolDayData#set:pool"
            )
        )
        assert pool_target is not None
        self.assert_wat_rejected(
            context,
            [
                (
                    helper.name,
                    lambda lines, _context: self.replace(
                        lines,
                        date_index,
                        f"call ${pool_target}",
                    ),
                )
            ],
        )

        save = self.function_by_suffix(context, "schema/Pool#save")
        pool_key = next(
            index
            for index, line in enumerate(save.lines)
            if VERIFIER.BURN.decoded_constant(line, context["memory"]) == "Pool"
        )
        self.assert_wat_rejected(
            context,
            [
                (
                    save.name,
                    lambda lines, _context: self.replace(
                        lines,
                        pool_key,
                        "i32.const 0",
                    ),
                )
            ],
        )

    def test_17_nullable_physical_site_mutation_fails_closed(self) -> None:
        context = self.by_profile["legacy-mainnet-qmrv"]
        # The deployed legacy module deduplicates this nullable setter under
        # Pool#set:tick even when PoolDayData calls it. The caller supplies the
        # entity authority; the symbol name does not.
        nullable = self.function_by_suffix(context, "schema/Pool#set:tick")
        map_set = VERIFIER.BURN.LEGACY_ENTITY_MAP_SET_CALL
        site = next(
            index
            for index, line in enumerate(nullable.lines)
            if VERIFIER.BURN.call_name(line) == map_set
        )

        def remove_site(lines: list[str], _context: dict[str, Any]) -> None:
            indent = lines[site][: len(lines[site]) - len(lines[site].lstrip())]
            lines[site : site + 1] = [
                f"{indent}drop",
                f"{indent}drop",
                f"{indent}drop",
            ]

        self.assert_wat_rejected(context, [(nullable.name, remove_site)])

    def test_18_duplicate_json_keys_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pool-burn-v2-json-") as temporary:
            path = Path(temporary) / "duplicate.json"
            path.write_text('{"format_version":1,"format_version":1}\n')
            with self.assertRaises(self.expected_errors):
                VERIFIER.load_json(path)

    def test_19_detached_regeneration_is_byte_identical(self) -> None:
        committed = (ROOT / VERIFIER.CONTRACT_PATH).read_bytes()
        with tempfile.TemporaryDirectory(prefix="pool-burn-v2-detached-") as temporary:
            detached = Path(temporary) / "repository"
            shutil.copytree(
                ROOT,
                detached,
                ignore=shutil.ignore_patterns(
                    ".git",
                    "target",
                    "__pycache__",
                    "*.pyc",
                ),
            )
            generated = detached / VERIFIER.CONTRACT_PATH
            generated.unlink()
            result = subprocess.run(
                [
                    sys.executable,
                    str(detached / "scripts/verify-uniswap-v3-pool-burn-v2.py"),
                    "--root",
                    str(detached),
                    "--wasm2wat",
                    str(self.wasm2wat),
                    "--write-contract",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertEqual(generated.read_bytes(), committed)

    def test_20_documentation_indexes_and_ci_preserve_the_boundary(self) -> None:
        component = (ROOT / "uniswap-v3/pool-burn/v2/README.md").read_text()
        eligibility = (
            ROOT / "uniswap-v3/pool-burn/v2/docs/eligibility.md"
        ).read_text()
        provenance = (
            ROOT / "uniswap-v3/pool-burn/v2/docs/provenance.md"
        ).read_text()
        indexes = (ROOT / "README.md").read_text() + (
            ROOT / "uniswap-v3/README.md"
        ).read_text()
        workflow = (ROOT / ".github/workflows/ci.yaml").read_text()
        combined = component + eligibility + provenance
        for value in (
            "299",
            "2,392",
            "16",
            "976",
            "504",
            "40",
            "64",
            "792",
            "264",
            "147",
            "151",
            "195",
            "17",
            "124",
            "28",
        ):
            self.assertIn(value, combined)
        self.assertIn("pool-burn/v2", indexes)
        self.assertIn("pool-burn-v2.py", workflow)
        self.assertIn("Physical and semantic ledgers must not be conflated", combined)
        self.assertIn("no issue checkbox", combined.lower())
        self.assertNotIn("preserved or unchanged", component.split("never", 1)[0])
        for gate in (
            "scheduler_implemented",
            "output_implemented",
            "store_implemented",
            "package_implemented",
            "checkpoint_authority",
            "backfill_ready",
            "deployment_ready",
            "production_ready",
            "readiness_complete",
        ):
            self.assertIn(gate, eligibility)


if __name__ == "__main__":
    unittest.main()
