from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
VERIFIER_PATH = ROOT / "scripts/verify-uniswap-v3-modern-factory-static.py"
SPEC = importlib.util.spec_from_file_location(
    "uniswap_v3_modern_factory_static_for_runtime_tests", VERIFIER_PATH
)
assert SPEC is not None and SPEC.loader is not None
VERIFIER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VERIFIER
SPEC.loader.exec_module(VERIFIER)
RUNTIME = VERIFIER.RUNTIME


class SharedRuntimeError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SharedRuntimeError(message)


@dataclass(frozen=True)
class FakeFunction:
    name: str
    lines: tuple[str, ...]


class WatRuntimeFoundationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contexts = VERIFIER.load_contexts(ROOT)

    @staticmethod
    def module_context() -> tuple[dict[str, Any], FakeFunction, Any]:
        start = FakeFunction("~start", ("global.set $critical",))
        context = {
            "cid": "fixture",
            "module_text": "\n".join(
                (
                    "(module",
                    "  (global $critical (mut i32) (i32.const 0))",
                    ")",
                )
            ),
            "exports": {"_start": "~start"},
            "functions": {"~start": start},
        }
        spec = RUNTIME.ModuleStateSpec(
            initializer_export="_start",
            initializer_function="~start",
            mutable_globals=("$critical",),
            expected_global_set_inventory={"$critical": [["~start", 0]]},
        )
        return context, start, spec

    def test_module_state_algorithm_accepts_only_the_exact_closed_inventory(self) -> None:
        context, start, spec = self.module_context()
        proof = RUNTIME.prove_module_state_invariants(
            context,
            start,
            spec,
            require=require,
            normalized=lambda line: line.strip().removesuffix(")"),
            canonical_sha256=lambda _value: "fixture-digest",
        )
        self.assertEqual(
            proof["complete_global_set_inventory"],
            {"$critical": [["~start", 0]]},
        )
        self.assertTrue(
            proof["critical_global_initializers_and_all_writers_machine_proven"]
        )

    def test_module_state_algorithm_rejects_export_start_initializer_and_writer_drift(self) -> None:
        base, start, spec = self.module_context()
        cases = (
            ({**base, "exports": {"_start": "other"}}, "export binding drift"),
            (
                {**base, "module_text": base["module_text"].replace(
                    "(module", "(module\n  (start $~start)", 1
                )},
                "unexpected native WebAssembly start section",
            ),
            (
                {**base, "module_text": base["module_text"].replace(
                    "(i32.const 0)", "(i32.const 1)", 1
                )},
                "zero initializer drift",
            ),
            (
                {**base, "functions": {
                    "~start": FakeFunction(
                        "~start", ("global.set $critical", "global.set $critical")
                    )
                }},
                "writer inventory drift",
            ),
        )
        for changed, expected in cases:
            with self.subTest(expected=expected):
                with self.assertRaisesRegex(SharedRuntimeError, expected):
                    RUNTIME.prove_module_state_invariants(
                        changed,
                        start,
                        spec,
                        require=require,
                        normalized=lambda line: line.strip().removesuffix(")"),
                        canonical_sha256=lambda _value: "fixture-digest",
                    )

    def test_direct_memory_classifier_fails_closed_over_writer_families(self) -> None:
        normalize = lambda line: line.strip().removesuffix(")")
        for instruction in (
            "i32.store",
            "f64.store align=2",
            "v128.store64_lane 1",
            "i64.atomic.rmw16.cmpxchg_u",
            "memory.copy",
            "memory.init 0",
        ):
            with self.subTest(instruction=instruction):
                self.assertTrue(RUNTIME.is_direct_memory_write(instruction, normalize))
        for instruction in ("i32.load", "memory.grow", "call $index/store.set"):
            with self.subTest(instruction=instruction):
                self.assertFalse(RUNTIME.is_direct_memory_write(instruction, normalize))

    def test_modern_collection_algorithm_rejects_a_rehashed_setter_noop(self) -> None:
        context = self.contexts[0]
        typed_set = VERIFIER.function_by_suffix(context, VERIFIER.TYPED_MAP_SET_CALL)
        changed_lines = list(typed_set.lines)
        indent = changed_lines[36][: len(changed_lines[36]) - len(changed_lines[36].lstrip())]
        changed_lines[36] = f"{indent}local.get $p1"
        changed_function = VERIFIER.WRITER.WatFunction(
            typed_set.name,
            typed_set.start_line,
            tuple(changed_lines),
            typed_set.function_index,
        )
        changed = {
            **context,
            "functions": {**context["functions"], typed_set.name: changed_function},
        }
        with self.assertRaisesRegex(
            VERIFIER.VerificationError,
            "TypedMap#set key/value/entry/push operand drift",
        ):
            RUNTIME.prove_modern_collection_capsule(
                changed, VERIFIER.runtime_ops(), VERIFIER.MODERN_COLLECTION_SPEC
            )

    def test_modern_indexed_collection_algorithm_rejects_get_result_drift(self) -> None:
        context = self.contexts[0]
        typed_get = VERIFIER.function_by_suffix(context, VERIFIER.TYPED_MAP_GET_CALL)
        changed_lines = list(typed_get.lines)
        index = next(
            index
            for index, line in enumerate(changed_lines)
            if VERIFIER.normalized(line) == "i32.load offset=4"
        )
        indent = changed_lines[index][
            : len(changed_lines[index]) - len(changed_lines[index].lstrip())
        ]
        changed_lines[index] = f"{indent}i32.load"
        changed_function = VERIFIER.WRITER.WatFunction(
            typed_get.name,
            typed_get.start_line,
            tuple(changed_lines),
            typed_get.function_index,
        )
        changed = {
            **context,
            "functions": {**context["functions"], typed_get.name: changed_function},
        }
        with self.assertRaisesRegex(
            VERIFIER.VerificationError,
            "TypedMap#get receiver/key/ordered-result drift",
        ):
            RUNTIME.prove_modern_collection_capsule(
                changed, VERIFIER.runtime_ops(), VERIFIER.MODERN_COLLECTION_SPEC
            )

    def test_only_aggregate_collection_capsule_is_public_and_equality_is_required(self) -> None:
        self.assertFalse(hasattr(RUNTIME, "prove_modern_allocator_identity"))
        self.assertFalse(
            hasattr(RUNTIME, "prove_modern_typed_map_collection_runtime")
        )
        self.assertFalse(hasattr(RUNTIME, "prove_modern_indexed_collection_access"))
        context = self.contexts[0]
        proof = RUNTIME.prove_modern_collection_capsule(
            context, VERIFIER.runtime_ops(), VERIFIER.MODERN_COLLECTION_SPEC
        )
        self.assertTrue(proof["modern_collection_capsule_structurally_closed"])
        self.assertTrue(
            proof["typed_map_collection_runtime"][
                "collection_mutation_chain_structurally_closed"
            ]
        )
        bad_spec = replace(
            VERIFIER.MODERN_COLLECTION_SPEC,
            string_eq_body_sha256="0" * 64,
        )
        with self.assertRaisesRegex(
            VERIFIER.VerificationError,
            "retained String.__eq primitive body drift",
        ):
            RUNTIME.prove_modern_collection_capsule(
                context, VERIFIER.runtime_ops(), bad_spec
            )

    def test_divergent_candidate_root_runtime_is_never_executed_or_certified(self) -> None:
        marker = "DIVERGENT_CANDIDATE_RUNTIME_EXECUTED"
        divergent_runtime = f'raise RuntimeError("{marker}")\n'
        for write in (False, True):
            with self.subTest(write=write), tempfile.TemporaryDirectory(
                prefix="uniswap-v3-divergent-runtime-root-"
            ) as directory:
                candidate = Path(directory)
                runtime_path = candidate / VERIFIER.RUNTIME_SOURCE_PATH
                runtime_path.parent.mkdir(parents=True)
                runtime_path.write_text(divergent_runtime)
                command = [
                    sys.executable,
                    str(VERIFIER_PATH),
                    "--root",
                    str(candidate),
                ]
                if write:
                    command.append("--write")
                result = subprocess.run(
                    command,
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                output = result.stdout + result.stderr
                self.assertEqual(result.returncode, 1, output)
                self.assertIn(
                    "candidate-root shared WAT runtime bytes differ from the exact imported runtime bytes",
                    output,
                )
                self.assertNotIn(marker, output)
                self.assertFalse(
                    (candidate / VERIFIER.CONTRACT_PATH).exists(),
                    "--write must reject before creating a candidate contract",
                )


if __name__ == "__main__":
    unittest.main()
