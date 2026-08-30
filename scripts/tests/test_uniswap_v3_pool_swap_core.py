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
VERIFIER_PATH = ROOT / "scripts/verify-uniswap-v3-pool-swap-core.py"
SPEC = importlib.util.spec_from_file_location("uniswap_v3_pool_swap_core_v1", VERIFIER_PATH)
assert SPEC is not None and SPEC.loader is not None
VERIFIER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VERIFIER
SPEC.loader.exec_module(VERIFIER)

Mutation = tuple[str, Callable[[list[str], dict[str, Any]], None]]


class PoolSwapCoreSemanticsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sources = VERIFIER.load_sources(ROOT, recompute_wat=True)
        cls.contract = VERIFIER.verify_contract(ROOT, sources=cls.sources, recompute_wat=False)
        cls.contexts = cls.sources["pool_wat_contexts"]
        cls.by_profile = {context["profile"]["profile_id"]: context for context in cls.contexts.values()}
        wasm2wat = next(iter(cls.contexts.values()))["wasm2wat"]
        cls.wasm2wat = VERIFIER.INITIALIZE.resolve_tool(wasm2wat, "wasm2wat")
        cls.wat2wasm = VERIFIER.INITIALIZE.resolve_tool(wasm2wat.with_name("wat2wasm"), "wat2wasm")
        cls.expected_errors = tuple(dict.fromkeys((VERIFIER.VerificationError, VERIFIER.MINT.VerificationError, VERIFIER.INITIALIZE.VerificationError, VERIFIER.POOL_RUNTIME.VerificationError, VERIFIER.V2.VerificationError, VERIFIER.WRITER.VerificationError)))

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
        with tempfile.TemporaryDirectory(prefix="pool-swap-core-wat-") as temporary:
            wat = Path(temporary) / "fixture.wat"
            wasm = Path(temporary) / "fixture.wasm"
            wat.write_text("\n".join(wat_lines) + "\n")
            compiled = subprocess.run([str(self.wat2wasm), "--debug-names", str(wat), "-o", str(wasm)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            regenerated = VERIFIER.WRITER.run_wasm2wat(self.wasm2wat, wasm).decode()
        memory, functions, indirect_targets, exports = VERIFIER.WRITER.parse_wat(regenerated)
        handler = VERIFIER.WRITER.resolve_handler(functions, exports, VERIFIER.HANDLER_EXPORT)
        return {**context, "memory": memory, "functions": functions, "indirect_targets": indirect_targets, "exports": exports, "handler": handler, "wat_text": regenerated}

    def assert_wat_rejected(self, context: dict[str, Any], mutations: list[Mutation]) -> None:
        with self.assertRaises(self.expected_errors):
            VERIFIER.prove_pool_swap_core_wat_context(self.roundtrip(context, mutations))

    def assert_contract_rejected(self, mutation: dict[str, Any]) -> None:
        with self.assertRaises(self.expected_errors):
            VERIFIER.verify_contract(ROOT, mutation, sources=self.sources, recompute_wat=False)

    def handler_mutation(self, context: dict[str, Any], index: int, instruction: str) -> Mutation:
        return (context["handler"].name, lambda lines, _context: self.replace(lines, index, instruction))

    def test_01_committed_contract_is_deterministic(self) -> None:
        self.assertEqual(self.contract, VERIFIER.expected_contract_from_sources(self.sources))
        result = subprocess.run([sys.executable, str(VERIFIER_PATH), "--root", str(ROOT)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("8 mappings, 24 segment-field call-flow evidence records, 28 diffs", result.stdout)

    def test_02_scope_counts_remain_exactly_bounded(self) -> None:
        scope = self.contract["scope"]
        self.assertEqual((scope["selected_field_count"], scope["segment_field_call_flow_evidence_count"], scope["cumulative_selected_field_count"], scope["cumulative_residual_field_count"]), (3, 24, 36, 230))

    def test_03_truth_boundary_promotes_only_declared_claims(self) -> None:
        truth = self.contract["truth_boundary"]
        self.assertEqual({key for key, value in truth.items() if value}, set(VERIFIER.TRUE_FLAGS))
        self.assertEqual({key for key, value in truth.items() if not value}, set(VERIFIER.FALSE_FLAGS))
        for key in (
            "bytes_to_hex_host_semantics_rederived",
            "numeric_host_semantics_rederived",
            "graph_store_host_semantics_rederived",
            "imported_host_semantics_rederived",
        ):
            with self.subTest(key=key):
                self.assertIs(truth[key], False)

    def test_04_unmodified_legacy_and_modern_contexts_prove(self) -> None:
        for context in self.contexts.values():
            with self.subTest(profile=context["profile"]["profile_id"]):
                VERIFIER.prove_pool_swap_core_wat_context(self.roundtrip(context, []))

    def test_05_modern_liquidity_index_mutation_is_rejected(self) -> None:
        context = self.by_profile["modern-base"]
        self.assert_wat_rejected(context, [self.handler_mutation(context, 766, "i32.const 4")])

    def test_06_modern_tick_index_mutation_is_rejected(self) -> None:
        context = self.by_profile["modern-mainnet"]
        self.assert_wat_rejected(context, [self.handler_mutation(context, 798, "i32.const 5")])

    def test_07_modern_sqrt_price_index_mutation_is_rejected(self) -> None:
        context = self.by_profile["modern-base"]
        self.assert_wat_rejected(context, [self.handler_mutation(context, 816, "i32.const 5")])

    def test_08_legacy_liquidity_index_mutation_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-root"]
        helper = self.function_by_suffix(context, "Mint__Params#get:amount0")
        self.assert_wat_rejected(context, [(helper.name, lambda lines, _context: self.replace(lines, 4, "i32.const 4"))])

    def test_09_legacy_tick_index_mutation_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-qmrv"]
        helper = self.function_by_suffix(context, "Swap__Params#get:tick")
        self.assert_wat_rejected(context, [(helper.name, lambda lines, _context: self.replace(lines, 4, "i32.const 5"))])

    def test_10_legacy_sqrt_price_index_mutation_is_rejected(self) -> None:
        context = self.by_profile["legacy-base-root"]
        helper = self.function_by_suffix(context, "Mint__Params#get:amount")
        self.assert_wat_rejected(context, [(helper.name, lambda lines, _context: self.replace(lines, 4, "i32.const 6"))])

    def test_11_modern_liquidity_key_mutation_is_rejected(self) -> None:
        context = self.by_profile["modern-base"]
        self.assert_wat_rejected(context, [self.handler_mutation(context, 782, "i32.const 0")])

    def test_12_modern_sqrt_price_key_mutation_is_rejected(self) -> None:
        context = self.by_profile["modern-mainnet"]
        self.assert_wat_rejected(context, [self.handler_mutation(context, 832, "i32.const 0")])

    def test_13_legacy_misleading_liquidity_setter_key_mutation_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-root"]
        helper = self.function_by_suffix(context, "PoolDayData#set:liquidity")
        self.assert_wat_rejected(context, [(helper.name, lambda lines, _context: self.replace(lines, 2, "i32.const 0"))])

    def test_14_legacy_sqrt_price_setter_key_mutation_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-qmrv"]
        helper = self.function_by_suffix(context, "schema/Pool#set:sqrtPrice")
        self.assert_wat_rejected(context, [(helper.name, lambda lines, _context: self.replace(lines, 2, "i32.const 0"))])

    def test_15_modern_liquidity_receiver_mutation_is_rejected(self) -> None:
        context = self.by_profile["modern-base"]
        self.assert_wat_rejected(context, [self.handler_mutation(context, 781, "i32.const 0")])

    def test_16_modern_tick_receiver_mutation_is_rejected(self) -> None:
        context = self.by_profile["modern-mainnet"]
        self.assert_wat_rejected(context, [self.handler_mutation(context, 794, "i32.const 0")])

    def test_17_legacy_sqrt_price_receiver_mutation_is_rejected(self) -> None:
        context = self.by_profile["legacy-base-root"]
        self.assert_wat_rejected(context, [self.handler_mutation(context, 229, "i32.const 0")])

    def test_18_modern_value_kind_mutation_is_rejected(self) -> None:
        context = self.by_profile["modern-base"]
        self.assert_wat_rejected(context, [self.handler_mutation(context, 776, "i32.const 2")])

    def test_19_modern_value_payload_mutation_is_rejected(self) -> None:
        context = self.by_profile["modern-mainnet"]
        self.assert_wat_rejected(context, [self.handler_mutation(context, 779, "i64.const 0")])

    def test_20_modern_tick_nonzero_conversion_mutation_is_rejected(self) -> None:
        context = self.by_profile["modern-base"]
        def mutate(lines: list[str], _context: dict[str, Any]) -> None:
            indent = lines[802][: len(lines[802]) - len(lines[802].lstrip())]
            lines[802:803] = [f"{indent}drop", f"{indent}i32.const 0"]
        self.assert_wat_rejected(context, [(context["handler"].name, mutate)])

    def test_21_legacy_value_from_bigint_kind_mutation_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-root"]
        helper = self.function_by_suffix(context, "Value.fromBigInt")
        self.assert_wat_rejected(context, [(helper.name, lambda lines, _context: self.replace(lines, 4, "i32.const 2"))])

    def test_22_legacy_tick_integer_conversion_mutation_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-root"]
        helper = self.function_by_suffix(context, "ByteArray.fromI32")
        self.assert_wat_rejected(context, [(helper.name, lambda lines, _context: self.replace(lines, 13, "i32.const 16"))])

    def test_23_modern_required_pool_trap_fallthrough_is_rejected(self) -> None:
        context = self.by_profile["modern-base"]
        def mutate(lines: list[str], _context: dict[str, Any]) -> None:
            indent = lines[40][: len(lines[40]) - len(lines[40].lstrip())]
            lines[40:42] = [f"{indent}drop", f"{indent}drop", f"{indent}drop", f"{indent}drop", f"{indent}nop"]
        self.assert_wat_rejected(context, [(context["handler"].name, mutate)])

    def test_24_modern_two_token_guard_mutation_is_rejected(self) -> None:
        context = self.by_profile["modern-mainnet"]
        def mutate(lines: list[str], _context: dict[str, Any]) -> None:
            indent = lines[62][: len(lines[62]) - len(lines[62].lstrip())]
            lines[62:63] = [f"{indent}drop", f"{indent}drop"]
        self.assert_wat_rejected(context, [(context["handler"].name, mutate)])

    def test_25_excluded_pool_early_return_mutation_is_rejected(self) -> None:
        context = self.by_profile["modern-base"]
        self.assert_wat_rejected(context, [self.handler_mutation(context, 48, "nop")])

    def test_26_bytes_to_hex_operand_boundary_mutation_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-root"]
        self.assert_wat_rejected(context, [self.handler_mutation(context, 8, "nop")])

    def test_27_first_pool_save_receiver_mutation_is_rejected(self) -> None:
        context = self.by_profile["modern-mainnet"]
        self.assert_wat_rejected(context, [self.handler_mutation(context, 1192, "i32.const 0")])

    def test_28_first_pool_save_removal_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-root"]
        self.assert_wat_rejected(context, [self.handler_mutation(context, 334, "drop")])

    def test_29_second_pool_save_removal_is_rejected(self) -> None:
        context = self.by_profile["modern-base"]
        self.assert_wat_rejected(context, [self.handler_mutation(context, 2602, "drop")])

    def test_30_third_pool_save_insertion_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-qmrv"]
        target = VERIFIER.call_name(context["handler"].lines[334])
        assert target is not None
        def mutate(lines: list[str], _context: dict[str, Any]) -> None:
            self.insert(lines, 335, ["local.get $l1", f"call ${target}"])
        self.assert_wat_rejected(context, [(context["handler"].name, mutate)])

    def test_31_reachable_hidden_direct_write_is_rejected(self) -> None:
        context = self.by_profile["legacy-base-root"]
        helper = self.function_by_suffix(context, "Value.fromBigInt")
        def mutate(lines: list[str], _context: dict[str, Any]) -> None:
            self.insert(lines, 10, ["i32.const 0", "i32.const 0", "i32.store"])
        self.assert_wat_rejected(context, [(helper.name, mutate)])

    def test_32_reachable_runtime_helper_body_mutation_is_rejected(self) -> None:
        context = self.by_profile["modern-base"]
        helper = self.function_by_suffix(context, "String.__eq")
        self.assert_wat_rejected(context, [(helper.name, lambda lines, _context: self.insert(lines, len(lines) - 1, ["nop"]))])

    def test_33_pool_store_target_mutation_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-root"]
        helper = self.function_by_suffix(context, "schema/Pool#save")
        key = next(index for index, line in enumerate(helper.lines) if VERIFIER.decoded_constant(line, context["memory"]) == "Pool")
        self.assert_wat_rejected(context, [(helper.name, lambda lines, _context: self.replace(lines, key, "i32.const 0"))])

    def test_34_truth_flag_promotion_is_rejected(self) -> None:
        mutated = copy.deepcopy(self.contract)
        mutated["truth_boundary"]["production_ready"] = True
        self.assert_contract_rejected(mutated)

    def test_35_cumulative_count_promotion_is_rejected(self) -> None:
        mutated = copy.deepcopy(self.contract)
        mutated["scope"]["cumulative_selected_field_count"] = 39
        self.assert_contract_rejected(mutated)

    def test_36_mapping_proof_mutation_is_rejected(self) -> None:
        mutated = copy.deepcopy(self.contract)
        mutated["mapping_proofs"][0]["selected_handler_structural_wat_projection_complete"] = True
        self.assert_contract_rejected(mutated)

    def test_37_segment_field_completion_mutation_is_rejected(self) -> None:
        mutated = copy.deepcopy(self.contract)
        mutated["segments"][0]["semantic_surface"]["fields"][0]["complete_selected_handler_projection"] = True
        self.assert_contract_rejected(mutated)

    def test_38_source_digest_mutation_is_rejected(self) -> None:
        mutated = copy.deepcopy(self.contract)
        mutated["source_contracts"]["pool_mint"]["raw_sha256"] = "0" * 64
        self.assert_contract_rejected(mutated)

    def test_39_pairwise_diff_mutation_is_rejected(self) -> None:
        mutated = copy.deepcopy(self.contract)
        mutated["segment_diffs"].pop()
        self.assert_contract_rejected(mutated)

    def test_40_duplicate_json_keys_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pool-swap-core-json-") as temporary:
            path = Path(temporary) / "duplicate.json"
            path.write_text('{"format_version":1,"format_version":1}\n')
            with self.assertRaises(self.expected_errors):
                VERIFIER.load_json_strict(path)


if __name__ == "__main__":
    unittest.main()
