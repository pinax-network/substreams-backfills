from __future__ import annotations

import copy
import hashlib
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
VERIFIER_PATH = ROOT / "scripts/verify-uniswap-v3-pool-swap-v2.py"
SPEC = importlib.util.spec_from_file_location(
    "uniswap_v3_pool_swap_v2",
    VERIFIER_PATH,
)
assert SPEC is not None and SPEC.loader is not None
VERIFIER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VERIFIER
SPEC.loader.exec_module(VERIFIER)

Mutation = tuple[str, Callable[[list[str], dict[str, Any]], None]]


class PoolSwapV2Test(unittest.TestCase):
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
        cls.core_by_cid = {
            item["mapping_cid"]: item
            for item in cls.sources["core_contract"]["mapping_proofs"]
        }
        cls.fee_by_cid = {
            item["mapping_cid"]: item
            for item in cls.sources["fee_contract"]["mapping_proofs"]
        }
        cls.field_catalog = cls.sources["field_catalog"]
        wasm2wat = next(iter(cls.contexts.values()))["wasm2wat"]
        cls.wasm2wat = VERIFIER.FEE.INITIALIZE.resolve_tool(wasm2wat, "wasm2wat")
        cls.wat2wasm = VERIFIER.FEE.INITIALIZE.resolve_tool(
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
        with tempfile.TemporaryDirectory(prefix="pool-swap-v2-wat-") as temporary:
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
                self.core_by_cid[context["mapping_cid"]],
                self.fee_by_cid[context["mapping_cid"]],
                self.field_catalog,
            )

    def assert_local_wat_rejected(
        self,
        context: dict[str, Any],
        mutations: list[Mutation],
        expected_error: str,
    ) -> None:
        """Rebind inherited whole-WAT pins so rejection must reach this verifier."""
        changed = self.roundtrip(context, mutations)
        changed_core = copy.deepcopy(self.core_by_cid[context["mapping_cid"]])
        changed_fee = copy.deepcopy(self.fee_by_cid[context["mapping_cid"]])
        wat_sha256 = hashlib.sha256(changed["wat_text"].encode()).hexdigest()
        handler_sha256 = VERIFIER.FEE.function_sha256(changed["handler"])
        for parent in (changed_core, changed_fee):
            parent["retained_wasm"]["wat_sha256"] = wat_sha256
            parent["handler_binding"]["body_sha256"] = handler_sha256
        with self.assertRaisesRegex(self.expected_errors, expected_error):
            VERIFIER.prove_complete_context(
                changed,
                changed_core,
                changed_fee,
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
            VERIFIER.verify_generated_contract(contract, self.contract)

    def test_01_committed_contract_is_deterministic(self) -> None:
        self.assertEqual(
            self.contract,
            VERIFIER.expected_contract_from_sources(self.sources),
        )
        self.assertEqual(
            (self.contract["format_version"], self.contract["contract_version"]),
            (1, "uniswap-v3-pool-swap/v2"),
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
            "stored_field_with_exact_setter_and_lexically_later_origin_overlap_store_outcome_count": 1152,
            "reachable_store_without_exact_setter_outcome_count": 360,
            "derived_without_direct_store_transition_outcome_count": 104,
            "stored_field_outside_pool_swap_store_closure_outcome_count": 776,
            "pool_swap_core_selected_overlay_count": 24,
            "pool_swap_fee_growth_selected_overlay_count": 16,
            "swap_required_field_overlay_count": 112,
            "swap_nullable_field_overlay_count": 8,
            "required_absent_overlay_count": 0,
            "reachable_function_count": 1404,
            "direct_callsite_count": 9968,
            "direct_memory_write_site_count": 2368,
            "physical_typed_map_set_site_count": 754,
            "physical_site_to_invocation_edge_count": 1608,
            "lexical_schema_field_invocation_count": 1576,
            "lexical_setter_exact_receiver_flow_binding_count": 1576,
            "lexical_setter_invocation_with_store_receiver_origin_overlap_count": 1576,
            "lexical_setter_invocation_with_all_equal_store_receiver_origin_sets_count": 1089,
            "lexical_setter_invocation_with_overlap_only_store_receiver_origin_set_count": 487,
            "setter_to_store_receiver_origin_overlap_edge_count": 1720,
            "setter_to_store_receiver_exact_equal_origin_set_edge_count": 1233,
            "setter_to_store_receiver_overlap_without_origin_set_equality_edge_count": 487,
            "physical_receiver_flow_edge_count": 1608,
            "returned_helper_store_origin_overlap_invocation_count": 60,
            "returned_helper_store_authority_record_count": 15,
            "expanded_handler_to_setter_path_count": 2072,
            "lexical_graph_store_invocation_count": 163,
            "lexical_store_exact_target_receiver_binding_count": 163,
            "physical_store_set_site_count": 104,
            "expanded_store_path_count": 211,
            "reachable_call_indirect_count": 2,
            "unique_stored_setter_field_count_per_segment": 144,
            "lexical_schema_field_invocation_count_per_mapping": 197,
            "expanded_handler_to_setter_path_count_per_mapping": 259,
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
        self.assertEqual(len(denominator_keys), 41)
        for key in denominator_keys:
            with self.subTest(key=key):
                changed = copy.deepcopy(self.contract)
                changed["scope"][key] -= 1
                self.assert_contract_rejected(changed)

    def test_04_categories_are_mutually_exclusive_and_complete(self) -> None:
        boolean_keys = (
            "stored_field_with_exact_setter_and_lexically_later_same_group_store_receiver_origin_overlap",
            "stored_field_on_reachable_store_without_exact_schema_setter",
            "derived_field_without_direct_graph_store_transition",
            "stored_field_outside_pool_swap_store_closure",
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
                    summary["stored_field_with_exact_setter_and_lexically_later_origin_overlap_store_count"],
                    summary["reachable_store_without_exact_setter_count"],
                    summary["derived_without_direct_store_transition_count"],
                    summary["stored_field_outside_pool_swap_store_closure_count"],
                    summary["pool_swap_core_selected_overlay_count"],
                    summary["pool_swap_fee_growth_selected_overlay_count"],
                    summary["swap_required_field_count"],
                    summary["swap_nullable_field_count"],
                    summary["required_absent_overlay_count"],
                ),
                (144, 45, 13, 97, 3, 2, 14, 1, 0),
            )
            for item in outcomes:
                self.assertEqual(sum(item[key] for key in boolean_keys), 1)
                category_totals[item["lexical_static_category"]] += 1
        self.assertEqual(
            category_totals,
            Counter(
                {
                    VERIFIER.CATEGORY_SETTER: 1152,
                    VERIFIER.CATEGORY_NO_SETTER: 360,
                    VERIFIER.CATEGORY_DERIVED: 104,
                    VERIFIER.CATEGORY_OUTSIDE: 776,
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
                if item["stored_field_on_reachable_store_without_exact_schema_setter"]
            ]
            self.assertEqual(len(no_setter), 45)
            for item in no_setter:
                self.assertTrue(item["no_reachable_exact_schema_api_setter_flow_bound"])
                self.assertFalse(item["loaded_field_preservation_proven"])
                self.assertFalse(item["field_value_unchanged_proven"])
                self.assertFalse(item["field_value_semantics_complete"])
                self.assertFalse(item["imported_numeric_semantics_complete"])
                self.assertFalse(item["imported_comparator_semantics_complete"])
                self.assertFalse(item["graph_store_visibility_or_version_proven"])
                self.assertFalse(item["graph_store_persistence_proven"])
                self.assertFalse(item["last_writer_semantics_proven"])
            derived = {
                (item["entity"], item["field"])
                for item in outcomes
                if item["derived_field_without_direct_graph_store_transition"]
                and item["derived_child_association"] is not None
            }
            self.assertEqual(derived, expected_associations)
            self.assertTrue(
                all(
                    not item["graph_store_persistence_proven"]
                    for item in outcomes
                )
            )

    def test_06_swap_nullability_and_zero_required_absence_are_exact(self) -> None:
        for segment in self.contract["segments"]:
            outcomes = segment["semantic_surface"]["field_outcomes"]
            absent = [item for item in outcomes if item["required_absent_overlay"]]
            self.assertEqual(absent, [])
            required = [item["field"] for item in outcomes if item["swap_required_field_overlay"]]
            nullable = [item["field"] for item in outcomes if item["swap_nullable_field_overlay"]]
            self.assertEqual(set(required), set(VERIFIER.SWAP_REQUIRED_FIELDS))
            self.assertEqual(set(nullable), set(VERIFIER.SWAP_NULLABLE_FIELDS))
            self.assertEqual((len(required), len(nullable)), (14, 1))
            self.assertTrue(
                all(
                    item[
                        "stored_field_with_exact_setter_and_lexically_later_same_group_store_receiver_origin_overlap"
                    ]
                    for item in outcomes
                    if item["entity"] == "Swap"
                )
            )

    def test_07_lexical_physical_expanded_and_store_ledgers_are_separate(self) -> None:
        totals = Counter()
        expected_inventory = {
            "legacy-base-root": (197, 1183, 185, 60, 13, 0),
            "legacy-mainnet-qmrv": (197, 1176, 185, 60, 13, 0),
            "legacy-mainnet-root": (197, 1172, 185, 60, 13, 0),
            "legacy-mainnet-stable": (197, 1177, 185, 60, 13, 0),
            "legacy-mainnet-stable-fee-tier-1": (197, 1180, 185, 60, 13, 0),
            "legacy-mainnet-stable-fee-tier-100": (197, 1180, 185, 60, 13, 0),
            "modern-base": (111, 1459, 630, 197, 13, 1),
            "modern-mainnet": (111, 1441, 628, 197, 13, 1),
        }
        for proof in self.contract["mapping_proofs"]:
            closure = proof["schema_api_invocation_closure"]
            inventory = proof["reachable_inventory"]
            store = proof["store_closure"]
            profile = proof["profile_id"]
            self.assertEqual(closure["lexical_field_invocation_count"], 197)
            self.assertEqual(
                closure["lexical_setter_exact_receiver_flow_binding_count"],
                197,
            )
            self.assertEqual(
                closure[
                    "lexical_setter_invocation_with_store_receiver_origin_overlap_count"
                ],
                197,
            )
            self.assertEqual(
                closure[
                    "lexical_setter_invocation_with_all_equal_store_receiver_origin_sets_count"
                ]
                + closure[
                    "lexical_setter_invocation_with_overlap_only_store_receiver_origin_set_count"
                ],
                197,
            )
            self.assertEqual(closure["physical_receiver_flow_edge_count"], 201)
            expected_returned_helper = (
                12
                if profile.startswith("legacy-mainnet-")
                else 0
            )
            self.assertEqual(
                closure["returned_helper_store_origin_overlap_invocation_count"],
                expected_returned_helper,
            )
            self.assertEqual(closure["physical_site_to_invocation_edge_count"], 201)
            self.assertEqual(closure["nullable_branch_alternative_count"], 4)
            self.assertEqual(
                Counter(
                    (item["entity"], item["field"])
                    for item in closure["physical_site_to_invocation_edges"]
                    if item["nullable_branch_alternative"]
                ),
                Counter(VERIFIER.NULLABLE_SETTER_BRANCH_IDENTITIES),
            )
            self.assertEqual(closure["expanded_handler_to_setter_path_count"], 259)
            self.assertEqual(closure["unique_stored_setter_field_count"], 144)
            self.assertEqual(closure["unclassified_physical_typed_map_set_site_count"], 0)
            self.assertIn("distinct denominators", closure["physical_vs_semantic_ledger_warning"])
            authorities = closure["lexical_field_invocations"]
            authority_ids = {item["receiver_authority_id"] for item in authorities}
            self.assertEqual(len(authority_ids), 197)
            self.assertEqual(
                sum(item["physical_receiver_flow_count"] for item in authorities),
                201,
            )
            self.assertTrue(
                all(
                    item["setter_receiver_bound_by_exact_retained_operand_flow"]
                    and item["same_group_store_receiver_value_origin_overlap_bound"]
                    and not item["field_value_semantics_complete"]
                    for item in authorities
                )
            )
            self.assertTrue(
                all(
                    item["receiver_authority_id"] in authority_ids
                    for item in closure["physical_site_to_invocation_edges"]
                    + closure["expanded_handler_to_setter_paths"]
                )
            )
            actual = (
                inventory["reachable_function_count"],
                inventory["direct_callsite_count"],
                inventory["direct_memory_write_site_count"],
                inventory["physical_typed_map_set_site_count"],
                inventory["physical_store_set_site_count"],
                inventory["reachable_call_indirect_count"],
            )
            self.assertEqual(actual, expected_inventory[profile])
            expected_store = (
                (23, 29)
                if profile.startswith("modern-")
                else (22, 28)
                if profile == "legacy-base-root"
                else (19, 25)
            )
            self.assertEqual(
                (
                    store["lexical_graph_store_invocation_count"],
                    store["expanded_store_path_count"],
                ),
                expected_store,
            )
            self.assertEqual(
                store["lexical_store_exact_target_receiver_binding_count"],
                expected_store[0],
            )
            store_authority_ids = {
                item["store_authority_id"]
                for item in store["lexical_graph_store_invocations"]
            }
            self.assertEqual(len(store_authority_ids), expected_store[0])
            expected_helper_records = 3 if expected_returned_helper else 0
            self.assertEqual(
                store["returned_helper_store_authority_record_count"],
                expected_helper_records,
            )
            helper_authority_ids = {
                item["store_authority_id"]
                for item in store["returned_helper_store_authorities"]
            }
            self.assertEqual(len(helper_authority_ids), expected_helper_records)
            store_record_by_id = {
                item["store_authority_id"]: item
                for item in store["lexical_graph_store_invocations"]
                + store["returned_helper_store_authorities"]
            }
            for record in store["lexical_graph_store_invocations"]:
                authority = record["receiver_store_authority"]
                if authority["binding_kind"] == "direct_store_target_and_receiver_operands":
                    self.assertTrue(
                        authority[
                            "direct_store_exact_target_and_receiver_value_operands_machine_bound"
                        ]
                    )
                    self.assertNotIn(
                        "same_caller_receiver_to_save_parameter_to_store_value_machine_bound",
                        authority,
                    )
                    self.assertIsNone(authority["save_function"])
                    self.assertIsNone(authority["save_receiver_parameter"])
                else:
                    self.assertEqual(
                        authority["binding_kind"],
                        "caller_receiver_operand_through_save_parameter_to_store_value",
                    )
                    self.assertTrue(
                        authority[
                            "same_caller_receiver_to_save_parameter_to_store_value_machine_bound"
                        ]
                    )
                    self.assertNotIn(
                        "direct_store_exact_target_and_receiver_value_operands_machine_bound",
                        authority,
                    )
                    self.assertIsNotNone(authority["save_function"])
                    self.assertIsNotNone(authority["save_receiver_parameter"])
            authority_by_id = {
                authority_id: item["receiver_store_authority"]
                for authority_id, item in store_record_by_id.items()
            }
            self.assertTrue(
                all(
                    set(item["same_group_origin_overlap_store_authority_ids"]).issubset(
                        authority_by_id
                    )
                    and item[
                        "same_group_origin_overlap_store_authority_inventory_sha256"
                    ]
                    == VERIFIER.canonical_sha256(
                        [
                            authority_by_id[authority_id]
                            for authority_id in item[
                                "same_group_origin_overlap_store_authority_ids"
                            ]
                        ]
                    )
                    for item in authorities
                )
            )
            exact_equal_origin_set_relations = 0
            overlap_without_origin_set_equality_relations = 0
            exact_equal_origin_set_edges = 0
            overlap_without_origin_set_equality_edges = 0
            for item in authorities:
                setter_atoms = VERIFIER._value_identity_atoms(
                    item["receiver_value_identity"]
                )
                store_atom_sets = [
                    VERIFIER._value_identity_atoms(
                        store_record_by_id[authority_id]["receiver_value_identity"]
                    )
                    for authority_id in item[
                        "same_group_origin_overlap_store_authority_ids"
                    ]
                ]
                self.assertTrue(store_atom_sets)
                self.assertTrue(
                    all(setter_atoms & store_atoms for store_atoms in store_atom_sets)
                )
                if all(setter_atoms == store_atoms for store_atoms in store_atom_sets):
                    exact_equal_origin_set_relations += 1
                else:
                    overlap_without_origin_set_equality_relations += 1
                exact_equal_origin_set_edges += sum(
                    setter_atoms == store_atoms for store_atoms in store_atom_sets
                )
                overlap_without_origin_set_equality_edges += sum(
                    setter_atoms != store_atoms for store_atoms in store_atom_sets
                )
            self.assertEqual(
                exact_equal_origin_set_relations,
                closure[
                    "lexical_setter_invocation_with_all_equal_store_receiver_origin_sets_count"
                ],
            )
            self.assertEqual(
                overlap_without_origin_set_equality_relations,
                closure[
                    "lexical_setter_invocation_with_overlap_only_store_receiver_origin_set_count"
                ],
            )
            self.assertEqual(
                exact_equal_origin_set_edges,
                closure["setter_to_store_receiver_exact_equal_origin_set_edge_count"],
            )
            self.assertEqual(
                overlap_without_origin_set_equality_edges,
                closure[
                    "setter_to_store_receiver_overlap_without_origin_set_equality_edge_count"
                ],
            )
            self.assertEqual(
                exact_equal_origin_set_edges
                + overlap_without_origin_set_equality_edges,
                closure["setter_to_store_receiver_origin_overlap_edge_count"],
            )
            self.assertEqual(store["physical_store_set_site_count"], 13)
            self.assertEqual(store["reachable_store_targets"], list(VERIFIER.STORE_TARGETS))
            self.assertFalse(store["graph_store_visibility_or_version_proven"])
            self.assertFalse(store["graph_store_persistence_proven"])
            self.assertFalse(store["last_writer_semantics_proven"])
            totals.update(
                functions=actual[0],
                calls=actual[1],
                writes=actual[2],
                physical_setters=actual[3],
                physical_stores=actual[4],
                indirect=actual[5],
                lexical_fields=closure["lexical_field_invocation_count"],
                setter_receiver_flows=closure[
                    "lexical_setter_exact_receiver_flow_binding_count"
                ],
                setter_invocations_with_store_receiver_origin_overlap=closure[
                    "lexical_setter_invocation_with_store_receiver_origin_overlap_count"
                ],
                setter_invocations_with_all_equal_store_receiver_origin_sets=closure[
                    "lexical_setter_invocation_with_all_equal_store_receiver_origin_sets_count"
                ],
                setter_invocations_with_overlap_only_store_receiver_origin_set=closure[
                    "lexical_setter_invocation_with_overlap_only_store_receiver_origin_set_count"
                ],
                setter_to_store_receiver_origin_overlap_edges=closure[
                    "setter_to_store_receiver_origin_overlap_edge_count"
                ],
                setter_to_store_receiver_exact_equal_origin_set_edges=closure[
                    "setter_to_store_receiver_exact_equal_origin_set_edge_count"
                ],
                setter_to_store_receiver_overlap_without_origin_set_equality_edges=closure[
                    "setter_to_store_receiver_overlap_without_origin_set_equality_edge_count"
                ],
                receiver_flow_edges=closure["physical_receiver_flow_edge_count"],
                returned_helper_origin_overlap_invocations=closure[
                    "returned_helper_store_origin_overlap_invocation_count"
                ],
                returned_helper_authority_records=store[
                    "returned_helper_store_authority_record_count"
                ],
                edges=closure["physical_site_to_invocation_edge_count"],
                expanded_fields=closure["expanded_handler_to_setter_path_count"],
                lexical_stores=store["lexical_graph_store_invocation_count"],
                store_exact_target_receiver_flows=store[
                    "lexical_store_exact_target_receiver_binding_count"
                ],
                expanded_stores=store["expanded_store_path_count"],
            )
        self.assertEqual(
            totals,
            Counter(
                functions=1404,
                calls=9968,
                writes=2368,
                physical_setters=754,
                physical_stores=104,
                indirect=2,
                lexical_fields=1576,
                setter_receiver_flows=1576,
                setter_invocations_with_store_receiver_origin_overlap=1576,
                setter_invocations_with_all_equal_store_receiver_origin_sets=1089,
                setter_invocations_with_overlap_only_store_receiver_origin_set=487,
                setter_to_store_receiver_origin_overlap_edges=1720,
                setter_to_store_receiver_exact_equal_origin_set_edges=1233,
                setter_to_store_receiver_overlap_without_origin_set_equality_edges=487,
                receiver_flow_edges=1608,
                returned_helper_origin_overlap_invocations=60,
                returned_helper_authority_records=15,
                edges=1608,
                expanded_fields=2072,
                lexical_stores=163,
                store_exact_target_receiver_flows=163,
                expanded_stores=211,
            ),
        )
    def test_08_helper_multiplicity_and_unique_field_denominators_are_exact(self) -> None:
        expected_multiplicity = {
            group: len(paths) for group, paths in VERIFIER.PATH_IDS.items()
        }
        expected_entity_counts = {
            "Bundle": 1,
            "Factory": 8,
            "Pool": 17,
            "PoolDayData": 20,
            "PoolHourData": 20,
            "Swap": 15,
            "Tick": 2,
            "TickDayData": 12,
            "Token": 8,
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
                144,
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

    def test_09_profile_order_duplicate_save_and_guard_boundaries_are_exact(self) -> None:
        modern_duplicates = 0
        legacy_mainnet_post_store = 0
        for proof in self.contract["mapping_proofs"]:
            ordering = proof["ordering_and_guards"]
            outer = ordering["outer_two_token_guard"]
            profile = proof["profile_id"]
            self.assertEqual(
                ordering[
                    "unique_field_identity_count_with_at_least_one_lexically_later_same_group_origin_overlap_store"
                ],
                144,
            )
            expected_without_later = (
                0 if profile == "legacy-base-root" or profile.startswith("modern-") else 12
            )
            self.assertEqual(
                ordering[
                    "lexical_setter_invocation_count_without_lexically_later_same_group_origin_overlap_store"
                ],
                expected_without_later,
            )
            self.assertNotIn("expanded_setter_store_order", ordering)
            self.assertIn("does not prove", ordering["relation_scope"])
            self.assertFalse(ordering["common_execution_path_proven"])
            self.assertFalse(ordering["receiver_must_alias_proven"])
            self.assertFalse(ordering["branch_correlation_proven"])
            self.assertEqual(
                ordering["selected_pool_core_flow"]["fields"],
                list(VERIFIER.CORE_SELECTED_FIELDS),
            )
            self.assertEqual(
                ordering["selected_pool_fee_growth_flow"]["fields"],
                list(VERIFIER.FEE_SELECTED_FIELDS),
            )
            self.assertFalse(ordering["imported_numeric_semantics_complete"])
            self.assertFalse(ordering["imported_comparator_semantics_complete"])
            self.assertFalse(ordering["contract_call_value_semantics_complete"])
            self.assertFalse(ordering["graph_store_visibility_or_version_proven"])
            self.assertFalse(ordering["graph_store_persistence_proven"])
            self.assertFalse(ordering["last_writer_semantics_proven"])
            if profile.startswith("modern-"):
                self.assertTrue(
                    outer["all_handler_schema_invocations_stores_and_helper_calls_inside_guard"]
                )
                self.assertTrue(
                    outer["missing_either_token_skips_entire_classified_handler_effect_body"]
                )
                duplicate = ordering["modern_duplicate_pool_hour_data_save"]
                self.assertIsNotNone(duplicate)
                self.assertTrue(
                    duplicate["duplicate_save_lexical_order_and_local_name_bound"]
                )
                self.assertFalse(
                    duplicate["duplicate_save_common_execution_path_proven"]
                )
                self.assertFalse(duplicate["duplicate_save_receiver_must_alias_proven"])
                self.assertEqual(
                    duplicate["intervening_pool_hour_data_setter_invocation_count"], 0
                )
                self.assertFalse(duplicate["graph_store_visibility_or_version_proven"])
                self.assertFalse(duplicate["graph_store_persistence_proven"])
                self.assertFalse(duplicate["last_writer_semantics_proven"])
                modern_duplicates += 1
            else:
                self.assertFalse(
                    outer["all_handler_schema_invocations_stores_and_helper_calls_inside_guard"]
                )
                self.assertFalse(
                    outer["missing_either_token_skips_entire_classified_handler_effect_body"]
                )
                self.assertIsNone(ordering["modern_duplicate_pool_hour_data_save"])
                if expected_without_later:
                    residual = ordering[
                        "legacy_mainnet_setter_without_lexically_later_handler_origin_overlap_store"
                    ]
                    self.assertEqual(residual["setter_invocation_count"], 12)
                    self.assertFalse(residual["common_execution_path_proven"])
                    self.assertFalse(residual["receiver_must_alias_proven"])
                    self.assertFalse(residual["loaded_field_preservation_proven"])
                    self.assertFalse(residual["field_value_unchanged_proven"])
                    self.assertFalse(residual["last_writer_semantics_proven"])
                    legacy_mainnet_post_store += 1
        self.assertEqual((modern_duplicates, legacy_mainnet_post_store), (2, 5))
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
            self.assertFalse(segment["semantic_surface"]["pool_swap_semantics_complete"])
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
        invocation["setter_receiver_bound_by_exact_retained_operand_flow"] = False
        mutations.append(changed)
        changed = copy.deepcopy(self.contract)
        changed["mapping_proofs"][0]["schema_api_invocation_closure"][
            "physical_site_to_invocation_edges"
        ][0]["receiver_authority_id"] = "unbound-authority"
        mutations.append(changed)
        changed = copy.deepcopy(self.contract)
        changed["mapping_proofs"][0]["schema_api_invocation_closure"][
            "lexical_field_invocations"
        ][0]["same_group_origin_overlap_store_authority_ids"] = [
            "wrong-store-authority"
        ]
        mutations.append(changed)
        changed = copy.deepcopy(self.contract)
        changed["mapping_proofs"][0]["schema_api_invocation_closure"][
            "lexical_field_invocations"
        ][0]["field"] = "notAField"
        mutations.append(changed)
        changed = copy.deepcopy(self.contract)
        changed["mapping_proofs"][0]["store_closure"]["reachable_store_targets"][0] = "Swap"
        mutations.append(changed)
        changed = copy.deepcopy(self.contract)
        changed["mapping_proofs"][0]["store_closure"]["lexical_graph_store_invocations"].pop()
        mutations.append(changed)
        changed = copy.deepcopy(self.contract)
        modern = next(
            item for item in changed["mapping_proofs"]
            if item["control_generation"] == "modern"
        )
        modern["store_closure"]["modern_duplicate_pool_hour_data_save"][
            "shared_receiver_operand_local_name"
        ] = "$different"
        mutations.append(changed)
        changed = copy.deepcopy(self.contract)
        modern = next(
            item for item in changed["mapping_proofs"]
            if item["control_generation"] == "modern"
        )
        modern["store_closure"]["modern_duplicate_pool_hour_data_save"][
            "second_relative_wat_line"
        ] -= 10
        mutations.append(changed)
        changed = copy.deepcopy(self.contract)
        changed["mapping_proofs"][0]["store_closure"]["profile_store_shape"] = "wrong"
        mutations.append(changed)
        changed = copy.deepcopy(self.contract)
        changed["mapping_proofs"][0]["ordering_and_guards"][
            "lexical_setter_store_origin_overlap_order"
        ][0]["has_lexically_later_same_group_origin_overlap_store"] = False
        mutations.append(changed)
        for ordinal, changed in enumerate(mutations):
            with self.subTest(ordinal=ordinal):
                self.assert_contract_rejected(changed)

    def test_13_guard_category_no_preservation_truth_and_diff_mutations_fail_closed(self) -> None:
        mutations: list[dict[str, Any]] = []
        changed = copy.deepcopy(self.contract)
        modern = next(
            item
            for item in changed["mapping_proofs"]
            if item["control_generation"] == "modern"
        )
        modern["ordering_and_guards"]["outer_two_token_guard"][
            "all_handler_schema_invocations_stores_and_helper_calls_inside_guard"
        ] = False
        mutations.append(changed)
        changed = copy.deepcopy(self.contract)
        outcome = changed["segments"][0]["semantic_surface"]["field_outcomes"][0]
        outcome["lexical_static_category"] = VERIFIER.CATEGORY_SETTER
        outcome["stored_field_outside_pool_swap_store_closure"] = False
        outcome[
            "stored_field_with_exact_setter_and_lexically_later_same_group_store_receiver_origin_overlap"
        ] = True
        mutations.append(changed)
        changed = copy.deepcopy(self.contract)
        no_setter = next(
            item
            for item in changed["segments"][0]["semantic_surface"]["field_outcomes"]
            if item["stored_field_on_reachable_store_without_exact_schema_setter"]
        )
        no_setter["loaded_field_preservation_proven"] = True
        mutations.append(changed)
        changed = copy.deepcopy(self.contract)
        no_setter = next(
            item
            for item in changed["segments"][0]["semantic_surface"]["field_outcomes"]
            if item["stored_field_on_reachable_store_without_exact_schema_setter"]
        )
        no_setter["graph_store_visibility_or_version_proven"] = True
        mutations.append(changed)
        changed = copy.deepcopy(self.contract)
        no_setter = next(
            item
            for item in changed["segments"][0]["semantic_surface"]["field_outcomes"]
            if item["stored_field_on_reachable_store_without_exact_schema_setter"]
        )
        no_setter["last_writer_semantics_proven"] = True
        mutations.append(changed)
        changed = copy.deepcopy(self.contract)
        log_index = next(
            item
            for item in changed["segments"][0]["semantic_surface"]["field_outcomes"]
            if (item["entity"], item["field"]) == ("Swap", "logIndex")
        )
        log_index["swap_nullable_field_overlay"] = False
        mutations.append(changed)
        changed = copy.deepcopy(self.contract)
        changed["truth_boundary"]["backfill_ready"] = True
        mutations.append(changed)
        changed = copy.deepcopy(self.contract)
        changed["segment_diffs"].pop()
        mutations.append(changed)
        for ordinal, changed in enumerate(mutations):
            with self.subTest(ordinal=ordinal):
                self.assert_contract_rejected(changed)

    def test_14_direct_schema_catalog_identity_shape_and_nullability_fail_closed(self) -> None:
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
        changed_records = copy.deepcopy(records)
        log_index = next(
            item
            for item in changed_records
            if (item["entity"], item["field"]) == ("Swap", "logIndex")
        )
        log_index["type"] = "BigInt!"
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

    def test_15_core_fee_store_guard_and_call_order_evidence_fail_closed(self) -> None:
        context = self.by_profile["modern-base"]
        cid = context["mapping_cid"]
        core = self.core_by_cid[cid]
        fee = self.fee_by_cid[cid]
        mutations: list[tuple[dict[str, Any], dict[str, Any]]] = []

        changed_core = copy.deepcopy(core)
        changed_core["save_and_effect_closure"]["direct_pool_save_count"] = 1
        mutations.append((changed_core, fee))

        changed_core = copy.deepcopy(core)
        changed_core["save_and_effect_closure"]["transitive_store_evidence"][
            "reachable_store_set_targets"
        ][0] = "Swap"
        mutations.append((changed_core, fee))

        changed_core = copy.deepcopy(core)
        changed_core["control_and_entity_boundary"][
            "selected_update_guard_start_index"
        ] += 500
        mutations.append((changed_core, fee))

        changed_fee = copy.deepcopy(fee)
        changed_fee["save_and_effect_closure"][
            "both_setters_precede_second_pool_save_machine_proven"
        ] = False
        mutations.append((core, changed_fee))

        changed_fee = copy.deepcopy(fee)
        changed_fee["selected_field_flows"]["call_order"].reverse()
        mutations.append((core, changed_fee))

        for ordinal, (changed_core, changed_fee) in enumerate(mutations):
            with self.subTest(ordinal=ordinal):
                with self.assertRaises(self.expected_errors):
                    VERIFIER.prove_complete_context(
                        context,
                        changed_core,
                        changed_fee,
                        self.field_catalog,
                    )
    def test_16_compile_valid_receiver_key_store_and_origin_overlap_mutations_fail_closed(self) -> None:
        context = self.by_profile["legacy-mainnet-root"]
        handler = context["handler"]
        abort_targets = {
            target
            for function in context["functions"].values()
            for line in function.lines
            if (target := VERIFIER.FEE.call_name(line)) is not None
            and target.endswith("/abort")
        }
        self.assertEqual(len(abort_targets), 1)
        abort_target = next(iter(abort_targets))
        selected_index = next(
            index
            for index, line in enumerate(handler.lines)
            if (VERIFIER.FEE.call_name(line) or "").endswith(
                "schema/Pool#set:totalValueLockedToken0"
            )
        )
        selected_target = VERIFIER.FEE.call_name(handler.lines[selected_index])
        assert selected_target is not None
        selected_receiver = VERIFIER._call_operand_expressions(
            handler,
            selected_index,
            VERIFIER._wat_signatures(context)["functions"][selected_target][0],
            VERIFIER._wat_signatures(context)["functions"],
        )[0]
        self.assertEqual(selected_receiver["lines"], ["local.get $l1"])
        self.assert_local_wat_rejected(
            context,
            [
                (
                    handler.name,
                    lambda lines, _context: self.replace(
                        lines,
                        selected_receiver["start_relative_wat_line"],
                        "i32.const 0",
                    ),
                )
            ],
            "local caller receiver operand proof failed for totalValueLockedToken0",
        )

        selected_setter = self.function_by_suffix(
            context,
            "schema/Pool#set:totalValueLockedToken0",
        )

        def reassign_setter_receiver(
            lines: list[str], _context: dict[str, Any]
        ) -> None:
            indent = lines[1][: len(lines[1]) - len(lines[1].lstrip())]
            lines[1:1] = [f"{indent}i32.const 0", f"{indent}local.set $p0"]

        self.assert_local_wat_rejected(
            context,
            [(selected_setter.name, reassign_setter_receiver)],
            "setter receiver parameter for totalValueLockedToken0 entry-value identity proof failed",
        )

        def reassign_setter_receiver_before_call_then_trap(
            lines: list[str], _context: dict[str, Any]
        ) -> None:
            indent = lines[1][: len(lines[1]) - len(lines[1].lstrip())]
            nested = f"{indent}  "
            retained_body = [
                line
                for line in lines[1:]
                if not (
                    (VERIFIER.FEE.call_name(line) or "").endswith(
                        "Value.fromBigDecimal"
                    )
                )
            ]
            if len(retained_body) != len(lines[1:]) - 1:
                raise AssertionError("expected one replaceable setter value-converter call")
            original_body = [line.lstrip() for line in retained_body]
            if not original_body[-1].rstrip().endswith(")"):
                raise AssertionError("expected setter function-closing parenthesis")
            original_body[-1] = original_body[-1].rstrip()[:-1]
            lines[1:] = [
                f"{indent}i32.const 1",
                f"{indent}if $setter_receiver_call_then_trap",
                f"{nested}i32.const 0",
                f"{nested}local.set $p0",
                *[f"{nested}{line}" for line in original_body],
                f"{nested}i32.const 0",
                f"{nested}i32.const 0",
                f"{nested}i32.const 0",
                f"{nested}i32.const 0",
                f"{nested}call ${abort_target}",
                f"{nested}unreachable",
                f"{indent}end)",
            ]

        self.assert_local_wat_rejected(
            context,
            [
                (
                    selected_setter.name,
                    reassign_setter_receiver_before_call_then_trap,
                )
            ],
            "setter receiver parameter for totalValueLockedToken0 entry-value identity proof failed",
        )

        def overwrite_setter_receiver_on_second_loop_iteration(
            lines: list[str], _context: dict[str, Any]
        ) -> None:
            indent = lines[1][: len(lines[1]) - len(lines[1].lstrip())]
            nested = f"{indent}  "
            lines[1:1] = [
                f"{indent}(local $receiver_alias i32)",
                f"{indent}(local $loop_counter i32)",
                f"{indent}local.get $p0",
                f"{indent}local.set $receiver_alias",
                f"{indent}i32.const 0",
                f"{indent}local.set $loop_counter",
                f"{indent}loop $receiver_second_iteration",
                f"{nested}local.get $p0",
                f"{nested}local.set $receiver_alias",
                f"{nested}i32.const 0",
                f"{nested}local.set $p0",
                f"{nested}local.get $loop_counter",
                f"{nested}i32.const 1",
                f"{nested}i32.add",
                f"{nested}local.tee $loop_counter",
                f"{nested}i32.const 2",
                f"{nested}i32.lt_u",
                f"{nested}br_if $receiver_second_iteration",
                f"{indent}end",
                f"{indent}local.get $receiver_alias",
                f"{indent}local.set $p0",
            ]

        self.assert_local_wat_rejected(
            context,
            [
                (
                    selected_setter.name,
                    overwrite_setter_receiver_on_second_loop_iteration,
                )
            ],
            "setter receiver parameter for totalValueLockedToken0 entry-value identity proof failed",
        )

        def branch_table_skips_setter_receiver_restore(
            lines: list[str], _context: dict[str, Any]
        ) -> None:
            indent = lines[1][: len(lines[1]) - len(lines[1].lstrip())]
            nested = f"{indent}  "
            lines[1:1] = [
                f"{indent}(local $receiver_alias i32)",
                f"{indent}local.get $p0",
                f"{indent}local.set $receiver_alias",
                f"{indent}i32.const 0",
                f"{indent}local.set $p0",
                f"{indent}block $receiver_restore_exit",
                f"{nested}i32.const 0",
                f"{nested}br_table $receiver_restore_exit",
                f"{nested}local.get $receiver_alias",
                f"{nested}local.set $p0",
                f"{indent}end",
            ]

        self.assert_local_wat_rejected(
            context,
            [(selected_setter.name, branch_table_skips_setter_receiver_restore)],
            "setter receiver parameter for totalValueLockedToken0 entry-value identity proof failed",
        )

        def structured_setter_receiver(
            lines: list[str], _context: dict[str, Any]
        ) -> None:
            start = selected_receiver["start_relative_wat_line"]
            indent = lines[start][: len(lines[start]) - len(lines[start].lstrip())]
            lines[start : start + 1] = [
                f"{indent}block $receiver_mutation (result i32)",
                f"{indent}  local.get $l1",
                f"{indent}  local.tee $l1",
                f"{indent}  i32.const 4",
                f"{indent}  i32.add",
                f"{indent}end",
            ]

        self.assert_local_wat_rejected(
            context,
            [(handler.name, structured_setter_receiver)],
            "local caller receiver operand proof failed for totalValueLockedToken0",
        )

        setter_map_set = next(
            index
            for index, line in enumerate(selected_setter.lines)
            if VERIFIER.FEE.call_name(line) == VERIFIER.FEE.LEGACY_MAP_SET
        )
        setter_key_operand = VERIFIER._call_operand_expressions(
            selected_setter,
            setter_map_set,
            3,
            VERIFIER._wat_signatures(context)["functions"],
        )[1]
        self.assertEqual(len(setter_key_operand["lines"]), 1)

        def structured_setter_key(
            lines: list[str], _context: dict[str, Any]
        ) -> None:
            start = setter_key_operand["start_relative_wat_line"]
            indent = lines[start][: len(lines[start]) - len(lines[start].lstrip())]
            literal = lines[start].strip().rstrip(")")
            lines[start : start + 1] = [
                f"{indent}block $key_mutation (result i32)",
                f"{indent}  {literal}",
                f"{indent}  drop",
                f"{indent}  i32.const 0",
                f"{indent}end",
            ]

        self.assert_local_wat_rejected(
            context,
            [(selected_setter.name, structured_setter_key)],
            "local field-key operand proof failed for totalValueLockedToken0",
        )

        helper = self.function_by_suffix(context, "updatePoolDayData")
        date_index = next(
            index
            for index, line in enumerate(helper.lines)
            if (VERIFIER.FEE.call_name(line) or "").endswith(
                "schema/PoolDayData#set:date"
            )
        )
        pool_target = next(
            VERIFIER.FEE.call_name(line)
            for line in helper.lines
            if (VERIFIER.FEE.call_name(line) or "").endswith(
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

        returned_helper = self.function_by_suffix(context, "updatePoolHourData")
        helper_return_local = VERIFIER.FEE.local_name(
            returned_helper.lines[-1], "get"
        )
        self.assertIsNotNone(helper_return_local)

        def add_alternative_helper_return_origin(
            lines: list[str], _context: dict[str, Any]
        ) -> None:
            insertion = len(lines) - 1
            indent = lines[insertion][
                : len(lines[insertion]) - len(lines[insertion].lstrip())
            ]
            lines[insertion:insertion] = [
                f"{indent}i32.const 0",
                f"{indent}if",
                f"{indent}  i32.const 0",
                f"{indent}  local.set {helper_return_local}",
                f"{indent}end",
            ]

        self.assert_local_wat_rejected(
            context,
            [(returned_helper.name, add_alternative_helper_return_origin)],
            "returned-helper store/return receiver origin-set equality proof failed",
        )

        def return_equal_origin_through_different_local(
            lines: list[str], _context: dict[str, Any]
        ) -> None:
            declaration_end = 1
            while (
                declaration_end < len(lines)
                and lines[declaration_end].lstrip().startswith("(local ")
            ):
                declaration_end += 1
            indent = lines[declaration_end][
                : len(lines[declaration_end])
                - len(lines[declaration_end].lstrip())
            ]
            lines[declaration_end:declaration_end] = [
                f"{indent}(local $receiver_alias i32)"
            ]
            store_index = len(lines) - 2
            if VERIFIER.FEE.call_name(lines[store_index]) is None:
                raise AssertionError("expected penultimate helper store call")
            lines[store_index - 1 : store_index - 1] = [
                f"{indent}local.get {helper_return_local}",
                f"{indent}local.set $receiver_alias",
            ]
            lines[-1] = lines[-1].replace(
                str(helper_return_local), "$receiver_alias"
            )

        self.assert_local_wat_rejected(
            context,
            [(returned_helper.name, return_equal_origin_through_different_local)],
            "returned-helper store/terminal return receiver local equality proof failed",
        )

        def break_helper_store_terminal_return_adjacency(
            lines: list[str], _context: dict[str, Any]
        ) -> None:
            insertion = len(lines) - 1
            indent = lines[insertion][
                : len(lines[insertion]) - len(lines[insertion].lstrip())
            ]
            lines[insertion:insertion] = [
                f"{indent}i32.const 0",
                f"{indent}drop",
            ]

        self.assert_local_wat_rejected(
            context,
            [(returned_helper.name, break_helper_store_terminal_return_adjacency)],
            "returned-helper internal store/terminal return adjacency proof failed",
        )

        save = self.function_by_suffix(context, "schema/Pool#save")
        pool_key = next(
            index
            for index, line in enumerate(save.lines)
            if VERIFIER.FEE.decoded_constant(line, context["memory"]) == "Pool"
        )
        self.assert_local_wat_rejected(
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
            "direct store target operand proof failed",
        )

        def structured_store_target(
            lines: list[str], _context: dict[str, Any]
        ) -> None:
            indent = lines[pool_key][
                : len(lines[pool_key]) - len(lines[pool_key].lstrip())
            ]
            literal = lines[pool_key].strip().rstrip(")")
            lines[pool_key : pool_key + 1] = [
                f"{indent}block $store_target_mutation (result i32)",
                f"{indent}  {literal}",
                f"{indent}  drop",
                f"{indent}  i32.const 0",
                f"{indent}end",
            ]

        self.assert_local_wat_rejected(
            context,
            [(save.name, structured_store_target)],
            "direct store target operand proof failed",
        )

        store_set_index = next(
            index
            for index, line in enumerate(save.lines)
            if VERIFIER.FEE.call_name(line) == VERIFIER.WRITER.STORE_SET_CALL
        )
        store_operands = VERIFIER._call_operand_expressions(
            save,
            store_set_index,
            3,
            VERIFIER._wat_signatures(context)["functions"],
        )
        store_operand_start = store_operands[0]["start_relative_wat_line"]

        def reassign_save_receiver(
            lines: list[str], _context: dict[str, Any]
        ) -> None:
            insertion = 2 if lines[1].lstrip().startswith("(local ") else 1
            indent = lines[insertion][
                : len(lines[insertion]) - len(lines[insertion].lstrip())
            ]
            lines[insertion:insertion] = [
                f"{indent}i32.const 0",
                f"{indent}local.set $p0",
            ]

        self.assert_local_wat_rejected(
            context,
            [(save.name, reassign_save_receiver)],
            "save receiver parameter for Pool entry-value identity proof failed",
        )

        def reassign_save_receiver_before_store_then_trap(
            lines: list[str], _context: dict[str, Any]
        ) -> None:
            earlier_abort = next(
                index
                for index, line in enumerate(lines[:store_operand_start])
                if VERIFIER.FEE.call_name(line) == abort_target
            )
            abort_indent = lines[earlier_abort][
                : len(lines[earlier_abort]) - len(lines[earlier_abort].lstrip())
            ]
            lines[earlier_abort : earlier_abort + 1] = [
                f"{abort_indent}drop",
                f"{abort_indent}drop",
                f"{abort_indent}drop",
                f"{abort_indent}drop",
            ]
            current_store_set = next(
                index
                for index, line in enumerate(lines)
                if VERIFIER.FEE.call_name(line) == VERIFIER.WRITER.STORE_SET_CALL
            )
            current_store_start = current_store_set - 4
            indent = lines[current_store_start][
                : len(lines[current_store_start])
                - len(lines[current_store_start].lstrip())
            ]
            nested = f"{indent}  "
            original_store_tail = [
                line.lstrip() for line in lines[current_store_start:]
            ]
            if not original_store_tail[-1].rstrip().endswith(")"):
                raise AssertionError("expected save function-closing parenthesis")
            original_store_tail[-1] = original_store_tail[-1].rstrip()[:-1]
            lines[current_store_start:] = [
                f"{indent}i32.const 1",
                f"{indent}if $save_receiver_store_then_trap",
                f"{nested}i32.const 0",
                f"{nested}local.set $p0",
                *[f"{nested}{line}" for line in original_store_tail],
                f"{nested}i32.const 0",
                f"{nested}i32.const 0",
                f"{nested}i32.const 0",
                f"{nested}i32.const 0",
                f"{nested}call ${abort_target}",
                f"{nested}unreachable",
                f"{indent}end)",
            ]

        self.assert_local_wat_rejected(
            context,
            [(save.name, reassign_save_receiver_before_store_then_trap)],
            "save receiver parameter for Pool entry-value identity proof failed",
        )

        def overwrite_save_receiver_on_second_loop_iteration(
            lines: list[str], _context: dict[str, Any]
        ) -> None:
            declaration_end = 1
            while (
                declaration_end < len(lines)
                and lines[declaration_end].lstrip().startswith("(local ")
            ):
                declaration_end += 1
            declaration_indent = lines[1][
                : len(lines[1]) - len(lines[1].lstrip())
            ]
            lines[declaration_end:declaration_end] = [
                f"{declaration_indent}(local $receiver_alias i32)",
                f"{declaration_indent}(local $loop_counter i32)",
            ]
            current_store_set = next(
                index
                for index, line in enumerate(lines)
                if VERIFIER.FEE.call_name(line) == VERIFIER.WRITER.STORE_SET_CALL
            )
            insertion = current_store_set - 4
            indent = lines[insertion][
                : len(lines[insertion]) - len(lines[insertion].lstrip())
            ]
            nested = f"{indent}  "
            lines[insertion:insertion] = [
                f"{indent}local.get $p0",
                f"{indent}local.set $receiver_alias",
                f"{indent}i32.const 0",
                f"{indent}local.set $loop_counter",
                f"{indent}loop $save_receiver_second_iteration",
                f"{nested}local.get $p0",
                f"{nested}local.set $receiver_alias",
                f"{nested}i32.const 0",
                f"{nested}local.set $p0",
                f"{nested}local.get $loop_counter",
                f"{nested}i32.const 1",
                f"{nested}i32.add",
                f"{nested}local.tee $loop_counter",
                f"{nested}i32.const 2",
                f"{nested}i32.lt_u",
                f"{nested}br_if $save_receiver_second_iteration",
                f"{indent}end",
                f"{indent}local.get $receiver_alias",
                f"{indent}local.set $p0",
            ]

        self.assert_local_wat_rejected(
            context,
            [(save.name, overwrite_save_receiver_on_second_loop_iteration)],
            "save receiver parameter for Pool entry-value identity proof failed",
        )

        self.assert_local_wat_rejected(
            context,
            [
                (
                    save.name,
                    lambda lines, _context: self.replace(
                        lines,
                        store_set_index - 1,
                        "local.get $l1",
                    ),
                )
            ],
            "local save receiver-flow proof failed for Pool",
        )

        constructor_target = next(
            operation["call_target"]
            for operation in VERIFIER._logical_operations(context, handler)
            if "#constructor" in operation["call_target"]
        )
        constructor = context["functions"][
            VERIFIER._resolve_function_name(context, constructor_target)
        ]

        def break_constructor_map_set_terminal_adjacency(
            lines: list[str], _context: dict[str, Any]
        ) -> None:
            insertion = len(lines) - 1
            indent = lines[insertion][
                : len(lines[insertion]) - len(lines[insertion].lstrip())
            ]
            lines[insertion:insertion] = [
                f"{indent}i32.const 0",
                f"{indent}drop",
            ]

        self.assert_local_wat_rejected(
            context,
            [(constructor.name, break_constructor_map_set_terminal_adjacency)],
            "constructor map-set/terminal return adjacency proof failed for id",
        )

        entity_unset = self.function_by_suffix(context, "Entity#unset")

        def replace_unset_receiver_after_prefix(
            lines: list[str], _context: dict[str, Any]
        ) -> None:
            indent = lines[1][: len(lines[1]) - len(lines[1].lstrip())]
            lines[3:3] = [
                f"{indent}drop",
                f"{indent}drop",
                f"{indent}i32.const 0",
                f"{indent}local.get $p1",
            ]

        self.assert_local_wat_rejected(
            context,
            [(entity_unset.name, replace_unset_receiver_after_prefix)],
            "Entity#unset physical receiver/key operand proof failed",
        )

        def transform_unset_key(
            lines: list[str], _context: dict[str, Any]
        ) -> None:
            indent = lines[2][: len(lines[2]) - len(lines[2].lstrip())]
            lines[3:3] = [f"{indent}i32.const 4", f"{indent}i32.add"]

        self.assert_local_wat_rejected(
            context,
            [(entity_unset.name, transform_unset_key)],
            "Entity#unset physical receiver/key operand proof failed",
        )

        def reassign_unset_key_within_operand(
            lines: list[str], _context: dict[str, Any]
        ) -> None:
            indent = lines[2][: len(lines[2]) - len(lines[2].lstrip())]
            lines[3:3] = [
                f"{indent}drop",
                f"{indent}i32.const 0",
                f"{indent}local.set $p1",
                f"{indent}local.get $p1",
            ]

        self.assert_local_wat_rejected(
            context,
            [(entity_unset.name, reassign_unset_key_within_operand)],
            "Entity#unset physical receiver/key operand proof failed",
        )

        modern = self.by_profile["modern-base"]
        modern_handler = modern["handler"]
        factory_tx_count_get = next(
            index
            for index, line in enumerate(modern_handler.lines)
            if (VERIFIER.FEE.call_name(line) or "").endswith(
                "schema/Factory#get:txCount"
            )
        )
        factory_tx_count_set = next(
            index
            for index, line in enumerate(modern_handler.lines)
            if index > factory_tx_count_get
            and VERIFIER.FEE.call_name(line) == VERIFIER.FEE.MODERN_MAP_SET
        )
        receiver_operand = VERIFIER._call_operand_expressions(
            modern_handler,
            factory_tx_count_set,
            3,
            VERIFIER._wat_signatures(modern)["functions"],
        )[0]
        self.assertEqual(receiver_operand["lines"], ["local.get $l4"])
        self.assert_local_wat_rejected(
            modern,
            [
                (
                    modern_handler.name,
                    lambda lines, _context: self.replace(
                        lines,
                        receiver_operand["start_relative_wat_line"],
                        "local.get $l5",
                    ),
                )
            ],
            "setter/store receiver-origin overlap entity proof failed for Factory.txCount",
        )

    def test_17_nullable_physical_site_mutation_fails_closed(self) -> None:
        context = self.by_profile["legacy-mainnet-qmrv"]
        # The deployed legacy module deduplicates this nullable setter under
        # Pool#set:tick even when PoolDayData calls it. The caller supplies the
        # entity classification input; the symbol name does not.
        nullable = self.function_by_suffix(context, "schema/Pool#set:tick")
        map_set = VERIFIER.FEE.LEGACY_MAP_SET
        site = next(
            index
            for index, line in enumerate(nullable.lines)
            if VERIFIER.FEE.call_name(line) == map_set
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
        with tempfile.TemporaryDirectory(prefix="pool-swap-v2-json-") as temporary:
            path = Path(temporary) / "duplicate.json"
            path.write_text('{"format_version":1,"format_version":1}\n')
            with self.assertRaises(self.expected_errors):
                VERIFIER.load_json(path)

    def test_19_detached_regeneration_is_byte_identical(self) -> None:
        committed = (ROOT / VERIFIER.CONTRACT_PATH).read_bytes()
        with tempfile.TemporaryDirectory(prefix="pool-swap-v2-detached-") as temporary:
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
                    str(detached / "scripts/verify-uniswap-v3-pool-swap-v2.py"),
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
        component = (ROOT / "uniswap-v3/pool-swap/v2/README.md").read_text()
        eligibility = (
            ROOT / "uniswap-v3/pool-swap/v2/docs/eligibility.md"
        ).read_text()
        provenance = (
            ROOT / "uniswap-v3/pool-swap/v2/docs/provenance.md"
        ).read_text()
        indexes = (ROOT / "README.md").read_text() + (
            ROOT / "uniswap-v3/README.md"
        ).read_text()
        workflow = (ROOT / ".github/workflows/ci.yaml").read_text()
        combined = component + eligibility + provenance
        for value in (
            "299",
            "2,392",
            "144",
            "1,152",
            "45",
            "360",
            "104",
            "776",
            "197",
            "201",
            "259",
            "19",
            "25",
            "22",
            "28",
            "23",
            "29",
            "13",
            "1,404",
            "9,968",
            "2,368",
            "754",
            "1,608",
            "1,576",
            "1,720",
            "1,233",
            "1,089",
            "487",
            "60",
            "2,072",
            "163",
            "211",
            "14",
        ):
            self.assertIn(value, combined)
        self.assertIn("pool-swap/v2", indexes)
        self.assertIn("pool-swap-v2.py", workflow)
        self.assertIn("Physical and semantic ledgers must not be conflated", combined)
        self.assertIn("finite worklist", combined)
        self.assertIn("loop backedges to a fixed point", combined)
        self.assertIn("br`/`br_if`/`br_table", combined)
        self.assertIn("may-alias", combined)
        self.assertIn("branch correlation", combined)
        self.assertIn("15 materialized", combined)
        self.assertIn("no issue checkbox", combined.lower())
        self.assertIn("never called preserved, unchanged", component)
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
            "setter_store_common_execution_path_proven",
            "setter_store_receiver_must_alias_proven",
            "setter_store_branch_correlation_proven",
            "duplicate_save_common_execution_path_proven",
            "duplicate_save_receiver_must_alias_proven",
            "all_returned_helper_invocations_and_paths_return_stored_receiver_proven",
            "all_successful_constructor_returns_and_control_paths_return_internal_receiver_proven",
        ):
            self.assertIn(gate, eligibility)


if __name__ == "__main__":
    unittest.main()
