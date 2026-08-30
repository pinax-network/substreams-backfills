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
VERIFIER_PATH = ROOT / "scripts/verify-uniswap-v3-pool-burn.py"
SPEC = importlib.util.spec_from_file_location(
    "uniswap_v3_pool_burn_semantics_v1",
    VERIFIER_PATH,
)
assert SPEC is not None and SPEC.loader is not None
VERIFIER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VERIFIER
SPEC.loader.exec_module(VERIFIER)


Mutation = tuple[str, Callable[[list[str], dict[str, Any]], None]]
ModuleMutation = Callable[[list[str], dict[str, Any]], None]


class PoolBurnSemanticsTest(unittest.TestCase):
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
        cls.wasm2wat = VERIFIER.INITIALIZE.resolve_tool(wasm2wat, "wasm2wat")
        cls.wat2wasm = VERIFIER.INITIALIZE.resolve_tool(
            wasm2wat.with_name("wat2wasm"), "wat2wasm"
        )
        cls.expected_errors = tuple(
            dict.fromkeys(
                (
                    VERIFIER.VerificationError,
                    VERIFIER.INITIALIZE.VerificationError,
                    VERIFIER.POOL_RUNTIME.VerificationError,
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

    def replace_instruction(self, lines: list[str], index: int, instruction: str) -> None:
        indent = lines[index][: len(lines[index]) - len(lines[index].lstrip())]
        closing = (
            ")"
            if lines[index].rstrip().endswith(")")
            and not instruction.rstrip().endswith(")")
            else ""
        )
        lines[index] = f"{indent}{instruction}{closing}"

    def insert_instructions(
        self, lines: list[str], index: int, instructions: list[str]
    ) -> None:
        indent = lines[index][: len(lines[index]) - len(lines[index].lstrip())]
        lines[index:index] = [f"{indent}{instruction}" for instruction in instructions]

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

        with tempfile.TemporaryDirectory(prefix="pool-burn-wat-mutation-") as temporary:
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
        handler = VERIFIER.WRITER.resolve_handler(
            functions, exports, VERIFIER.HANDLER_EXPORT
        )
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
            VERIFIER.prove_pool_burn_wat_context(mutated)

    def selected_setter_index(self, context: dict[str, Any], field: str) -> int:
        handler = context["handler"]
        if context["profile"]["control_generation"] == "legacy":
            return VERIFIER.single_call(
                handler, f"schema/Pool#set:{field}", f"{field} setter"
            )
        key = next(
            index
            for index, line in enumerate(handler.lines)
            if VERIFIER.decoded_constant(line, context["memory"]) == field
        )
        return key + 2

    def conversion_calls(self, context: dict[str, Any]) -> list[int]:
        return [
            index
            for index, line in enumerate(context["handler"].lines)
            if (VERIFIER.call_name(line) or "").endswith(
                "src/utils/index/convertTokenToDecimal"
            )
        ]

    def test_committed_contract_is_the_deterministic_projection(self) -> None:
        self.assertEqual(
            self.contract,
            VERIFIER.expected_contract_from_sources(self.sources),
        )
        self.assertEqual(
            (self.contract["format_version"], self.contract["contract_version"]),
            (1, "uniswap-v3-pool-burn-semantics/v1"),
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
            "8 mappings, 16 segment-field call-flow evidence records, 28 diffs",
            result.stdout,
        )

    def test_all_segments_and_cumulative_counts_are_exact(self) -> None:
        self.assertEqual(len(self.contract["mapping_proofs"]), 8)
        self.assertEqual(len(self.contract["segments"]), 8)
        self.assertEqual(len(self.contract["segment_diffs"]), 28)
        self.assertEqual(
            sum(
                len(segment["semantic_surface"]["fields"])
                for segment in self.contract["segments"]
            ),
            16,
        )
        scope = self.contract["scope"]
        self.assertEqual(
            (
                scope["inherited_initialize_selected_field_count"],
                scope["cumulative_selected_field_count"],
                scope["inherited_initialize_residual_field_count"],
                scope["cumulative_residual_field_count"],
            ),
            (36, 36, 230, 230),
        )

    def test_only_scoped_truths_are_promoted(self) -> None:
        truth = self.contract["truth_boundary"]
        self.assertEqual(
            {key for key, value in truth.items() if value},
            set(VERIFIER.TRUE_FLAGS),
        )
        self.assertEqual(
            {key for key, value in truth.items() if not value},
            set(VERIFIER.FALSE_FLAGS),
        )
        for segment in self.contract["segments"]:
            self.assertEqual(segment["execution_model"], "undecided")
            self.assertFalse(segment["backfill_allowed"])
            self.assertFalse(
                segment["semantic_surface"]["complete_pool_burn_handler_semantics"]
            )
            self.assertFalse(
                segment["semantic_surface"]["complete_pool_entity_history"]
            )
            self.assertFalse(
                segment["semantic_surface"]["selected_handler_projection_complete"]
            )
            self.assertTrue(
                segment["semantic_surface"]["selected_setter_and_save_call_flow_bound"]
            )
            for field in segment["semantic_surface"]["fields"]:
                self.assertFalse(field["complete_selected_handler_projection"])

    def test_unmodified_wat_roundtrip_preserves_legacy_and_modern_proofs(self) -> None:
        for profile in ("legacy-mainnet-root", "modern-mainnet"):
            with self.subTest(profile=profile):
                context = self.by_profile[profile]
                proof = VERIFIER.prove_pool_burn_wat_context(
                    self.roundtrip_context(context, [])
                )
                self.assertTrue(proof["selected_setter_and_save_call_flow_bound"])
                self.assertFalse(
                    proof["selected_handler_structural_wat_projection_complete"]
                )

    # Mutation family 1: the Pool must be loaded from the trigger address.
    def test_pool_load_identity_mutations_are_rejected(self) -> None:
        for profile in ("legacy-mainnet-root", "modern-mainnet"):
            context = self.by_profile[profile]
            load = VERIFIER.prove_pool_load(context)
            load_index = load["handler_load_wat_line"] - context["handler"].start_line

            def mutate(lines: list[str], _context: dict[str, Any]) -> None:
                self.insert_instructions(
                    lines,
                    load_index - 3,
                    ["i32.const 4", "i32.add"],
                )

            with self.subTest(profile=profile):
                self.assert_wat_rejected(
                    context,
                    [(context["handler"].name, mutate)],
                    f"{profile} Pool ID uses trigger address plus four",
                )

    # Mutation family 2: Burn amount0/amount1 are ABI parameters 4/5 exactly.
    def test_event_parameter_index_mutations_are_rejected(self) -> None:
        for profile in ("legacy-mainnet-root", "modern-mainnet"):
            context = self.by_profile[profile]
            generation = context["profile"]["control_generation"]
            proof = VERIFIER.prove_pool_burn_wat_context(context)
            for field, wrong_index in (
                ("totalValueLockedToken0", 5),
                ("totalValueLockedToken1", 4),
            ):
                if generation == "legacy":
                    getter_name = proof["event_amount_and_decimal_flows"]["fields"][
                        field
                    ]["parameter_getter"]["function"]
                    function = context["functions"][getter_name]
                    expected_index = VERIFIER.SELECTED_FIELDS[field][
                        "event_parameter_index"
                    ]

                    def mutate(
                        lines: list[str],
                        _context: dict[str, Any],
                        expected_index: int = expected_index,
                        wrong_index: int = wrong_index,
                    ) -> None:
                        index = next(
                            item
                            for item, line in enumerate(lines)
                            if VERIFIER.normalized(line)
                            == f"i32.const {expected_index}"
                        )
                        self.replace_instruction(lines, index, f"i32.const {wrong_index}")

                    mutations = [(function.name, mutate)]
                else:
                    ordinal = list(VERIFIER.SELECTED_FIELDS).index(field)
                    conversion = self.conversion_calls(context)[ordinal]
                    parameter = conversion - 6

                    def mutate(
                        lines: list[str],
                        _context: dict[str, Any],
                        parameter: int = parameter,
                        wrong_index: int = wrong_index,
                    ) -> None:
                        self.replace_instruction(
                            lines, parameter, f"i32.const {wrong_index}"
                        )

                    mutations = [(context["handler"].name, mutate)]
                with self.subTest(profile=profile, field=field):
                    self.assert_wat_rejected(
                        context,
                        mutations,
                        f"{profile} {field} reads the other Burn amount",
                    )

        legacy = self.by_profile["legacy-mainnet-root"]
        constructor = self.function_by_suffix(
            legacy, "Initialize__Params#constructor"
        )

        def return_event(lines: list[str], _context: dict[str, Any]) -> None:
            self.replace_instruction(lines, 10, "local.get $p0")

        self.assert_wat_rejected(
            legacy,
            [(constructor.name, return_event)],
            "legacy amount wrapper returns the event instead of its fresh wrapper",
        )

        modern = self.by_profile["modern-mainnet"]
        conversion = self.conversion_calls(modern)[0]
        wrapper_event_read = conversion - 11

        def reassign_event(lines: list[str], _context: dict[str, Any]) -> None:
            self.insert_instructions(
                lines,
                wrapper_event_read,
                [
                    "local.get $p0",
                    "i32.const 4",
                    "i32.add",
                    "local.set $p0",
                ],
            )

        self.assert_wat_rejected(
            modern,
            [(modern["handler"].name, reassign_event)],
            "modern amount wrapper stores a successfully reassigned event pointer",
        )

    # Mutation family 3: each amount must use the matching Pool token's decimals.
    def test_token_decimal_source_substitutions_are_rejected(self) -> None:
        for profile in ("legacy-mainnet-root", "modern-mainnet"):
            context = self.by_profile[profile]
            pool = VERIFIER.prove_pool_load(context)
            tokens = VERIFIER.prove_token_loads_and_guard(context, pool)
            conversions = self.conversion_calls(context)
            for ordinal, field in enumerate(VERIFIER.SELECTED_FIELDS):
                token_field = VERIFIER.SELECTED_FIELDS[field]["pool_token_field"]
                other = "token1" if token_field == "token0" else "token0"
                receiver = conversions[ordinal] - 2
                wrong_local = tokens["token_entity_locals"][other]

                def mutate(
                    lines: list[str],
                    _context: dict[str, Any],
                    receiver: int = receiver,
                    wrong_local: str = wrong_local,
                ) -> None:
                    self.replace_instruction(
                        lines, receiver, f"local.get {wrong_local}"
                    )

                with self.subTest(profile=profile, field=field):
                    self.assert_wat_rejected(
                        context,
                        [(context["handler"].name, mutate)],
                        f"{profile} {field} uses the other Token entity",
                    )

    # Mutation family 4: Token.decimals must use its exact key and BigInt type.
    def test_token_decimals_key_and_type_mutations_are_rejected(self) -> None:
        for profile in ("legacy-mainnet-root", "modern-mainnet"):
            context = self.by_profile[profile]
            getter = self.function_by_suffix(context, "schema/Token#get:decimals")
            wrong_key = self.constant_line(context, "derivedETH")

            def mutate_key(lines: list[str], _context: dict[str, Any]) -> None:
                self.replace_instruction(lines, 2, wrong_key)

            with self.subTest(profile=profile, mutation="key"):
                self.assert_wat_rejected(
                    context,
                    [(getter.name, mutate_key)],
                    f"{profile} Token.decimals key substitution",
                )

            string_target = next(
                VERIFIER.call_name(line)
                for function in context["functions"].values()
                for line in function.lines
                if (VERIFIER.call_name(line) or "").endswith("Value#toString")
            )

            def mutate_type(lines: list[str], _context: dict[str, Any]) -> None:
                index = next(
                    item
                    for item, line in enumerate(lines)
                    if (VERIFIER.call_name(line) or "").endswith("Value#toBigInt")
                )
                self.replace_instruction(lines, index, f"call ${string_target}")

            with self.subTest(profile=profile, mutation="type"):
                self.assert_wat_rejected(
                    context,
                    [(getter.name, mutate_type)],
                    f"{profile} Token.decimals deserialized as String",
                )

            namespace = (
                "~lib/@graphprotocol/graph-ts/common/value/Value"
                if context["profile"]["control_generation"] == "modern"
                else "~lib/@graphprotocol/graph-ts/index/Value"
            )
            decoders = (
                self.function_by_suffix(
                    context, "chain/ethereum/ethereum.Value#toBigInt"
                ),
                self.function_by_suffix(context, f"{namespace}#toBigInt"),
                self.function_by_suffix(context, f"{namespace}#toBigDecimal"),
                self.function_by_suffix(context, f"{namespace}#toString"),
            )
            for decoder in decoders:

                def corrupt_payload(
                    lines: list[str], _context: dict[str, Any]
                ) -> None:
                    payload = len(lines) - 3
                    self.replace_instruction(lines, payload, "i32.const 0")
                    self.replace_instruction(
                        lines, payload + 1, "i64.extend_i32_u"
                    )
                    self.replace_instruction(lines, payload + 2, "i32.wrap_i64")

                with self.subTest(profile=profile, decoder=decoder.name):
                    self.assert_wat_rejected(
                        context,
                        [(decoder.name, corrupt_payload)],
                        f"{profile} {decoder.name} returns zero instead of its payload",
                    )

    # Mutation family 5: ZERO_BI and ONE_BI initialization is semantic input.
    def test_decimal_constant_initialization_mutations_are_rejected(self) -> None:
        for profile in ("legacy-mainnet-root", "modern-mainnet"):
            context = self.by_profile[profile]
            constants = VERIFIER.prove_numeric_constant_initializers(context)
            function = context["functions"][constants["initializer_function"]]
            generation = context["profile"]["control_generation"]
            for constant, wrong in (("zero", 1), ("one", 0)):

                def mutate(
                    lines: list[str],
                    _context: dict[str, Any],
                    constant: str = constant,
                    wrong: int = wrong,
                ) -> None:
                    if generation == "legacy":
                        index = 1 if constant == "zero" else 4
                    else:
                        global_name = (
                            "$src/utils/constants/ZERO_BI"
                            if constant == "zero"
                            else "$src/utils/constants/ONE_BI"
                        )
                        assignment = next(
                            item
                            for item, line in enumerate(lines)
                            if VERIFIER.normalized(line)
                            == f"global.set {global_name}"
                        )
                        index = assignment - 2
                    self.replace_instruction(lines, index, f"i32.const {wrong}")

                with self.subTest(profile=profile, constant=constant):
                    self.assert_wat_rejected(
                        context,
                        [(function.name, mutate)],
                        f"{profile} {constant} BigInt initializer corruption",
                    )

    # Mutation family 6: decimal scaling is base ten with a closed exponent loop.
    def test_decimal_exponent_mutations_are_rejected(self) -> None:
        for profile in ("legacy-mainnet-root", "modern-mainnet"):
            context = self.by_profile[profile]
            exponent = self.function_by_suffix(
                context, "src/utils/index/exponentToBigDecimal"
            )
            one = self.constant_line(context, "1")

            def mutate(lines: list[str], _context: dict[str, Any]) -> None:
                index = next(
                    item
                    for item, line in enumerate(lines)
                    if VERIFIER.decoded_constant(line, context["memory"]) == "10"
                )
                self.replace_instruction(lines, index, one)

            with self.subTest(profile=profile):
                self.assert_wat_rejected(
                    context,
                    [(exponent.name, mutate)],
                    f"{profile} decimal exponent base ten replaced by one",
                )

            generation = context["profile"]["control_generation"]
            predicate = 11 if generation == "legacy" else 13
            loop_end = 23 if generation == "legacy" else 25

            def remove_predicate(
                lines: list[str], _context: dict[str, Any]
            ) -> None:
                self.replace_instruction(lines, predicate, "drop")
                self.replace_instruction(lines, loop_end, "nop")

            with self.subTest(profile=profile, mutation="predicate"):
                self.assert_wat_rejected(
                    context,
                    [(exponent.name, remove_predicate)],
                    f"{profile} exponent loop predicate removed",
                )

    # Mutation family 7: nonzero decimals divide by 10^decimals, never multiply.
    def test_decimal_conversion_operator_mutations_are_rejected(self) -> None:
        for profile in ("legacy-mainnet-root", "modern-mainnet"):
            context = self.by_profile[profile]
            conversion = self.function_by_suffix(
                context, "src/utils/index/convertTokenToDecimal"
            )
            times_target = next(
                VERIFIER.call_name(line)
                for function in context["functions"].values()
                for line in function.lines
                if (VERIFIER.call_name(line) or "").endswith("BigDecimal#times")
            )

            def mutate(lines: list[str], _context: dict[str, Any]) -> None:
                index = next(
                    item
                    for item, line in enumerate(lines)
                    if (VERIFIER.call_name(line) or "").endswith("BigDecimal#div")
                )
                self.replace_instruction(lines, index, f"call ${times_target}")

            with self.subTest(profile=profile):
                self.assert_wat_rejected(
                    context,
                    [(conversion.name, mutate)],
                    f"{profile} decimal division replaced by multiplication",
                )

            times = self.function_by_suffix(context, "BigDecimal#times")
            plus_host = next(
                VERIFIER.call_name(line)
                for function in context["functions"].values()
                for line in function.lines
                if (VERIFIER.call_name(line) or "").endswith("bigDecimal.plus")
            )

            def corrupt_helper(lines: list[str], _context: dict[str, Any]) -> None:
                target = next(
                    index
                    for index, line in enumerate(lines)
                    if (VERIFIER.call_name(line) or "").endswith(
                        "bigDecimal.times"
                    )
                )
                self.replace_instruction(lines, target, f"call ${plus_host}")

            with self.subTest(profile=profile, mutation="helper-body"):
                self.assert_wat_rejected(
                    context,
                    [(times.name, corrupt_helper)],
                    f"{profile} BigDecimal.times helper delegates to host addition",
                )

    # Mutation family 8: each subtraction reads the matching old Pool TVL field.
    def test_old_tvl_getter_substitutions_are_rejected(self) -> None:
        for profile in ("legacy-mainnet-root", "modern-mainnet"):
            context = self.by_profile[profile]
            generation = context["profile"]["control_generation"]
            for field in VERIFIER.SELECTED_FIELDS:
                other = (
                    "totalValueLockedToken1"
                    if field == "totalValueLockedToken0"
                    else "totalValueLockedToken0"
                )
                setter = self.selected_setter_index(context, field)
                getter = setter - (3 if generation == "legacy" else 17)
                wrong_target = self.function_by_suffix(
                    context, f"schema/Pool#get:{other}"
                ).name

                def mutate(
                    lines: list[str],
                    _context: dict[str, Any],
                    getter: int = getter,
                    wrong_target: str = wrong_target,
                ) -> None:
                    self.replace_instruction(lines, getter, f"call ${wrong_target}")

                with self.subTest(profile=profile, field=field):
                    self.assert_wat_rejected(
                        context,
                        [(context["handler"].name, mutate)],
                        f"{profile} {field} reads the other old TVL",
                    )

    # Mutation family 9: subtraction direction is old TVL minus Burn amount.
    def test_subtraction_direction_mutations_are_rejected(self) -> None:
        for profile in ("legacy-mainnet-root", "modern-mainnet"):
            context = self.by_profile[profile]
            generation = context["profile"]["control_generation"]
            field = "totalValueLockedToken0"
            proof = VERIFIER.prove_pool_burn_wat_context(context)
            amount_local = proof["event_amount_and_decimal_flows"]["fields"][field][
                "converted_amount_local"
            ]
            pool_local = proof["pool_load_identity"]["pool_entity_local"]
            getter_target = self.function_by_suffix(
                context, f"schema/Pool#get:{field}"
            ).name
            setter = self.selected_setter_index(context, field)
            receiver = setter - (4 if generation == "legacy" else 18)

            def mutate(lines: list[str], _context: dict[str, Any]) -> None:
                self.replace_instruction(lines, receiver, f"local.get {amount_local}")
                self.replace_instruction(lines, receiver + 1, f"local.get {pool_local}")
                self.replace_instruction(lines, receiver + 2, f"call ${getter_target}")

            with self.subTest(profile=profile):
                self.assert_wat_rejected(
                    context,
                    [(context["handler"].name, mutate)],
                    f"{profile} computes Burn amount minus old Pool TVL",
                )

    # Mutation family 10: subtraction cannot be replaced by another operator.
    def test_subtraction_operator_mutations_are_rejected(self) -> None:
        for profile in ("legacy-mainnet-root", "modern-mainnet"):
            context = self.by_profile[profile]
            generation = context["profile"]["control_generation"]
            setter = self.selected_setter_index(
                context, "totalValueLockedToken0"
            )
            subtraction = setter - (1 if generation == "legacy" else 15)
            plus_target = next(
                VERIFIER.call_name(line)
                for function in context["functions"].values()
                for line in function.lines
                if (VERIFIER.call_name(line) or "").endswith("BigDecimal#plus")
            )

            def mutate(lines: list[str], _context: dict[str, Any]) -> None:
                self.replace_instruction(lines, subtraction, f"call ${plus_target}")

            with self.subTest(profile=profile):
                self.assert_wat_rejected(
                    context,
                    [(context["handler"].name, mutate)],
                    f"{profile} Pool TVL subtraction replaced by addition",
                )

    # Mutation family 11: selected setters use their exact field keys.
    def test_setter_field_key_mutations_are_rejected(self) -> None:
        for profile in ("legacy-mainnet-root", "modern-mainnet"):
            context = self.by_profile[profile]
            generation = context["profile"]["control_generation"]
            field = "totalValueLockedToken0"
            wrong_key = self.constant_line(context, "totalValueLockedToken1")
            if generation == "legacy":
                function = self.function_by_suffix(
                    context, f"schema/Pool#set:{field}"
                )
                key = 2
            else:
                function = context["handler"]
                key = self.selected_setter_index(context, field) - 2

            def mutate(lines: list[str], _context: dict[str, Any]) -> None:
                self.replace_instruction(lines, key, wrong_key)

            with self.subTest(profile=profile):
                self.assert_wat_rejected(
                    context,
                    [(function.name, mutate)],
                    f"{profile} token0 TVL setter writes token1 key",
                )

    # Mutation family 12: setters require BigDecimal Value kind and payload flow.
    def test_setter_value_kind_and_payload_mutations_are_rejected(self) -> None:
        for profile in ("legacy-mainnet-root", "modern-mainnet"):
            context = self.by_profile[profile]
            generation = context["profile"]["control_generation"]
            if generation == "legacy":
                function = self.function_by_suffix(context, "Value.fromBigDecimal")
                kind = 4
                payload = 8
            else:
                function = context["handler"]
                key = self.selected_setter_index(
                    context, "totalValueLockedToken0"
                ) - 2
                kind = key - 6
                payload = key - 12

            def mutate_kind(lines: list[str], _context: dict[str, Any]) -> None:
                self.replace_instruction(lines, kind, "i32.const 7")

            with self.subTest(profile=profile, mutation="kind"):
                self.assert_wat_rejected(
                    context,
                    [(function.name, mutate_kind)],
                    f"{profile} selected setter uses a non-BigDecimal Value kind",
                )

            def mutate_payload(lines: list[str], _context: dict[str, Any]) -> None:
                indent = lines[payload][
                    : len(lines[payload]) - len(lines[payload].lstrip())
                ]
                lines[payload : payload + 1] = [
                    f"{indent}drop",
                    f"{indent}i64.const 0",
                ]

            with self.subTest(profile=profile, mutation="payload"):
                self.assert_wat_rejected(
                    context,
                    [(function.name, mutate_payload)],
                    f"{profile} selected setter discards the subtraction payload",
                )

    # Mutation family 13: setters must receive the exact trigger-loaded Pool.
    def test_selected_setter_pool_identity_mutations_are_rejected(self) -> None:
        for profile in ("legacy-mainnet-root", "modern-mainnet"):
            context = self.by_profile[profile]
            generation = context["profile"]["control_generation"]
            pool = VERIFIER.prove_pool_load(context)
            tokens = VERIFIER.prove_token_loads_and_guard(context, pool)
            setter = self.selected_setter_index(
                context, "totalValueLockedToken0"
            )
            receiver = setter - (5 if generation == "legacy" else 3)
            token_local = tokens["token_entity_locals"]["token0"]

            def mutate(lines: list[str], _context: dict[str, Any]) -> None:
                self.replace_instruction(
                    lines, receiver, f"local.get {token_local}"
                )

            with self.subTest(profile=profile):
                self.assert_wat_rejected(
                    context,
                    [(context["handler"].name, mutate)],
                    f"{profile} selected setter receives Token instead of Pool",
                )

    # Mutation family 14: modern missing-token behavior is a two-token no-op.
    def test_modern_two_token_guard_noop_mutations_are_rejected(self) -> None:
        context = self.by_profile["modern-mainnet"]
        pool = VERIFIER.prove_pool_load(context)
        tokens = VERIFIER.prove_token_loads_and_guard(context, pool)
        guard = tokens["selected_update_guard_start_index"]
        self.assertIsNotNone(guard)
        assert guard is not None

        def mutate(lines: list[str], _context: dict[str, Any]) -> None:
            del lines[guard - 3 : guard]

        self.assert_wat_rejected(
            context,
            [(context["handler"].name, mutate)],
            "modern guard checks token1 only and updates when token0 is missing",
        )

    # Mutation family 15: Pool.save is present, ordered, and uses the same Pool.
    def test_pool_save_presence_order_and_receiver_mutations_are_rejected(self) -> None:
        for profile in ("legacy-mainnet-root", "modern-mainnet"):
            context = self.by_profile[profile]
            handler = context["handler"]
            generation = context["profile"]["control_generation"]
            save = VERIFIER.single_call(handler, "schema/Pool#save", "Pool.save")

            def remove(lines: list[str], _context: dict[str, Any]) -> None:
                del lines[save - 1 : save + 1]

            with self.subTest(profile=profile, mutation="missing"):
                self.assert_wat_rejected(
                    context,
                    [(handler.name, remove)],
                    f"{profile} Pool.save removed",
                )

            first_setter = self.selected_setter_index(
                context, "totalValueLockedToken0"
            )
            selected_start = first_setter - (
                5 if generation == "legacy" else 18
            )

            def reorder(lines: list[str], _context: dict[str, Any]) -> None:
                pair = lines[save - 1 : save + 1]
                del lines[save - 1 : save + 1]
                lines[selected_start:selected_start] = pair

            with self.subTest(profile=profile, mutation="ordering"):
                self.assert_wat_rejected(
                    context,
                    [(handler.name, reorder)],
                    f"{profile} Pool.save moved before selected setters",
                )

            pool = VERIFIER.prove_pool_load(context)
            tokens = VERIFIER.prove_token_loads_and_guard(context, pool)
            wrong_local = tokens["token_entity_locals"]["token0"]

            def wrong_receiver(lines: list[str], _context: dict[str, Any]) -> None:
                self.replace_instruction(
                    lines, save - 1, f"local.get {wrong_local}"
                )

            with self.subTest(profile=profile, mutation="receiver"):
                self.assert_wat_rejected(
                    context,
                    [(handler.name, wrong_receiver)],
                    f"{profile} Pool.save receives Token",
                )

    # Mutation family 16: hidden direct, helper, indirect, and remove effects fail.
    def test_hidden_store_and_remove_effect_mutations_are_rejected(self) -> None:
        legacy = self.by_profile["legacy-mainnet-root"]
        legacy_handler = legacy["handler"]
        legacy_save = VERIFIER.single_call(
            legacy_handler, "schema/Pool#save", "legacy Pool.save"
        )
        legacy_pool = VERIFIER.prove_pool_load(legacy)["pool_entity_local"]
        pool_save_helper = self.function_by_suffix(legacy, "schema/Pool#save")

        def direct(lines: list[str], _context: dict[str, Any]) -> None:
            self.insert_instructions(
                lines,
                legacy_save - 1,
                [
                    "i32.const 0",
                    "if",
                    f"  local.get {legacy_pool}",
                    f"  call ${pool_save_helper.name}",
                    "end",
                ],
            )

        self.assert_wat_rejected(
            legacy,
            [(legacy_handler.name, direct)],
            "hidden direct Pool.save",
        )

        helper = self.function_by_suffix(legacy, "/updatePoolDayData")

        def transitive(lines: list[str], _context: dict[str, Any]) -> None:
            insert = 1
            while insert < len(lines) and VERIFIER.normalized(lines[insert]).startswith(
                "(local "
            ):
                insert += 1
            self.insert_instructions(
                lines,
                insert,
                [
                    "i32.const 0",
                    "if",
                    "  i32.const 0",
                    f"  call ${pool_save_helper.name}",
                    "end",
                ],
            )

        self.assert_wat_rejected(
            legacy,
            [(helper.name, transitive)],
            "hidden helper-reachable Pool.save",
        )

        modern = self.by_profile["modern-mainnet"]
        self.assertEqual(len(modern["indirect_targets"]), 1)
        indirect = modern["functions"][modern["indirect_targets"][0]]
        modern_pool_save = self.function_by_suffix(modern, "schema/Pool#save")

        def indirect_store(lines: list[str], _context: dict[str, Any]) -> None:
            insert = 1
            while insert < len(lines) and VERIFIER.normalized(lines[insert]).startswith(
                "(local "
            ):
                insert += 1
            self.insert_instructions(
                lines,
                insert,
                [
                    "i32.const 0",
                    "if",
                    "  i32.const 0",
                    f"  call ${modern_pool_save.name}",
                    "end",
                ],
            )

        self.assert_wat_rejected(
            modern,
            [(indirect.name, indirect_store)],
            "hidden indirect-table Pool.save",
        )

        pool_constant = self.constant_line(legacy, "Pool")
        bytes_to_hex = next(
            VERIFIER.call_name(line)
            for line in legacy_handler.lines
            if (VERIFIER.call_name(line) or "").endswith(
                "typeConversion.bytesToHex"
            )
        )
        remove_symbol = "audit/pool-store.remove"

        def remove_effect(lines: list[str], _context: dict[str, Any]) -> None:
            self.insert_instructions(
                lines,
                legacy_save - 1,
                [
                    pool_constant,
                    "local.get $p0",
                    "i32.load",
                    f"call ${bytes_to_hex}",
                    f"call ${remove_symbol}",
                ],
            )

        def add_remove_import(
            lines: list[str], _context: dict[str, Any]
        ) -> None:
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
            legacy,
            [(legacy_handler.name, remove_effect)],
            "reachable Pool store.remove",
            module_mutation=add_remove_import,
        )

    def test_same_wat_pool_runtime_capsules_are_consumed(self) -> None:
        runtime_by_cid = self.sources["pool_runtime_proof_by_cid"]
        self.assertEqual(set(runtime_by_cid), set(self.contexts))
        self.assertEqual(len(runtime_by_cid), 8)
        for cid, context in self.contexts.items():
            runtime = runtime_by_cid[cid]
            self.assertEqual(
                runtime["artifact_selection_tuple"][:2],
                [context["profile"]["profile_id"], cid],
            )
        for profile in ("modern-base", "legacy-mainnet-root"):
            with self.subTest(profile=profile):
                proof = VERIFIER.prove_pool_burn_wat_context(self.by_profile[profile])
                binding = proof["pool_runtime_binding"]
                self.assertEqual(
                    binding["contract_version"],
                    VERIFIER.POOL_RUNTIME_CONTRACT_VERSION,
                )
                self.assertTrue(binding["same_context_runtime_capsule_recomputed"])
                facts = binding["collection_facts"]
                self.assertIn("event_param_array_get", facts)
                self.assertIn("typed_map_get", facts)
                self.assertIn("typed_map_set", facts)
                if profile == "modern-base":
                    self.assertTrue(
                        facts["collection_mutation_chain_structurally_closed"]
                    )
                else:
                    self.assertIn("typed_map_get_entry", facts)
                    self.assertIn("entry_array_runtime", facts)
                    self.assertIn("do not reenter exported memory.reset", facts["freshness_scope"])

        mismatched = dict(self.by_profile["modern-base"])
        mismatched["profile"] = {
            **mismatched["profile"],
            "profile_id": "modern-mainnet",
        }
        with self.assertRaises(self.expected_errors):
            VERIFIER.prove_pool_burn_wat_context(mismatched)

    def test_baseline_alias_and_dynamic_key_residuals_are_explicit(self) -> None:
        expected = {
            "modern-base": (149, 147, 526),
            "legacy-mainnet-root": (54, 52, 166),
        }
        for profile, counts in expected.items():
            with self.subTest(profile=profile):
                proof = VERIFIER.prove_pool_burn_wat_context(self.by_profile[profile])
                persistence = proof["persistence_and_effect_closure"]
                inventory = persistence["reachable_in_memory_mutation_inventory"]
                self.assertEqual(
                    (
                        inventory["reachable_typed_map_set_site_count"],
                        inventory[
                            "baseline_typed_map_set_sites_without_selected_receiver_key_value_proof"
                        ],
                        inventory[
                            "baseline_direct_memory_write_sites_without_selected_payload_alias_proof"
                        ],
                    ),
                    counts,
                )
                self.assertFalse(
                    inventory["baseline_effect_inventory_semantically_closed_for_selected_fields"]
                )
                self.assertFalse(persistence["no_later_selected_field_overwrites_proven"])
                self.assertFalse(persistence["selected_tvl_persistence_projection_complete"])

    def test_runtime_setter_getter_and_allocator_counterexamples_are_rejected(self) -> None:
        cases = (
            ("modern-base", VERIFIER.MODERN_ENTITY_MAP_SET_CALL, 2, "return"),
            ("legacy-mainnet-root", VERIFIER.LEGACY_ENTITY_MAP_SET_CALL, 2, "return"),
            ("modern-base", VERIFIER.EVENT_PARAM_ARRAY_GET_CALL, 16, "i32.const 1"),
            ("legacy-mainnet-root", "EventParam>#__get", 11, "i32.const 1"),
            ("modern-base", "~lib/rt/stub/__alloc", 72, "local.get $l1)"),
            (
                "legacy-mainnet-root",
                "allocator/arena/__memory_allocate",
                60,
                "local.get $l1)",
            ),
        )
        for profile, suffix, index, replacement in cases:
            context = self.by_profile[profile]
            function = self.function_by_suffix(context, suffix)

            def mutate(
                lines: list[str],
                _context: dict[str, Any],
                index: int = index,
                replacement: str = replacement,
            ) -> None:
                if replacement == "return" and profile == "modern-base":
                    self.insert_instructions(lines, index, [replacement])
                else:
                    self.replace_instruction(lines, index, replacement)

            with self.subTest(profile=profile, suffix=suffix):
                self.assert_wat_rejected(
                    context,
                    [(function.name, mutate)],
                    f"{profile} shared runtime counterexample {suffix}",
                )

    def test_bytes_to_hex_import_identity_mutations_are_rejected(self) -> None:
        for profile, expected_module, wrong_module in (
            ("modern-base", "conversion", "index"),
            ("legacy-mainnet-root", "index", "conversion"),
        ):
            context = self.by_profile[profile]

            def mutate_import(
                lines: list[str],
                _context: dict[str, Any],
                expected_module: str = expected_module,
                wrong_module: str = wrong_module,
            ) -> None:
                old = f'(import "{expected_module}" "typeConversion.bytesToHex"'
                new = f'(import "{wrong_module}" "typeConversion.bytesToHex"'
                matches = [index for index, line in enumerate(lines) if old in line]
                self.assertEqual(len(matches), 1)
                lines[matches[0]] = lines[matches[0]].replace(old, new, 1)

            with self.subTest(profile=profile):
                self.assert_wat_rejected(
                    context,
                    [],
                    f"{profile} bytesToHex host module substitution",
                    module_mutation=mutate_import,
                )

    def test_reachable_dynamic_helper_and_direct_payload_writes_are_rejected(self) -> None:
        context = self.by_profile["modern-base"]
        proof = VERIFIER.prove_pool_burn_wat_context(context)
        handler = context["handler"]
        first = "totalValueLockedToken0"
        setter = self.selected_setter_index(context, first)
        value_local = proof["field_value_and_setter_flow"]["fields"][first]["setter"][
            "value_local"
        ]

        def direct_payload_overwrite(
            lines: list[str], _context: dict[str, Any]
        ) -> None:
            self.insert_instructions(
                lines,
                setter + 1,
                [
                    "i32.const 0",
                    "if",
                    f"  local.get {value_local}",
                    "  i64.const 0",
                    "  i64.store offset=8",
                    "end",
                ],
            )

        self.assert_wat_rejected(
            context,
            [(handler.name, direct_payload_overwrite)],
            "modern selected Value payload overwritten after TypedMap#set",
        )

        helper = self.function_by_suffix(context, "/updatePoolDayData")
        selected_key = self.constant_line(context, first)

        def helper_hidden_selected_write(
            lines: list[str], _context: dict[str, Any]
        ) -> None:
            insert = 1
            while insert < len(lines) and VERIFIER.normalized(lines[insert]).startswith(
                "(local "
            ):
                insert += 1
            self.insert_instructions(
                lines,
                insert,
                [
                    "i32.const 0",
                    "if",
                    "  i32.const 0",
                    f"  {selected_key}",
                    "  i32.const 0",
                    f"  call ${VERIFIER.MODERN_ENTITY_MAP_SET_CALL}",
                    "end",
                ],
            )

        self.assert_wat_rejected(
            context,
            [(helper.name, helper_hidden_selected_write)],
            "modern helper-hidden selected-key TypedMap#set",
        )

        pool_local = proof["pool_load_identity"]["pool_entity_local"]

        def dynamic_key_write(lines: list[str], _context: dict[str, Any]) -> None:
            self.insert_instructions(
                lines,
                setter + 1,
                [
                    "i32.const 0",
                    "if",
                    f"  local.get {pool_local}",
                    "  local.get $p0",
                    "  i32.const 0",
                    f"  call ${VERIFIER.MODERN_ENTITY_MAP_SET_CALL}",
                    "end",
                ],
            )

        self.assert_wat_rejected(
            context,
            [(handler.name, dynamic_key_write)],
            "modern dynamic-key TypedMap#set after selected setter",
        )

    def test_legacy_dynamic_helper_and_direct_payload_writes_are_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-root"]
        proof = VERIFIER.prove_pool_burn_wat_context(context)
        handler = context["handler"]
        first = "totalValueLockedToken0"
        setter_index = self.selected_setter_index(context, first)
        setter_helper = self.function_by_suffix(context, f"schema/Pool#set:{first}")

        def direct_bigdecimal_payload_overwrite(
            lines: list[str], _context: dict[str, Any]
        ) -> None:
            self.insert_instructions(
                lines,
                1,
                [
                    "i32.const 0",
                    "if",
                    "  local.get $p1",
                    "  i64.const 0",
                    "  i64.store offset=8",
                    "end",
                ],
            )

        self.assert_wat_rejected(
            context,
            [(setter_helper.name, direct_bigdecimal_payload_overwrite)],
            "legacy selected BigDecimal payload overwritten before TypedMap#set",
        )

        helper = self.function_by_suffix(context, "/updatePoolDayData")
        selected_key = self.constant_line(context, first)

        def helper_hidden_selected_write(
            lines: list[str], _context: dict[str, Any]
        ) -> None:
            insert = 1
            while insert < len(lines) and VERIFIER.normalized(lines[insert]).startswith(
                "(local "
            ):
                insert += 1
            self.insert_instructions(
                lines,
                insert,
                [
                    "i32.const 0",
                    "if",
                    "  i32.const 0",
                    f"  {selected_key}",
                    "  i32.const 0",
                    f"  call ${VERIFIER.LEGACY_ENTITY_MAP_SET_CALL}",
                    "end",
                ],
            )

        self.assert_wat_rejected(
            context,
            [(helper.name, helper_hidden_selected_write)],
            "legacy helper-hidden selected-key TypedMap#set",
        )

        pool_local = proof["pool_load_identity"]["pool_entity_local"]

        def dynamic_key_write(lines: list[str], _context: dict[str, Any]) -> None:
            self.insert_instructions(
                lines,
                setter_index + 1,
                [
                    "i32.const 0",
                    "if",
                    f"  local.get {pool_local}",
                    "  local.get $p0",
                    "  i32.const 0",
                    f"  call ${VERIFIER.LEGACY_ENTITY_MAP_SET_CALL}",
                    "end",
                ],
            )

        self.assert_wat_rejected(
            context,
            [(handler.name, dynamic_key_write)],
            "legacy dynamic-key TypedMap#set after selected setter",
        )

    def test_adversarial_contract_mutations_fail_closed(self) -> None:
        mutations: list[tuple[str, dict[str, Any]]] = []

        promoted_burn = copy.deepcopy(self.contract)
        promoted_burn["truth_boundary"]["pool_burn_semantics_complete"] = True
        mutations.append(("promoted complete Burn semantics", promoted_burn))

        promoted_history = copy.deepcopy(self.contract)
        promoted_history["truth_boundary"]["pool_complete_entity_history"] = True
        mutations.append(("promoted Pool entity history", promoted_history))

        promoted_alias = copy.deepcopy(self.contract)
        promoted_alias["truth_boundary"][
            "direct_selected_payload_alias_safety_rederived"
        ] = True
        mutations.append(("promoted selected-payload alias safety", promoted_alias))

        promoted_no_overwrite = copy.deepcopy(self.contract)
        promoted_no_overwrite["truth_boundary"][
            "no_later_selected_field_overwrites_proven"
        ] = True
        mutations.append(("promoted no-later-overwrite claim", promoted_no_overwrite))

        promoted_persistence = copy.deepcopy(self.contract)
        promoted_persistence["truth_boundary"][
            "pool_burn_selected_tvl_persistence_proven"
        ] = True
        mutations.append(("promoted selected-TVL persistence", promoted_persistence))

        wrong_runtime = copy.deepcopy(self.contract)
        wrong_runtime["source_contracts"]["pool_runtime"]["raw_sha256"] = "0" * 64
        mutations.append(("substituted Pool runtime contract digest", wrong_runtime))

        wrong_count = copy.deepcopy(self.contract)
        wrong_count["scope"]["cumulative_residual_field_count"] = 0
        mutations.append(("false cumulative residual count", wrong_count))

        removed_segment_field = copy.deepcopy(self.contract)
        removed_segment_field["segments"][0]["semantic_surface"]["fields"].pop()
        removed_segment_field["segments"][0][
            "semantic_surface_sha256"
        ] = VERIFIER.canonical_sha256(
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
        with tempfile.TemporaryDirectory(prefix="pool-burn-duplicate-json-") as temporary:
            path = Path(temporary) / "duplicate.json"
            path.write_text('{"format_version": 1, "format_version": 2}\n')
            with self.assertRaises(VERIFIER.VerificationError):
                VERIFIER.load_json_strict(path)


if __name__ == "__main__":
    unittest.main()
