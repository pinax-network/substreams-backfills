from __future__ import annotations

import copy
import hashlib
import importlib.util
import shutil
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[2]
VERIFIER_PATH = ROOT / "scripts/verify-uniswap-v3-pool-runtime.py"
SPEC = importlib.util.spec_from_file_location("uniswap_v3_pool_runtime", VERIFIER_PATH)
assert SPEC is not None and SPEC.loader is not None
VERIFIER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VERIFIER
SPEC.loader.exec_module(VERIFIER)

Mutator = Callable[[list[str], dict[str, Any]], None]
ModuleMutator = Callable[[str], str]


class ModernPoolRuntimeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.executable = VERIFIER.resolve_wasm2wat(None)
        cls.contexts = {
            spec.profile_id: VERIFIER.load_context(ROOT, spec, cls.executable)
            for spec in VERIFIER.PROFILE_SPECS
        }
        cls.contract = VERIFIER.load_json(ROOT / VERIFIER.CONTRACT_PATH)
        cls.wat2wasm = shutil.which("wat2wasm")
        if cls.wat2wasm is None:
            raise unittest.SkipTest("wat2wasm is required for valid-WAT mutations")
        version = subprocess.run(
            [cls.wat2wasm, "--version"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if version.returncode != 0 or version.stdout.strip() != VERIFIER.WABT_VERSION:
            raise unittest.SkipTest("checksum-pinned WABT 1.0.35 wat2wasm is required")

    @staticmethod
    def set_normalized(lines: list[str], index: int, value: str) -> None:
        indent = lines[index][: len(lines[index]) - len(lines[index].lstrip())]
        lines[index] = f"{indent}{value}"

    @staticmethod
    def insert_normalized(lines: list[str], index: int, values: list[str]) -> None:
        indent = lines[index][: len(lines[index]) - len(lines[index].lstrip())]
        lines[index:index] = [f"{indent}{value}" for value in values]

    @staticmethod
    def selector(suffix: str) -> Callable[[dict[str, Any]], Any]:
        return lambda context: VERIFIER.function_by_suffix(context, suffix)

    def assert_valid_wat_mutation_rejected(
        self,
        label: str,
        selector: Callable[[dict[str, Any]], Any],
        mutate: Mutator,
        expected_error: str,
        *,
        profile: str = "modern-mainnet",
        mutate_module: ModuleMutator | None = None,
        refresh_start_authority: bool = False,
        refresh_initialized_data_authority: bool = False,
    ) -> None:
        base = self.contexts[profile]
        function = selector(base)
        lines = list(function.lines)
        mutate(lines, base)
        original = function.payload.decode()
        wat = base["module_text"]
        self.assertEqual(wat.count(original), 1, label)
        changed_wat = wat.replace(original, "\n".join(lines) + "\n", 1)
        if mutate_module is not None:
            changed_wat = mutate_module(changed_wat)
        with tempfile.TemporaryDirectory(prefix="modern-pool-runtime-wat-") as directory:
            wasm = Path(directory) / "mutation.wasm"
            validation = subprocess.run(
                [self.wat2wasm, "/dev/stdin", "-o", str(wasm), "--debug-names"],
                input=changed_wat.encode(),
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(
                validation.returncode,
                0,
                f"{label} must remain valid WAT: {validation.stderr.decode('utf-8', 'replace')}",
            )
        functions, exports = VERIFIER.parse_wat(changed_wat)
        changed = {
            **base,
            "functions": functions,
            "exports": exports,
            "module_text": changed_wat,
            "initialized_data": VERIFIER.initialized_data_inventory(changed_wat),
        }
        if refresh_start_authority:
            changed_start = VERIFIER.function_by_suffix(changed, "~start")
            changed["spec"] = replace(
                base["spec"],
                start_line_count=len(changed_start.lines),
                start_body_sha256=hashlib.sha256(changed_start.payload).hexdigest(),
            )
        if refresh_initialized_data_authority:
            changed["spec"] = replace(
                changed["spec"],
                initialized_data_end=changed["initialized_data"][
                    "maximum_end_exclusive"
                ],
                initialized_data_segment_count=changed["initialized_data"][
                    "segment_count"
                ],
            )
        with self.assertRaises(VERIFIER.VerificationError, msg=label) as caught:
            VERIFIER.prove_pool_runtime_context(changed)
        self.assertIn(expected_error, str(caught.exception), label)

    def test_committed_contract_is_the_deterministic_projection(self) -> None:
        self.assertEqual(self.contract, VERIFIER.expected_contract(ROOT))
        self.assertEqual(self.contract, VERIFIER.verify_contract(ROOT))
        result = subprocess.run(
            [sys.executable, str(VERIFIER_PATH), "--root", str(ROOT)],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_scope_selects_exactly_the_two_modern_artifact_tuples(self) -> None:
        observed = {
            tuple(proof["artifact_selection_tuple"])
            for proof in self.contract["modern_pool_runtime_proofs"]
        }
        self.assertEqual(observed, VERIFIER.EXPECTED_ARTIFACT_TUPLES)
        self.assertEqual(self.contract["scope"]["newly_closed_modern_runtime_profile_count"], 2)
        self.assertEqual(self.contract["scope"]["residual_legacy_runtime_profile_count"], 6)
        self.assertEqual(self.contract["scope"]["handler_semantics_added"], [])

    def test_runtime_truth_boundary_preserves_every_residual_gate(self) -> None:
        truth = self.contract["truth_boundary"]
        self.assertEqual({key for key, value in truth.items() if value}, VERIFIER.TRUE_FLAGS)
        self.assertEqual({key for key, value in truth.items() if not value}, VERIFIER.FALSE_FLAGS)
        for key in (
            "all_eight_pool_runtime_capsules_proven",
            "six_legacy_pool_runtime_capsules_proven",
            "pool_burn_handler_semantics_complete",
            "pool_mint_handler_semantics_complete",
            "pool_complete_entity_history",
            "logical_parity_complete",
            "physical_parity_complete",
            "poi_parity_complete",
            "backfill_ready",
            "production_ready",
            "readiness_complete",
        ):
            self.assertIs(truth[key], False, key)

    def test_self_rehashed_contract_cannot_promote_a_residual_gate(self) -> None:
        mutated = copy.deepcopy(self.contract)
        mutated["truth_boundary"]["pool_burn_handler_semantics_complete"] = True
        mutated["scope"]["residual_legacy_runtime_profile_count"] = 0
        projection = dict(mutated)
        projection.pop("projection_sha256")
        mutated["projection_sha256"] = VERIFIER.canonical_sha256(projection)
        with self.assertRaisesRegex(
            VERIFIER.VerificationError,
            "not the deterministic retained-WAT projection",
        ):
            VERIFIER.verify_contract(ROOT, contract=mutated)

    def test_candidate_root_runtime_bytes_bind_both_verify_and_write(self) -> None:
        with tempfile.TemporaryDirectory(prefix="modern-pool-candidate-root-") as directory:
            candidate = Path(directory)
            runtime = candidate / VERIFIER.RUNTIME_SOURCE_PATH
            runtime.parent.mkdir(parents=True)
            runtime.write_bytes(VERIFIER.RUNTIME_SOURCE_BYTES + b"\n# divergent candidate\n")
            for mode in ((), ("--write",)):
                with self.subTest(mode=mode or ("verify",)):
                    result = subprocess.run(
                        [
                            sys.executable,
                            str(VERIFIER_PATH),
                            "--root",
                            str(candidate),
                            *mode,
                        ],
                        check=False,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(
                        "candidate-root shared WAT runtime bytes differ",
                        result.stderr,
                    )

    def test_setter_early_return_key_value_and_inline_append_mutations_fail_closed(self) -> None:
        def early_return(lines: list[str], _context: dict[str, Any]) -> None:
            self.insert_normalized(lines, 2, ["return"])

        def key_value_swap(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 49, "local.get $p2")

        def wrong_append_operand(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 71, "local.get $p0")

        def wrong_new_length(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 74, "local.get $p1")

        for label, mutate in (
            ("setter early-return no-op", early_return),
            ("setter key/value swap", key_value_swap),
            ("setter inline append wrong operand", wrong_append_operand),
            ("setter inline append wrong committed length", wrong_new_length),
        ):
            with self.subTest(label=label):
                self.assert_valid_wat_mutation_rejected(
                    label,
                    self.selector(VERIFIER.TYPED_MAP_SET_CALL),
                    mutate,
                    "Pool TypedMap#set key/value/inline-append operand drift",
                )

    def test_getter_index_and_equality_mutations_fail_at_public_capsule(self) -> None:
        def event_index_scale(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 16, "i32.const 1")

        def map_get_returns_key(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 21, "i32.load")

        def reverse_string_equality(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 4, "i32.ne")

        cases = (
            (
                "EventParam getter index scale",
                VERIFIER.EVENT_PARAM_GET_CALL,
                event_index_scale,
                "Pool EventParam Array#get bounds/index/value drift",
            ),
            (
                "TypedMap getter returns key",
                VERIFIER.TYPED_MAP_GET_CALL,
                map_get_returns_key,
                "Pool TypedMap#get receiver/key/ordered-result drift",
            ),
            (
                "String equality reverses comparison",
                "~lib/string/String.__eq",
                reverse_string_equality,
                "retained String.__eq primitive body drift",
            ),
        )
        for label, suffix, mutate, expected in cases:
            with self.subTest(label=label):
                self.assert_valid_wat_mutation_rejected(
                    label, self.selector(suffix), mutate, expected
                )

    def test_allocator_return_and_reset_mutations_fail_closed(self) -> None:
        def alloc_returns_header(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 72, "local.get $l1)")

        def new_returns_header(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 32, "local.get $l2")

        def reset_allocator(lines: list[str], _context: dict[str, Any]) -> None:
            self.insert_normalized(
                lines,
                2,
                ["i32.const 0", "global.set $~lib/rt/stub/offset"],
            )

        for label, suffix, mutate, expected in (
            (
                "stub allocator returns header",
                "~lib/rt/stub/__alloc",
                alloc_returns_header,
                "stub/__alloc aligned extent/header/return identity drift",
            ),
            (
                "stub new returns header",
                "~lib/rt/stub/__new",
                new_returns_header,
                "stub/__new allocation/header/return identity drift",
            ),
            (
                "reachable helper resets allocator floor",
                "~lib/string/String.__eq",
                reset_allocator,
                "critical mutable-global writer inventory drift",
            ),
        ):
            with self.subTest(label=label):
                self.assert_valid_wat_mutation_rejected(
                    label, self.selector(suffix), mutate, expected
                )

    def test_entity_capacity_and_low_level_boundaries_fail_closed(self) -> None:
        def entity_receiver_type(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 6, "i32.const 26")

        def ensure_old_capacity(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 223, "local.get $l3")

        def memory_fill_wider_store(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 8, "i32.store16")

        def memory_copy_zero_length(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 23, "i32.const 0")

        def memcpy_wider_load(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 22, "i32.load16_u")

        for label, suffix, mutate, expected in (
            (
                "Entity constructor receiver type ID changes",
                "common/collections/Entity#constructor",
                entity_receiver_type,
                "Pool Entity constructor type/backing/return drift",
            ),
            (
                "ensureCapacity commits the old capacity",
                "~lib/array/ensureCapacity",
                ensure_old_capacity,
                "Pool ensureCapacity committed capacity/backing behavior drift",
            ),
            (
                "memory.fill widens its first zero store",
                "~lib/memory/memory.fill",
                memory_fill_wider_store,
                "fixed retained Pool ~lib/memory/memory.fill body drift",
            ),
            (
                "memory.copy forces the memcpy length to zero",
                "~lib/memory/memory.copy",
                memory_copy_zero_length,
                "fixed retained Pool ~lib/memory/memory.copy body drift",
            ),
            (
                "memcpy widens its byte load",
                "~lib/util/memory/memcpy",
                memcpy_wider_load,
                "fixed retained Pool ~lib/util/memory/memcpy body drift",
            ),
        ):
            with self.subTest(label=label):
                self.assert_valid_wat_mutation_rejected(
                    label, self.selector(suffix), mutate, expected
                )

    def test_start_export_global_and_direct_memory_mutations_fail_closed(self) -> None:
        def unchanged(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 2, VERIFIER.normalized(lines[2]))

        def rebind_start(wat: str) -> str:
            old = '(export "_start" (func $~start))'
            new = '(export "_start" (func $~lib/rt/stub/__alloc))'
            self.assertEqual(wat.count(old), 1)
            return wat.replace(old, new, 1)

        def initialize_started_true(wat: str) -> str:
            old = '(global $~started (mut i32) (i32.const 0))'
            new = '(global $~started (mut i32) (i32.const 1))'
            self.assertEqual(wat.count(old), 1)
            return wat.replace(old, new, 1)

        def add_native_start(wat: str) -> str:
            marker = '(export "_start" (func $~start))'
            self.assertEqual(wat.count(marker), 1)
            return wat.replace(marker, f"{marker}\n  (start $~start)", 1)

        for label, module_mutator, expected in (
            ("_start export rebound", rebind_start, "_start export binding drift"),
            (
                "native start section added",
                add_native_start,
                "unexpected native WebAssembly start section",
            ),
            ("started global initialized true", initialize_started_true, "zero initializer drift"),
        ):
            with self.subTest(label=label):
                self.assert_valid_wat_mutation_rejected(
                    label,
                    self.selector("~start"),
                    unchanged,
                    expected,
                    mutate_module=module_mutator,
                )

        def direct_static_write(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 10, "i32.const 0")
            self.set_normalized(lines, 11, "i32.const 0")
            self.set_normalized(lines, 12, "i32.store")

        self.assert_valid_wat_mutation_rejected(
            "start writes below allocator floor",
            self.selector("~start"),
            direct_static_write,
            "Pool start acquired a direct linear-memory write",
            refresh_start_authority=True,
        )

    def test_initialized_data_cannot_reach_the_allocator_floor(self) -> None:
        base = self.contexts["modern-mainnet"]
        floor = base["spec"].allocator_floor

        def unchanged(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 2, VERIFIER.normalized(lines[2]))

        def move_highest_segment_to_floor(wat: str) -> str:
            candidates: list[tuple[int, int, str]] = []
            for line in wat.splitlines():
                match = VERIFIER.DATA_RE.fullmatch(line)
                if match is None:
                    continue
                payload = VERIFIER.decode_wat_string(match.group(2))
                candidates.append((int(match.group(1)) + len(payload), len(payload), line))
            self.assertTrue(candidates)
            _end, _size, original = max(candidates)
            changed = original.replace(
                f"(i32.const {int(VERIFIER.DATA_RE.fullmatch(original).group(1))})",
                f"(i32.const {floor})",
                1,
            )
            self.assertNotEqual(original, changed)
            self.assertEqual(wat.count(original), 1)
            return wat.replace(original, changed, 1)

        self.assert_valid_wat_mutation_rejected(
            "initialized data crosses allocator floor",
            self.selector("~start"),
            unchanged,
            "allocator floor overlaps initialized data",
            mutate_module=move_highest_segment_to_floor,
            refresh_initialized_data_authority=True,
        )


if __name__ == "__main__":
    unittest.main()
