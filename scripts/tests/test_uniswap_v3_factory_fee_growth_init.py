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
VERIFIER_PATH = ROOT / "scripts/verify-uniswap-v3-factory-fee-growth-init.py"
SPEC = importlib.util.spec_from_file_location(
    "uniswap_v3_factory_fee_growth_init_v1", VERIFIER_PATH
)
assert SPEC is not None and SPEC.loader is not None
VERIFIER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VERIFIER
SPEC.loader.exec_module(VERIFIER)

Mutation = tuple[str, Callable[[list[str], dict[str, Any]], None]]
SemanticCheck = Callable[[dict[str, Any]], Any]
ModuleMutation = Callable[[str], str]


class FactoryFeeGrowthInitializationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sources = VERIFIER.load_sources(ROOT, recompute_wat=True)
        cls.contract = VERIFIER.verify_contract(
            ROOT, sources=cls.sources, recompute_wat=False
        )
        cls.contexts = cls.sources["legacy_contexts"]
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
                    VERIFIER.MODERN.VerificationError,
                    VERIFIER.FEE_GROWTH.VerificationError,
                    VERIFIER.EFFECTS.VerificationError,
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
        module_mutation: ModuleMutation | None = None,
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
        if module_mutation is not None:
            wat_text = module_mutation(wat_text)
        with tempfile.TemporaryDirectory(
            prefix="factory-fee-growth-init-wat-"
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
        module_mutation: ModuleMutation | None = None,
        expected_message: str | None = None,
    ) -> None:
        changed = self.roundtrip(context, mutations, module_mutation)
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
            [sys.executable, str(VERIFIER_PATH), "--root", str(ROOT)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn(
            "4 unique legacy mappings, 12 legacy and 16 total initialization records, 28 diffs",
            result.stdout,
        )

    def test_02_scope_is_exactly_bounded(self) -> None:
        scope = self.contract["scope"]
        self.assertEqual(
            (
                scope["unique_legacy_mapping_count"],
                scope["legacy_segment_count"],
                scope["modern_parent_segment_count"],
                scope["total_initialization_record_count"],
                scope["cumulative_selected_field_count"],
                scope["cumulative_residual_field_count"],
                scope["factory_paths_closed_before_and_after"],
                scope["factory_paths_residual_before_and_after"],
            ),
            (4, 6, 2, 16, 36, 230, 14, 4),
        )
        self.assertEqual(
            scope["selected_fields"],
            ["Pool.feeGrowthGlobal0X128", "Pool.feeGrowthGlobal1X128"],
        )

    def test_03_truth_boundary_promotes_only_declared_claims(self) -> None:
        truth = self.contract["truth_boundary"]
        self.assertEqual(
            {key for key, value in truth.items() if value}, set(VERIFIER.TRUE_FLAGS)
        )
        self.assertEqual(
            {key for key, value in truth.items() if not value},
            set(VERIFIER.FALSE_FLAGS),
        )
        for key in (
            "legacy_factory_complete_static_handler_contracts_proven",
            "all_sixty_legacy_stored_fields_proven",
            "numeric_zero_preserved_across_host_reset_lifecycle",
            "fresh_value_allocation_proven",
            "typed_map_get_entry_semantics_rederived",
            "typed_map_get_semantics_rederived",
            "typed_map_entry_constructor_semantics_rederived",
            "typed_map_entry_array_push_semantics_rederived",
            "entity_constructor_semantics_rederived",
            "entity_backing_array_construction_semantics_rederived",
            "value_to_string_semantics_rederived",
            "legacy_selected_field_mutation_proven",
            "selected_persistence_proven",
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
                upstream = self.sources["upstream_factory_effects"][context["cid"]]
                proof = VERIFIER.prove_legacy_context(context, upstream)
                self.assertTrue(
                    proof[
                        "selected_initialization_setter_and_save_call_operand_flow_machine_proven"
                    ]
                )
                self.assertFalse(proof["selected_field_mutation_proven"])
                self.assertFalse(proof["value_from_bigint"]["fresh_value_allocation_proven"])
                self.assertFalse(
                    proof["typed_map_set"]["get_entry_search_semantics_rederived"]
                )
                self.assertFalse(
                    proof["pool_entity_receiver_origin"][
                        "entity_constructor_semantics_rederived"
                    ]
                )

    def test_05_shared_normalized_slices_match_all_profiles(self) -> None:
        for context in self.contexts:
            with self.subTest(profile=context["profile"]["profile_id"]):
                self.assertEqual(
                    VERIFIER.decoded_string_normalized_slice_sha256(
                        context["handler"], context["memory"], 341, 351
                    ),
                    VERIFIER.SETTER_DECODED_KEY_NORMALIZED_SHA256,
                )
                self.assertEqual(
                    VERIFIER.decoded_string_normalized_slice_sha256(
                        context["handler"], context["memory"], 341, 421
                    ),
                    VERIFIER.THROUGH_SAVE_DECODED_STRING_NORMALIZED_SHA256,
                )

    def test_06_pool_getter_mutation_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-root"]
        self.assert_wat_rejected(
            context,
            [
                self.handler_mutation(
                    context,
                    86,
                    "call $src/types/Factory/Factory/PoolCreated__Params#get:token0",
                )
            ],
            VERIFIER.prove_receiver_origin,
            expected_message="event-to-Pool receiver flow drift",
        )

    def test_07_bytes_to_hex_mutation_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-qmrv"]
        self.assert_wat_rejected(
            context,
            [
                self.handler_mutation(
                    context,
                    87,
                    "call $~lib/@graphprotocol/graph-ts/index/typeConversion.bytesToString",
                )
            ],
            VERIFIER.prove_receiver_origin,
            expected_message="event-to-Pool receiver flow drift",
        )

    def test_08_receiver_local_mutation_is_rejected(self) -> None:
        context = self.by_profile["legacy-base-root"]
        self.assert_wat_rejected(
            context,
            [self.handler_mutation(context, 89, "local.set $l2")],
            VERIFIER.prove_receiver_origin,
            expected_message="event-to-Pool receiver flow drift",
        )

    def test_09_generic_constructor_body_mutation_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-stable"]
        constructor = self.function_by_suffix(
            context, "src/types/schema/Factory#constructor"
        )
        self.assert_wat_rejected(
            context,
            [
                (
                    constructor.name,
                    lambda lines, _context: self.replace(
                        lines, 6, "i32.const 0"
                    ),
                )
            ],
            VERIFIER.prove_receiver_origin,
            expected_message="constructor ID key drift",
        )

    def test_10_fee0_key_duplication_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-root"]
        fee1_pointer = VERIFIER.EXPECTED["legacy-mainnet-root"]["setter_keys"][1]
        self.assert_wat_rejected(
            context,
            [self.handler_mutation(context, 342, f"i32.const {fee1_pointer}")],
            VERIFIER.prove_selected_setter_through_save,
            expected_message="exact receiver/key/g2/Value/set flow drift",
        )

    def test_11_fee1_key_swap_is_rejected(self) -> None:
        context = self.by_profile["legacy-base-root"]
        fee0_pointer = VERIFIER.EXPECTED["legacy-base-root"]["setter_keys"][0]
        self.assert_wat_rejected(
            context,
            [self.handler_mutation(context, 347, f"i32.const {fee0_pointer}")],
            VERIFIER.prove_selected_setter_through_save,
            expected_message="exact receiver/key/g2/Value/set flow drift",
        )

    def test_12_fee0_global_g3_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-qmrv"]
        self.assert_wat_rejected(
            context,
            [self.handler_mutation(context, 343, "global.get $g3")],
            VERIFIER.prove_selected_setter_through_save,
            expected_message="exact receiver/key/g2/Value/set flow drift",
        )

    def test_13_fee1_global_g4_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-stable"]
        self.assert_wat_rejected(
            context,
            [self.handler_mutation(context, 348, "global.get $g4")],
            VERIFIER.prove_selected_setter_through_save,
            expected_message="exact receiver/key/g2/Value/set flow drift",
        )

    def test_14_value_wrapper_substitution_is_rejected(self) -> None:
        context = self.by_profile["legacy-base-root"]
        self.assert_wat_rejected(
            context,
            [
                self.handler_mutation(
                    context,
                    344,
                    "call $~lib/@graphprotocol/graph-ts/index/Value.fromString",
                )
            ],
            VERIFIER.prove_selected_setter_through_save,
            expected_message="exact receiver/key/g2/Value/set flow drift",
        )

    def test_15_setter_receiver_substitution_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-root"]
        self.assert_wat_rejected(
            context,
            [self.handler_mutation(context, 346, "local.get $l2")],
            VERIFIER.prove_selected_setter_through_save,
            expected_message="exact receiver/key/g2/Value/set flow drift",
        )

    def test_16_value_kind_mutation_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-qmrv"]
        value = self.function_by_suffix(context, "Value.fromBigInt")
        self.assert_wat_rejected(
            context,
            [(value.name, lambda lines, _context: self.replace(lines, 4, "i32.const 6"))],
            VERIFIER.prove_value_from_bigint,
            expected_message="Value kind/payload/return identity drift",
        )

    def test_17_value_payload_mutation_is_rejected(self) -> None:
        context = self.by_profile["legacy-base-root"]
        value = self.function_by_suffix(context, "Value.fromBigInt")
        self.assert_wat_rejected(
            context,
            [(value.name, lambda lines, _context: self.replace(lines, 7, "i32.const 0"))],
            VERIFIER.prove_value_from_bigint,
            expected_message="Value kind/payload/return identity drift",
        )

    def test_18_native_zero_to_one_mutation_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-stable"]
        constants = context["functions"]["start:src/utils/constants"]
        self.assert_wat_rejected(
            context,
            [(constants.name, lambda lines, _context: self.replace(lines, 5, "i32.const 1"))],
            VERIFIER.prove_native_start_and_g2,
            expected_message="zero/one constant construction drift",
        )

    def test_19_g2_writer_rebound_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-root"]
        constants = context["functions"]["start:src/utils/constants"]
        self.assert_wat_rejected(
            context,
            [(constants.name, lambda lines, _context: self.replace(lines, 7, "global.set $g3"))],
            VERIFIER.prove_native_start_and_g2,
            expected_message="complete global writer inventory drift",
        )

    def test_20_second_g2_writer_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-qmrv"]
        constants = context["functions"]["start:src/utils/constants"]
        self.assert_wat_rejected(
            context,
            [(constants.name, lambda lines, _context: self.replace(lines, 10, "global.set $g2"))],
            VERIFIER.prove_native_start_and_g2,
            expected_message="complete global writer inventory drift",
        )

    def test_21_memory_reset_writing_g2_is_rejected(self) -> None:
        context = self.by_profile["legacy-base-root"]
        reset = self.function_by_suffix(context, "~lib/memory/memory.reset")
        self.assert_wat_rejected(
            context,
            [(reset.name, lambda lines, _context: self.replace(lines, 2, "global.set $g2"))],
            VERIFIER.prove_native_start_and_g2,
            expected_message="complete global writer inventory drift",
        )

    def test_22_native_start_rebinding_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-stable"]
        self.assert_wat_rejected(
            context,
            [],
            VERIFIER.prove_native_start_and_g2,
            lambda wat: wat.replace(
                "(start $start)", "(start $start:src/utils/constants)", 1
            ),
            expected_message="native start drift",
        )

    def test_23_inserted_return_before_save_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-root"]
        self.assert_wat_rejected(
            context,
            [
                (
                    context["handler"].name,
                    lambda lines, _context: self.insert(lines, 351, ["return"]),
                )
            ],
            VERIFIER.prove_selected_setter_through_save,
            expected_message="selected setter-through-save control bypass drift",
        )

    def test_24_inserted_structured_control_before_save_is_rejected(self) -> None:
        context = self.by_profile["legacy-base-root"]
        self.assert_wat_rejected(
            context,
            [
                (
                    context["handler"].name,
                    lambda lines, _context: self.insert(
                        lines, 351, ["i32.const 0", "if", "end"]
                    ),
                )
            ],
            VERIFIER.prove_selected_setter_through_save,
            expected_message="selected setter-through-save control bypass drift",
        )

    def test_25_inserted_receiver_reassignment_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-qmrv"]
        self.assert_wat_rejected(
            context,
            [
                (
                    context["handler"].name,
                    lambda lines, _context: self.insert(
                        lines, 351, ["i32.const 0", "local.set $l1"]
                    ),
                )
            ],
            VERIFIER.prove_selected_setter_through_save,
            expected_message="selected Pool receiver reassignment drift",
        )

    def test_26_pool_save_receiver_mutation_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-stable"]
        self.assert_wat_rejected(
            context,
            [self.handler_mutation(context, 419, "local.get $l2")],
            VERIFIER.prove_selected_setter_through_save,
            expected_message="Pool save receiver drift",
        )

    def test_27_pool_save_target_mutation_is_rejected(self) -> None:
        context = self.by_profile["legacy-base-root"]
        save = self.function_by_suffix(context, "src/types/schema/Pool#save")
        self.assert_wat_rejected(
            context,
            [(save.name, lambda lines, _context: self.replace(lines, 27, "i32.const 328"))],
            VERIFIER.prove_pool_save,
            expected_message="Pool store target drift",
        )

    def test_28_pool_save_id_key_mutation_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-root"]
        save = self.function_by_suffix(context, "src/types/schema/Pool#save")
        pointer = VERIFIER.EXPECTED["legacy-mainnet-root"]["setter_keys"][0]
        self.assert_wat_rejected(
            context,
            [(save.name, lambda lines, _context: self.replace(lines, 3, f"i32.const {pointer}"))],
            VERIFIER.prove_pool_save,
            expected_message="Pool#save ID key drift",
        )

    def test_29_pool_save_missing_id_trap_mutation_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-qmrv"]
        save = self.function_by_suffix(context, "src/types/schema/Pool#save")
        self.assert_wat_rejected(
            context,
            [(save.name, lambda lines, _context: self.replace(lines, 13, "nop"))],
            VERIFIER.prove_pool_save,
            expected_message="Pool#save missing-ID trap drift",
        )

    def test_30_pool_save_wrong_kind_trap_mutation_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-stable"]
        save = self.function_by_suffix(context, "src/types/schema/Pool#save")
        self.assert_wat_rejected(
            context,
            [(save.name, lambda lines, _context: self.replace(lines, 25, "nop"))],
            VERIFIER.prove_pool_save,
            expected_message="Pool#save wrong-kind trap drift",
        )

    def test_31_typed_map_update_offset_mutation_is_rejected(self) -> None:
        context = self.by_profile["legacy-base-root"]
        typed_map = self.function_by_suffix(context, VERIFIER.LEGACY_MAP_SET)
        self.assert_wat_rejected(
            context,
            [(typed_map.name, lambda lines, _context: self.replace(lines, 9, "i32.store offset=8"))],
            VERIFIER.prove_typed_map_set,
            expected_message="TypedMap outer update/entry-construction/push call-operand flow drift",
        )

    def test_32_typed_map_append_value_mutation_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-root"]
        typed_map = self.function_by_suffix(context, VERIFIER.LEGACY_MAP_SET)
        self.assert_wat_rejected(
            context,
            [(typed_map.name, lambda lines, _context: self.replace(lines, 13, "local.get $p0"))],
            VERIFIER.prove_typed_map_set,
            expected_message="TypedMap outer update/entry-construction/push call-operand flow drift",
        )

    def test_33_excluded_pool_return_mutation_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-qmrv"]
        self.assert_wat_rejected(
            context,
            [self.handler_mutation(context, 8, "nop")],
            VERIFIER.prove_guard_and_return_boundaries,
            expected_message="excluded Pool return prefix drift",
        )

    def test_34_token0_decimals_return_mutation_is_rejected(self) -> None:
        context = self.by_profile["legacy-base-root"]
        self.assert_wat_rejected(
            context,
            [self.handler_mutation(context, 137, "nop")],
            VERIFIER.prove_guard_and_return_boundaries,
            expected_message="token0 early return drift",
        )

    def test_35_token1_decimals_return_mutation_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-stable"]
        self.assert_wat_rejected(
            context,
            [self.handler_mutation(context, 211, "nop")],
            VERIFIER.prove_guard_and_return_boundaries,
            expected_message="token1 early return drift",
        )

    def test_36_total_supply_decode_overclaim_shape_mutation_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-root"]
        helper = self.function_by_suffix(context, "fetchTokenTotalSupply")
        self.assert_wat_rejected(
            context,
            [(helper.name, lambda lines, _context: self.replace(lines, 9, "i32.const 0"))],
            VERIFIER.prove_legacy_static_residuals,
            expected_message="totalSupply pointer/revert flow drift",
        )

    def test_37_static_array_shape_mutation_is_rejected(self) -> None:
        context = self.by_profile["legacy-base-root"]
        helper = self.function_by_suffix(
            context, "StaticTokenDefinition.fromAddress"
        )

        def mutate(lines: list[str], _context: dict[str, Any]) -> None:
            index = next(
                i for i, line in enumerate(lines) if VERIFIER.normalized(line) == "i32.const 6"
            )
            self.replace(lines, index, "i32.const 5")

        self.assert_wat_rejected(
            context,
            [(helper.name, mutate)],
            VERIFIER.prove_legacy_static_residuals,
        )

    def test_38_reachable_unselected_helper_mutation_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-qmrv"]
        helper = self.function_by_suffix(context, "~lib/string/String.__eq")

        def mutate(lines: list[str], _context: dict[str, Any]) -> None:
            index = next(
                i for i, line in enumerate(lines) if VERIFIER.normalized(line) == "i32.const 0"
            )
            self.replace(lines, index, "i32.const 1")

        changed = self.roundtrip(context, [(helper.name, mutate)])
        upstream = self.sources["upstream_factory_effects"][context["cid"]]
        with self.assertRaises(self.expected_errors):
            VERIFIER.prove_reachable_residual_inventory(changed, upstream)

    def test_39_missing_segment_is_rejected(self) -> None:
        changed = copy.deepcopy(self.contract)
        changed["segments"].pop()
        self.assert_contract_rejected(changed)

    def test_40_missing_selected_field_record_is_rejected(self) -> None:
        changed = copy.deepcopy(self.contract)
        changed["segments"][0]["semantic_surface"]["fields"].pop()
        self.assert_contract_rejected(changed)

    def test_41_missing_pairwise_diff_is_rejected(self) -> None:
        changed = copy.deepcopy(self.contract)
        changed["segment_diffs"].pop()
        self.assert_contract_rejected(changed)

    def test_42_field_ledger_mutation_is_rejected(self) -> None:
        changed = copy.deepcopy(self.contract)
        changed["scope"]["cumulative_residual_field_count"] = 229
        self.assert_contract_rejected(changed)

    def test_43_factory_closure_mutation_is_rejected(self) -> None:
        changed = copy.deepcopy(self.contract)
        changed["scope"]["factory_paths_closed_before_and_after"] = 18
        self.assert_contract_rejected(changed)

    def test_44_complete_static_promotion_is_rejected(self) -> None:
        changed = copy.deepcopy(self.contract)
        changed["truth_boundary"][
            "legacy_factory_complete_static_handler_contracts_proven"
        ] = True
        self.assert_contract_rejected(changed)

    def test_45_static_array_safety_promotion_is_rejected(self) -> None:
        changed = copy.deepcopy(self.contract)
        changed["legacy_mapping_proofs"][0]["legacy_static_residual_boundary"][
            "static_array_safe"
        ] = True
        self.assert_contract_rejected(changed)

    def test_46_total_supply_decode_promotion_is_rejected(self) -> None:
        changed = copy.deepcopy(self.contract)
        changed["legacy_mapping_proofs"][0]["legacy_static_residual_boundary"][
            "total_supply_helper"
        ]["erc20_result_data_decoded"] = True
        self.assert_contract_rejected(changed)

    def test_47_issue_completion_promotion_is_rejected(self) -> None:
        changed = copy.deepcopy(self.contract)
        changed["truth_boundary"]["issue_38_acceptance_criterion_complete"] = True
        self.assert_contract_rejected(changed)

    def test_48_readiness_promotion_is_rejected(self) -> None:
        changed = copy.deepcopy(self.contract)
        changed["truth_boundary"]["production_ready"] = True
        self.assert_contract_rejected(changed)

    def test_49_legacy_field_mutation_promotion_is_rejected(self) -> None:
        changed = copy.deepcopy(self.contract)
        changed["truth_boundary"]["legacy_selected_field_mutation_proven"] = True
        self.assert_contract_rejected(changed)

    def test_50_parent_digest_mutation_is_rejected(self) -> None:
        changed = copy.deepcopy(self.contract)
        changed["source_contracts"]["pool_swap_fee_growth"]["raw_sha256"] = "0" * 64
        self.assert_contract_rejected(changed)

    def test_51_canonical_base_mutation_is_rejected(self) -> None:
        changed = copy.deepcopy(self.contract)
        changed["authority_contract"]["canonical_base"]["canonical_merge_commit"] = "0" * 40
        self.assert_contract_rejected(changed)

    def test_52_duplicate_json_keys_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="factory-init-json-") as temporary:
            path = Path(temporary) / "duplicate.json"
            path.write_text('{"scope":{},"scope":{}}\n')
            with self.assertRaises(self.expected_errors):
                VERIFIER.load_json(path)

    def test_53_documentation_keeps_refusal_boundary_explicit(self) -> None:
        readme = (
            ROOT / "uniswap-v3/factory-fee-growth-init/v1/README.md"
        ).read_text()
        eligibility = (
            ROOT
            / "uniswap-v3/factory-fee-growth-init/v1/docs/eligibility.md"
        ).read_text()
        provenance = (
            ROOT
            / "uniswap-v3/factory-fee-growth-init/v1/docs/provenance.md"
        ).read_text()
        self.assertIn("four unique legacy Factory mappings", readme)
        self.assertIn("16", readme)
        self.assertIn("14/18", eligibility)
        self.assertIn("36 selected / 230 residual", eligibility)
        self.assertIn("canonical", provenance.lower())
        self.assertIn("pointer returned by `ByteArray.fromI32(0)`", readme)
        self.assertIn("legacy selected field mutation remains false", eligibility.lower())
        self.assertNotIn("BigInt-zero", readme + eligibility)
        self.assertNotIn("all 60 legacy fields are proven", readme)


if __name__ == "__main__":
    unittest.main()
