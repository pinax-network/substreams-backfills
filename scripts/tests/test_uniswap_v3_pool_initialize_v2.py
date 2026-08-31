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
VERIFIER_PATH = ROOT / "scripts/verify-uniswap-v3-pool-initialize-v2.py"
SPEC = importlib.util.spec_from_file_location("uniswap_v3_pool_initialize_v2", VERIFIER_PATH)
assert SPEC is not None and SPEC.loader is not None
VERIFIER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VERIFIER
SPEC.loader.exec_module(VERIFIER)

Mutation = tuple[str, Callable[[list[str], dict[str, Any]], None]]


class PoolInitializeV2Test(unittest.TestCase):
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
            for item in cls.sources["initialize_contract"]["mapping_proofs"]
        }
        cls.proof_by_cid = {
            item["mapping_cid"]: item
            for item in cls.contract["mapping_proofs"]
        }
        cls.field_catalog = cls.sources["field_catalog"]
        wasm2wat = next(iter(cls.contexts.values()))["wasm2wat"]
        cls.wasm2wat = VERIFIER.INITIALIZE.resolve_tool(wasm2wat, "wasm2wat")
        cls.wat2wasm = VERIFIER.INITIALIZE.resolve_tool(
            wasm2wat.with_name("wat2wasm"),
            "wat2wasm",
        )

    @staticmethod
    def replace(lines: list[str], index: int, instruction: str) -> None:
        indent = lines[index][: len(lines[index]) - len(lines[index].lstrip())]
        closing = ")" if lines[index].rstrip().endswith(")") and not instruction.rstrip().endswith(")") else ""
        lines[index] = f"{indent}{instruction}{closing}"

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
        with tempfile.TemporaryDirectory(prefix="pool-initialize-v2-wat-") as temporary:
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
        changed = self.roundtrip(context, mutations)
        with self.assertRaises(VERIFIER.VerificationError):
            VERIFIER.prove_complete_context(
                changed,
                self.parent_by_cid[context["mapping_cid"]],
                self.field_catalog,
            )

    def rehash_contract_surfaces(self, contract: dict[str, Any]) -> None:
        proof_hashes = {
            proof["mapping_cid"]: VERIFIER.canonical_sha256(proof)
            for proof in contract["mapping_proofs"]
        }
        for segment in contract["segments"]:
            segment["semantic_surface_sha256"] = VERIFIER.canonical_sha256(
                segment["semantic_surface"]
            )
            segment["provenance_surface"]["mapping_proof_sha256"] = proof_hashes[
                segment["provenance_surface"]["mapping_cid"]
            ]
            segment["provenance_surface_sha256"] = VERIFIER.canonical_sha256(
                segment["provenance_surface"]
            )
        contract["segment_diffs"] = VERIFIER.build_segment_diffs(contract["segments"])

    def assert_contract_rejected(self, contract: dict[str, Any]) -> None:
        self.rehash_contract_surfaces(contract)
        with self.assertRaises(VERIFIER.VerificationError):
            VERIFIER.verify_contract(
                ROOT,
                contract,
                sources=self.sources,
                recompute_wat=False,
            )

    def test_01_committed_contract_is_deterministic(self) -> None:
        self.assertEqual(self.contract, VERIFIER.expected_contract_from_sources(self.sources))
        result = subprocess.run(
            [sys.executable, str(VERIFIER_PATH), "--root", str(ROOT), "--wasm2wat", str(self.wasm2wat)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("8 segments, 2392 field outcomes, 28 diffs", result.stdout)
        self.assertIn("no issue checkbox completed", result.stdout)

    def test_02_all_segments_have_exact_299_field_outcomes(self) -> None:
        self.assertEqual(len(self.contract["segments"]), 8)
        self.assertEqual(
            sum(len(item["semantic_surface"]["field_outcomes"]) for item in self.contract["segments"]),
            2392,
        )
        for segment in self.contract["segments"]:
            surface = segment["semantic_surface"]
            outcomes = surface["field_outcomes"]
            self.assertEqual(len(outcomes), 299)
            self.assertEqual(
                len({(item["entity"], item["field"]) for item in outcomes}),
                299,
            )
            expected_associations = 95 if surface["pool_saved"] else 59
            self.assertEqual(
                surface["field_outcome_summary"]["conservative_entity_writer_association_count"],
                expected_associations,
            )
            self.assertEqual(
                surface["field_outcome_summary"]["direct_stored_field_association_count"],
                87 if surface["pool_saved"] else 58,
            )
            self.assertTrue(all(item["complete_path_qualified_static_initialize_outcome"] for item in outcomes))
            self.assertTrue(all(not item["complete_entity_history"] for item in outcomes))
            self.assertEqual(segment["execution_model"], "undecided")
            self.assertFalse(segment["backfill_allowed"])

    def test_03_complete_transition_ledgers_preserve_only_proved_call_order(self) -> None:
        for segment in self.contract["segments"]:
            surface = segment["semantic_surface"]
            proof = self.proof_by_cid[segment["provenance_surface"]["mapping_cid"]]
            by_field = {
                (item["entity"], item["field"]): item
                for item in surface["field_outcomes"]
            }
            pool_sqrt = by_field[("Pool", "sqrtPrice")]
            day_sqrt = by_field[("PoolDayData", "sqrtPrice")]
            token_derived = by_field[("Token", "derivedETH")]
            if surface["pool_saved"]:
                self.assertEqual(pool_sqrt["static_transition"], "write_before_entity_save")
            else:
                self.assertEqual(pool_sqrt["static_transition"], "in_memory_write_without_reachable_pool_store")
            self.assertIn("visibility/version", day_sqrt["value_or_preservation_source"])
            self.assertIn("unproved", day_sqrt["value_or_preservation_source"])
            order = proof["handler_save_and_window_store_get_order"]
            self.assertEqual(order["pool_save_call_present"], surface["pool_saved"])
            self.assertFalse(order["pool_store_get_return_visibility_or_version_proven"])
            self.assertFalse(order["imported_graph_store_read_after_write_semantics_complete"])
            if surface["pool_saved"]:
                self.assertLess(
                    order["pool_save_relative_wat_line"],
                    order["day_helper_call_relative_wat_line"],
                )
            else:
                self.assertIsNone(order["pool_save_relative_wat_line"])
            for helper in ("day_helper_pool_store_get_path", "hour_helper_pool_store_get_path"):
                self.assertTrue(order[helper]["helper_reaches_exact_pool_store_get"])
                self.assertFalse(order[helper]["pool_store_get_return_visibility_or_version_proven"])
            if surface["control_generation"] == "modern":
                self.assertEqual(token_derived["static_transition"], "conditional_both_tokens_write_else_no_token_store")
                self.assertTrue(token_derived["conditional_transition"])
            else:
                self.assertIn("successful_non_null_path", token_derived["static_transition"])
            self.assertEqual(by_field[("PoolHourData", "close")]["static_transition"], "write_before_entity_save")
            self.assertEqual(by_field[("PoolDayData", "close")]["static_transition"], "conditional_create_write_else_preserve")
            for entity in ("PoolDayData", "PoolHourData"):
                tick = by_field[(entity, "tick")]
                self.assertEqual(tick["schema_type"], "BigInt")
                self.assertEqual(
                    tick["static_transition"],
                    "nullable_setter_non_null_write_or_null_or_unset_before_entity_save",
                )
                self.assertIn("null branch", tick["value_or_preservation_source"])
                tx_count = by_field[(entity, "txCount")]
                self.assertEqual(
                    tx_count["static_transition"],
                    "big_int_plus_result_write_before_entity_save",
                )
                self.assertIn("BigInt#plus", tx_count["value_or_preservation_source"])
                self.assertIn("numeric semantics are unproved", tx_count["value_or_preservation_source"])
                for field in ("high", "low"):
                    outcome = by_field[(entity, field)]
                    self.assertEqual(
                        outcome["static_transition"],
                        "missing_row_create_write_then_comparator_return_controlled_optional_write_else_preserve",
                    )
                    self.assertIn("unconditionally invokes", outcome["value_or_preservation_source"])
                    self.assertIn("comparator", outcome["value_or_preservation_source"])
                    self.assertIn("semantics are unproved", outcome["value_or_preservation_source"])
            day_id_source = by_field[("PoolDayData", "id")]["value_or_preservation_source"]
            self.assertIn("hex(event.address)", day_id_source)
            self.assertIn("signed-i32", day_id_source)
            self.assertIn("86400", day_id_source)
            for derived_key in (("Pool", "poolDayData"), ("Token", "tokenDayData")):
                derived = by_field[derived_key]
                self.assertEqual(derived["storage"], "derived")
                self.assertIn("@derivedFrom", derived["directives"])
                self.assertFalse(derived["direct_stored_field_association"])
            pool_day_relation = by_field[("Pool", "poolDayData")]
            self.assertEqual(
                pool_day_relation["static_transition"],
                "conditional_child_create_adds_derived_relation_else_preserve",
            )
            self.assertTrue(pool_day_relation["conditional_transition"])
            self.assertTrue(pool_day_relation["potential_query_visible_transition"])
            token_day_relation = by_field[("Token", "tokenDayData")]
            self.assertEqual(
                token_day_relation["static_transition"],
                "derived_query_field_no_direct_store_transition",
            )
            self.assertFalse(token_day_relation["potential_query_visible_transition"])

    def test_04_every_mapping_closes_writes_calls_saves_and_indirect_targets(self) -> None:
        self.assertEqual(len(self.contract["mapping_proofs"]), 8)
        for proof in self.contract["mapping_proofs"]:
            closure = proof["complete_reachable_mutation_and_call_closure"]
            saving = proof["initialize_v1_pool_projection"]["persistence"]["profile_expected_to_persist"]
            self.assertTrue(closure["all_reachable_function_bodies_bound"])
            self.assertTrue(closure["all_reachable_setter_save_remove_helper_and_indirect_sites_accounted"])
            self.assertEqual(closure["reachable_store_set_site_count"], 5 if saving else 4)
            self.assertEqual(closure["schema_save_invocation_count"], 6 if saving else 5)
            self.assertEqual(closure["reachable_store_remove_call_count"], 0)
            self.assertEqual(closure["reachable_ethereum_call_count"], 0)
            self.assertEqual(closure["reachable_call_indirect_count"], 1 if proof["control_generation"] == "modern" else 0)
            self.assertEqual(len(closure["closed_indirect_table_targets"]), 1)
            self.assertEqual(proof["complete_static_expanded_field_invocation_site_count"], 56)
            self.assertTrue(
                proof["handler_field_invocation_ledger"]
                ["potential_lexical_invocation_sites_not_one_execution_trace"]
            )
            self.assertEqual(
                proof["window_helper_ledgers"]["PoolDayData"]["expanded_field_invocation_count"],
                25,
            )
            self.assertEqual(
                proof["window_helper_ledgers"]["PoolHourData"]["expanded_field_invocation_count"],
                26,
            )
            for entity in ("PoolDayData", "PoolHourData"):
                helper = proof["window_helper_ledgers"][entity]
                for field in ("high", "low"):
                    control = helper["high_low_write_control"][field]
                    self.assertTrue(control["missing_row_create_setter_is_unconditional_within_missing_branch"])
                    self.assertTrue(control["separate_comparator_return_controls_later_setter"])
                    self.assertTrue(control["create_and_later_setter_sites_can_both_occur_on_missing_row_path"])
                    self.assertFalse(control["imported_big_decimal_comparator_semantics_complete"])
                plus = helper["tx_count_big_int_plus_write"]
                self.assertTrue(plus["call_result_written_by_final_tx_count_setter"])
                self.assertFalse(plus["imported_big_int_plus_numeric_semantics_complete"])
                tick = helper["nullable_tick_setter"]
                self.assertTrue(tick["nullable_non_null_and_null_or_unset_branches_bound"])
                catalog = proof["interval_field_catalog_nullability"][entity]
                self.assertEqual(catalog["catalog_field_count"], 20)
                self.assertEqual(catalog["non_null_field_count"], 19)
                self.assertEqual(catalog["nullable_fields"], ["tick"])
                self.assertFalse(catalog["all_twenty_fields_non_null_or_required"])

    def test_05_all_28_diffs_are_recursive_and_reproducible(self) -> None:
        diffs = self.contract["segment_diffs"]
        self.assertEqual(len(diffs), 28)
        by_id = {item["segment_id"]: item for item in self.contract["segments"]}
        for diff in diffs:
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
            self.assertFalse(diff["complete_entity_histories_compared"])
            self.assertFalse(diff["boundary_state_compared"])

    def test_06_all_broad_live_and_issue_gates_remain_false(self) -> None:
        truth = self.contract["truth_boundary"]
        self.assertEqual({key for key, value in truth.items() if value}, set(VERIFIER.TRUE_FLAGS))
        self.assertEqual({key for key, value in truth.items() if not value}, set(VERIFIER.FALSE_FLAGS))
        self.assertFalse(self.contract["scope"]["issue_acceptance_checkbox_completed"])
        self.assertFalse(self.contract["issue_checkbox_assessment"]["issue_37"]["completed"])
        self.assertFalse(self.contract["issue_checkbox_assessment"]["issue_38"]["completed"])

    def test_07_compile_valid_handler_setter_substitution_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-root"]
        handler = context["handler"]
        sqrt_index = next(
            index
            for index, line in enumerate(handler.lines)
            if (VERIFIER.call_name(line) or "").endswith("schema/Pool#set:sqrtPrice")
        )
        tick_target = next(
            VERIFIER.call_name(line)
            for line in handler.lines
            if (VERIFIER.call_name(line) or "").endswith("schema/Pool#set:tick")
        )
        self.assert_wat_rejected(
            context,
            [(handler.name, lambda lines, _context: self.replace(lines, sqrt_index, f"call ${tick_target}"))],
        )

    def test_08_compile_valid_day_helper_field_substitution_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-qmrv"]
        helper = self.function_by_suffix(context, "updatePoolDayData")
        date_index = next(
            index
            for index, line in enumerate(helper.lines)
            if (VERIFIER.call_name(line) or "").endswith("schema/PoolDayData#set:date")
        )
        pool_target = next(
            VERIFIER.call_name(line)
            for line in helper.lines
            if (VERIFIER.call_name(line) or "").endswith("schema/PoolDayData#set:pool")
        )
        self.assert_wat_rejected(
            context,
            [(helper.name, lambda lines, _context: self.replace(lines, date_index, f"call ${pool_target}"))],
        )

    def test_09_compile_valid_modern_hour_key_substitution_is_rejected(self) -> None:
        context = self.by_profile["modern-mainnet"]
        helper = self.function_by_suffix(context, "updatePoolHourData")
        key_index = next(
            index
            for index, line in enumerate(helper.lines)
            if VERIFIER.decoded_constant(line, context["memory"]) == "periodStartUnix"
        )
        replacement = next(
            VERIFIER.normalized(line)
            for line in helper.lines
            if VERIFIER.decoded_constant(line, context["memory"]) == "pool"
        )
        self.assert_wat_rejected(
            context,
            [(helper.name, lambda lines, _context: self.replace(lines, key_index, replacement))],
        )

    def test_10_compile_valid_indirect_target_body_mutation_is_rejected(self) -> None:
        context = self.by_profile["modern-base"]
        target_name = context["indirect_targets"][0]
        target = context["functions"][target_name]
        receiver_index = next(
            index
            for index, line in enumerate(target.lines)
            if VERIFIER.normalized(line) == "local.get $p0"
        )
        self.assert_wat_rejected(
            context,
            [(target.name, lambda lines, _context: self.replace(lines, receiver_index, "local.get $p1"))],
        )

    def test_11_self_rehashed_contract_omissions_and_promotions_fail_closed(self) -> None:
        mutations = []
        changed = copy.deepcopy(self.contract)
        changed["segments"][0]["semantic_surface"]["field_outcomes"].pop()
        changed["segments"][0]["semantic_surface_sha256"] = VERIFIER.canonical_sha256(
            changed["segments"][0]["semantic_surface"]
        )
        mutations.append(changed)
        changed = copy.deepcopy(self.contract)
        changed["mapping_proofs"][0]["complete_reachable_mutation_and_call_closure"]["schema_save_invocations"].pop()
        mutations.append(changed)
        changed = copy.deepcopy(self.contract)
        changed["truth_boundary"]["backfill_ready"] = True
        mutations.append(changed)
        changed = copy.deepcopy(self.contract)
        changed["scope"]["issue_acceptance_checkbox_completed"] = True
        mutations.append(changed)
        changed = copy.deepcopy(self.contract)
        changed["source_contracts"]["factory_static_v2"]["canonical_sha256"] = "0" * 64
        mutations.append(changed)
        for ordinal, mutation in enumerate(mutations):
            with self.subTest(ordinal=ordinal):
                with self.assertRaises(VERIFIER.VerificationError):
                    VERIFIER.verify_contract(
                        ROOT,
                        mutation,
                        sources=self.sources,
                        recompute_wat=False,
                    )

    def test_12_documentation_and_indexes_preserve_the_boundary(self) -> None:
        readme = (ROOT / "uniswap-v3/pool-initialize/v2/README.md").read_text()
        eligibility = (ROOT / "uniswap-v3/pool-initialize/v2/docs/eligibility.md").read_text()
        provenance = (ROOT / "uniswap-v3/pool-initialize/v2/docs/provenance.md").read_text()
        indexes = (ROOT / "README.md").read_text() + (ROOT / "uniswap-v3/README.md").read_text()
        combined = readme + eligibility + provenance
        for value in ("299", "2,392", "25", "26", "56", "3", "5", "28", "visibility", "19", "nullable", "BigInt#plus"):
            self.assertIn(value, combined)
        self.assertIn("pool-initialize/v2", indexes)
        self.assertIn("completes no checkbox", combined.lower())
        for gate in ("backfill_ready", "production_ready", "issue_37", "issue_38"):
            self.assertIn(gate, eligibility)
        for overclaim in (
            "event-updated saved Pool",
            "pre-event persisted Pool",
            "txCount is incremented",
            "strict extrema",
            "all 20 required fields",
        ):
            self.assertNotIn(overclaim, combined + indexes)

    def test_13_store_visibility_overclaim_fails_closed_after_rehash(self) -> None:
        changed = copy.deepcopy(self.contract)
        proof = changed["mapping_proofs"][0]
        proof["handler_save_and_window_store_get_order"][
            "pool_store_get_return_visibility_or_version_proven"
        ] = True
        proof["pool_store_get_return_visibility_or_version_proven"] = True
        self.assert_contract_rejected(changed)

    def test_14_comparator_numeric_overclaim_fails_closed_after_rehash(self) -> None:
        changed = copy.deepcopy(self.contract)
        outcomes = changed["segments"][0]["semantic_surface"]["field_outcomes"]
        high = next(
            item
            for item in outcomes
            if item["entity"] == "PoolDayData" and item["field"] == "high"
        )
        high["static_transition"] = "conditional_strict_maximum_write_else_preserve"
        high["value_or_preservation_source"] = "strict maximum of existing high and Pool.token0Price"
        self.assert_contract_rejected(changed)

    def test_15_big_int_increment_overclaim_fails_closed_after_rehash(self) -> None:
        changed = copy.deepcopy(self.contract)
        outcomes = changed["segments"][0]["semantic_surface"]["field_outcomes"]
        tx_count = next(
            item
            for item in outcomes
            if item["entity"] == "PoolHourData" and item["field"] == "txCount"
        )
        tx_count["static_transition"] = "numeric_increment_before_entity_save"
        tx_count["value_or_preservation_source"] = "txCount is incremented by one"
        self.assert_contract_rejected(changed)

    def test_16_all_required_tick_overclaim_fails_closed_after_rehash(self) -> None:
        changed = copy.deepcopy(self.contract)
        outcomes = changed["segments"][0]["semantic_surface"]["field_outcomes"]
        tick = next(
            item
            for item in outcomes
            if item["entity"] == "PoolDayData" and item["field"] == "tick"
        )
        tick["schema_type"] = "BigInt!"
        tick["static_transition"] = "required_field_write_before_entity_save"
        self.assert_contract_rejected(changed)


if __name__ == "__main__":
    unittest.main()
