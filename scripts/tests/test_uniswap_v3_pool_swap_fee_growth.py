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
VERIFIER_PATH = ROOT / "scripts/verify-uniswap-v3-pool-swap-fee-growth.py"
SPEC = importlib.util.spec_from_file_location("uniswap_v3_pool_swap_fee_growth_v1", VERIFIER_PATH)
assert SPEC is not None and SPEC.loader is not None
VERIFIER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VERIFIER
SPEC.loader.exec_module(VERIFIER)

Mutation = tuple[str, Callable[[list[str], dict[str, Any]], None]]


class PoolSwapFeeGrowthSemanticsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sources = VERIFIER.load_sources(ROOT, recompute_wat=True)
        cls.contract = VERIFIER.verify_contract(ROOT, sources=cls.sources, recompute_wat=False)
        cls.contexts = cls.sources["pool_wat_contexts"]
        cls.by_profile = {context["profile"]["profile_id"]: context for context in cls.contexts.values()}
        wasm2wat = next(iter(cls.contexts.values()))["wasm2wat"]
        cls.wasm2wat = VERIFIER.INITIALIZE.resolve_tool(wasm2wat, "wasm2wat")
        cls.wat2wasm = VERIFIER.INITIALIZE.resolve_tool(wasm2wat.with_name("wat2wasm"), "wat2wasm")
        cls.expected_errors = tuple(
            dict.fromkeys(
                (
                    VERIFIER.VerificationError,
                    VERIFIER.FLASH.VerificationError,
                    VERIFIER.SWAP.VerificationError,
                    VERIFIER.MINT.VerificationError,
                    VERIFIER.INITIALIZE.VerificationError,
                    VERIFIER.POOL_RUNTIME.VerificationError,
                    VERIFIER.V2.VerificationError,
                    VERIFIER.WRITER.VerificationError,
                )
            )
        )

    def replace(self, lines: list[str], index: int, instruction: str) -> None:
        indent = lines[index][: len(lines[index]) - len(lines[index].lstrip())]
        closing = ")" if lines[index].rstrip().endswith(")") and not instruction.rstrip().endswith(")") else ""
        lines[index] = f"{indent}{instruction}{closing}"

    def insert(self, lines: list[str], index: int, instructions: list[str]) -> None:
        indent = lines[index][: len(lines[index]) - len(lines[index].lstrip())]
        lines[index:index] = [f"{indent}{instruction}" for instruction in instructions]

    def function_by_suffix(self, context: dict[str, Any], suffix: str) -> Any:
        matches = [function for name, function in context["functions"].items() if name.endswith(suffix)]
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
        with tempfile.TemporaryDirectory(prefix="pool-swap-fee-growth-wat-") as temporary:
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
            "indirect_targets": indirect_targets,
            "exports": exports,
            "handler": handler,
            "wat_text": regenerated,
        }

    def assert_wat_rejected(self, context: dict[str, Any], mutations: list[Mutation]) -> None:
        with self.assertRaises(self.expected_errors):
            VERIFIER.prove_pool_swap_fee_growth_wat_context(self.roundtrip(context, mutations))

    def assert_contract_rejected(self, mutation: dict[str, Any]) -> None:
        with self.assertRaises(self.expected_errors):
            VERIFIER.verify_contract(ROOT, mutation, sources=self.sources, recompute_wat=False)

    def handler_mutation(self, context: dict[str, Any], index: int, instruction: str) -> Mutation:
        return (context["handler"].name, lambda lines, _context: self.replace(lines, index, instruction))

    def test_01_committed_contract_is_deterministic(self) -> None:
        self.assertEqual(self.contract, VERIFIER.expected_contract_from_sources(self.sources))
        result = subprocess.run(
            [sys.executable, str(VERIFIER_PATH), "--root", str(ROOT)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("8 mappings, 16 segment-field call-flow records, 28 diffs", result.stdout)

    def test_02_scope_counts_remain_exactly_bounded(self) -> None:
        scope = self.contract["scope"]
        self.assertEqual(
            scope["claim"],
            "exact retained-WAT Pool.handleSwap event-address Pool bind, ordered feeGrowthGlobal0X128/1X128 non-try calls, result-zero BigInt decodes, uncrossed same-Pool setters, and same-receiver second Pool.save path across all eight profiles; host semantics, persistence, complete Swap, and readiness remain false",
        )
        component_readme = (ROOT / "uniswap-v3/pool-swap-fee-growth/v1/README.md").read_text()
        self.assertIn(
            "6. set `feeGrowthGlobal0X128` on the selected Pool from the first decoded value;",
            component_readme,
        )
        self.assertIn(
            "7. set `feeGrowthGlobal1X128` on that same Pool from the second decoded value;",
            component_readme,
        )
        self.assertIn("8. reach the second save of that same Pool receiver.", component_readme)
        self.assertNotIn("set the two matching fields", component_readme)
        self.assertEqual(
            (
                scope["selected_field_count"],
                scope["segment_field_call_flow_evidence_count"],
                scope["cumulative_selected_field_count"],
                scope["cumulative_residual_field_count"],
            ),
            (2, 16, 36, 230),
        )

    def test_03_truth_boundary_promotes_only_declared_claims(self) -> None:
        truth = self.contract["truth_boundary"]
        self.assertEqual({key for key, value in truth.items() if value}, set(VERIFIER.TRUE_FLAGS))
        self.assertEqual({key for key, value in truth.items() if not value}, set(VERIFIER.FALSE_FLAGS))
        for key in (
            "pool_swap_fee_growth_output_implemented",
            "host_eth_call_semantics_rederived",
            "host_call_block_pointer_semantics_rederived",
            "host_call_error_classification_rederived",
            "graph_handler_rollback_proven_by_retained_wat",
            "issue_37_flash_implementation_criterion_complete",
            "issue_38_complete_field_history_criterion_complete",
        ):
            with self.subTest(key=key):
                self.assertIs(truth[key], False)
        self.assertIs(truth["canonical_flash_merge_base_verified"], True)

    def test_04_unmodified_legacy_and_modern_contexts_prove(self) -> None:
        for context in self.contexts.values():
            with self.subTest(profile=context["profile"]["profile_id"]):
                VERIFIER.prove_pool_swap_fee_growth_wat_context(self.roundtrip(context, []))

    def test_05_selectors_are_independently_derived(self) -> None:
        self.assertEqual(VERIFIER.FLASH.selector("feeGrowthGlobal0X128()"), "f3058399")
        self.assertEqual(VERIFIER.FLASH.selector("feeGrowthGlobal1X128()"), "46141319")

    def test_06_modern_fee0_method_mutation_is_rejected(self) -> None:
        context = self.by_profile["modern-base"]
        self.assert_wat_rejected(context, [self.handler_mutation(context, 1709, "i32.const 0")])

    def test_07_modern_fee0_signature_mutation_is_rejected(self) -> None:
        context = self.by_profile["modern-mainnet"]
        self.assert_wat_rejected(context, [self.handler_mutation(context, 1710, "i32.const 0")])

    def test_08_modern_fee1_method_mutation_is_rejected(self) -> None:
        context = self.by_profile["modern-base"]
        self.assert_wat_rejected(context, [self.handler_mutation(context, 1721, "i32.const 0")])

    def test_09_modern_fee1_signature_mutation_is_rejected(self) -> None:
        context = self.by_profile["modern-mainnet"]
        self.assert_wat_rejected(context, [self.handler_mutation(context, 1722, "i32.const 0")])

    def test_10_modern_call_order_mutation_is_rejected(self) -> None:
        context = self.by_profile["modern-base"]
        replacement = VERIFIER.normalized(context["handler"].lines[1721])
        self.assert_wat_rejected(context, [self.handler_mutation(context, 1709, replacement)])

    def test_11_modern_fee0_result_index_mutation_is_rejected(self) -> None:
        context = self.by_profile["modern-base"]
        self.assert_wat_rejected(context, [self.handler_mutation(context, 1716, "i32.const 1")])

    def test_12_modern_fee1_result_index_mutation_is_rejected(self) -> None:
        context = self.by_profile["modern-mainnet"]
        self.assert_wat_rejected(context, [self.handler_mutation(context, 1728, "i32.const 1")])

    def test_13_modern_fee0_decode_mutation_is_rejected(self) -> None:
        context = self.by_profile["modern-base"]

        def mutate(lines: list[str], _context: dict[str, Any]) -> None:
            indent = lines[1718][: len(lines[1718]) - len(lines[1718].lstrip())]
            lines[1718:1719] = [f"{indent}drop", f"{indent}i32.const 0"]

        self.assert_wat_rejected(context, [(context["handler"].name, mutate)])

    def test_14_modern_fee1_decode_mutation_is_rejected(self) -> None:
        context = self.by_profile["modern-mainnet"]

        def mutate(lines: list[str], _context: dict[str, Any]) -> None:
            indent = lines[1730][: len(lines[1730]) - len(lines[1730].lstrip())]
            lines[1730:1731] = [f"{indent}drop", f"{indent}i32.const 0"]

        self.assert_wat_rejected(context, [(context["handler"].name, mutate)])

    def test_15_modern_fee0_result_local_mutation_is_rejected(self) -> None:
        context = self.by_profile["modern-base"]
        self.assert_wat_rejected(context, [self.handler_mutation(context, 1719, "local.set $p0")])

    def test_16_modern_fee1_result_local_mutation_is_rejected(self) -> None:
        context = self.by_profile["modern-mainnet"]
        self.assert_wat_rejected(context, [self.handler_mutation(context, 1731, "local.set $l2")])

    def test_17_modern_second_call_receiver_mutation_is_rejected(self) -> None:
        context = self.by_profile["modern-base"]
        self.assert_wat_rejected(context, [self.handler_mutation(context, 1720, "i32.const 0")])

    def test_18_modern_fee0_key_mutation_is_rejected(self) -> None:
        context = self.by_profile["modern-mainnet"]
        self.assert_wat_rejected(context, [self.handler_mutation(context, 1745, "i32.const 0")])

    def test_19_modern_fee1_key_mutation_is_rejected(self) -> None:
        context = self.by_profile["modern-base"]
        self.assert_wat_rejected(context, [self.handler_mutation(context, 1761, "i32.const 0")])

    def test_20_modern_fee0_receiver_mutation_is_rejected(self) -> None:
        context = self.by_profile["modern-mainnet"]
        self.assert_wat_rejected(context, [self.handler_mutation(context, 1744, "i32.const 0")])

    def test_21_modern_fee1_receiver_mutation_is_rejected(self) -> None:
        context = self.by_profile["modern-base"]
        self.assert_wat_rejected(context, [self.handler_mutation(context, 1760, "i32.const 0")])

    def test_22_modern_fee0_value_kind_mutation_is_rejected(self) -> None:
        context = self.by_profile["modern-base"]
        self.assert_wat_rejected(context, [self.handler_mutation(context, 1739, "i32.const 6")])

    def test_23_modern_fee1_value_payload_mutation_is_rejected(self) -> None:
        context = self.by_profile["modern-mainnet"]
        self.assert_wat_rejected(context, [self.handler_mutation(context, 1758, "i64.const 0")])

    def test_24_modern_pool_save_receiver_mutation_is_rejected(self) -> None:
        context = self.by_profile["modern-base"]
        self.assert_wat_rejected(context, [self.handler_mutation(context, 2601, "i32.const 0")])

    def test_25_modern_pool_save_removal_is_rejected(self) -> None:
        context = self.by_profile["modern-mainnet"]
        self.assert_wat_rejected(context, [self.handler_mutation(context, 2602, "drop")])

    def test_26_duplicate_pool_save_is_rejected(self) -> None:
        context = self.by_profile["modern-base"]
        raw_call = context["handler"].lines[2602].strip().rstrip(")")

        def mutate(lines: list[str], _context: dict[str, Any]) -> None:
            self.insert(lines, 2601, ["local.get $l1", raw_call])

        self.assert_wat_rejected(context, [(context["handler"].name, mutate)])

    def test_27_modern_nontry_null_trap_fallthrough_is_rejected(self) -> None:
        context = self.by_profile["modern-base"]
        helper = self.function_by_suffix(context, "ethereum.SmartContract#call")
        self.assert_wat_rejected(context, [(helper.name, lambda lines, _context: self.replace(lines, 57, "nop"))])

    def test_28_modern_ethereum_call_target_mutation_is_rejected(self) -> None:
        context = self.by_profile["modern-mainnet"]
        helper = self.function_by_suffix(context, "ethereum.SmartContract#call")

        def mutate(lines: list[str], _context: dict[str, Any]) -> None:
            indent = lines[42][: len(lines[42]) - len(lines[42].lstrip())]
            lines[42:43] = [f"{indent}drop", f"{indent}i32.const 0"]

        self.assert_wat_rejected(context, [(helper.name, mutate)])

    def test_29_legacy_fee0_method_mutation_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-root"]
        helper = self.function_by_suffix(context, "Pool#feeGrowthGlobal0X128")
        self.assert_wat_rejected(context, [(helper.name, lambda lines, _context: self.replace(lines, 2, "i32.const 0"))])

    def test_30_legacy_fee0_signature_mutation_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-qmrv"]
        helper = self.function_by_suffix(context, "Pool#feeGrowthGlobal0X128")
        self.assert_wat_rejected(context, [(helper.name, lambda lines, _context: self.replace(lines, 3, "i32.const 0"))])

    def test_31_legacy_fee1_result_index_mutation_is_rejected(self) -> None:
        context = self.by_profile["legacy-base-root"]
        helper = self.function_by_suffix(context, "Pool#feeGrowthGlobal1X128")
        self.assert_wat_rejected(context, [(helper.name, lambda lines, _context: self.replace(lines, 6, "i32.const 1"))])

    def test_32_legacy_misleading_fee0_setter_key_mutation_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-root"]
        helper = self.function_by_suffix(context, "PoolDayData#set:feeGrowthGlobal0X128")
        self.assert_wat_rejected(context, [(helper.name, lambda lines, _context: self.replace(lines, 2, "i32.const 0"))])

    def test_33_legacy_misleading_fee1_setter_receiver_mutation_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-qmrv"]
        helper = self.function_by_suffix(context, "PoolDayData#set:feeGrowthGlobal1X128")
        self.assert_wat_rejected(context, [(helper.name, lambda lines, _context: self.replace(lines, 1, "i32.const 0"))])

    def test_34_legacy_fee0_result_local_crosswire_is_rejected(self) -> None:
        context = self.by_profile["legacy-base-root"]
        self.assert_wat_rejected(context, [self.handler_mutation(context, 487, "local.set $p0")])

    def test_35_legacy_call_order_mutation_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-root"]
        target = VERIFIER.call_name(context["handler"].lines[489])
        assert target is not None
        self.assert_wat_rejected(context, [self.handler_mutation(context, 486, f"call ${target}")])

    def test_36_legacy_pool_save_removal_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-qmrv"]
        self.assert_wat_rejected(context, [self.handler_mutation(context, 699, "drop")])

    def test_37_legacy_nontry_null_trap_fallthrough_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-root"]
        helper = self.function_by_suffix(context, "ethereum.SmartContract#call")
        self.assert_wat_rejected(context, [(helper.name, lambda lines, _context: self.replace(lines, 24, "nop"))])

    def test_38_reachable_hidden_direct_write_is_rejected(self) -> None:
        context = self.by_profile["legacy-base-root"]
        helper = self.function_by_suffix(context, "Value.fromBigInt")

        def mutate(lines: list[str], _context: dict[str, Any]) -> None:
            self.insert(lines, 10, ["i32.const 0", "i32.const 0", "i32.store"])

        self.assert_wat_rejected(context, [(helper.name, mutate)])

    def test_39_pool_store_target_mutation_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-root"]
        helper = self.function_by_suffix(context, "schema/Pool#save")
        key = next(index for index, line in enumerate(helper.lines) if VERIFIER.decoded_constant(line, context["memory"]) == "Pool")
        self.assert_wat_rejected(context, [(helper.name, lambda lines, _context: self.replace(lines, key, "i32.const 0"))])

    def test_40_truth_flag_promotion_is_rejected(self) -> None:
        mutated = copy.deepcopy(self.contract)
        mutated["truth_boundary"]["pool_swap_fee_growth_output_implemented"] = True
        self.assert_contract_rejected(mutated)

    def test_41_cumulative_count_promotion_is_rejected(self) -> None:
        mutated = copy.deepcopy(self.contract)
        mutated["scope"]["cumulative_selected_field_count"] = 38
        self.assert_contract_rejected(mutated)

    def test_42_mapping_proof_overpromotion_is_rejected(self) -> None:
        mutated = copy.deepcopy(self.contract)
        mutated["mapping_proofs"][0]["complete_pool_swap_handler_semantics"] = True
        self.assert_contract_rejected(mutated)

    def test_43_selected_persistence_promotion_is_rejected(self) -> None:
        mutated = copy.deepcopy(self.contract)
        mutated["segments"][0]["semantic_surface"]["selected_persistence_proven"] = True
        self.assert_contract_rejected(mutated)

    def test_44_source_digest_mutation_is_rejected(self) -> None:
        mutated = copy.deepcopy(self.contract)
        mutated["source_contracts"]["segment_writer_matrix"]["raw_sha256"] = "0" * 64
        self.assert_contract_rejected(mutated)

    def test_45_pairwise_diff_mutation_is_rejected(self) -> None:
        mutated = copy.deepcopy(self.contract)
        mutated["segment_diffs"].pop()
        self.assert_contract_rejected(mutated)

    def test_46_duplicate_json_keys_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pool-swap-fee-growth-json-") as temporary:
            path = Path(temporary) / "duplicate.json"
            path.write_text('{"format_version":1,"format_version":1}\n')
            with self.assertRaises(self.expected_errors):
                VERIFIER.load_json_strict(path)

    def test_47_modern_nonempty_call_arguments_are_rejected(self) -> None:
        context = self.by_profile["modern-base"]
        self.assert_wat_rejected(context, [self.handler_mutation(context, 1711, "i32.const 1")])

    def test_48_value_to_bigint_kind_drift_is_rejected(self) -> None:
        context = self.by_profile["modern-mainnet"]
        helper = self.function_by_suffix(context, "ethereum.Value#toBigInt")
        self.assert_wat_rejected(context, [(helper.name, lambda lines, _context: self.replace(lines, 10, "i32.const 5"))])

    def test_49_branch_between_second_setter_and_save_is_rejected(self) -> None:
        context = self.by_profile["modern-base"]

        def mutate(lines: list[str], _context: dict[str, Any]) -> None:
            self.insert(lines, 1764, ["block $fee_growth_test", "br $fee_growth_test", "end"])

        self.assert_wat_rejected(context, [(context["handler"].name, mutate)])

    def test_50_excluded_pool_return_mutation_is_rejected(self) -> None:
        context = self.by_profile["modern-mainnet"]
        self.assert_wat_rejected(context, [self.handler_mutation(context, 48, "nop")])

    def test_51_flash_dependency_digest_mutation_is_rejected(self) -> None:
        mutated = copy.deepcopy(self.contract)
        mutated["source_contracts"]["pool_flash"]["raw_sha256"] = "f" * 64
        self.assert_contract_rejected(mutated)


if __name__ == "__main__":
    unittest.main()
