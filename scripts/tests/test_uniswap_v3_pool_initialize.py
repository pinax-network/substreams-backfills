from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[2]
VERIFIER_PATH = ROOT / "scripts/verify-uniswap-v3-pool-initialize.py"
SPEC = importlib.util.spec_from_file_location(
    "uniswap_v3_pool_initialize_semantics_v1",
    VERIFIER_PATH,
)
assert SPEC is not None and SPEC.loader is not None
VERIFIER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VERIFIER
SPEC.loader.exec_module(VERIFIER)


Mutation = tuple[str, Callable[[list[str], dict[str, Any]], None]]
ModuleMutation = Callable[[list[str], dict[str, Any]], None]


class PoolInitializeSemanticsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sources = VERIFIER.load_sources(ROOT, recompute_wat=True)
        cls.contract = VERIFIER.verify_contract(
            ROOT,
            sources=cls.sources,
            recompute_wat=False,
        )
        cls.contexts = cls.sources["pool_wat_contexts"]
        cls.by_profile = {
            context["profile"]["profile_id"]: context
            for context in cls.contexts.values()
        }
        wasm2wat = next(iter(cls.contexts.values()))["wasm2wat"]
        cls.wasm2wat = VERIFIER.resolve_tool(wasm2wat, "wasm2wat")
        cls.wat2wasm = VERIFIER.resolve_tool(wasm2wat.with_name("wat2wasm"), "wat2wasm")
        cls.expected_errors = tuple(
            dict.fromkeys(
                (
                    VERIFIER.VerificationError,
                    VERIFIER.V2.VerificationError,
                    VERIFIER.WRITER.VerificationError,
                )
            )
        )

    def assert_contract_rejected(self, mutation: dict[str, Any], label: str) -> None:
        with self.assertRaises(self.expected_errors, msg=label):
            VERIFIER.verify_contract(
                ROOT,
                mutation,
                sources=self.sources,
                recompute_wat=False,
            )

    def function_by_suffix(self, context: dict[str, Any], suffix: str) -> Any:
        matches = [
            function
            for name, function in context["functions"].items()
            if name.endswith(suffix)
        ]
        self.assertEqual(len(matches), 1, suffix)
        return matches[0]

    def constant_line(self, context: dict[str, Any], value: str) -> str:
        for function in context["functions"].values():
            for line in function.lines:
                if VERIFIER.decoded_constant(line, context["memory"]) == value:
                    return VERIFIER.normalized(line)
        self.fail(f"decoded constant not found: {value}")

    def roundtrip_context(
        self,
        context: dict[str, Any],
        mutations: list[Mutation],
        module_mutation: ModuleMutation | None = None,
    ) -> dict[str, Any]:
        replacements: list[tuple[int, int, list[str]]] = []
        for function_name, mutate in mutations:
            function = context["functions"][function_name]
            lines = list(function.lines)
            mutate(lines, context)
            replacements.append((function.start_line - 1, len(function.lines), lines))

        wat_lines = context["wat_text"].splitlines()
        for start, old_length, replacement in sorted(replacements, reverse=True):
            wat_lines[start : start + old_length] = replacement
        if module_mutation is not None:
            module_mutation(wat_lines, context)
        wat_text = "\n".join(wat_lines) + "\n"

        with tempfile.TemporaryDirectory(prefix="pool-initialize-wat-mutation-") as temporary:
            temporary_path = Path(temporary)
            wat_path = temporary_path / "mutated.wat"
            wasm_path = temporary_path / "mutated.wasm"
            wat_path.write_text(wat_text)
            compiled = subprocess.run(
                [
                    str(self.wat2wasm),
                    "--debug-names",
                    str(wat_path),
                    "-o",
                    str(wasm_path),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            regenerated = VERIFIER.WRITER.run_wasm2wat(self.wasm2wat, wasm_path).decode()

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

    def assert_wat_rejected(
        self,
        context: dict[str, Any],
        mutations: list[Mutation],
        label: str,
        module_mutation: ModuleMutation | None = None,
    ) -> None:
        mutated = self.roundtrip_context(context, mutations, module_mutation)
        with self.assertRaises(self.expected_errors, msg=label):
            VERIFIER.prove_pool_initialize_wat_context(mutated)

    def test_committed_contract_is_the_deterministic_projection(self) -> None:
        self.assertEqual(self.contract, VERIFIER.expected_contract_from_sources(self.sources))
        self.assertEqual(
            (self.contract["format_version"], self.contract["contract_version"]),
            (1, "uniswap-v3-pool-initialize-semantics/v1"),
        )
        result = subprocess.run(
            [sys.executable, str(VERIFIER_PATH), "--root", str(ROOT)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("8 mappings, 16 segment-field projections, 28 diffs", result.stdout)

    def test_exact_three_save_and_five_no_save_profiles_are_proven(self) -> None:
        proofs = self.contract["mapping_proofs"]
        saving = {
            item["profile_id"]: item["persistence"]["handler_save_wat_line"]
            for item in proofs
            if item["persistence"]["profile_expected_to_persist"]
        }
        self.assertEqual(
            saving,
            {
                "legacy-base-root": 4118,
                "modern-base": 5567,
                "modern-mainnet": 5547,
            },
        )
        no_save = [
            item
            for item in proofs
            if not item["persistence"]["profile_expected_to_persist"]
        ]
        self.assertEqual(len(no_save), 5)
        for proof in no_save:
            persistence = proof["persistence"]
            self.assertTrue(persistence["no_transitive_pool_store_machine_proven"])
            self.assertNotIn(
                "Pool",
                persistence["transitive_store_evidence"]["reachable_store_set_targets"],
            )
            self.assertEqual(persistence["direct_pool_save_count"], 0)

    def test_all_segments_have_two_exact_selected_handler_projections(self) -> None:
        segments = self.contract["segments"]
        self.assertEqual(len(segments), 8)
        self.assertEqual(
            sum(len(item["semantic_surface"]["fields"]) for item in segments),
            16,
        )
        for segment in segments:
            fields = segment["semantic_surface"]["fields"]
            self.assertEqual({item["field"] for item in fields}, {"sqrtPrice", "tick"})
            self.assertTrue(all(item["complete_selected_handler_projection"] for item in fields))
            self.assertTrue(all(not item["complete_entity_history"] for item in fields))
            self.assertTrue(segment["semantic_surface"]["selected_handler_projection_complete"])
            self.assertFalse(segment["semantic_surface"]["complete_pool_entity_history"])
            self.assertEqual(segment["execution_model"], "undecided")
            self.assertFalse(segment["backfill_allowed"])

    def test_cumulative_counts_and_scoped_diffs_are_exact(self) -> None:
        scope = self.contract["scope"]
        self.assertEqual(
            (
                scope["inherited_v2_selected_field_count"],
                scope["cumulative_selected_field_count"],
                scope["inherited_v2_residual_field_count"],
                scope["cumulative_residual_field_count"],
            ),
            (34, 36, 232, 230),
        )
        diffs = self.contract["segment_diffs"]
        self.assertEqual(len(diffs), 28)
        by_id = {item["segment_id"]: item for item in self.contract["segments"]}
        for diff in diffs:
            left = by_id[diff["left_segment_id"]]
            right = by_id[diff["right_segment_id"]]
            self.assertEqual(
                diff["scoped_semantic_diff_paths"],
                VERIFIER.json_diff_paths(left["semantic_surface"], right["semantic_surface"]),
            )
            self.assertFalse(diff["complete_writer_semantics_compared"])
            self.assertFalse(diff["boundary_state_compared"])
            self.assertFalse(diff["graph_oracle_compared"])

    def test_only_scoped_truths_are_promoted(self) -> None:
        truth = self.contract["truth_boundary"]
        self.assertEqual({key for key, value in truth.items() if value}, set(VERIFIER.TRUE_FLAGS))
        self.assertEqual({key for key, value in truth.items() if not value}, set(VERIFIER.FALSE_FLAGS))
        for gate in (
            "pool_non_flash_handler_semantics_complete",
            "pool_mint_semantics_complete",
            "pool_burn_semantics_complete",
            "pool_swap_semantics_complete",
            "pool_complete_entity_history",
            "runtime_population_complete",
            "logical_parity_complete",
            "physical_parity_complete",
            "poi_parity_complete",
            "backfill_ready",
            "production_ready",
        ):
            self.assertFalse(truth[gate], gate)

    def test_unmodified_wat_roundtrip_preserves_legacy_and_modern_proofs(self) -> None:
        for profile in ("legacy-mainnet-root", "modern-mainnet"):
            with self.subTest(profile=profile):
                context = self.by_profile[profile]
                roundtripped = self.roundtrip_context(context, [])
                proof = VERIFIER.prove_pool_initialize_wat_context(roundtripped)
                self.assertTrue(proof["selected_handler_projection_complete"])

    def test_wrong_sqrt_price_parameter_index_is_rejected(self) -> None:
        for profile in ("legacy-mainnet-root", "modern-mainnet"):
            context = self.by_profile[profile]

            def mutate(lines: list[str], _context: dict[str, Any]) -> None:
                function = context["handler"]
                call = VERIFIER.single_call(
                    function,
                    "ethereum.Value#toBigInt",
                    "mutated sqrtPrice conversion",
                )
                parameter = next(
                    index
                    for index in range(call - 1, max(-1, call - 9), -1)
                    if VERIFIER.normalized(lines[index]) == "i32.const 0"
                )
                indent = lines[parameter][: len(lines[parameter]) - len(lines[parameter].lstrip())]
                lines[parameter] = f"{indent}i32.const 1"

            self.assert_wat_rejected(
                context,
                [(context["handler"].name, mutate)],
                f"{profile} wrong sqrtPrice parameter index",
            )

    def test_wrong_tick_parameter_index_is_rejected(self) -> None:
        legacy = self.by_profile["legacy-mainnet-root"]
        legacy_getter = self.function_by_suffix(legacy, "Initialize__Params#get:tick")

        def mutate_legacy(lines: list[str], _context: dict[str, Any]) -> None:
            index = next(i for i, line in enumerate(lines) if VERIFIER.normalized(line) == "i32.const 1")
            indent = lines[index][: len(lines[index]) - len(lines[index].lstrip())]
            lines[index] = f"{indent}i32.const 0"

        self.assert_wat_rejected(
            legacy,
            [(legacy_getter.name, mutate_legacy)],
            "legacy wrong tick parameter index",
        )

        modern = self.by_profile["modern-mainnet"]

        def mutate_modern(lines: list[str], _context: dict[str, Any]) -> None:
            function = modern["handler"]
            call = VERIFIER.single_call(function, "ethereum.Value#toI32", "mutated tick conversion")
            index = next(
                candidate
                for candidate in range(call - 1, call - 9, -1)
                if VERIFIER.normalized(lines[candidate]) == "i32.const 1"
            )
            indent = lines[index][: len(lines[index]) - len(lines[index].lstrip())]
            lines[index] = f"{indent}i32.const 0"

        self.assert_wat_rejected(
            modern,
            [(modern["handler"].name, mutate_modern)],
            "modern wrong tick parameter index",
        )

    def test_wrong_legacy_parameter_lookup_call_target_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-root"]
        wrong_target = "~lib/internal/typedarray/TypedArray<u8>#__get"

        def mutate(lines: list[str], _context: dict[str, Any]) -> None:
            target = next(
                index
                for index, line in enumerate(lines)
                if VERIFIER.call_name(line) == VERIFIER.EVENT_PARAM_ARRAY_GET_CALL
            )
            indent = lines[target][: len(lines[target]) - len(lines[target].lstrip())]
            lines[target] = f"{indent}call ${wrong_target}"

        self.assert_wat_rejected(
            context,
            [(context["handler"].name, mutate)],
            "legacy EventParam lookup replaced by TypedArray byte lookup",
        )

    def test_wrong_loaded_pool_receiver_is_rejected(self) -> None:
        for profile in ("legacy-mainnet-root", "modern-mainnet"):
            context = self.by_profile[profile]
            generation = context["profile"]["control_generation"]

            def mutate(lines: list[str], _context: dict[str, Any]) -> None:
                function = context["handler"]
                setter = VERIFIER.single_call(function, "schema/Pool#set:tick", "mutated tick setter")
                receiver = setter - (5 if generation == "legacy" else 9)
                indent = lines[receiver][: len(lines[receiver]) - len(lines[receiver].lstrip())]
                lines[receiver] = f"{indent}local.get $p0"

            self.assert_wat_rejected(
                context,
                [(context["handler"].name, mutate)],
                f"{profile} wrong Pool setter receiver",
            )

    def test_loaded_pool_local_overwrite_is_rejected(self) -> None:
        for profile in ("legacy-mainnet-root", "legacy-base-root"):
            context = self.by_profile[profile]

            def mutate(lines: list[str], _context: dict[str, Any]) -> None:
                function = context["handler"]
                load = VERIFIER.single_call(function, "schema/Pool.load", "Pool.load")
                pool_local = VERIFIER.local_name(lines[load + 1], "tee")
                self.assertIsNotNone(pool_local)
                insert = load + 2
                indent = lines[insert][: len(lines[insert]) - len(lines[insert].lstrip())]
                lines[insert:insert] = [
                    f"{indent}drop",
                    f"{indent}local.get $p0",
                    f"{indent}local.tee {pool_local}",
                ]

            self.assert_wat_rejected(
                context,
                [(context["handler"].name, mutate)],
                f"{profile} loaded Pool local overwritten by event object",
            )

    def test_original_event_parameter_reassignment_before_pool_load_is_rejected(self) -> None:
        for profile in ("legacy-mainnet-root", "modern-mainnet"):
            context = self.by_profile[profile]

            def mutate(lines: list[str], _context: dict[str, Any]) -> None:
                insert = 1
                while insert < len(lines) and VERIFIER.normalized(lines[insert]).startswith(
                    "(local "
                ):
                    insert += 1
                indent = lines[insert][: len(lines[insert]) - len(lines[insert].lstrip())]
                lines[insert:insert] = [
                    f"{indent}local.get $p0",
                    f"{indent}i32.const 4",
                    f"{indent}i32.add",
                    f"{indent}local.set $p0",
                ]

            self.assert_wat_rejected(
                context,
                [(context["handler"].name, mutate)],
                f"{profile} original event parameter reassigned before Pool load",
            )

    def test_legacy_event_parameter_wrapper_corruption_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-root"]
        constructor = self.function_by_suffix(context, "Initialize__Params#constructor")

        def mutate(lines: list[str], _context: dict[str, Any]) -> None:
            source = next(
                index
                for index, line in enumerate(lines)
                if VERIFIER.normalized(line) == "local.get $p0"
            )
            indent = lines[source][: len(lines[source]) - len(lines[source].lstrip())]
            lines[source + 1 : source + 1] = [
                f"{indent}i32.const 4",
                f"{indent}i32.add",
            ]

        self.assert_wat_rejected(
            context,
            [(constructor.name, mutate)],
            "legacy Initialize parameter wrapper stores event pointer plus four",
        )

    def test_wrong_sqrt_price_value_conversion_is_rejected(self) -> None:
        for profile in ("legacy-mainnet-root", "modern-mainnet"):
            context = self.by_profile[profile]

            def mutate(lines: list[str], _context: dict[str, Any]) -> None:
                function = context["handler"]
                source = VERIFIER.single_call(function, "ethereum.Value#toBigInt", "sqrtPrice conversion")
                replacement = next(
                    VERIFIER.call_name(line)
                    for candidate in context["functions"].values()
                    for line in candidate.lines
                    if (VERIFIER.call_name(line) or "").endswith("ethereum.Value#toI32")
                )
                indent = lines[source][: len(lines[source]) - len(lines[source].lstrip())]
                lines[source] = f"{indent}call ${replacement}"

            self.assert_wat_rejected(
                context,
                [(context["handler"].name, mutate)],
                f"{profile} wrong sqrtPrice value conversion",
            )

    def test_modern_sqrt_price_bigint_local_overwrite_is_rejected(self) -> None:
        context = self.by_profile["modern-mainnet"]

        def mutate(lines: list[str], _context: dict[str, Any]) -> None:
            function = context["handler"]
            conversion = VERIFIER.single_call(
                function,
                "ethereum.Value#toBigInt",
                "modern sqrtPrice conversion",
            )
            local = VERIFIER.local_name(lines[conversion + 2], "set")
            self.assertIsNotNone(local)
            insert = conversion + 3
            indent = lines[insert][: len(lines[insert]) - len(lines[insert].lstrip())]
            lines[insert:insert] = [
                f"{indent}i64.const 0",
                f"{indent}local.set {local}",
            ]

        self.assert_wat_rejected(
            context,
            [(context["handler"].name, mutate)],
            "modern sqrtPrice BigInt local overwritten before Value construction",
        )

    def test_modern_sqrt_price_value_allocation_corruption_is_rejected(self) -> None:
        context = self.by_profile["modern-mainnet"]

        def mutate(lines: list[str], _context: dict[str, Any]) -> None:
            function = context["handler"]
            conversion = VERIFIER.single_call(
                function,
                "ethereum.Value#toBigInt",
                "modern sqrtPrice conversion",
            )
            allocation = next(
                index
                for index in range(conversion + 1, len(lines))
                if (VERIFIER.call_name(lines[index]) or "").endswith("__new")
            )
            size = allocation - 2
            indent = lines[size][: len(lines[size]) - len(lines[size].lstrip())]
            lines[size] = f"{indent}i32.const 8"

        self.assert_wat_rejected(
            context,
            [(context["handler"].name, mutate)],
            "modern sqrtPrice Value allocation size corruption",
        )

    def test_modern_tick_setter_dropped_payload_is_rejected(self) -> None:
        context = self.by_profile["modern-mainnet"]
        setter = self.function_by_suffix(context, "schema/Pool#set:tick")

        def mutate(lines: list[str], _context: dict[str, Any]) -> None:
            assignment = next(
                index
                for index, line in enumerate(lines)
                if VERIFIER.normalized(line) == "local.set $l2"
            )
            indent = lines[assignment][: len(lines[assignment]) - len(lines[assignment].lstrip())]
            lines[assignment] = f"{indent}drop"

        self.assert_wat_rejected(
            context,
            [(setter.name, mutate)],
            "modern Pool.tick setter drops the incoming BigInt payload",
        )

    def test_wrong_legacy_signed_bigint_byte_writer_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-root"]
        conversion = self.function_by_suffix(context, "ByteArray.fromI32")
        wrong_target = "~lib/array/Array<~lib/string/String>#__set"

        def mutate(lines: list[str], _context: dict[str, Any]) -> None:
            target = next(
                index
                for index, line in enumerate(lines)
                if VERIFIER.call_name(line) == VERIFIER.LEGACY_BIGINT_BYTE_SET_CALL
            )
            indent = lines[target][: len(lines[target]) - len(lines[target].lstrip())]
            lines[target] = f"{indent}call ${wrong_target}"

        self.assert_wat_rejected(
            context,
            [(conversion.name, mutate)],
            "legacy signed BigInt byte writer replaced by String array writer",
        )

    def test_dead_or_wrong_field_key_is_rejected(self) -> None:
        legacy = self.by_profile["legacy-mainnet-root"]
        sqrt_setter = self.function_by_suffix(legacy, "schema/Pool#set:sqrtPrice")
        tick_constant = self.constant_line(legacy, "tick")

        def mutate_legacy(lines: list[str], _context: dict[str, Any]) -> None:
            key = next(
                index
                for index, line in enumerate(lines)
                if VERIFIER.decoded_constant(line, legacy["memory"]) == "sqrtPrice"
            )
            indent = lines[key][: len(lines[key]) - len(lines[key].lstrip())]
            lines[key] = f"{indent}{tick_constant}"

        self.assert_wat_rejected(
            legacy,
            [(sqrt_setter.name, mutate_legacy)],
            "legacy wrong sqrtPrice key",
        )

        modern = self.by_profile["modern-mainnet"]
        modern_tick_constant = self.constant_line(modern, "tick")

        def mutate_modern(lines: list[str], _context: dict[str, Any]) -> None:
            key = next(
                index
                for index, line in enumerate(lines)
                if VERIFIER.decoded_constant(line, modern["memory"]) == "sqrtPrice"
            )
            indent = lines[key][: len(lines[key]) - len(lines[key].lstrip())]
            lines[key] = f"{indent}{modern_tick_constant}"

        self.assert_wat_rejected(
            modern,
            [(modern["handler"].name, mutate_modern)],
            "modern wrong sqrtPrice key",
        )

    def test_conditional_setter_bypass_is_rejected(self) -> None:
        context = self.by_profile["modern-mainnet"]

        def mutate(lines: list[str], _context: dict[str, Any]) -> None:
            function = context["handler"]
            setter = VERIFIER.single_call(function, "schema/Pool#set:tick", "conditional tick setter")
            start = setter - 9
            indent = lines[start][: len(lines[start]) - len(lines[start].lstrip())]
            lines[start:start] = [f"{indent}i32.const 0", f"{indent}if"]
            lines.insert(setter + 3, f"{indent}end")

        self.assert_wat_rejected(
            context,
            [(context["handler"].name, mutate)],
            "conditional tick setter bypass",
        )

    def test_early_return_before_setters_is_rejected(self) -> None:
        for profile in ("legacy-mainnet-root", "modern-mainnet"):
            context = self.by_profile[profile]

            def mutate(lines: list[str], _context: dict[str, Any]) -> None:
                insert = 1
                while insert < len(lines) and VERIFIER.normalized(lines[insert]).startswith(
                    "(local "
                ):
                    insert += 1
                indent = lines[insert][: len(lines[insert]) - len(lines[insert].lstrip())]
                lines.insert(insert, f"{indent}return")

            self.assert_wat_rejected(
                context,
                [(context["handler"].name, mutate)],
                f"{profile} early return before Pool setters",
            )

    def test_top_level_abort_before_setters_is_rejected(self) -> None:
        context = self.by_profile["modern-mainnet"]

        def mutate(lines: list[str], _context: dict[str, Any]) -> None:
            abort = next(
                index
                for index, line in enumerate(lines)
                if (VERIFIER.call_name(line) or "").endswith("builtins/abort")
            )
            branch_end = VERIFIER.V2.matching_wat_end(
                lines,
                abort - 5,
                "missing Pool branch",
            )
            indent = lines[branch_end + 1][
                : len(lines[branch_end + 1]) - len(lines[branch_end + 1].lstrip())
            ]
            fatal_call = [
                f"{indent}{VERIFIER.normalized(line)}"
                for line in lines[abort - 4 : abort + 1]
            ]
            lines[branch_end + 1 : branch_end + 1] = fatal_call

        self.assert_wat_rejected(
            context,
            [(context["handler"].name, mutate)],
            "top-level fatal host abort before Pool setters",
        )

    def test_conditional_or_wrong_receiver_pool_save_is_rejected(self) -> None:
        for profile in ("legacy-base-root", "modern-mainnet"):
            context = self.by_profile[profile]

            def conditional(lines: list[str], _context: dict[str, Any]) -> None:
                function = context["handler"]
                save = VERIFIER.single_call(function, "schema/Pool#save", "conditional Pool.save")
                start = save - 1
                indent = lines[start][: len(lines[start]) - len(lines[start].lstrip())]
                lines[start:start] = [f"{indent}i32.const 0", f"{indent}if"]
                lines.insert(save + 3, f"{indent}end")

            self.assert_wat_rejected(
                context,
                [(context["handler"].name, conditional)],
                f"{profile} conditional Pool.save",
            )

            def wrong_receiver(lines: list[str], _context: dict[str, Any]) -> None:
                function = context["handler"]
                save = VERIFIER.single_call(function, "schema/Pool#save", "wrong Pool.save receiver")
                indent = lines[save - 1][: len(lines[save - 1]) - len(lines[save - 1].lstrip())]
                lines[save - 1] = f"{indent}local.get $p0"

            self.assert_wat_rejected(
                context,
                [(context["handler"].name, wrong_receiver)],
                f"{profile} wrong Pool.save receiver",
            )

    def test_additional_reachable_pool_save_after_handler_save_is_rejected(self) -> None:
        context = self.by_profile["legacy-base-root"]
        helper = self.function_by_suffix(context, "/updatePoolDayData")
        sqrt_setter = self.function_by_suffix(context, "schema/Pool#set:sqrtPrice")
        pool_save = self.function_by_suffix(context, "schema/Pool#save")

        def mutate(lines: list[str], _context: dict[str, Any]) -> None:
            insert = next(
                index
                for index, line in enumerate(lines)
                if (VERIFIER.call_name(line) or "").endswith("schema/PoolDayData#save")
            )
            indent = lines[insert][: len(lines[insert]) - len(lines[insert].lstrip())]
            lines[insert:insert] = [
                f"{indent}local.get $l1",
                f"{indent}global.get $g2",
                f"{indent}call ${sqrt_setter.name}",
                f"{indent}local.get $l1",
                f"{indent}call ${pool_save.name}",
            ]

        self.assert_wat_rejected(
            context,
            [(helper.name, mutate)],
            "reachable helper overwrites and re-saves Pool after Initialize handler save",
        )

    def test_wrong_pool_save_helper_target_is_rejected(self) -> None:
        for profile in ("legacy-base-root", "modern-mainnet"):
            context = self.by_profile[profile]
            helper = self.function_by_suffix(context, "schema/Pool#save")
            token_constant = self.constant_line(context, "Token")

            def mutate(lines: list[str], _context: dict[str, Any]) -> None:
                store_set = VERIFIER.single_call(helper, VERIFIER.WRITER.STORE_SET_CALL, "Pool.save store.set")
                target = store_set - 4
                indent = lines[target][: len(lines[target]) - len(lines[target].lstrip())]
                lines[target] = f"{indent}{token_constant}"

            self.assert_wat_rejected(
                context,
                [(helper.name, mutate)],
                f"{profile} wrong Pool.save entity target",
            )

    def test_pool_save_helper_else_branch_store_is_rejected(self) -> None:
        context = self.by_profile["modern-mainnet"]
        helper = self.function_by_suffix(context, "schema/Pool#save")

        def mutate(lines: list[str], _context: dict[str, Any]) -> None:
            store_set = VERIFIER.single_call(
                helper,
                VERIFIER.WRITER.STORE_SET_CALL,
                "Pool.save store.set moved to else branch",
            )
            target = store_set - 4
            indent = lines[target][: len(lines[target]) - len(lines[target].lstrip())]
            lines.insert(target, f"{indent}else")

        self.assert_wat_rejected(
            context,
            [(helper.name, mutate)],
            "modern Pool.save store.set moved to else branch",
        )

    def test_pool_save_helper_fatal_effect_before_store_is_rejected(self) -> None:
        for profile in ("legacy-base-root", "modern-mainnet"):
            context = self.by_profile[profile]
            helper = self.function_by_suffix(context, "schema/Pool#save")

            def mutate(lines: list[str], _context: dict[str, Any]) -> None:
                store_set = VERIFIER.single_call(
                    helper,
                    VERIFIER.WRITER.STORE_SET_CALL,
                    "Pool.save store.set",
                )
                abort = next(
                    index
                    for index, line in enumerate(lines)
                    if (VERIFIER.call_name(line) or "").endswith(
                        ("builtins/abort", "env/abort")
                    )
                )
                target = store_set - 4
                indent = lines[target][: len(lines[target]) - len(lines[target].lstrip())]
                fatal = [
                    f"{indent}{VERIFIER.normalized(line)}"
                    for line in lines[abort - 4 : abort + 1]
                ]
                fatal.append(f"{indent}unreachable")
                lines[target:target] = fatal

            self.assert_wat_rejected(
                context,
                [(helper.name, mutate)],
                f"{profile} fatal abort and unreachable immediately before Pool store.set",
            )

    def test_pool_save_helper_entity_parameter_overwrite_is_rejected(self) -> None:
        for profile in ("legacy-base-root", "modern-mainnet"):
            context = self.by_profile[profile]
            helper = self.function_by_suffix(context, "schema/Pool#save")

            def mutate(lines: list[str], _context: dict[str, Any]) -> None:
                store_set = VERIFIER.single_call(
                    helper,
                    VERIFIER.WRITER.STORE_SET_CALL,
                    "Pool.save store.set",
                )
                id_local = VERIFIER.local_name(lines[store_set - 3])
                self.assertIsNotNone(id_local)
                target = store_set - 4
                indent = lines[target][: len(lines[target]) - len(lines[target].lstrip())]
                lines[target:target] = [
                    f"{indent}local.get {id_local}",
                    f"{indent}local.set $p0",
                ]

            self.assert_wat_rejected(
                context,
                [(helper.name, mutate)],
                f"{profile} Pool.save entity parameter overwritten by ID Value",
            )

    def test_pool_save_helper_id_local_overwrite_is_rejected(self) -> None:
        for profile in ("legacy-base-root", "modern-mainnet"):
            context = self.by_profile[profile]
            helper = self.function_by_suffix(context, "schema/Pool#save")

            def mutate(lines: list[str], _context: dict[str, Any]) -> None:
                store_set = VERIFIER.single_call(
                    helper,
                    VERIFIER.WRITER.STORE_SET_CALL,
                    "Pool.save store.set",
                )
                id_local = VERIFIER.local_name(lines[store_set - 3])
                self.assertIsNotNone(id_local)
                target = store_set - 4
                indent = lines[target][: len(lines[target]) - len(lines[target].lstrip())]
                lines[target:target] = [
                    f"{indent}i32.const 0",
                    f"{indent}local.set {id_local}",
                ]

            self.assert_wat_rejected(
                context,
                [(helper.name, mutate)],
                f"{profile} Pool.save ID Value local overwritten before store.set",
            )

    def test_dormant_direct_pool_save_in_no_save_profile_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-root"]
        save_helper = self.function_by_suffix(context, "schema/Pool#save")
        proof = VERIFIER.prove_legacy_pool_load(context)
        pool_local = proof["pool_entity_local"]

        def mutate(lines: list[str], _context: dict[str, Any]) -> None:
            function = context["handler"]
            setter = VERIFIER.single_call(function, "schema/Pool#set:tick", "no-save tick setter")
            insert = setter + 1
            indent = lines[setter][: len(lines[setter]) - len(lines[setter].lstrip())]
            lines[insert:insert] = [
                f"{indent}i32.const 0",
                f"{indent}if",
                f"{indent}  local.get {pool_local}",
                f"{indent}  call ${save_helper.name}",
                f"{indent}end",
            ]

        self.assert_wat_rejected(
            context,
            [(context["handler"].name, mutate)],
            "dormant direct Pool.save in historical no-save profile",
        )

    def test_reachable_pool_store_remove_in_no_save_profile_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-root"]
        pool_constant = self.constant_line(context, "Pool")
        remove_symbol = "audit/pool-store.remove"

        def mutate_handler(lines: list[str], _context: dict[str, Any]) -> None:
            function = context["handler"]
            setter = VERIFIER.single_call(function, "schema/Pool#set:tick", "tick setter")
            bytes_to_hex = next(
                VERIFIER.call_name(line)
                for line in function.lines
                if (VERIFIER.call_name(line) or "").endswith("typeConversion.bytesToHex")
            )
            insert = setter + 1
            indent = lines[insert][: len(lines[insert]) - len(lines[insert].lstrip())]
            lines[insert:insert] = [
                f"{indent}{pool_constant}",
                f"{indent}local.get $p0",
                f"{indent}i32.load",
                f"{indent}call ${bytes_to_hex}",
                f"{indent}call ${remove_symbol}",
            ]

        def add_store_remove_import(lines: list[str], _context: dict[str, Any]) -> None:
            imports = [
                index
                for index, line in enumerate(lines)
                if line.lstrip().startswith("(import ")
            ]
            self.assertTrue(imports)
            lines.insert(
                imports[-1] + 1,
                f'  (import "index" "store.remove" (func ${remove_symbol} (type $t8)))',
            )

        self.assert_wat_rejected(
            context,
            [(context["handler"].name, mutate_handler)],
            "reachable Pool store.remove in historical no-save profile",
            module_mutation=add_store_remove_import,
        )

    def test_transitive_helper_pool_save_in_no_save_profile_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-root"]
        helper = self.function_by_suffix(context, "/updatePoolDayData")
        save_helper = self.function_by_suffix(context, "schema/Pool#save")

        def mutate(lines: list[str], _context: dict[str, Any]) -> None:
            insert = 1
            while insert < len(lines) and VERIFIER.normalized(lines[insert]).startswith("(local "):
                insert += 1
            indent = lines[insert][: len(lines[insert]) - len(lines[insert].lstrip())]
            lines[insert:insert] = [
                f"{indent}i32.const 0",
                f"{indent}if",
                f"{indent}  local.get $p0",
                f"{indent}  call ${save_helper.name}",
                f"{indent}end",
            ]

        self.assert_wat_rejected(
            context,
            [(helper.name, mutate)],
            "transitive helper Pool.save in historical no-save profile",
        )

    def test_adversarial_contract_mutations_fail_closed(self) -> None:
        mutations: list[tuple[str, dict[str, Any]]] = []

        promoted_pool = copy.deepcopy(self.contract)
        promoted_pool["truth_boundary"]["pool_non_flash_handler_semantics_complete"] = True
        mutations.append(("promoted complete Pool semantics", promoted_pool))

        promoted_history = copy.deepcopy(self.contract)
        promoted_history["truth_boundary"]["pool_complete_entity_history"] = True
        mutations.append(("promoted Pool entity history", promoted_history))

        wrong_count = copy.deepcopy(self.contract)
        wrong_count["scope"]["cumulative_residual_field_count"] = 0
        mutations.append(("false cumulative residual count", wrong_count))

        false_persistence = copy.deepcopy(self.contract)
        proof = next(
            item
            for item in false_persistence["mapping_proofs"]
            if item["profile_id"] == "legacy-mainnet-root"
        )
        proof["persistence"]["no_transitive_pool_store_machine_proven"] = False
        mutations.append(("changed no-save proof", false_persistence))

        removed_segment_field = copy.deepcopy(self.contract)
        removed_segment_field["segments"][0]["semantic_surface"]["fields"].pop()
        removed_segment_field["segments"][0]["semantic_surface_sha256"] = VERIFIER.canonical_sha256(
            removed_segment_field["segments"][0]["semantic_surface"]
        )
        mutations.append(("self-rehashed removed segment field", removed_segment_field))

        removed_diff = copy.deepcopy(self.contract)
        removed_diff["segment_diffs"].pop()
        mutations.append(("removed scoped diff", removed_diff))

        numeric_false = copy.deepcopy(self.contract)
        numeric_false["truth_boundary"]["backfill_ready"] = 0
        mutations.append(("numeric false gate", numeric_false))

        for label, mutation in mutations:
            with self.subTest(label=label):
                self.assert_contract_rejected(mutation, label)

    def test_duplicate_json_keys_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pool-initialize-duplicate-json-") as temporary:
            path = Path(temporary) / "duplicate.json"
            path.write_text('{"format_version": 1, "format_version": 2}\n')
            with self.assertRaises(VERIFIER.VerificationError):
                VERIFIER.load_json_strict(path)


if __name__ == "__main__":
    unittest.main()
