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
VERIFIER_PATH = ROOT / "scripts/verify-uniswap-v3-factory-pool-bigint-init.py"
SPEC = importlib.util.spec_from_file_location(
    "uniswap_v3_factory_pool_bigint_init_v1", VERIFIER_PATH
)
assert SPEC is not None and SPEC.loader is not None
VERIFIER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VERIFIER
SPEC.loader.exec_module(VERIFIER)

Mutation = tuple[str, Callable[[list[str], dict[str, Any]], None]]
SemanticCheck = Callable[[dict[str, Any]], Any]


class FactoryPoolBigintInitializationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sources = VERIFIER.load_sources(ROOT, recompute_wat=True)
        cls.contract = VERIFIER.verify_contract(
            ROOT, sources=cls.sources, recompute_wat=False
        )
        cls.contexts = cls.sources["legacy_contexts"]
        cls.parent_by_cid = {
            proof["mapping_cid"]: proof
            for proof in cls.sources["parent_sources"]["legacy_proofs"]
        }
        cls.by_profile = {
            context["profile"]["profile_id"]: context
            for context in cls.contexts
        }
        cls.wasm2wat = cls.contexts[0]["wasm2wat"]
        cls.wat2wasm = cls.wasm2wat.with_name("wat2wasm")
        cls.expected_errors = tuple(
            dict.fromkeys(
                (
                    VERIFIER.VerificationError,
                    VERIFIER.PARENT.VerificationError,
                    VERIFIER.PARENT.MODERN.VerificationError,
                    VERIFIER.PARENT.FEE_GROWTH.VerificationError,
                    VERIFIER.PARENT.EFFECTS.VerificationError,
                    VERIFIER.V2.VerificationError,
                    VERIFIER.WRITER.VerificationError,
                )
            )
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

    def roundtrip(
        self,
        context: dict[str, Any],
        mutations: list[Mutation],
    ) -> dict[str, Any]:
        replacements = []
        for function_name, mutate in mutations:
            function = context["functions"][function_name]
            lines = list(function.lines)
            mutate(lines, context)
            replacements.append((function.start_line - 1, len(function.lines), lines))
        wat_lines = context["wat_text"].splitlines()
        for start, length, replacement in sorted(replacements, reverse=True):
            wat_lines[start : start + length] = replacement
        wat_text = "\n".join(wat_lines) + "\n"
        with tempfile.TemporaryDirectory(
            prefix="factory-pool-bigint-init-wat-"
        ) as temporary:
            wat = Path(temporary) / "fixture.wat"
            wasm = Path(temporary) / "fixture.wasm"
            wat.write_text(wat_text)
            compiled = subprocess.run(
                [str(self.wat2wasm), "--debug-names", str(wat), "-o", str(wasm)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            regenerated = VERIFIER.WRITER.run_wasm2wat(self.wasm2wat, wasm).decode()
        memory, functions, indirect, exports = VERIFIER.WRITER.parse_wat(regenerated)
        handler = VERIFIER.WRITER.resolve_handler(
            functions, exports, VERIFIER.HANDLER_EXPORT
        )
        return {
            **context,
            "memory": memory,
            "functions": functions,
            "indirect": tuple(indirect),
            "exports": exports,
            "handler": handler,
            "wat_text": regenerated,
            "module_text": regenerated,
        }

    def assert_wat_rejected(
        self,
        context: dict[str, Any],
        mutations: list[Mutation],
        check: SemanticCheck,
        expected_message: str | None = None,
    ) -> None:
        changed = self.roundtrip(context, mutations)
        with self.assertRaises(self.expected_errors) as caught:
            check(changed)
        if expected_message is not None:
            self.assertIn(expected_message, str(caught.exception))

    def handler_mutation(
        self, context: dict[str, Any], index: int, instruction: str
    ) -> Mutation:
        return (
            context["handler"].name,
            lambda lines, _context: self.replace(lines, index, instruction),
        )

    def assert_contract_rejected(self, value: dict[str, Any]) -> None:
        with self.assertRaises(self.expected_errors):
            VERIFIER.verify_contract(
                ROOT, value, sources=self.sources, recompute_wat=False
            )

    def test_01_committed_contract_is_deterministic(self) -> None:
        self.assertEqual(
            self.contract, VERIFIER.expected_contract_from_sources(self.sources)
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
        self.assertIn(
            "4 unique legacy mappings, 30 legacy and 40 total initialization records, 28 diffs; "
            "6 fully selected direct sites of 44 reachable static sites and "
            "7/78 expanded invocations selected",
            result.stdout,
        )

    def test_02_scope_and_site_accounting_are_exact(self) -> None:
        scope = self.contract["scope"]
        self.assertEqual(
            (
                scope["unique_legacy_mapping_count"],
                scope["legacy_mapping_field_flow_count"],
                scope["legacy_segment_count"],
                scope["legacy_segment_field_call_flow_record_count"],
                scope["modern_parent_segment_count"],
                scope["modern_parent_field_record_count"],
                scope["total_initialization_record_count"],
                scope["pairwise_scoped_diff_count"],
            ),
            (4, 20, 6, 30, 2, 10, 40, 28),
        )
        self.assertEqual(
            (
                scope["retained_static_typed_map_set_site_count"],
                scope["cumulative_fully_selected_direct_static_site_count"],
                scope["cumulative_unclassified_static_site_count"],
                scope["retained_expanded_map_write_invocation_count"],
                scope["cumulative_selected_expanded_invocation_count"],
                scope["cumulative_residual_expanded_invocation_count"],
            ),
            (44, 6, 38, 78, 7, 71),
        )
        self.assertIs(scope["shared_tx_count_static_site_remains_residual"], True)
        self.assertEqual(
            scope["selected_fields"],
            [f"Pool.{field}" for field in VERIFIER.SELECTED_FIELDS],
        )

    def test_03_ledgers_and_truth_boundary_remain_bounded(self) -> None:
        scope = self.contract["scope"]
        self.assertEqual(
            (
                scope["cumulative_selected_field_count"],
                scope["cumulative_residual_field_count"],
                scope["factory_paths_closed_before_and_after"],
                scope["factory_paths_residual_before_and_after"],
                scope["legacy_factory_field_call_flow_capsules_after"],
                scope["legacy_factory_fields_without_call_flow_capsules_after"],
            ),
            (36, 230, 14, 4, 7, 53),
        )
        truth = self.contract["truth_boundary"]
        self.assertEqual({key for key, value in truth.items() if value}, set(VERIFIER.TRUE_FLAGS))
        self.assertEqual({key for key, value in truth.items() if not value}, set(VERIFIER.FALSE_FLAGS))
        for key in (
            "legacy_selected_field_mutation_proven",
            "selected_persistence_proven",
            "shared_tx_count_static_site_fully_selected",
            "all_four_shared_tx_count_invocations_selected",
            "factory_set_tx_count_symbol_is_pool_entity_authority",
            "fresh_value_allocation_proven",
            "typed_map_get_entry_semantics_rederived",
            "entity_backing_array_construction_semantics_rederived",
            "issue_37_acceptance_criterion_complete",
            "issue_38_acceptance_criterion_complete",
            "backfill_ready",
            "production_ready",
            "readiness_complete",
        ):
            with self.subTest(key=key):
                self.assertIs(truth[key], False)

    def test_04_all_four_unmodified_legacy_contexts_prove(self) -> None:
        for context in self.contexts:
            with self.subTest(profile=context["profile"]["profile_id"]):
                proof = VERIFIER.prove_legacy_context(
                    context, self.parent_by_cid[context["cid"]]
                )
                self.assertTrue(
                    proof[
                        "selected_bigint_initialization_call_operand_flow_machine_proven"
                    ]
                )
                self.assertEqual(len(proof["selected_fields"]), 5)
                self.assertFalse(proof["legacy_selected_field_mutation_proven"])
                self.assertFalse(
                    proof["shared_tx_count_helper_and_invocations"][
                        "shared_static_typed_map_set_site_fully_selected"
                    ]
                )

    def test_05_normalized_direct_helper_and_save_anchors_match(self) -> None:
        for context in self.contexts:
            with self.subTest(profile=context["profile"]["profile_id"]):
                direct = VERIFIER.prove_direct_bigint_groups(context)
                shared = VERIFIER.prove_shared_tx_count_helper_and_invocations(context)
                through = VERIFIER.prove_same_receiver_through_save(context)
                self.assertEqual(
                    direct["direct_group_decoded_string_normalized_sha256"],
                    VERIFIER.DIRECT_CONCAT_DECODED_NORMALIZED_SHA256,
                )
                self.assertEqual(
                    shared["helper"]["decoded_string_normalized_sha256"],
                    VERIFIER.TX_HELPER_DECODED_NORMALIZED_SHA256,
                )
                self.assertEqual(
                    through["selected_region_decoded_string_normalized_sha256"],
                    VERIFIER.THROUGH_SAVE_DECODED_NORMALIZED_SHA256,
                )

    def test_06_each_direct_key_crossing_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-root"]
        pointers = VERIFIER.EXPECTED["legacy-mainnet-root"]["direct_key_pointers"]
        for ordinal, (_, base) in enumerate(VERIFIER.DIRECT_FIELD_BASES):
            replacement = pointers[(ordinal + 1) % len(pointers)]
            with self.subTest(base=base):
                self.assert_wat_rejected(
                    context,
                    [self.handler_mutation(context, base + 1, f"i32.const {replacement}")],
                    VERIFIER.prove_direct_bigint_groups,
                    expected_message="direct receiver/key/g2/Value/set flow drift",
                )

    def test_07_direct_receiver_substitution_is_rejected(self) -> None:
        context = self.by_profile["legacy-base-root"]
        self.assert_wat_rejected(
            context,
            [self.handler_mutation(context, 331, "local.get $l2")],
            VERIFIER.prove_direct_bigint_groups,
            expected_message="direct receiver/key/g2/Value/set flow drift",
        )

    def test_08_direct_g2_substitution_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-qmrv"]
        self.assert_wat_rejected(
            context,
            [self.handler_mutation(context, 338, "global.get $g3")],
            VERIFIER.prove_direct_bigint_groups,
            expected_message="direct receiver/key/g2/Value/set flow drift",
        )

    def test_09_direct_wrapper_substitution_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-stable"]
        self.assert_wat_rejected(
            context,
            [
                self.handler_mutation(
                    context,
                    364,
                    "call $~lib/@graphprotocol/graph-ts/index/Value.fromBigDecimal",
                )
            ],
            VERIFIER.prove_direct_bigint_groups,
            expected_message="direct receiver/key/g2/Value/set flow drift",
        )

    def test_10_direct_group_swap_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-root"]

        def swap(lines: list[str], _context: dict[str, Any]) -> None:
            first = lines[323:328]
            second = lines[331:336]
            lines[323:328] = second
            lines[331:336] = first

        self.assert_wat_rejected(
            context,
            [(context["handler"].name, swap)],
            VERIFIER.prove_direct_bigint_groups,
            expected_message="direct receiver/key/g2/Value/set flow drift",
        )

    def test_10b_direct_typed_map_target_is_rejected(self) -> None:
        context = self.by_profile["legacy-base-root"]
        self.assert_wat_rejected(
            context,
            [
                self.handler_mutation(
                    context, 327, "call $~lib/internal/memory/memcpy"
                )
            ],
            VERIFIER.prove_direct_bigint_groups,
            expected_message="direct receiver/key/g2/Value/set flow drift",
        )

    def test_11_selected_tx_count_receiver_is_rejected(self) -> None:
        context = self.by_profile["legacy-base-root"]
        self.assert_wat_rejected(
            context,
            [self.handler_mutation(context, 328, "local.get $l2")],
            VERIFIER.prove_shared_tx_count_helper_and_invocations,
            expected_message="shared txCount invocation 330 operands drift",
        )

    def test_12_selected_tx_count_global_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-qmrv"]
        self.assert_wat_rejected(
            context,
            [self.handler_mutation(context, 329, "global.get $g3")],
            VERIFIER.prove_shared_tx_count_helper_and_invocations,
            expected_message="shared txCount invocation 330 operands drift",
        )

    def test_13_selected_tx_count_target_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-stable"]
        self.assert_wat_rejected(
            context,
            [
                self.handler_mutation(
                    context, 330, "call $src/types/schema/Factory#set:poolCount"
                )
            ],
            VERIFIER.prove_shared_tx_count_helper_and_invocations,
            expected_message="shared txCount invocation inventory drift",
        )

    def test_14_shared_helper_key_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-root"]
        helper = self.function_by_suffix(context, "src/types/schema/Factory#set:txCount")
        replacement = VERIFIER.EXPECTED["legacy-mainnet-root"]["direct_key_pointers"][0]
        self.assert_wat_rejected(
            context,
            [(helper.name, lambda lines, _context: self.replace(lines, 2, f"i32.const {replacement}"))],
            VERIFIER.prove_shared_tx_count_helper_and_invocations,
            expected_message="shared txCount helper receiver/key/value/set operand drift",
        )

    def test_15_shared_helper_wrapper_is_rejected(self) -> None:
        context = self.by_profile["legacy-base-root"]
        helper = self.function_by_suffix(context, "src/types/schema/Factory#set:txCount")
        self.assert_wat_rejected(
            context,
            [
                (
                    helper.name,
                    lambda lines, _context: self.replace(
                        lines,
                        4,
                        "call $~lib/@graphprotocol/graph-ts/index/Value.fromBigDecimal",
                    ),
                )
            ],
            VERIFIER.prove_shared_tx_count_helper_and_invocations,
            expected_message="shared txCount helper receiver/key/value/set operand drift",
        )

    def test_16_shared_helper_receiver_operand_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-qmrv"]
        helper = self.function_by_suffix(context, "src/types/schema/Factory#set:txCount")
        self.assert_wat_rejected(
            context,
            [(helper.name, lambda lines, _context: self.replace(lines, 1, "local.get $p1"))],
            VERIFIER.prove_shared_tx_count_helper_and_invocations,
            expected_message="shared txCount helper receiver/key/value/set operand drift",
        )

    def test_16b_shared_helper_typed_map_target_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-root"]
        helper = self.function_by_suffix(context, "src/types/schema/Factory#set:txCount")
        self.assert_wat_rejected(
            context,
            [
                (
                    helper.name,
                    lambda lines, _context: self.replace(
                        lines, 5, "call $~lib/internal/memory/memcpy"
                    ),
                )
            ],
            VERIFIER.prove_shared_tx_count_helper_and_invocations,
            expected_message="shared txCount helper receiver/key/value/set operand drift",
        )

    def test_17_non_pool_shared_invocation_mutation_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-stable"]
        self.assert_wat_rejected(
            context,
            [
                self.handler_mutation(
                    context, 60, "call $src/types/schema/Factory#set:poolCount"
                )
            ],
            VERIFIER.prove_shared_tx_count_helper_and_invocations,
            expected_message="shared txCount invocation inventory drift",
        )

    def test_18_inserted_return_before_save_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-root"]
        self.assert_wat_rejected(
            context,
            [
                (
                    context["handler"].name,
                    lambda lines, _context: self.insert(lines, 366, ["return"]),
                )
            ],
            VERIFIER.prove_same_receiver_through_save,
            expected_message="bigint-through-save control bypass drift",
        )

    def test_19_inserted_structured_control_before_save_is_rejected(self) -> None:
        context = self.by_profile["legacy-base-root"]
        self.assert_wat_rejected(
            context,
            [
                (
                    context["handler"].name,
                    lambda lines, _context: self.insert(
                        lines, 366, ["i32.const 0", "if", "end"]
                    ),
                )
            ],
            VERIFIER.prove_same_receiver_through_save,
            expected_message="bigint-through-save control bypass drift",
        )

    def test_20_inserted_receiver_reassignment_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-qmrv"]
        self.assert_wat_rejected(
            context,
            [
                (
                    context["handler"].name,
                    lambda lines, _context: self.insert(
                        lines, 366, ["i32.const 0", "local.set $l1"]
                    ),
                )
            ],
            VERIFIER.prove_same_receiver_through_save,
            expected_message="Pool receiver reassignment before save drift",
        )

    def test_21_pool_save_receiver_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-stable"]
        self.assert_wat_rejected(
            context,
            [self.handler_mutation(context, 419, "local.get $l2")],
            VERIFIER.prove_same_receiver_through_save,
            expected_message="Pool save receiver drift",
        )

    def test_22_pool_save_target_is_rejected(self) -> None:
        context = self.by_profile["legacy-base-root"]
        self.assert_wat_rejected(
            context,
            [self.handler_mutation(context, 420, "call $src/types/schema/Token#save")],
            VERIFIER.prove_same_receiver_through_save,
            expected_message="Pool save call drift",
        )

    def test_23_later_selected_key_alias_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-root"]
        pointer = VERIFIER.EXPECTED["legacy-mainnet-root"]["direct_key_pointers"][0]
        self.assert_wat_rejected(
            context,
            [self.handler_mutation(context, 367, f"i32.const {pointer}")],
            VERIFIER.prove_same_receiver_through_save,
            expected_message="bigint-through-save raw authority drift",
        )

    def test_24_residual_site_and_invocation_accounting_proves(self) -> None:
        for context in self.contexts:
            with self.subTest(profile=context["profile"]["profile_id"]):
                result = VERIFIER.prove_residual_accounting(
                    context, self.parent_by_cid[context["cid"]]
                )
                self.assertEqual(
                    (
                        result["fully_selected_direct_static_site_count"],
                        result["unclassified_static_typed_map_set_site_count"],
                        result["cumulative_selected_expanded_invocation_count"],
                        result["residual_expanded_invocation_count"],
                    ),
                    (6, 38, 7, 71),
                )
                self.assertTrue(result["shared_tx_count_static_site_remains_residual"])

    def test_25_reachable_unselected_helper_mutation_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-qmrv"]
        helper = self.function_by_suffix(context, "~lib/string/String.__eq")

        def mutate(lines: list[str], _context: dict[str, Any]) -> None:
            index = next(
                i
                for i, line in enumerate(lines)
                if VERIFIER.normalized(line) == "i32.const 0"
            )
            self.replace(lines, index, "i32.const 1")

        changed = self.roundtrip(context, [(helper.name, mutate)])
        upstream = self.sources["parent_sources"]["upstream_factory_effects"][
            context["cid"]
        ]
        with self.assertRaises(self.expected_errors):
            VERIFIER.PARENT.prove_reachable_residual_inventory(changed, upstream)

    def test_26_projection_and_pairwise_diff_counts_are_exact(self) -> None:
        self.assertEqual(len(self.contract["segments"]), 8)
        self.assertEqual(
            sum(
                len(segment["semantic_surface"]["fields"])
                for segment in self.contract["segments"]
            ),
            40,
        )
        self.assertEqual(len(self.contract["segment_diffs"]), 28)

    def test_27_missing_segment_field_or_diff_is_rejected(self) -> None:
        mutations = []
        changed = copy.deepcopy(self.contract)
        changed["segments"].pop()
        mutations.append(changed)
        changed = copy.deepcopy(self.contract)
        changed["segments"][0]["semantic_surface"]["fields"].pop()
        mutations.append(changed)
        changed = copy.deepcopy(self.contract)
        changed["segment_diffs"].pop()
        mutations.append(changed)
        for ordinal, value in enumerate(mutations):
            with self.subTest(ordinal=ordinal):
                self.assert_contract_rejected(value)

    def test_28_static_and_expanded_count_mutations_are_rejected(self) -> None:
        for key, value in (
            ("cumulative_fully_selected_direct_static_site_count", 7),
            ("cumulative_unclassified_static_site_count", 37),
            ("cumulative_selected_expanded_invocation_count", 8),
            ("cumulative_residual_expanded_invocation_count", 70),
        ):
            changed = copy.deepcopy(self.contract)
            changed["scope"][key] = value
            with self.subTest(key=key):
                self.assert_contract_rejected(changed)

    def test_29_shared_static_site_promotion_is_rejected(self) -> None:
        changed = copy.deepcopy(self.contract)
        changed["truth_boundary"]["shared_tx_count_static_site_fully_selected"] = True
        self.assert_contract_rejected(changed)

    def test_30_ledger_closure_issue_and_readiness_promotions_are_rejected(self) -> None:
        paths = (
            ("scope", "cumulative_residual_field_count", 229),
            ("scope", "factory_paths_closed_before_and_after", 18),
            ("truth_boundary", "legacy_selected_field_mutation_proven", True),
            ("truth_boundary", "issue_38_acceptance_criterion_complete", True),
            ("truth_boundary", "production_ready", True),
        )
        for section, key, value in paths:
            changed = copy.deepcopy(self.contract)
            changed[section][key] = value
            with self.subTest(key=key):
                self.assert_contract_rejected(changed)

    def test_31_parent_and_canonical_base_mutations_are_rejected(self) -> None:
        changed = copy.deepcopy(self.contract)
        changed["source_contracts"]["factory_fee_growth_initialization"][
            "raw_sha256"
        ] = "0" * 64
        self.assert_contract_rejected(changed)
        changed = copy.deepcopy(self.contract)
        changed["authority_contract"]["canonical_base"][
            "canonical_merge_commit"
        ] = "0" * 40
        self.assert_contract_rejected(changed)

    def test_32_duplicate_json_keys_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="factory-bigint-json-") as temporary:
            path = Path(temporary) / "duplicate.json"
            path.write_text('{"scope":{},"scope":{}}\n')
            with self.assertRaises(self.expected_errors):
                VERIFIER.load_json(path)

    def test_33_documentation_keeps_refusal_and_accounting_boundaries(self) -> None:
        readme = (
            ROOT / "uniswap-v3/factory-pool-bigint-init/v1/README.md"
        ).read_text()
        eligibility = (
            ROOT
            / "uniswap-v3/factory-pool-bigint-init/v1/docs/eligibility.md"
        ).read_text()
        provenance = (
            ROOT
            / "uniswap-v3/factory-pool-bigint-init/v1/docs/provenance.md"
        ).read_text()
        combined = readme + eligibility
        self.assertIn("40", combined)
        self.assertIn("36 selected / 230 residual", eligibility)
        self.assertIn("14/18", eligibility)
        self.assertIn("shared", combined.lower())
        self.assertIn("38", combined)
        self.assertIn("71", combined)
        self.assertIn("symbol", eligibility.lower())
        self.assertIn("canonical", provenance.lower())
        self.assertIn("pointer returned by `ByteArray.fromI32(0)`", readme)
        self.assertNotIn("BigInt-zero", combined)
        self.assertNotIn("all 60 legacy fields are proven", combined)


if __name__ == "__main__":
    unittest.main()
