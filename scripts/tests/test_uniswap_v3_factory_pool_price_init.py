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
VERIFIER_PATH = ROOT / "scripts/verify-uniswap-v3-factory-pool-price-init.py"
SPEC = importlib.util.spec_from_file_location(
    "uniswap_v3_factory_pool_price_init_v1", VERIFIER_PATH
)
assert SPEC is not None and SPEC.loader is not None
VERIFIER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VERIFIER
SPEC.loader.exec_module(VERIFIER)

Mutation = tuple[str, Callable[[list[str], dict[str, Any]], None]]
SemanticCheck = Callable[[dict[str, Any]], Any]


class FactoryPoolPriceInitializationTest(unittest.TestCase):
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
                    VERIFIER.PARENT.PARENT.VerificationError,
                    VERIFIER.PARENT.PARENT.MODERN.VerificationError,
                    VERIFIER.PARENT.PARENT.FEE_GROWTH.VerificationError,
                    VERIFIER.PARENT.PARENT.EFFECTS.VerificationError,
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
            prefix="factory-pool-price-init-wat-"
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
            "4 unique legacy mappings, 12 legacy and 16 total initialization records, 28 diffs; "
            "8 fully selected direct sites of 44 reachable static sites and "
            "9/78 expanded invocations selected",
            result.stdout,
        )

    def test_02_scope_site_and_invocation_accounting_are_exact(self) -> None:
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
            (4, 8, 6, 12, 2, 4, 16, 28),
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
            (44, 8, 36, 78, 9, 69),
        )
        self.assertIs(scope["shared_tx_count_static_site_remains_residual"], True)
        self.assertEqual(
            scope["selected_fields"],
            ["Pool.token0Price", "Pool.token1Price"],
        )

    def test_03_ledger_closure_and_false_gates_remain_bounded(self) -> None:
        scope = self.contract["scope"]
        self.assertEqual(
            (
                scope["cumulative_selected_field_count"],
                scope["cumulative_residual_field_count"],
                scope["factory_paths_closed_before_and_after"],
                scope["factory_paths_residual_before_and_after"],
                scope["legacy_factory_field_call_flow_capsules_before"],
                scope["legacy_factory_field_call_flow_capsules_after"],
                scope["legacy_factory_fields_without_call_flow_capsules_after"],
            ),
            (36, 230, 14, 4, 7, 9, 51),
        )
        truth = self.contract["truth_boundary"]
        self.assertEqual({key for key, value in truth.items() if value}, set(VERIFIER.TRUE_FLAGS))
        self.assertEqual({key for key, value in truth.items() if not value}, set(VERIFIER.FALSE_FLAGS))
        for key in (
            "big_decimal_from_string_numeric_semantics_rederived",
            "g4_pointer_is_proven_numeric_zero",
            "legacy_selected_price_field_mutation_proven",
            "legacy_selected_field_mutation_proven",
            "selected_persistence_proven",
            "runtime_population_complete",
            "logical_parity_complete",
            "physical_parity_complete",
            "poi_parity_complete",
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
                        "selected_price_initialization_call_operand_flow_machine_proven"
                    ]
                )
                self.assertEqual(len(proof["selected_fields"]), 2)
                self.assertFalse(proof["legacy_selected_price_field_mutation_proven"])
                self.assertFalse(
                    proof["big_decimal_from_string_to_g4"][
                        "g4_pointer_is_proven_numeric_zero"
                    ]
                )

    def test_05_normalized_g4_group_wrapper_and_save_anchors_match(self) -> None:
        for context in self.contexts:
            with self.subTest(profile=context["profile"]["profile_id"]):
                parent = self.parent_by_cid[context["cid"]]
                g4 = VERIFIER.prove_g4_pointer_origin(context, parent)
                direct = VERIFIER.prove_direct_price_groups(context)
                wrapper = VERIFIER.prove_value_from_bigdecimal(context)
                through = VERIFIER.prove_same_receiver_through_save(context)
                self.assertEqual(
                    g4["decoded_string_normalized_sha256"],
                    VERIFIER.G4_ORIGIN_DECODED_NORMALIZED_SHA256,
                )
                self.assertEqual(
                    direct["direct_group_decoded_string_normalized_sha256"],
                    VERIFIER.DIRECT_CONCAT_DECODED_NORMALIZED_SHA256,
                )
                self.assertEqual(
                    wrapper["body_sha256"], VERIFIER.VALUE_FROM_BIGDECIMAL_SHA256
                )
                self.assertEqual(
                    through["selected_region_decoded_string_normalized_sha256"],
                    VERIFIER.THROUGH_SAVE_DECODED_NORMALIZED_SHA256,
                )

    def test_06_g4_source_literal_crossing_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-root"]
        constants = context["functions"]["start:src/utils/constants"]
        self.assert_wat_rejected(
            context,
            [(constants.name, lambda lines, _context: self.replace(lines, 11, "i32.const 320"))],
            lambda changed: VERIFIER.prove_g4_pointer_origin(
                changed, self.parent_by_cid[context["cid"]]
            ),
            expected_message="string-to-bigDecimal-to-g4 pointer flow drift",
        )

    def test_07_g4_call_target_substitution_is_rejected(self) -> None:
        context = self.by_profile["legacy-base-root"]
        constants = context["functions"]["start:src/utils/constants"]
        self.assert_wat_rejected(
            context,
            [
                (
                    constants.name,
                    lambda lines, _context: self.replace(
                        lines,
                        12,
                        "call $~lib/@graphprotocol/graph-ts/index/ByteArray.fromI32",
                    ),
                )
            ],
            lambda changed: VERIFIER.prove_g4_pointer_origin(
                changed, self.parent_by_cid[context["cid"]]
            ),
            expected_message="string-to-bigDecimal-to-g4 pointer flow drift",
        )

    def test_08_g4_destination_global_substitution_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-qmrv"]
        constants = context["functions"]["start:src/utils/constants"]
        self.assert_wat_rejected(
            context,
            [(constants.name, lambda lines, _context: self.replace(lines, 13, "global.set $g5"))],
            lambda changed: VERIFIER.prove_g4_pointer_origin(
                changed, self.parent_by_cid[context["cid"]]
            ),
            expected_message="string-to-bigDecimal-to-g4 pointer flow drift",
        )

    def test_08b_second_g4_writer_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-stable"]
        constants = context["functions"]["start:src/utils/constants"]
        self.assert_wat_rejected(
            context,
            [(constants.name, lambda lines, _context: self.replace(lines, 16, "global.set $g4"))],
            lambda changed: VERIFIER.prove_g4_pointer_origin(
                changed, self.parent_by_cid[context["cid"]]
            ),
            expected_message="complete global writer inventory drift",
        )

    def test_09_value_kind_substitution_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-stable"]
        wrapper = self.function_by_suffix(context, "Value.fromBigDecimal")
        self.assert_wat_rejected(
            context,
            [(wrapper.name, lambda lines, _context: self.replace(lines, 4, "i32.const 7"))],
            VERIFIER.prove_value_from_bigdecimal,
            expected_message="Value kind/payload/return identity drift",
        )

    def test_10_value_payload_substitution_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-root"]
        wrapper = self.function_by_suffix(context, "Value.fromBigDecimal")
        self.assert_wat_rejected(
            context,
            [(wrapper.name, lambda lines, _context: self.replace(lines, 7, "local.get $l1"))],
            VERIFIER.prove_value_from_bigdecimal,
            expected_message="Value kind/payload/return identity drift",
        )

    def test_11_each_price_key_crossing_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-root"]
        pointers = VERIFIER.EXPECTED["legacy-mainnet-root"]["key_pointers"]
        for ordinal, (_, base) in enumerate(VERIFIER.DIRECT_FIELD_BASES):
            replacement = pointers[(ordinal + 1) % len(pointers)]
            with self.subTest(base=base):
                self.assert_wat_rejected(
                    context,
                    [self.handler_mutation(context, base + 1, f"i32.const {replacement}")],
                    VERIFIER.prove_direct_price_groups,
                    expected_message="direct receiver/key/g4/Value/set flow drift",
                )

    def test_12_price_receiver_and_g4_substitutions_are_rejected(self) -> None:
        cases = (
            ("legacy-base-root", 351, "local.get $l2"),
            ("legacy-mainnet-qmrv", 358, "global.get $g5"),
        )
        for profile, index, instruction in cases:
            context = self.by_profile[profile]
            with self.subTest(profile=profile, index=index):
                self.assert_wat_rejected(
                    context,
                    [self.handler_mutation(context, index, instruction)],
                    VERIFIER.prove_direct_price_groups,
                    expected_message="direct receiver/key/g4/Value/set flow drift",
                )

    def test_13_price_wrapper_and_set_target_substitutions_are_rejected(self) -> None:
        cases = (
            (
                "legacy-mainnet-stable",
                354,
                "call $~lib/@graphprotocol/graph-ts/index/Value.fromBigInt",
            ),
            ("legacy-base-root", 360, "call $~lib/internal/memory/memcpy"),
        )
        for profile, index, instruction in cases:
            context = self.by_profile[profile]
            with self.subTest(profile=profile, index=index):
                self.assert_wat_rejected(
                    context,
                    [self.handler_mutation(context, index, instruction)],
                    VERIFIER.prove_direct_price_groups,
                    expected_message="direct receiver/key/g4/Value/set flow drift",
                )

    def test_14_price_group_swap_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-root"]

        def swap(lines: list[str], _context: dict[str, Any]) -> None:
            first = lines[351:356]
            second = lines[356:361]
            lines[351:356] = second
            lines[356:361] = first

        self.assert_wat_rejected(
            context,
            [(context["handler"].name, swap)],
            VERIFIER.prove_direct_price_groups,
            expected_message="direct receiver/key/g4/Value/set flow drift",
        )

    def test_15_inserted_return_and_structured_control_are_rejected(self) -> None:
        cases = (
            ("legacy-mainnet-root", ["return"]),
            ("legacy-base-root", ["i32.const 0", "if", "end"]),
        )
        for profile, instructions in cases:
            context = self.by_profile[profile]
            with self.subTest(profile=profile):
                self.assert_wat_rejected(
                    context,
                    [
                        (
                            context["handler"].name,
                            lambda lines, _context, inserted=instructions: self.insert(
                                lines, 361, inserted
                            ),
                        )
                    ],
                    VERIFIER.prove_same_receiver_through_save,
                    expected_message="price-through-save control bypass drift",
                )

    def test_16_receiver_reassignment_and_pool_save_drift_are_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-qmrv"]
        self.assert_wat_rejected(
            context,
            [
                (
                    context["handler"].name,
                    lambda lines, _context: self.insert(
                        lines, 361, ["i32.const 0", "local.set $l1"]
                    ),
                )
            ],
            VERIFIER.prove_same_receiver_through_save,
            expected_message="Pool receiver reassignment before save drift",
        )
        context = self.by_profile["legacy-mainnet-stable"]
        self.assert_wat_rejected(
            context,
            [self.handler_mutation(context, 419, "local.get $l2")],
            VERIFIER.prove_same_receiver_through_save,
            expected_message="Pool save receiver drift",
        )
        context = self.by_profile["legacy-base-root"]
        self.assert_wat_rejected(
            context,
            [self.handler_mutation(context, 420, "call $src/types/schema/Token#save")],
            VERIFIER.prove_same_receiver_through_save,
            expected_message="Pool save call drift",
        )

    def test_17_later_selected_key_alias_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-root"]
        pointer = VERIFIER.EXPECTED["legacy-mainnet-root"]["key_pointers"][0]
        self.assert_wat_rejected(
            context,
            [self.handler_mutation(context, 367, f"i32.const {pointer}")],
            VERIFIER.prove_same_receiver_through_save,
            expected_message="price-through-save raw authority drift",
        )

    def test_18_residual_site_and_invocation_accounting_proves(self) -> None:
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
                    (8, 36, 9, 69),
                )
                self.assertEqual(
                    result["fully_selected_direct_static_site_relative_wat_lines"],
                    [327, 335, 340, 345, 350, 355, 360, 365],
                )
                self.assertTrue(result["shared_tx_count_static_site_remains_residual"])

    def test_19_projection_and_pairwise_diff_counts_are_exact(self) -> None:
        self.assertEqual(len(self.contract["segments"]), 8)
        self.assertEqual(
            sum(
                len(segment["semantic_surface"]["fields"])
                for segment in self.contract["segments"]
            ),
            16,
        )
        self.assertEqual(len(self.contract["segment_diffs"]), 28)
        generations = [
            segment["semantic_surface"]["control_generation"]
            for segment in self.contract["segments"]
        ]
        self.assertEqual(generations.count("legacy"), 6)
        self.assertEqual(generations.count("modern"), 2)

    def test_20_missing_segment_field_or_diff_is_rejected(self) -> None:
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

    def test_21_static_expanded_ledger_and_closure_mutations_are_rejected(self) -> None:
        paths = (
            ("scope", "cumulative_fully_selected_direct_static_site_count", 9),
            ("scope", "cumulative_unclassified_static_site_count", 35),
            ("scope", "cumulative_selected_expanded_invocation_count", 10),
            ("scope", "cumulative_residual_expanded_invocation_count", 68),
            ("scope", "cumulative_residual_field_count", 228),
            ("scope", "factory_paths_closed_before_and_after", 18),
        )
        for section, key, value in paths:
            changed = copy.deepcopy(self.contract)
            changed[section][key] = value
            with self.subTest(key=key):
                self.assert_contract_rejected(changed)

    def test_22_numeric_mutation_persistence_issue_and_readiness_promotions_are_rejected(self) -> None:
        for key in (
            "big_decimal_from_string_numeric_semantics_rederived",
            "g4_pointer_is_proven_numeric_zero",
            "legacy_selected_price_field_mutation_proven",
            "selected_persistence_proven",
            "issue_38_acceptance_criterion_complete",
            "backfill_ready",
            "production_ready",
            "readiness_complete",
        ):
            changed = copy.deepcopy(self.contract)
            changed["truth_boundary"][key] = True
            with self.subTest(key=key):
                self.assert_contract_rejected(changed)

    def test_23_parent_raw_canonical_and_base_mutations_are_rejected(self) -> None:
        paths = (
            (
                "source_contracts",
                "factory_pool_bigint_initialization",
                "raw_sha256",
            ),
            (
                "source_contracts",
                "factory_pool_bigint_initialization",
                "canonical_sha256",
            ),
            ("authority_contract", "canonical_base", "canonical_merge_commit"),
        )
        for section, subsection, key in paths:
            changed = copy.deepcopy(self.contract)
            changed[section][subsection][key] = "0" * (40 if key.endswith("commit") else 64)
            with self.subTest(key=key):
                self.assert_contract_rejected(changed)

    def test_24_duplicate_json_keys_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="factory-price-json-") as temporary:
            path = Path(temporary) / "duplicate.json"
            path.write_text('{"scope":{},"scope":{}}\n')
            with self.assertRaises(self.expected_errors):
                VERIFIER.load_json(path)

    def test_25_documentation_keeps_pointer_and_refusal_boundaries(self) -> None:
        readme = (
            ROOT / "uniswap-v3/factory-pool-price-init/v1/README.md"
        ).read_text()
        eligibility = (
            ROOT
            / "uniswap-v3/factory-pool-price-init/v1/docs/eligibility.md"
        ).read_text()
        provenance = (
            ROOT
            / "uniswap-v3/factory-pool-price-init/v1/docs/provenance.md"
        ).read_text()
        combined = readme + eligibility
        self.assertIn("16", combined)
        self.assertIn("36 selected / 230 residual", eligibility)
        self.assertIn("14/18", eligibility)
        self.assertIn("8/44", combined)
        self.assertIn("9/78", combined)
        self.assertIn("pointer returned by `bigDecimal.fromString(\"0\")`", readme)
        self.assertIn("canonical", provenance.lower())
        self.assertIn("numeric semantics", combined.lower())
        self.assertNotIn("BigDecimal-zero", combined)
        self.assertNotIn("numeric zero value", combined.lower())
        self.assertNotIn("all 60 legacy fields are proven", combined)


if __name__ == "__main__":
    unittest.main()
