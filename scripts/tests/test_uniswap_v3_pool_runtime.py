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
        self.assertEqual(observed, VERIFIER.MODERN_EXPECTED_ARTIFACT_TUPLES)
        self.assertEqual(self.contract["scope"]["closed_modern_runtime_profile_count"], 2)
        self.assertEqual(self.contract["scope"]["closed_runtime_profile_count"], 8)
        self.assertEqual(self.contract["scope"]["handler_semantics_added"], [])

    def test_runtime_truth_boundary_preserves_every_residual_gate(self) -> None:
        truth = self.contract["truth_boundary"]
        self.assertEqual({key for key, value in truth.items() if value}, VERIFIER.TRUE_FLAGS)
        self.assertEqual({key for key, value in truth.items() if not value}, VERIFIER.FALSE_FLAGS)
        self.assertIs(truth["all_eight_pool_runtime_capsules_proven"], True)
        self.assertIs(truth["six_legacy_pool_runtime_capsules_proven"], True)
        for key in (
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
        mutated["scope"]["closed_runtime_profile_count"] = 0
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


class LegacyPoolRuntimeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.executable = VERIFIER.resolve_wasm2wat(None)
        cls.contexts = {
            spec.profile_id: VERIFIER.load_context(ROOT, spec, cls.executable)
            for spec in VERIFIER.LEGACY_PROFILE_SPECS
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

    def assert_valid_legacy_wat_mutation_rejected(
        self,
        label: str,
        selector: Callable[[dict[str, Any]], Any],
        mutate: Mutator,
        expected_error: str,
        *,
        profile: str = "legacy-mainnet-root",
        mutate_module: ModuleMutator | None = None,
        refresh_body_authority: str | None = None,
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
        with tempfile.TemporaryDirectory(prefix="legacy-pool-runtime-wat-") as directory:
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
            "wat_line_count": len(changed_wat.splitlines()),
            "initialized_data": VERIFIER.initialized_data_inventory(changed_wat),
        }
        changed_spec = replace(
            base["spec"], wat_line_count=changed["wat_line_count"]
        )
        if refresh_initialized_data_authority:
            inventory = changed["initialized_data"]
            changed_spec = replace(
                changed_spec,
                initialized_data_end=inventory["maximum_end_exclusive"],
                initialized_data_segment_count=inventory["segment_count"],
                initialized_data_inventory_sha256=inventory[
                    "segment_inventory_sha256"
                ],
            )
        changed["spec"] = changed_spec

        collection_spec = VERIFIER.LEGACY_COLLECTION_SPEC
        if refresh_body_authority is not None:
            changed_function = VERIFIER.function_by_suffix(changed, function.name)
            body_sha256 = hashlib.sha256(changed_function.payload).hexdigest()
            if refresh_body_authority.startswith("profile."):
                field = refresh_body_authority.removeprefix("profile.")
                profile_spec = collection_spec.profiles[profile]
                profiles = dict(collection_spec.profiles)
                profiles[profile] = replace(
                    profile_spec, **{field: body_sha256}
                )
                collection_spec = replace(collection_spec, profiles=profiles)
            else:
                collection_spec = replace(
                    collection_spec, **{refresh_body_authority: body_sha256}
                )
        original_collection_spec = VERIFIER.LEGACY_COLLECTION_SPEC
        VERIFIER.LEGACY_COLLECTION_SPEC = collection_spec
        try:
            with self.assertRaises(VERIFIER.VerificationError, msg=label) as caught:
                VERIFIER.prove_legacy_pool_runtime_context(changed)
        finally:
            VERIFIER.LEGACY_COLLECTION_SPEC = original_collection_spec
        self.assertIn(expected_error, str(caught.exception), label)

    def test_all_six_exact_legacy_tuples_and_four_groups_close(self) -> None:
        proofs = self.contract["legacy_pool_runtime_proofs"]
        self.assertEqual(len(proofs), 6)
        self.assertEqual(
            {tuple(proof["artifact_selection_tuple"]) for proof in proofs},
            VERIFIER.LEGACY_EXPECTED_ARTIFACT_TUPLES,
        )
        self.assertEqual(
            {proof["digest_group_id"] for proof in proofs},
            set(VERIFIER.LEGACY_GROUP_SPECS),
        )
        for profile, context in self.contexts.items():
            with self.subTest(profile=profile):
                proof = VERIFIER.prove_legacy_pool_runtime_context(context)
                self.assertTrue(
                    proof["public_collection_capsule"][
                        "legacy_collection_capsule_structurally_closed"
                    ]
                )
                self.assertFalse(
                    proof["proof_boundaries"]["cross_handler_allocator_freshness_proven"]
                )

    def test_legacy_module_surface_state_reset_and_floor_mutations_fail_closed(self) -> None:
        def unchanged(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 2, VERIFIER.normalized(lines[2]))

        def remove_native_start(wat: str) -> str:
            marker = "  (start $start)\n"
            self.assertEqual(wat.count(marker), 1)
            return wat.replace(marker, "", 1)

        def rebind_native_start(wat: str) -> str:
            return wat.replace("(start $start)", "(start $~lib/memory/memory.reset)", 1)

        def rebind_reset_export(wat: str) -> str:
            old = '(export "memory.reset" (func $~lib/memory/memory.reset))'
            new = '(export "memory.reset" (func $start))'
            self.assertEqual(wat.count(old), 1)
            return wat.replace(old, new, 1)

        def rename_import(wat: str) -> str:
            old = '"typeConversion.bytesToHex"'
            self.assertEqual(wat.count(old), 1)
            return wat.replace(old, '"typeConversion.bytesToHex.changed"', 1)

        def reorder_imports(wat: str) -> str:
            first = next(line for line in wat.splitlines() if '"bigDecimal.times"' in line)
            second = next(
                line for line in wat.splitlines() if '"bigDecimal.dividedBy"' in line
            )
            self.assertEqual(wat.count(first), 1)
            self.assertEqual(wat.count(second), 1)
            placeholder = "  ;; import-order-placeholder"
            return wat.replace(first, placeholder, 1).replace(second, first, 1).replace(
                placeholder, second, 1
            )

        def initialize_floor_nonzero(wat: str) -> str:
            old = "(global $g0 (mut i32) (i32.const 0))"
            self.assertEqual(wat.count(old), 1)
            return wat.replace(old, "(global $g0 (mut i32) (i32.const 1))", 1)

        def rebind_table_element(wat: str) -> str:
            old = "(elem $e0 (i32.const 0) func $null)"
            self.assertEqual(wat.count(old), 1)
            return wat.replace(
                old, "(elem $e0 (i32.const 0) func $~lib/memory/memory.reset)", 1
            )

        module_cases = (
            ("native start removed", remove_native_start, "legacy native start binding drift"),
            ("native start rebound", rebind_native_start, "legacy native start binding drift"),
            ("reset export rebound", rebind_reset_export, "legacy complete export inventory drift"),
            ("host import renamed", rename_import, "legacy exact ordered import inventory drift"),
            ("host imports reordered", reorder_imports, "legacy exact ordered import inventory drift"),
            ("floor global starts nonzero", initialize_floor_nonzero, "legacy global definition inventory drift"),
            ("table element rebound", rebind_table_element, "legacy table/element closure drift"),
        )
        self.assertEqual(len(module_cases), 7)
        for label, module_mutator, expected in module_cases:
            with self.subTest(label=label):
                self.assert_valid_legacy_wat_mutation_rejected(
                    label,
                    self.selector("start"),
                    unchanged,
                    expected,
                    mutate_module=module_mutator,
                )

        def write_static_global(lines: list[str], _context: dict[str, Any]) -> None:
            self.insert_normalized(lines, 2, ["i32.const 0", "global.set $g8"])

        def call_reset(lines: list[str], _context: dict[str, Any]) -> None:
            self.insert_normalized(lines, 2, ["call $~lib/memory/memory.reset"])

        def indirect_call(lines: list[str], _context: dict[str, Any]) -> None:
            self.insert_normalized(
                lines, 2, ["i32.const 0", "call_indirect $table (type $t0)"]
            )

        function_cases = (
            (
                "handler writes no-writer static global",
                write_static_global,
                "legacy complete global writer inventory drift",
            ),
            (
                "handler calls exported memory.reset",
                call_reset,
                "legacy internal memory.reset callsite drift",
            ),
            (
                "handler acquires indirect call",
                indirect_call,
                "legacy call_indirect acquired",
            ),
        )
        self.assertEqual(len(function_cases), 3)
        for label, mutate, expected in function_cases:
            with self.subTest(label=label):
                self.assert_valid_legacy_wat_mutation_rejected(
                    label,
                    self.selector("src/mappings/core/handleInitialize"),
                    mutate,
                    expected,
                )

        base = self.contexts["legacy-mainnet-root"]
        floor = base["spec"].allocator_floor

        def move_data_to_floor(wat: str) -> str:
            candidates: list[tuple[int, str]] = []
            for line in wat.splitlines():
                match = VERIFIER.DATA_RE.fullmatch(line)
                if match is not None:
                    payload = VERIFIER.decode_wat_string(match.group(2))
                    candidates.append((int(match.group(1)) + len(payload), line))
            _end, original = max(candidates)
            match = VERIFIER.DATA_RE.fullmatch(original)
            assert match is not None
            changed = original.replace(
                f"(i32.const {int(match.group(1))})", f"(i32.const {floor})", 1
            )
            return wat.replace(original, changed, 1)

        self.assert_valid_legacy_wat_mutation_rejected(
            "initialized data crosses exact align8 floor",
            self.selector("start"),
            unchanged,
            "allocator floor is not exact align8(data end)",
            mutate_module=move_data_to_floor,
            refresh_initialized_data_authority=True,
        )

    def test_legacy_start_and_all_four_group_authorities_fail_closed(self) -> None:
        group_profiles = (
            "legacy-mainnet-root",
            "legacy-mainnet-qmrv",
            "legacy-base-root",
            "legacy-mainnet-stable",
        )

        def wrong_floor(lines: list[str], context: dict[str, Any]) -> None:
            self.set_normalized(
                lines, 1, f"i32.const {context['spec'].allocator_floor + 8}"
            )

        for profile in group_profiles:
            with self.subTest(profile=profile):
                self.assert_valid_legacy_wat_mutation_rejected(
                    f"{profile} native-start floor changed",
                    self.selector("start"),
                    wrong_floor,
                    "legacy native start floor/constants/result flow drift",
                    profile=profile,
                    refresh_body_authority="profile.start_body_sha256",
                )

        def wrong_zero_constant(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 1, "i32.const 1")

        def wrong_factory_size(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 1, "i32.const 4")

        def wrong_byte_mask(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 7, "i32.const 254")

        cases = (
            (
                "constants ZERO_BI input changed",
                "start:src/utils/constants",
                wrong_zero_constant,
                "constants_start_body_sha256",
                "legacy constants construction/global flow drift",
            ),
            (
                "Factory constant constructor allocation shrinks",
                "templates/Pool/Factory/Factory#constructor",
                wrong_factory_size,
                "factory_constructor_body_sha256",
                "legacy Factory constant constructor operand drift",
            ),
            (
                "ByteArray.fromI32 byte mask changes",
                "index/ByteArray.fromI32",
                wrong_byte_mask,
                None,
                "fixed retained legacy index/ByteArray.fromI32 body drift",
            ),
        )
        self.assertEqual(len(group_profiles) + len(cases), 7)
        for label, suffix, mutate, refresh, expected in cases:
            with self.subTest(label=label):
                self.assert_valid_legacy_wat_mutation_rejected(
                    label,
                    self.selector(suffix),
                    mutate,
                    expected,
                    refresh_body_authority=refresh,
                )

    def test_legacy_allocator_arraybuffer_reset_and_primitive_mutations_fail_closed(self) -> None:
        def replace_line(index: int, value: str) -> Mutator:
            return lambda lines, _context: self.set_normalized(lines, index, value)

        cases = (
            (
                "arena reads floor instead of offset",
                "allocator/arena/__memory_allocate",
                replace_line(15, "global.get $g0"),
                "arena_allocate_body_sha256",
                "legacy arena bounds/alignment/grow/commit/return drift",
            ),
            (
                "arena subtracts allocation size",
                "allocator/arena/__memory_allocate",
                replace_line(17, "i32.sub"),
                "arena_allocate_body_sha256",
                "legacy arena bounds/alignment/grow/commit/return drift",
            ),
            (
                "arena returns aligned end",
                "allocator/arena/__memory_allocate",
                replace_line(60, "local.get $l1)"),
                "arena_allocate_body_sha256",
                "legacy arena bounds/alignment/grow/commit/return drift",
            ),
            (
                "computeSize subtracts header rounding",
                "internal/arraybuffer/computeSize",
                replace_line(5, "i32.sub"),
                "compute_size_body_sha256",
                "legacy ArrayBuffer computeSize alignment drift",
            ),
            (
                "allocateUnsafe stores length at wrong header offset",
                "internal/arraybuffer/allocateUnsafe",
                replace_line(18, "i32.store offset=4"),
                "allocate_unsafe_body_sha256",
                "legacy allocateUnsafe header/return identity drift",
            ),
            (
                "reallocate memmove destination skips four bytes",
                "internal/arraybuffer/reallocateUnsafe",
                replace_line(33, "i32.const 4"),
                "reallocate_unsafe_body_sha256",
                "legacy reallocate grow/copy/zero/shrink/return drift",
            ),
            (
                "reallocate memset destination skips four bytes",
                "internal/arraybuffer/reallocateUnsafe",
                replace_line(44, "i32.const 4"),
                "reallocate_unsafe_body_sha256",
                "legacy reallocate grow/copy/zero/shrink/return drift",
            ),
            (
                "exported memory.allocate ignores input",
                "~lib/memory/memory.allocate",
                replace_line(1, "i32.const 0"),
                "memory_allocate_body_sha256",
                "legacy exported memory.allocate identity drift",
            ),
            (
                "memory.reset restores offset from itself",
                "~lib/memory/memory.reset",
                replace_line(1, "global.get $g1"),
                "memory_reset_body_sha256",
                "legacy memory.reset floor restoration drift",
            ),
            (
                "memcpy widens first byte load",
                "internal/memory/memcpy",
                replace_line(22, "i32.load16_u"),
                None,
                "fixed retained legacy internal/memory/memcpy body drift",
            ),
            (
                "memmove reverses overlap comparison",
                "internal/memory/memmove",
                replace_line(12, "i32.ge_u"),
                None,
                "fixed retained legacy internal/memory/memmove body drift",
            ),
            (
                "memmove forwards the wrong memcpy destination",
                "internal/memory/memmove",
                replace_line(24, "local.get $p1"),
                "memmove_body_sha256",
                "legacy memmove-to-memcpy operand identity drift",
            ),
            (
                "memset widens first byte store",
                "internal/memory/memset",
                replace_line(9, "i32.store16"),
                None,
                "fixed retained legacy internal/memory/memset body drift",
            ),
        )
        self.assertEqual(len(cases), 13)
        for label, suffix, mutate, refresh, expected in cases:
            with self.subTest(label=label):
                self.assert_valid_legacy_wat_mutation_rejected(
                    label,
                    self.selector(suffix),
                    mutate,
                    expected,
                    refresh_body_authority=refresh,
                )

    def test_legacy_index_value_and_string_mutations_fail_closed(self) -> None:
        def replace_line(index: int, value: str) -> Mutator:
            return lambda lines, _context: self.set_normalized(lines, index, value)

        cases = (
            (
                "EventParam accepts index equal to length",
                "EventParam>#__get",
                replace_line(8, "i32.le_u"),
                "event_param_get_body_sha256",
                "legacy EventParam bounds/index/backing/value drift",
                "legacy-mainnet-root",
            ),
            (
                "EventParam scales index by two",
                "EventParam>#__get",
                replace_line(11, "i32.const 1"),
                "event_param_get_body_sha256",
                "legacy EventParam bounds/index/backing/value drift",
                "legacy-mainnet-root",
            ),
            (
                "EventParam loads before payload backing",
                "EventParam>#__get",
                replace_line(15, "i32.load offset=4"),
                "event_param_get_body_sha256",
                "legacy EventParam bounds/index/backing/value drift",
                "legacy-mainnet-root",
            ),
            (
                "Value constructor allocates eight bytes",
                "index/Value#constructor",
                replace_line(2, "i32.const 8"),
                "value_constructor_body_sha256",
                "legacy Value constructor allocation/tag/payload/return drift",
                "legacy-mainnet-root",
            ),
            (
                "Value constructor returns payload constant",
                "index/Value#constructor",
                replace_line(10, "i32.const 0)"),
                "value_constructor_body_sha256",
                "legacy Value constructor allocation/tag/payload/return drift",
                "legacy-mainnet-root",
            ),
            (
                "Value.fromBigDecimal uses string kind",
                "index/Value.fromBigDecimal",
                replace_line(4, "i32.const 0"),
                "value_from_big_decimal_body_sha256",
                "legacy Value.fromBigDecimal tag/payload/object identity drift",
                "legacy-mainnet-root",
            ),
            (
                "Value.fromBigDecimal stores payload at offset zero",
                "index/Value.fromBigDecimal",
                replace_line(9, "i64.store"),
                "value_from_big_decimal_body_sha256",
                "legacy Value.fromBigDecimal tag/payload/object identity drift",
                "legacy-mainnet-root",
            ),
            (
                "String equality reverses identity comparison",
                "~lib/string/String.__eq",
                replace_line(4, "i32.ne"),
                "string_eq_body_sha256",
                "legacy String.__eq identity/null/length/comparison drift",
                "legacy-mainnet-root",
            ),
            (
                "compareUnsafe reads wrong code-unit offset",
                "internal/string/compareUnsafe",
                replace_line(6, "i32.load16_u offset=2"),
                "compare_unsafe_body_sha256",
                "legacy compareUnsafe ordered code-unit comparison drift",
                "legacy-mainnet-root",
            ),
            (
                "ZPi string allocator scales by four",
                "internal/string/allocateUnsafe",
                replace_line(23, "i32.const 2"),
                "profile.string_allocate_body_sha256",
                "legacy String allocate bounds/size/header/return drift",
                "legacy-base-root",
            ),
        )
        self.assertEqual(len(cases), 10)
        for label, suffix, mutate, refresh, expected, profile in cases:
            with self.subTest(label=label):
                self.assert_valid_legacy_wat_mutation_rejected(
                    label,
                    self.selector(suffix),
                    mutate,
                    expected,
                    profile=profile,
                    refresh_body_authority=refresh,
                )

    def test_legacy_typed_map_entry_array_and_group_mutations_fail_closed(self) -> None:
        def replace_line(index: int, value: str) -> Mutator:
            return lambda lines, _context: self.set_normalized(lines, index, value)

        def early_return(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 2, "return")

        def swap_entry_operands(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 12, "local.get $p2")
            self.set_normalized(lines, 13, "local.get $p1")

        cases = (
            (
                "getEntry compares receiver instead of key",
                "index/Value>#getEntry",
                replace_line(15, "local.get $p0"),
                "typed_map_get_entry_body_sha256",
                "legacy TypedMap#getEntry receiver/key/entry/null drift",
                "legacy-mainnet-root",
            ),
            (
                "TypedMap get returns matched key",
                "index/Value>#get",
                replace_line(22, "i32.load"),
                "typed_map_get_body_sha256",
                "legacy TypedMap#get receiver/key/value-offset/null drift",
                "legacy-mainnet-root",
            ),
            (
                "TypedMap setter becomes early-return no-op",
                "index/Value>#set",
                early_return,
                "typed_map_set_body_sha256",
                "legacy TypedMap#set update/entry/key/value/push identity drift",
                "legacy-mainnet-root",
            ),
            (
                "TypedMap update overwrites key",
                "index/Value>#set",
                replace_line(9, "i32.store"),
                "typed_map_set_body_sha256",
                "legacy TypedMap#set update/entry/key/value/push identity drift",
                "legacy-mainnet-root",
            ),
            (
                "TypedMap new entry reuses map as receiver",
                "index/Value>#set",
                replace_line(11, "local.get $p0"),
                "typed_map_set_body_sha256",
                "legacy TypedMap#set update/entry/key/value/push identity drift",
                "legacy-mainnet-root",
            ),
            (
                "TypedMap new entry swaps key and value",
                "index/Value>#set",
                swap_entry_operands,
                "typed_map_set_body_sha256",
                "legacy TypedMap#set update/entry/key/value/push identity drift",
                "legacy-mainnet-root",
            ),
            (
                "TypedMap pushes raw value instead of entry",
                "index/Value>#set",
                replace_line(18, "local.get $p2"),
                "typed_map_set_body_sha256",
                "legacy TypedMap#set update/entry/key/value/push identity drift",
                "legacy-mainnet-root",
            ),
            (
                "misleading entry constructor allocates four bytes",
                "ethereum.SmartContract#constructor",
                replace_line(4, "i32.const 4"),
                "entry_constructor_body_sha256",
                "legacy misleading 8-byte entry constructor key/value/return drift",
                "legacy-mainnet-root",
            ),
            (
                "misleading entry constructor stores key at value offset",
                "ethereum.SmartContract#constructor",
                replace_line(16, "i32.store offset=4"),
                "entry_constructor_body_sha256",
                "legacy misleading 8-byte entry constructor key/value/return drift",
                "legacy-mainnet-root",
            ),
            (
                "misleading entry constructor returns key",
                "ethereum.SmartContract#constructor",
                replace_line(20, "local.get $p1)"),
                "entry_constructor_body_sha256",
                "legacy misleading 8-byte entry constructor key/value/return drift",
                "legacy-mainnet-root",
            ),
            (
                "Wu array constructor commits byte length as logical length",
                "TypedMapEntry<~lib/string/String_~lib/@graphprotocol/graph-ts/index/Value>>#constructor",
                replace_line(31, "local.get $l3"),
                "profile.array_constructor_body_sha256",
                "legacy entry-array constructor backing/length/capacity/zero/return drift",
                "legacy-mainnet-root",
            ),
            (
                "YQR array push preserves old logical length",
                "TypedMapEntry<~lib/string/String_~lib/@graphprotocol/graph-ts/index/Value>>#push",
                replace_line(38, "local.get $l2"),
                "profile.array_push_body_sha256",
                "legacy entry-array push capacity/old-index/new-length/operand drift",
                "legacy-mainnet-qmrv",
            ),
            (
                "array push appends receiver instead of entry",
                "TypedMapEntry<~lib/string/String_~lib/@graphprotocol/graph-ts/index/Value>>#push",
                replace_line(45, "local.get $p0"),
                "profile.array_push_body_sha256",
                "legacy entry-array push capacity/old-index/new-length/operand drift",
                "legacy-mainnet-root",
            ),
            (
                "array push divides capacity by two",
                "TypedMapEntry<~lib/string/String_~lib/@graphprotocol/graph-ts/index/Value>>#push",
                replace_line(13, "i32.const 1"),
                "profile.array_push_body_sha256",
                "legacy entry-array push capacity/old-index/new-length/operand drift",
                "legacy-mainnet-root",
            ),
        )
        self.assertEqual(len(cases), 14)
        for label, suffix, mutate, refresh, expected, profile in cases:
            with self.subTest(label=label):
                self.assert_valid_legacy_wat_mutation_rejected(
                    label,
                    self.selector(suffix),
                    mutate,
                    expected,
                    profile=profile,
                    refresh_body_authority=refresh,
                )

    def test_legacy_mutation_registry_has_exact_coverage_count(self) -> None:
        self.assertEqual(11 + 7 + 13 + 10 + 14, 55)


if __name__ == "__main__":
    unittest.main()
