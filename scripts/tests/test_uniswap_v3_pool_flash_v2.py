from __future__ import annotations

import copy
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[2]
VERIFIER_PATH = ROOT / "scripts/verify-uniswap-v3-pool-flash-v2.py"
SPEC = importlib.util.spec_from_file_location("uniswap_v3_pool_flash_v2", VERIFIER_PATH)
assert SPEC is not None and SPEC.loader is not None
VERIFIER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VERIFIER
SPEC.loader.exec_module(VERIFIER)

Mutation = tuple[str, Callable[[list[str], dict[str, Any]], None]]


class PoolFlashV2Test(unittest.TestCase):
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
        cls.field_catalog = cls.sources["field_catalog"]
        wasm2wat = next(iter(cls.contexts.values()))["wasm2wat"]
        cls.wasm2wat = VERIFIER.FLASH.INITIALIZE.resolve_tool(wasm2wat, "wasm2wat")
        cls.wat2wasm = VERIFIER.FLASH.INITIALIZE.resolve_tool(
            wasm2wat.with_name("wat2wasm"),
            "wat2wasm",
        )
        cls.expected_errors = tuple(
            dict.fromkeys((VERIFIER.VerificationError, *VERIFIER.UPSTREAM_ERRORS))
        )

    @staticmethod
    def replace(lines: list[str], index: int, instruction: str) -> None:
        indent = lines[index][: len(lines[index]) - len(lines[index].lstrip())]
        closing = ")" if lines[index].rstrip().endswith(")") and not instruction.rstrip().endswith(")") else ""
        lines[index] = f"{indent}{instruction}{closing}"

    @staticmethod
    def insert(lines: list[str], index: int, instructions: list[str]) -> None:
        indent = lines[index][: len(lines[index]) - len(lines[index].lstrip())]
        lines[index:index] = [f"{indent}{instruction}" for instruction in instructions]

    def function_by_suffix(self, context: dict[str, Any], suffix: str) -> Any:
        matches = [
            function
            for name, function in context["functions"].items()
            if name.endswith(suffix)
        ]
        self.assertEqual(len(matches), 1, suffix)
        return matches[0]

    def roundtrip(self, context: dict[str, Any], mutations: list[Mutation]) -> dict[str, Any]:
        replacements = []
        for function_name, mutate in mutations:
            function = context["functions"][function_name]
            lines = list(function.lines)
            mutate(lines, context)
            replacements.append((function.start_line - 1, len(function.lines), lines))
        wat_lines = context["wat_text"].splitlines()
        for start, length, replacement in sorted(replacements, reverse=True):
            wat_lines[start : start + length] = replacement
        with tempfile.TemporaryDirectory(prefix="pool-flash-v2-wat-") as temporary:
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
        memory, functions, indirect_targets, exports = VERIFIER.WRITER.parse_wat(regenerated)
        handler = VERIFIER.WRITER.resolve_handler(functions, exports, VERIFIER.HANDLER_EXPORT)
        return {
            **context,
            "memory": memory,
            "functions": functions,
            "indirect_targets": tuple(indirect_targets),
            "exports": exports,
            "handler": handler,
            "wat_text": regenerated,
        }

    def assert_wat_rejected(self, context: dict[str, Any], mutations: list[Mutation]) -> None:
        with self.assertRaises(self.expected_errors):
            VERIFIER.prove_complete_context(
                self.roundtrip(context, mutations),
                self.field_catalog,
            )

    def assert_contract_rejected(self, value: dict[str, Any]) -> None:
        with self.assertRaises(self.expected_errors):
            VERIFIER.verify_contract(
                ROOT,
                value,
                sources=self.sources,
                recompute_wat=False,
            )

    def handler_mutation(self, context: dict[str, Any], index: int, instruction: str) -> Mutation:
        return (
            context["handler"].name,
            lambda lines, _context: self.replace(lines, index, instruction),
        )

    def test_01_committed_contract_is_deterministic(self) -> None:
        self.assertEqual(
            self.contract,
            VERIFIER.expected_contract_from_sources(self.sources),
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

    def test_02_exact_denominators_and_mutually_exclusive_categories(self) -> None:
        scope = self.contract["scope"]
        self.assertEqual(
            (
                scope["schema_field_count_per_segment"],
                scope["field_outcome_count"],
                scope["selected_fee_growth_setter_before_save_outcome_count"],
                scope["other_stored_pool_without_reachable_schema_setter_before_save_outcome_count"],
                scope["derived_pool_without_direct_graph_store_transition_outcome_count"],
                scope["outside_pool_only_graph_store_closure_outcome_count"],
                scope["flash_required_absent_outcome_count"],
                scope["pairwise_recursive_diff_count"],
            ),
            (299, 2392, 16, 216, 56, 2104, 96, 28),
        )
        for segment in self.contract["segments"]:
            outcomes = segment["semantic_surface"]["field_outcomes"]
            self.assertEqual(len(outcomes), 299)
            self.assertEqual(
                len({(item["entity"], item["field"]) for item in outcomes}),
                299,
            )
            for item in outcomes:
                self.assertEqual(
                    sum(
                        (
                            item["selected_fee_growth_setter_before_save"],
                            item["other_stored_pool_without_reachable_schema_setter_before_save"],
                            item["derived_pool_without_direct_graph_store_transition"],
                            item["outside_pool_only_graph_store_closure"],
                        )
                    ),
                    1,
                )

    def test_03_selected_fields_are_the_only_reachable_schema_setters(self) -> None:
        for segment in self.contract["segments"]:
            semantic = segment["semantic_surface"]
            closure = semantic["schema_api_and_store_closure"]
            self.assertEqual(
                (
                    closure["reachable_schema_setter_site_count"],
                    closure["selected_schema_setter_site_count"],
                    closure["other_reachable_schema_setter_site_count"],
                ),
                (2, 2, 0),
            )
            selected = [
                item
                for item in semantic["field_outcomes"]
                if item["selected_fee_growth_setter_before_save"]
            ]
            self.assertEqual([item["field"] for item in selected], list(VERIFIER.SELECTED_FIELDS))
            for item in selected:
                self.assertTrue(item["schema_setter_reachable_for_field"])
                self.assertTrue(item["same_loaded_pool_reaches_sole_save_machine_bound"])
                self.assertEqual(item["selected_structural_value_flow"]["decode_index"], 0)
                self.assertFalse(item["selected_structural_value_flow"]["host_return_value_semantics_complete"])

    def test_04_other_stored_pool_fields_make_no_value_claim(self) -> None:
        for segment in self.contract["segments"]:
            other = [
                item
                for item in segment["semantic_surface"]["field_outcomes"]
                if item["other_stored_pool_without_reachable_schema_setter_before_save"]
            ]
            self.assertEqual(len(other), 27)
            for item in other:
                self.assertFalse(item["schema_setter_reachable_for_field"])
                self.assertTrue(
                    item[
                        "no_reachable_schema_setter_for_field_before_same_pool_save_machine_bound"
                    ]
                )
                self.assertTrue(item["same_loaded_pool_reaches_sole_save_machine_bound"])
                self.assertFalse(item["field_value_semantics_complete"])
                self.assertFalse(item["field_value_unchanged_proven"])

    def test_05_derived_outside_and_flash_absence_counts_are_exact(self) -> None:
        for segment in self.contract["segments"]:
            outcomes = segment["semantic_surface"]["field_outcomes"]
            derived = [item for item in outcomes if item["derived_pool_without_direct_graph_store_transition"]]
            outside = [item for item in outcomes if item["outside_pool_only_graph_store_closure"]]
            flash = [item for item in outcomes if item["flash_required_absent"]]
            self.assertEqual((len(derived), len(outside), len(flash)), (7, 263, 12))
            self.assertTrue(all(item["storage"] == "derived" for item in derived))
            self.assertTrue(all(item["no_direct_graph_store_transition_machine_bound"] for item in derived))
            self.assertTrue(all(item["pool_only_graph_store_target_excludes_entity"] for item in outside))
            self.assertTrue(all(item["entity"] == "Flash" for item in flash))
            self.assertTrue(all(item["static_required_absence_machine_bound"] for item in flash))
            self.assertTrue(all(not item["complete_entity_history"] for item in outcomes))

    def test_06_normal_success_ordering_and_host_boundaries_are_exact(self) -> None:
        for proof in self.contract["mapping_proofs"]:
            ordering = proof["normal_success_ordering"]
            closure = proof["schema_api_and_store_closure"]
            self.assertTrue(ordering["event_address_pool_load_machine_bound"])
            self.assertTrue(ordering["event_address_contract_bind_machine_bound"])
            self.assertTrue(ordering["fee0_before_fee1_machine_bound"])
            self.assertTrue(ordering["both_setters_after_both_successful_decodes_machine_bound"])
            self.assertTrue(ordering["same_loaded_pool_reaches_sole_save_machine_bound"])
            self.assertTrue(ordering["nontry_null_branches_trap_before_setters_and_save_machine_bound"])
            self.assertFalse(ordering["host_call_value_semantics_complete"])
            self.assertFalse(ordering["host_call_error_semantics_complete"])
            self.assertEqual(closure["reachable_graph_store_targets"], ["Pool"])
            self.assertEqual(closure["reachable_graph_store_set_site_count"], 1)
            self.assertFalse(closure["flash_entity_store_target_reachable"])
            self.assertFalse(closure["graph_store_persistence_proven"])

    def test_07_all_28_recursive_diffs_reproduce(self) -> None:
        by_id = {item["segment_id"]: item for item in self.contract["segments"]}
        self.assertEqual(len(self.contract["segment_diffs"]), 28)
        for diff in self.contract["segment_diffs"]:
            left = by_id[diff["left_segment_id"]]
            right = by_id[diff["right_segment_id"]]
            self.assertEqual(
                diff["recursive_semantic_diff_paths"],
                VERIFIER.json_diff_paths(left["semantic_surface"], right["semantic_surface"]),
            )
            self.assertEqual(
                diff["recursive_provenance_diff_paths"],
                VERIFIER.json_diff_paths(left["provenance_surface"], right["provenance_surface"]),
            )
            self.assertTrue(diff["recursive_semantic_diff_paths"])
            self.assertTrue(diff["recursive_provenance_diff_paths"])
            self.assertFalse(diff["complete_entity_histories_compared"])
            self.assertFalse(diff["boundary_state_compared"])

    def test_08_all_broad_live_and_issue_gates_remain_false(self) -> None:
        truth = self.contract["truth_boundary"]
        self.assertEqual({key for key, value in truth.items() if value}, set(VERIFIER.TRUE_FLAGS))
        self.assertEqual({key for key, value in truth.items() if not value}, set(VERIFIER.FALSE_FLAGS))
        for key in (
            "host_call_value_semantics_complete",
            "graph_store_persistence_proven",
            "complete_entity_history",
            "scheduler_implemented",
            "output_implemented",
            "store_implemented",
            "package_implemented",
            "boundary_continuity_complete",
            "logical_parity_complete",
            "physical_parity_complete",
            "poi_parity_complete",
            "checkpoint_authority",
            "backfill_ready",
            "deployment_ready",
            "production_ready",
            "readiness_complete",
        ):
            with self.subTest(key=key):
                self.assertIs(truth[key], False)
        self.assertFalse(self.contract["scope"]["issue_acceptance_checkbox_completed"])

    def test_09_modern_call_decode_order_mutation_is_rejected(self) -> None:
        context = self.by_profile["modern-base"]
        replacement = VERIFIER.FLASH.normalized(context["handler"].lines[41])
        self.assert_wat_rejected(
            context,
            [self.handler_mutation(context, 29, replacement)],
        )

    def test_10_modern_second_decode_mutation_is_rejected(self) -> None:
        context = self.by_profile["modern-mainnet"]

        def mutate(lines: list[str], _context: dict[str, Any]) -> None:
            indent = lines[50][: len(lines[50]) - len(lines[50].lstrip())]
            lines[50:51] = [f"{indent}drop", f"{indent}i32.const 0"]

        self.assert_wat_rejected(context, [(context["handler"].name, mutate)])

    def test_11_setter_receiver_and_same_pool_save_mutations_are_rejected(self) -> None:
        context = self.by_profile["modern-base"]
        self.assert_wat_rejected(context, [self.handler_mutation(context, 70, "i32.const 0")])
        self.assert_wat_rejected(context, [self.handler_mutation(context, 88, "i32.const 0")])

    def test_12_nontry_null_trap_fallthrough_is_rejected(self) -> None:
        context = self.by_profile["modern-mainnet"]
        helper = self.function_by_suffix(context, "ethereum.SmartContract#call")
        self.assert_wat_rejected(
            context,
            [(helper.name, lambda lines, _context: self.replace(lines, 57, "nop"))],
        )

    def test_13_legacy_alias_key_and_call_order_mutations_are_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-root"]
        setter = self.function_by_suffix(context, "PoolDayData#set:feeGrowthGlobal0X128")
        self.assert_wat_rejected(
            context,
            [(setter.name, lambda lines, _context: self.replace(lines, 2, "i32.const 0"))],
        )
        target = VERIFIER.FLASH.call_name(context["handler"].lines[14])
        assert target is not None
        self.assert_wat_rejected(context, [self.handler_mutation(context, 11, f"call ${target}")])

    def test_14_pool_only_store_target_and_reachable_inventory_mutations_are_rejected(self) -> None:
        context = self.by_profile["legacy-base-root"]
        save = self.function_by_suffix(context, "schema/Pool#save")
        key = next(
            index
            for index, line in enumerate(save.lines)
            if VERIFIER.FLASH.decoded_constant(line, context["memory"]) == "Pool"
        )
        self.assert_wat_rejected(
            context,
            [(save.name, lambda lines, _context: self.replace(lines, key, "i32.const 0"))],
        )
        value = self.function_by_suffix(context, "Value.fromBigInt")
        self.assert_wat_rejected(
            context,
            [
                (
                    value.name,
                    lambda lines, _context: self.insert(
                        lines,
                        10,
                        ["i32.const 0", "i32.const 0", "i32.store"],
                    ),
                )
            ],
        )

    def test_15_every_scope_denominator_fails_closed(self) -> None:
        denominators = {
            "schema_field_count_per_segment": 298,
            "field_outcome_count": 2391,
            "selected_fee_growth_setter_before_save_outcome_count": 15,
            "other_stored_pool_without_reachable_schema_setter_before_save_outcome_count": 215,
            "derived_pool_without_direct_graph_store_transition_outcome_count": 55,
            "outside_pool_only_graph_store_closure_outcome_count": 2103,
            "flash_required_absent_outcome_count": 95,
            "pairwise_recursive_diff_count": 27,
        }
        for key, value in denominators.items():
            with self.subTest(key=key):
                changed = copy.deepcopy(self.contract)
                changed["scope"][key] = value
                self.assert_contract_rejected(changed)

    def test_16_segment_category_omissions_and_overpromotions_fail_closed(self) -> None:
        mutations = []
        changed = copy.deepcopy(self.contract)
        changed["segments"][0]["semantic_surface"]["field_outcomes"].pop()
        changed["segments"][0]["semantic_surface_sha256"] = VERIFIER.canonical_sha256(
            changed["segments"][0]["semantic_surface"]
        )
        mutations.append(changed)
        changed = copy.deepcopy(self.contract)
        changed["segments"][0]["semantic_surface"]["field_outcome_summary"][
            "other_stored_pool_without_reachable_schema_setter_before_save_count"
        ] = 26
        mutations.append(changed)
        changed = copy.deepcopy(self.contract)
        changed["segments"][0]["semantic_surface"]["field_outcomes"][0][
            "field_value_unchanged_proven"
        ] = True
        mutations.append(changed)
        changed = copy.deepcopy(self.contract)
        changed["segments"][0]["semantic_surface"]["field_outcomes"][0][
            "graph_store_persistence_proven"
        ] = True
        mutations.append(changed)
        changed = copy.deepcopy(self.contract)
        changed["truth_boundary"]["backfill_ready"] = True
        mutations.append(changed)
        changed = copy.deepcopy(self.contract)
        changed["mapping_proofs"][0]["complete_pool_flash_handler_semantics"] = True
        mutations.append(changed)
        changed = copy.deepcopy(self.contract)
        changed["segment_diffs"].pop()
        mutations.append(changed)
        for ordinal, changed in enumerate(mutations):
            with self.subTest(ordinal=ordinal):
                self.assert_contract_rejected(changed)

    def test_17_source_and_direct_recomputation_bindings_fail_closed(self) -> None:
        self.assertTrue(self.contract["source_contracts"]["pool_flash_v1"]["recomputed_directly"])
        self.assertTrue(
            self.contract["source_contracts"]["segment_field_semantics_v2"][
                "recomputed_directly"
            ]
        )
        self.assertTrue(
            self.contract["source_contracts"]["segment_field_semantics_v2"][
                "matches_pool_flash_v1_dependency"
            ]
        )
        for source, key in (
            ("pool_flash_v1_verifier", "raw_sha256"),
            ("pool_flash_v1", "canonical_sha256"),
            ("pool_flash_v1", "transitive_source_contracts_sha256"),
            ("segment_field_semantics_v2_verifier", "raw_sha256"),
            ("segment_field_semantics_v2", "field_catalog_sha256"),
        ):
            with self.subTest(source=source, key=key):
                changed = copy.deepcopy(self.contract)
                changed["source_contracts"][source][key] = "0" * 64
                self.assert_contract_rejected(changed)

    def test_18_duplicate_json_keys_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pool-flash-v2-json-") as temporary:
            path = Path(temporary) / "duplicate.json"
            path.write_text('{"format_version":1,"format_version":1}\n')
            with self.assertRaises(self.expected_errors):
                VERIFIER.load_json(path)

    def test_19_documentation_and_indexes_preserve_the_boundary(self) -> None:
        component = (ROOT / "uniswap-v3/pool-flash/v2/README.md").read_text()
        eligibility = (ROOT / "uniswap-v3/pool-flash/v2/docs/eligibility.md").read_text()
        provenance = (ROOT / "uniswap-v3/pool-flash/v2/docs/provenance.md").read_text()
        indexes = (ROOT / "README.md").read_text() + (ROOT / "uniswap-v3/README.md").read_text()
        combined = component + eligibility + provenance
        for value in ("299", "2,392", "16", "216", "56", "2,104", "96", "28"):
            self.assertIn(value, combined)
        self.assertIn("pool-flash/v2", indexes)
        self.assertIn("Factory static v2 is not an input", combined)
        self.assertIn("no issue checkbox", combined.lower())
        for gate in (
            "scheduler_implemented",
            "output_implemented",
            "store_implemented",
            "package_implemented",
            "backfill_ready",
            "deployment_ready",
            "production_ready",
            "readiness_complete",
        ):
            self.assertIn(gate, eligibility)


if __name__ == "__main__":
    unittest.main()
