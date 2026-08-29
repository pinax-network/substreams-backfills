from __future__ import annotations

import copy
import importlib.util
import shutil
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VERIFIER_PATH = ROOT / "scripts/verify-uniswap-v3-modern-factory-guard.py"
SPEC = importlib.util.spec_from_file_location("uniswap_v3_modern_factory_guard", VERIFIER_PATH)
assert SPEC is not None and SPEC.loader is not None
VERIFIER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VERIFIER
SPEC.loader.exec_module(VERIFIER)


class ModernFactoryGuardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contexts = VERIFIER.load_contexts(ROOT)
        cls.proofs = [VERIFIER.prove_modern_guard(context) for context in cls.contexts]
        cls.contract = VERIFIER.load_json(ROOT / VERIFIER.CONTRACT_PATH)
        cls.modern = next(
            context for context in cls.contexts if context["profile"]["profile_id"] == "modern-mainnet"
        )
        cls.handler = cls.modern["handler"]
        cls.original_lines = list(cls.handler.lines)
        artifact = ROOT / f"uniswap-v3/graft-ancestry/v1/artifacts/{cls.modern['cid']}"
        executable = VERIFIER.WRITER.resolve_wasm2wat(None)
        cls.full_wat = VERIFIER.WRITER.run_wasm2wat(executable, artifact).decode()
        cls.wat2wasm = shutil.which("wat2wasm")
        if cls.wat2wasm is None:
            raise unittest.SkipTest("wat2wasm is required for valid-mutation fixtures")
        version = subprocess.run(
            [cls.wat2wasm, "--version"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if version.returncode != 0 or version.stdout.strip() != VERIFIER.WRITER.WABT_VERSION:
            raise unittest.SkipTest("checksum-pinned WABT 1.0.35 wat2wasm is required")

    @staticmethod
    def set_normalized(lines: list[str], index: int, value: str) -> None:
        indent = lines[index][: len(lines[index]) - len(lines[index].lstrip())]
        lines[index] = f"{indent}{value}"

    def assert_valid_wat_mutation_rejected(self, label: str, mutate: object) -> None:
        lines = list(self.original_lines)
        mutate(lines, self.modern)
        original_payload = self.handler.payload.decode()
        self.assertEqual(self.full_wat.count(original_payload), 1, label)
        changed_payload = "\n".join(lines) + "\n"
        changed_wat = self.full_wat.replace(original_payload, changed_payload, 1)
        validation = subprocess.run(
            [self.wat2wasm, "/dev/stdin", "-o", "/dev/null", "--debug-names"],
            input=changed_wat.encode(),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(
            validation.returncode,
            0,
            f"{label} fixture must remain WAT-valid: {validation.stderr.decode('utf-8', 'replace')}",
        )
        memory, functions, _indirect, exports = VERIFIER.WRITER.parse_wat(changed_wat)
        handler = VERIFIER.WRITER.resolve_handler(functions, exports, "handlePoolCreated")
        changed = {**self.modern, "memory": memory, "functions": functions, "handler": handler}
        with self.assertRaises(VERIFIER.VerificationError, msg=label):
            VERIFIER.prove_modern_guard(changed)

    def test_committed_contract_is_the_deterministic_projection(self) -> None:
        self.assertEqual(self.contract, VERIFIER.expected_contract(ROOT))
        self.assertEqual(self.contract, VERIFIER.verify_contract(ROOT))

    def test_scope_closes_only_the_two_modern_guard_paths(self) -> None:
        scope = self.contract["scope"]
        self.assertEqual(
            (
                scope["factory_upstream_path_count"],
                scope["closed_before_this_supplement"],
                scope["newly_closed_modern_guard_paths"],
                scope["cumulative_closed_after_this_supplement"],
                scope["residual_after_this_supplement"],
            ),
            (18, 4, 2, 6, 12),
        )
        truth = self.contract["truth_boundary"]
        self.assertEqual({key for key, value in truth.items() if value}, VERIFIER.TRUE_FLAGS)
        self.assertEqual({key for key, value in truth.items() if not value}, VERIFIER.FALSE_FLAGS)
        self.assertTrue(all(type(value) is bool for value in truth.values()))

    def test_each_exact_modern_guard_has_one_equal_and_twenty_one_mismatch_paths(self) -> None:
        self.assertEqual({proof["profile_id"] for proof in self.proofs}, {"modern-base", "modern-mainnet"})
        for proof in self.proofs:
            self.assertTrue(proof["event_pool_to_comparison_to_early_return_machine_proven"])
            equality = proof["equality_and_return"]
            self.assertEqual(equality["early_return_path_count"], 1)
            self.assertEqual(equality["normal_continuation_path_count"], 21)
            self.assertEqual(len(equality["mismatch_paths"]), 21)
            self.assertEqual(equality["equal_path"]["compared_byte_indexes"], list(range(20)))
            literal = proof["excluded_pool_value_flow"]
            self.assertEqual(literal["byte_array_length"], 20)
            self.assertEqual(len(literal["loop_iterations"]), 20)
            self.assertEqual(literal["byte_array_hex"], VERIFIER.EXCLUDED_POOL[2:])
            self.assertEqual(proof["structured_control"]["node_count"], 10)
            self.assertEqual(len(proof["ssa"]["versions"]), 8)

    def test_six_reviewed_fail_open_counterexamples_are_valid_and_rejected(self) -> None:
        def invert_loop_condition(lines: list[str], _context: dict[str, object]) -> None:
            self.set_normalized(lines, 125, "i32.lt_s")

        def use_parser_index_as_loop_bound(lines: list[str], _context: dict[str, object]) -> None:
            self.set_normalized(lines, 124, "local.get $l4")

        def compare_byte_zero_repeatedly(lines: list[str], _context: dict[str, object]) -> None:
            self.set_normalized(lines, 129, "i32.const 0")
            self.set_normalized(lines, 132, "i32.const 0")

        def remove_loop_backedge(lines: list[str], _context: dict[str, object]) -> None:
            self.set_normalized(lines, 141, "nop")

        def increment_wrong_local(lines: list[str], _context: dict[str, object]) -> None:
            self.set_normalized(lines, 140, "local.set $l4")

        def bypass_all_comparisons(lines: list[str], _context: dict[str, object]) -> None:
            indent = lines[111][: len(lines[111]) - len(lines[111].lstrip())]
            lines[111:111] = [f"{indent}i32.const 0", f"{indent}if"]
            normal_true = next(
                index
                for index in range(130, len(lines) - 2)
                if VERIFIER.normalized(lines[index]) == "i32.const 1"
                and VERIFIER.normalized(lines[index + 1]) == "end"
                and VERIFIER.normalized(lines[index + 2]).startswith("if ")
            )
            lines.insert(normal_true, f"{indent}end")

        mutations = [
            ("inverted byte-loop condition", invert_loop_condition),
            ("parser index substituted for comparison index", use_parser_index_as_loop_bound),
            ("byte zero compared repeatedly", compare_byte_zero_repeatedly),
            ("byte-loop backedge removed", remove_loop_backedge),
            ("wrong loop-carried local incremented", increment_wrong_local),
            ("structured control bypasses all comparisons", bypass_all_comparisons),
        ]
        for label, mutate in mutations:
            with self.subTest(label=label):
                self.assert_valid_wat_mutation_rejected(label, mutate)

    def test_operand_branch_literal_heap_local_and_call_mutations_are_valid_and_rejected(self) -> None:
        def self_comparison(lines: list[str], _context: dict[str, object]) -> None:
            self.set_normalized(lines, 114, "local.get $l1")
            self.set_normalized(lines, 131, "local.get $l1")

        def invert_final_branch(lines: list[str], _context: dict[str, object]) -> None:
            indent = lines[146][: len(lines[146]) - len(lines[146].lstrip())]
            lines.insert(146, f"{indent}i32.eqz")

        def substitute_active_literal(lines: list[str], context: dict[str, object]) -> None:
            wrong = next(
                VERIFIER.normalized(line)
                for line in lines[149:]
                if VERIFIER.V2.decoded_wat_constant(line, context["memory"]) == "Factory"
            )
            self.set_normalized(lines, 63, wrong)

        def mutate_excluded_heap(lines: list[str], _context: dict[str, object]) -> None:
            indent = lines[111][: len(lines[111]) - len(lines[111].lstrip())]
            lines[111:111] = [f"{indent}local.get $l5", f"{indent}i32.const 0", f"{indent}i32.store"]

        def mutate_event_local(lines: list[str], _context: dict[str, object]) -> None:
            indent = lines[20][: len(lines[20]) - len(lines[20].lstrip())]
            lines[20:20] = [f"{indent}i32.const 0", f"{indent}local.set $l1"]

        def change_call_target(lines: list[str], _context: dict[str, object]) -> None:
            self.set_normalized(
                lines,
                18,
                "call $~lib/@graphprotocol/graph-ts/common/conversion/typeConversion.bytesToHex",
            )

        mutations = [
            ("pool/excluded self-comparison", self_comparison),
            ("equal branch inverted", invert_final_branch),
            ("active excluded literal substituted", substitute_active_literal),
            ("excluded heap changed after construction", mutate_excluded_heap),
            ("event pool local overwritten", mutate_event_local),
            ("event conversion call target changed", change_call_target),
        ]
        for label, mutate in mutations:
            with self.subTest(label=label):
                self.assert_valid_wat_mutation_rejected(label, mutate)

    def test_extra_return_select_and_call_indirect_are_valid_and_rejected(self) -> None:
        def extra_return(lines: list[str], _context: dict[str, object]) -> None:
            indent = lines[20][: len(lines[20]) - len(lines[20].lstrip())]
            lines.insert(20, f"{indent}return")

        def inserted_select(lines: list[str], _context: dict[str, object]) -> None:
            indent = lines[111][: len(lines[111]) - len(lines[111].lstrip())]
            lines[111:111] = [
                f"{indent}i32.const 7",
                f"{indent}i32.const 9",
                f"{indent}i32.const 0",
                f"{indent}select",
                f"{indent}drop",
            ]

        def inserted_call_indirect(lines: list[str], _context: dict[str, object]) -> None:
            indent = lines[111][: len(lines[111]) - len(lines[111].lstrip())]
            lines[111:111] = [
                f"{indent}i32.const 0",
                f"{indent}i32.const 0",
                f"{indent}i32.const 0",
                f"{indent}i32.const 1",
                f"{indent}call_indirect $0 (type $t3)",
                f"{indent}drop",
            ]

        for label, mutate in (
            ("extra early return", extra_return),
            ("unmodeled select", inserted_select),
            ("unmodeled call_indirect", inserted_call_indirect),
        ):
            with self.subTest(label=label):
                self.assert_valid_wat_mutation_rejected(label, mutate)

    def test_self_rehashed_contract_cannot_promote_residual_gates(self) -> None:
        mutations: list[tuple[str, dict[str, object]]] = []
        for gate in sorted(VERIFIER.FALSE_FLAGS):
            changed = copy.deepcopy(self.contract)
            changed["truth_boundary"][gate] = True
            mutations.append((f"promoted residual gate {gate}", changed))
        changed_scope = copy.deepcopy(self.contract)
        changed_scope["scope"]["residual_after_this_supplement"] = 0
        mutations.append(("promoted residual path count", changed_scope))
        changed_proof = copy.deepcopy(self.contract)
        changed_proof["modern_factory_guard_proofs"][0]["equality_and_return"]["early_return_path_count"] = 2
        mutations.append(("self-rehashed equality proof", changed_proof))
        for label, changed in mutations:
            with self.subTest(label=label):
                with self.assertRaises(VERIFIER.VerificationError):
                    VERIFIER.verify_contract(ROOT, changed)


if __name__ == "__main__":
    unittest.main()
