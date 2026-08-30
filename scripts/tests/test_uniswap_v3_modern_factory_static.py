from __future__ import annotations

import copy
import hashlib
import importlib.util
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections import deque
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Callable
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
VERIFIER_PATH = ROOT / "scripts/verify-uniswap-v3-modern-factory-static.py"
SPEC = importlib.util.spec_from_file_location(
    "uniswap_v3_modern_factory_static", VERIFIER_PATH
)
assert SPEC is not None and SPEC.loader is not None
VERIFIER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VERIFIER
SPEC.loader.exec_module(VERIFIER)


Mutator = Callable[[list[str], dict[str, Any]], None]
SemanticCheck = Callable[[dict[str, Any]], None]
ModuleMutator = Callable[[str], str]


class ModernFactoryStaticTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contexts = VERIFIER.load_contexts(ROOT)
        cls.by_profile = {
            context["profile"]["profile_id"]: context for context in cls.contexts
        }
        cls.contract = VERIFIER.load_json(ROOT / VERIFIER.CONTRACT_PATH)
        cls.proofs = [VERIFIER.prove_modern_static(context) for context in cls.contexts]
        cls.token_constructors = {
            profile: VERIFIER.EFFECTS.prove_factory_effects(context)[
                "generation_frontend"
            ]["token_constructor_proof"]
            for profile, context in cls.by_profile.items()
        }
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
        executable = VERIFIER.WRITER.resolve_wasm2wat(None)
        cls.full_wat = {}
        for profile, context in cls.by_profile.items():
            artifact = (
                ROOT
                / "uniswap-v3/graft-ancestry/v1/artifacts"
                / context["cid"]
            )
            cls.full_wat[profile] = VERIFIER.WRITER.run_wasm2wat(
                executable, artifact
            ).decode()

    @staticmethod
    def set_normalized(lines: list[str], index: int, value: str) -> None:
        indent = lines[index][: len(lines[index]) - len(lines[index].lstrip())]
        lines[index] = f"{indent}{value}"

    @staticmethod
    def insert_normalized(lines: list[str], index: int, values: list[str]) -> None:
        indent = lines[index][: len(lines[index]) - len(lines[index].lstrip())]
        lines[index:index] = [f"{indent}{value}" for value in values]

    def function_selector(self, suffix: str) -> Callable[[dict[str, Any]], Any]:
        return lambda context: VERIFIER.function_by_suffix(context, suffix)

    def field_check(self, context: dict[str, Any]) -> None:
        profile = context["profile"]["profile_id"]
        VERIFIER.prove_field_contract(context, self.token_constructors[profile])

    @staticmethod
    def total_supply_dataflow_check(context: dict[str, Any]) -> None:
        helper = VERIFIER.function_by_suffix(context, "/fetchTokenTotalSupply")
        try:
            VERIFIER.V2.prove_factory_total_supply_helper(
                context["cid"], "modern", helper, context["functions"]
            )
        except VERIFIER.V2.VerificationError as error:
            raise VERIFIER.VerificationError(str(error)) from error

    @staticmethod
    def public_collection_capsule_check(context: dict[str, Any]) -> None:
        VERIFIER.RUNTIME.prove_modern_collection_capsule(
            context,
            VERIFIER.runtime_ops(),
            VERIFIER.MODERN_COLLECTION_SPEC,
        )

    @staticmethod
    def refreshed_reachable_body_bindings_sha256(context: dict[str, Any]) -> str:
        normalized_functions = {
            name.replace("generated/schema/", "src/types/schema/"): function
            for name, function in context["functions"].items()
        }
        root = context["handler"].name.replace(
            "generated/schema/", "src/types/schema/"
        )
        indirect = tuple(
            name.replace("generated/schema/", "src/types/schema/")
            for name in context["indirect"]
        )
        queue: deque[str] = deque([root])
        visited: set[str] = set()
        while queue:
            name = queue.popleft()
            if name in visited:
                continue
            visited.add(name)
            function = normalized_functions[name]
            for raw_line in function.lines:
                target = VERIFIER.call_name(raw_line)
                if target is not None:
                    normalized_target = target.replace(
                        "generated/schema/", "src/types/schema/"
                    )
                    if normalized_target in normalized_functions:
                        queue.append(normalized_target)
                elif VERIFIER.normalized(raw_line).startswith("call_indirect"):
                    queue.extend(indirect)
        bindings = [
            {
                "function": name,
                "body_sha256": hashlib.sha256(
                    normalized_functions[name].payload
                ).hexdigest(),
            }
            for name in sorted(visited)
        ]
        return VERIFIER.EFFECTS.canonical_sha256(bindings)

    def assert_valid_wat_mutation_rejected(
        self,
        label: str,
        selector: Callable[[dict[str, Any]], Any],
        mutate: Mutator,
        semantic_check: SemanticCheck,
        expected_error: str,
        *,
        profile: str = "modern-mainnet",
        refresh_helper_key: str | None = None,
        refresh_fee_slice_authority: bool = False,
        refresh_reachable_body_authority: bool = False,
        mutate_module: ModuleMutator | None = None,
    ) -> None:
        base = self.by_profile[profile]
        function = selector(base)
        lines = list(function.lines)
        mutate(lines, base)
        original_payload = function.payload.decode()
        full_wat = self.full_wat[profile]
        self.assertEqual(full_wat.count(original_payload), 1, label)
        changed_payload = "\n".join(lines) + "\n"
        changed_wat = full_wat.replace(original_payload, changed_payload, 1)
        if mutate_module is not None:
            changed_wat = mutate_module(changed_wat)
        with tempfile.TemporaryDirectory(prefix="modern-factory-static-wat-") as directory:
            wasm_path = Path(directory) / "mutation.wasm"
            validation = subprocess.run(
                [self.wat2wasm, "/dev/stdin", "-o", str(wasm_path), "--debug-names"],
                input=changed_wat.encode(),
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(
                validation.returncode,
                0,
                f"{label} fixture must remain WAT-valid: "
                f"{validation.stderr.decode('utf-8', 'replace')}",
            )
        memory, functions, indirect, exports = VERIFIER.WRITER.parse_wat(changed_wat)
        parsed_handler = VERIFIER.WRITER.resolve_handler(
            functions, exports, "handlePoolCreated"
        )
        handler = VERIFIER.WRITER.WatFunction(
            parsed_handler.name,
            base["handler"].start_line,
            parsed_handler.lines,
            parsed_handler.function_index,
        )
        functions[parsed_handler.name] = handler
        changed = {
            **base,
            "memory": memory,
            "functions": functions,
            "handler": handler,
            "indirect": indirect,
            "module_text": changed_wat,
            "exports": exports,
        }
        if refresh_reachable_body_authority:
            changed["expected"] = {
                **base["expected"],
                "reachable_body_bindings_sha256": self.refreshed_reachable_body_bindings_sha256(
                    changed
                ),
            }
            outer_closure = VERIFIER.EFFECTS.scan_reachable_effects(changed)
            self.assertEqual(
                outer_closure["reachable_function_body_bindings_sha256"],
                changed["expected"]["reachable_body_bindings_sha256"],
                label,
            )
        helper_patch = nullcontext()
        if refresh_helper_key is not None:
            expected = VERIFIER.EXPECTED_HELPERS[profile][refresh_helper_key]
            changed_function = functions[function.name]
            refreshed = (
                expected[0],
                len(changed_function.lines),
                hashlib.sha256(changed_function.payload).hexdigest(),
            )
            helper_patch = mock.patch.dict(
                VERIFIER.EXPECTED_HELPERS[profile],
                {refresh_helper_key: refreshed},
                clear=False,
            )
        fee_slice_patch = nullcontext()
        if refresh_fee_slice_authority:
            fee_slice_patch = mock.patch.dict(
                VERIFIER.EXPECTED_FEE_TIER_SLICE_SHA256,
                {
                    profile: VERIFIER.normalized_slice_sha256(
                        changed["handler"], 1311, 1483
                    )
                },
                clear=False,
            )
        with helper_patch, fee_slice_patch:
            with self.assertRaises(VERIFIER.VerificationError, msg=label) as caught:
                semantic_check(changed)
        message = str(caught.exception)
        self.assertIn(expected_error, message, f"{label}: {message}")

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

    def test_scope_closes_only_the_two_modern_static_paths(self) -> None:
        scope = self.contract["scope"]
        self.assertEqual(
            (
                scope["factory_upstream_path_count"],
                scope["closed_before_this_supplement"],
                scope["newly_closed_complete_static_handler_paths"],
                scope["cumulative_closed_after_this_supplement"],
                scope["residual_after_this_supplement"],
            ),
            (18, 12, 2, 14, 4),
        )
        self.assertEqual(
            (
                scope["stored_field_contract_count_per_mapping"],
                scope["written_field_count_per_mapping"],
                scope["required_absent_field_count_per_mapping"],
                scope["modern_segment_field_projection_count"],
            ),
            (60, 59, 1, 120),
        )
        self.assertEqual(
            (
                scope["v2_global_selected_field_count_before_and_after"],
                scope["v2_global_residual_conditional_field_count_before_and_after"],
            ),
            (34, 232),
        )
        truth = self.contract["truth_boundary"]
        self.assertEqual({key for key, value in truth.items() if value}, VERIFIER.TRUE_FLAGS)
        self.assertEqual(
            {key for key, value in truth.items() if not value}, VERIFIER.FALSE_FLAGS
        )
        self.assertFalse(truth["all_six_factory_complete_static_handler_contracts_proven"])
        self.assertFalse(truth["graph_handler_rollback_proven_by_retained_wat"])
        self.assertFalse(truth["backfill_ready"])
        self.assertFalse(truth["production_ready"])

    def test_each_modern_profile_has_the_complete_bounded_field_contract(self) -> None:
        self.assertEqual(
            {proof["profile_id"] for proof in self.proofs},
            {"modern-base", "modern-mainnet"},
        )
        for proof in self.proofs:
            fields = proof["field_contract"]
            self.assertEqual(
                (
                    fields["stored_field_contract_count"],
                    fields["written_field_count"],
                    fields["required_absent_fields"],
                    fields["handler_typed_map_set_count"],
                ),
                (60, 59, ["Pool.tick"], 76),
            )
            self.assertTrue(fields["token_id_constructor_flow"]["constructor_id_and_receiver_machine_proven"])
            traces = proof["normal_return_and_partial_effect_contract"]
            self.assertEqual(
                traces["normal_exit_traces"],
                [
                    [],
                    ["Bundle.save"],
                    list(VERIFIER.FULL_SUFFIX),
                    ["Bundle.save", *VERIFIER.FULL_SUFFIX],
                ],
            )
            self.assertFalse(proof["graph_handler_rollback_proven_by_retained_wat"])
            self.assertFalse(proof["actual_historic_call_outcomes_bound"])

    def test_field_key_constant_receiver_and_event_mutations_are_valid_and_rejected(self) -> None:
        def field_key(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 1595, VERIFIER.normalized(lines[1643]))

        def zero_bigint(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(
                lines, 1566, "global.get $src/utils/constants/ONE_BI"
            )

        def receiver(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 1578, "local.get $l4")

        def token_event_index(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 614, "i32.const 1")

        def pool_event_index(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 512, "i32.const 3")

        def fee_event_index(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 1323, "i32.const 3")

        def timestamp_source(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 1500, "i32.load offset=28")

        cases = [
            ("field-key substitution", field_key, self.field_check, "field key drift"),
            ("ZERO_BI substitution", zero_bigint, self.field_check, "Pool.liquidity ZERO_BI exact payload source drift"),
            ("entity receiver substitution", receiver, self.field_check, "Pool.liquidity exact entity receiver drift"),
            ("token event-index substitution", token_event_index, self.field_check, "event/helper argument flow drift"),
            ("Pool.id event-index substitution", pool_event_index, VERIFIER.prove_special_field_flows, "Pool.id continuous event[4]/decode/payload source drift"),
            ("fee event-index substitution", fee_event_index, VERIFIER.prove_special_field_flows, "Pool.feeTier exact retained conversion slice drift"),
            ("timestamp source substitution", timestamp_source, VERIFIER.prove_special_field_flows, "Pool.createdAtTimestamp continuous block-field payload source drift"),
        ]
        for label, mutate, check, expected in cases:
            with self.subTest(label=label):
                self.assert_valid_wat_mutation_rejected(
                    label,
                    self.function_selector("src/mappings/factory/handlePoolCreated"),
                    mutate,
                    check,
                    expected,
                )

    def test_exact_setter_kind_receiver_payload_and_final_operands_are_rejected(self) -> None:
        def factory_id_kind(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 164, "i32.const 7")

        def factory_id_receiver(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 169, "local.get $l1")

        def factory_id_payload(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 167, VERIFIER.normalized(lines[374]))

        def factory_id_final_value(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 171, "local.get $l4")

        def factory_pool_count_final_value(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 498, "local.get $l4")

        def token_name_final_value(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 664, "local.get $l3")

        def bundle_id_kind(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 371, "i32.const 7")

        def timestamp_kind(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 1507, "i32.const 0")

        def pool_id_payload_source(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 517, "local.set $l3")

        def pool_count_plus_operand(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 482, "local.get $l3")

        cases = [
            ("Factory.id Value-kind substitution", factory_id_kind, "Factory.id exact Value kind drift"),
            ("Factory.id receiver substitution", factory_id_receiver, "Factory.id exact entity receiver drift"),
            ("Factory.id payload substitution", factory_id_payload, "Factory.id exact decoded Value payload drift"),
            ("Factory.id final-Value substitution", factory_id_final_value, "Factory.id exact final Value operand drift"),
            ("Factory.poolCount final-Value substitution", factory_pool_count_final_value, "Factory.poolCount exact final Value operand drift"),
            ("Token.name final-Value substitution", token_name_final_value, "Token[token0].name exact final Value operand drift"),
            ("Bundle.id Value-kind substitution", bundle_id_kind, "Bundle.id exact Value kind drift"),
            ("Pool.createdAtTimestamp Value-kind substitution", timestamp_kind, "Pool.createdAtTimestamp exact Value kind drift"),
            ("Pool.id decoded payload-local substitution", pool_id_payload_source, "Pool.id continuous event[4]/decode/payload source drift"),
            ("Factory.poolCount plus operand substitution", pool_count_plus_operand, "Factory.poolCount continuous getter/decode/plus source drift"),
        ]
        for label, mutate, expected in cases:
            with self.subTest(label=label):
                self.assert_valid_wat_mutation_rejected(
                    label,
                    self.function_selector("src/mappings/factory/handlePoolCreated"),
                    mutate,
                    self.field_check,
                    expected,
                )

    def test_each_inline_setter_uses_its_exact_wrapper_local(self) -> None:
        def pool_token0_wrapper(lines: list[str], _context: dict[str, Any]) -> None:
            for site in (1301, 1304, 1309):
                self.set_normalized(lines, site, VERIFIER.normalized(lines[site]).replace("$l1", "$l2"))

        def factory_pool_count_wrapper(lines: list[str], _context: dict[str, Any]) -> None:
            for site in (490, 493, 498):
                self.set_normalized(lines, site, VERIFIER.normalized(lines[site]).replace("$l1", "$p0"))

        def pool_created_at_wrapper(lines: list[str], _context: dict[str, Any]) -> None:
            for site in (1488, 1491, 1496):
                self.set_normalized(lines, site, VERIFIER.normalized(lines[site]).replace("$l1", "$p0"))

        for label, mutate in (
            ("Pool.token0 wrapper moved from l1 to l2", pool_token0_wrapper),
            ("Factory.poolCount wrapper moved from l1 to p0", factory_pool_count_wrapper),
            ("Pool.createdAtTimestamp wrapper moved from l1 to p0", pool_created_at_wrapper),
        ):
            with self.subTest(label=label):
                self.assert_valid_wat_mutation_rejected(
                    label,
                    self.function_selector("src/mappings/factory/handlePoolCreated"),
                    mutate,
                    VERIFIER.prove_special_field_flows,
                    "exact Value allocation/identity drift",
                )

    def test_handler_entry_event_and_zero_fee_index_are_reaching_definitions(self) -> None:
        def overwrite_entry_event(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 118, "local.set $p0")

        self.assert_valid_wat_mutation_rejected(
            "handler entry event overwritten before event reads",
            self.function_selector("src/mappings/factory/handlePoolCreated"),
            overwrite_entry_event,
            VERIFIER.prove_handler_entry_local_stability,
            "handler entry event $p0 write inventory drift",
        )

    def test_fee_tier_assembly_mutation_survives_digest_refresh_but_fails_semantics(self) -> None:
        def assembly_operator(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 1465, "i32.add")

        self.assert_valid_wat_mutation_rejected(
            "Pool.feeTier intermediate byte assembly changed behind refreshed slice authority",
            self.function_selector("src/mappings/factory/handlePoolCreated"),
            assembly_operator,
            VERIFIER.prove_special_field_flows,
            "Pool.feeTier exact byte assembly/BigInt source drift",
            refresh_fee_slice_authority=True,
        )

    def test_early_return_whitelist_and_bundle_mutations_are_valid_and_rejected(self) -> None:
        def decimals_return(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 725, "nop")

        def whitelist_direction(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 1249, "local.get $l3")

        def remove_bundle_store(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 443, "drop")
            self.insert_normalized(lines, 444, ["drop", "drop"])

        cases = [
            ("null-decimals return removed", decimals_return, self.field_check, "null-decimals early-return flow drift"),
            ("whitelist update direction reversed", whitelist_direction, VERIFIER.prove_whitelist_updates, "token0-to-token1 exact whitelist source/receiver/key/Value/set binding drift"),
            ("Bundle partial effect removed", remove_bundle_store, VERIFIER.prove_partial_effect_traces, "Bundle partial-effect site/argument drift"),
        ]
        for label, mutate, check, expected in cases:
            with self.subTest(label=label):
                self.assert_valid_wat_mutation_rejected(
                    label,
                    self.function_selector("src/mappings/factory/handlePoolCreated"),
                    mutate,
                    check,
                    expected,
                )

    def test_required_pool_tick_absence_has_a_valid_counterexample(self) -> None:
        def tick_key(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 1675, "i32.const 60000")

        def add_tick_string(wat: str) -> str:
            body = wat.rstrip()
            self.assertTrue(body.endswith(")"))
            data = r'  (data $tick (i32.const 59996) "\08\00\00\00t\00i\00c\00k\00")'
            return f"{body[:-1]}\n{data}\n)\n"

        self.assert_valid_wat_mutation_rejected(
            "Pool.tick field introduced",
            self.function_selector("src/mappings/factory/handlePoolCreated"),
            tick_key,
            self.field_check,
            "Pool.tick required-absence drift",
            mutate_module=add_tick_string,
        )

    def test_reachable_helper_injected_pool_tick_is_rejected_after_helper_rehash(self) -> None:
        def inject_pool_tick_set(lines: list[str], _context: dict[str, Any]) -> None:
            self.insert_normalized(
                lines,
                1,
                [
                    "local.get $p0",
                    "i32.const 60000",
                    "i32.const 16",
                    "i32.const 27",
                    f"call ${VERIFIER.STUB_NEW_CALL}",
                    "local.tee $p0",
                    "i32.const 7",
                    "i32.store",
                    "local.get $p0",
                    "i64.const 0",
                    "i64.store offset=8",
                    "local.get $p0",
                    f"call ${VERIFIER.TYPED_MAP_SET_CALL}",
                ],
            )

        def add_tick_string(wat: str) -> str:
            body = wat.rstrip()
            self.assertTrue(body.endswith(")"))
            data = r'  (data $helper_tick (i32.const 59996) "\08\00\00\00t\00i\00c\00k\00")'
            return f"{body[:-1]}\n{data}\n)\n"

        def closure_check(context: dict[str, Any]) -> None:
            VERIFIER.prove_reachable_typed_map_setter_closure(
                context, self.token_constructors["modern-mainnet"]
            )

        self.assert_valid_wat_mutation_rejected(
            "reachable Pool id helper injects Pool.tick setter",
            self.function_selector("schema/Pool#get:id"),
            inject_pool_tick_set,
            closure_check,
            "reachable helper TypedMap#set inventory drift",
            refresh_helper_key="pool_id_getter",
            mutate_module=add_tick_string,
        )

    def test_helper_and_static_profile_mutations_are_valid_and_rejected(self) -> None:
        def symbol_fallback(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 102, "i32.const 11040")

        def name_static_field(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 100, "i32.load offset=4")

        def decimals_threshold(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 252, "i32.const 0")

        def static_decimals(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 21, "i32.const 10")

        def start_zero(lines: list[str], _context: dict[str, Any]) -> None:
            site = next(
                index
                for index in range(len(lines) - 2)
                if VERIFIER.normalized(lines[index]) == "i32.const 0"
                and (VERIFIER.call_name(lines[index + 1]) or "").endswith("BigInt.fromI32")
                and VERIFIER.normalized(lines[index + 2]).endswith("ZERO_BI")
            )
            self.set_normalized(lines, site, "i32.const 2")

        def string_array_value_kind(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 97, "i32.const 7")

        cases = [
            (
                "symbol fallback changed",
                self.function_selector("/fetchTokenSymbol"),
                symbol_fallback,
                lambda context: VERIFIER.prove_string_metadata_helper(
                    context, "symbol", 4
                ),
                "symbol helper fallback outcome drift",
                "symbol",
            ),
            (
                "name static-field changed behind refreshed body authority",
                self.function_selector("/fetchTokenName"),
                name_static_field,
                lambda context: VERIFIER.prove_string_metadata_helper(
                    context, "name", 8
                ),
                "name helper fallback outcome drift",
                "name",
            ),
            (
                "decimals threshold changed behind refreshed body authority",
                self.function_selector("/fetchTokenDecimals"),
                decimals_threshold,
                VERIFIER.prove_decimals_helper,
                "decimals helper less-than-255 return flow drift",
                "decimals",
            ),
            (
                "static decimals changed behind refreshed body authority",
                self.function_selector("StaticTokenDefinition.fromAddress"),
                static_decimals,
                VERIFIER.prove_static_definitions,
                "static-definition semantic tuple drift",
                "static_definition",
            ),
            (
                "ZERO_BI initializer changed behind refreshed body authority",
                self.function_selector("~start"),
                start_zero,
                VERIFIER.prove_start_constants,
                "module-start BigInt constant flow drift",
                "start",
            ),
            (
                "StringArray Value kind changed behind refreshed body authority",
                self.function_selector("Value.fromStringArray"),
                string_array_value_kind,
                VERIFIER.prove_string_array_value_helper,
                "StringArray Value exact kind/payload/return drift",
                "string_array_value",
            ),
        ]
        for label, selector, mutate, check, expected, refresh in cases:
            with self.subTest(label=label):
                self.assert_valid_wat_mutation_rejected(
                    label,
                    selector,
                    mutate,
                    check,
                    expected,
                    refresh_helper_key=refresh,
                )

    def test_structural_array_whitelist_getter_and_static_mutations_survive_authority_refresh(self) -> None:
        def string_array_length_slot(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 56, "i32.store offset=8")

        def whitelist_backing_source(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 14, "i32.const 0")

        def whitelist_getter_length_slot(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 78, "i32.store offset=8")

        def pool_id_key(lines: list[str], context: dict[str, Any]) -> None:
            self.set_normalized(lines, 2, VERIFIER.normalized(context["handler"].lines[1291]))

        def token_id_key(lines: list[str], context: dict[str, Any]) -> None:
            self.set_normalized(lines, 2, VERIFIER.normalized(context["handler"].lines[631]))

        def static_compare_input(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 138, "local.get $l1")

        def static_tuple_slot(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 46, "i32.store")

        def base_static_miss(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 35, "local.get $p0)")

        cases = [
            (
                "StringArray destination length moved from offset 12",
                self.function_selector("Value.fromStringArray"),
                string_array_length_slot,
                VERIFIER.prove_string_array_value_helper,
                "StringArray Value allocation/buffer/capacity/length drift",
                "string_array_value",
                "modern-mainnet",
            ),
            (
                "whitelist captured backing source replaced with zero",
                self.function_selector("Array<~lib/string/String>#includes"),
                whitelist_backing_source,
                VERIFIER.prove_whitelist_membership_helper,
                "whitelist includes captured-array/input-loop/equality/return drift",
                "whitelist_membership",
                "modern-mainnet",
            ),
            (
                "whitelist getter destination length moved from offset 12",
                self.function_selector("schema/Token#get:whitelistPools"),
                whitelist_getter_length_slot,
                VERIFIER.prove_whitelist_getter_helper,
                "whitelist getter destination allocation/capacity/length drift",
                "whitelist_getter",
                "modern-mainnet",
            ),
            (
                "Pool id getter key changed to token0",
                self.function_selector("schema/Pool#get:id"),
                pool_id_key,
                lambda context: VERIFIER.prove_id_getter_helper(
                    context, "pool_id_getter", "schema/Pool#get:id"
                ),
                "exact receiver/id/null-kind/same-Value-toString flow drift",
                "pool_id_getter",
                "modern-mainnet",
            ),
            (
                "Token id getter key changed to symbol",
                self.function_selector("schema/Token#get:id"),
                token_id_key,
                lambda context: VERIFIER.prove_id_getter_helper(
                    context, "token_id_getter", "schema/Token#get:id"
                ),
                "exact receiver/id/null-kind/same-Value-toString flow drift",
                "token_id_getter",
                "modern-mainnet",
            ),
            (
                "mainnet static lookup compare uses array local",
                self.function_selector("StaticTokenDefinition.fromAddress"),
                static_compare_input,
                VERIFIER.prove_static_definitions,
                "static-definition input-address/loop/compare/return/null drift",
                "static_definition",
                "modern-mainnet",
            ),
            (
                "mainnet static tuple insertion offset removed",
                self.function_selector("StaticTokenDefinition.fromAddress"),
                static_tuple_slot,
                VERIFIER.prove_static_definitions,
                "static-definition tuple slot 1 placement drift",
                "static_definition",
                "modern-mainnet",
            ),
            (
                "Base static miss returns input local",
                self.function_selector("StaticTokenDefinition.fromAddress"),
                base_static_miss,
                VERIFIER.prove_static_definitions,
                "empty static-definition array/input-loop/null-return drift",
                "static_definition",
                "modern-base",
            ),
        ]
        for label, selector, mutate, check, expected, refresh, profile in cases:
            with self.subTest(label=label):
                self.assert_valid_wat_mutation_rejected(
                    label,
                    selector,
                    mutate,
                    check,
                    expected,
                    refresh_helper_key=refresh,
                    profile=profile,
                )

    def test_token_helper_source_and_decimals_comparator_mutations_survive_authority_refresh(self) -> None:
        def zero_symbol_address(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 6, "i32.const 0")

        def zero_name_address(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 6, "i32.const 0")

        def zero_total_supply_address(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 6, "i32.const 0")

        def zero_decimals_address(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 7, "i32.const 0")

        def reverse_decimals_byte_comparison(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 227, "i32.gt_u")

        cases = [
            (
                "symbol SmartContract address replaced with zero",
                "/fetchTokenSymbol",
                zero_symbol_address,
                lambda context: VERIFIER.prove_string_metadata_helper(context, "symbol", 4),
                "symbol exact input-address SmartContract construction drift",
                "symbol",
            ),
            (
                "name SmartContract address replaced with zero",
                "/fetchTokenName",
                zero_name_address,
                lambda context: VERIFIER.prove_string_metadata_helper(context, "name", 8),
                "name exact input-address SmartContract construction drift",
                "name",
            ),
            (
                "totalSupply SmartContract address replaced with zero",
                "/fetchTokenTotalSupply",
                zero_total_supply_address,
                VERIFIER.prove_token_helpers,
                "totalSupply exact input-address SmartContract construction drift",
                "total_supply",
            ),
            (
                "decimals SmartContract address replaced with zero",
                "/fetchTokenDecimals",
                zero_decimals_address,
                VERIFIER.prove_decimals_helper,
                "decimals exact input-address SmartContract construction drift",
                "decimals",
            ),
            (
                "decimals unsigned byte comparator direction reversed",
                "/fetchTokenDecimals",
                reverse_decimals_byte_comparison,
                VERIFIER.prove_decimals_helper,
                "decimals complete signed BigInt comparison/dataflow drift",
                "decimals",
            ),
        ]
        for label, suffix, mutate, check, expected, refresh in cases:
            with self.subTest(label=label):
                self.assert_valid_wat_mutation_rejected(
                    label,
                    self.function_selector(suffix),
                    mutate,
                    check,
                    expected,
                    refresh_helper_key=refresh,
                )

    def test_transitive_primitive_mutations_fail_beyond_top_level_helper_authority(self) -> None:
        def common_value_kind_gate(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 2, "i32.load offset=8")

        def string_equality_operator(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 4, "i32.ne")

        def static_constructor_field(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 10, "i32.store offset=8")

        for label, selector, mutate, check, expected in (
            (
                "common entity Value string decoder reads the payload as its kind",
                self.function_selector("common/value/Value#toString"),
                common_value_kind_gate,
                VERIFIER.prove_shared_runtime_primitives,
                "exact kind gate/same Value payload return drift",
            ),
            (
                "retained String equality primitive reverses the identity comparison",
                self.function_selector("~lib/string/String.__eq"),
                string_equality_operator,
                self.public_collection_capsule_check,
                "retained String.__eq primitive body drift",
            ),
            (
                "static tuple constructor writes two fields to offset 8",
                self.function_selector("StaticTokenDefinition#constructor"),
                static_constructor_field,
                VERIFIER.prove_static_definitions,
                "StaticTokenDefinition constructor allocation/zeroing/return drift",
            ),
        ):
            with self.subTest(label=label):
                self.assert_valid_wat_mutation_rejected(
                    label,
                    selector,
                    mutate,
                    check,
                    expected,
                )

    def test_collection_allocator_and_start_mutations_fail_after_outer_authority_refresh(self) -> None:
        def overwrite_whitelist_length(lines: list[str], _context: dict[str, Any]) -> None:
            self.insert_normalized(
                lines, 48, ["i32.const 4764", "i32.const 0", "i32.store"]
            )

        def overwrite_whitelist_pointer_with_float_store(
            lines: list[str], _context: dict[str, Any]
        ) -> None:
            self.insert_normalized(
                lines, 48, ["i32.const 4756", "f32.const 0", "f32.store"]
            )

        def overwrite_whitelist_pointer_with_bulk_fill(
            lines: list[str], _context: dict[str, Any]
        ) -> None:
            self.insert_normalized(
                lines,
                48,
                ["i32.const 4756", "i32.const 0", "i32.const 4", "memory.fill"],
            )

        def push_wrong_operand(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 16, "local.get $p0")

        def typed_set_update_value(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 36, "local.get $p1")

        def typed_set_insert_value(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 52, "local.get $p1")

        def typed_set_insert_key(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 49, "local.get $p2")

        def ensure_wrong_capacity_commit(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 223, "local.get $l3")

        def ensure_wrong_backing_commit(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 216, "local.get $l4")

        def ensure_wrong_growth_selection(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 47, "i32.gt_u")

        def stub_new_wrong_return(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 32, "local.get $l2")

        def stub_alloc_wrong_return(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 72, "local.get $l1)")

        def entity_wrong_map_operand(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 55, "local.get $p0")

        def entity_second_null_allocation_wrong_receiver(
            lines: list[str], _context: dict[str, Any]
        ) -> None:
            self.set_normalized(lines, 16, "local.set $l1")

        def memory_fill_wider_store(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 8, "i32.store16")

        def memory_copy_zero_length(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 23, "i32.const 0")

        def memcpy_wider_load(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 22, "i32.load16_u")

        for label, mutate in (
            (
                "module start integer-store overwrites mainnet whitelist length",
                overwrite_whitelist_length,
            ),
            (
                "module start float-store overwrites mainnet whitelist pointer",
                overwrite_whitelist_pointer_with_float_store,
            ),
            (
                "module start bulk-fill overwrites mainnet whitelist pointer",
                overwrite_whitelist_pointer_with_bulk_fill,
            ),
        ):
            with self.subTest(label=label):
                self.assert_valid_wat_mutation_rejected(
                    label,
                    self.function_selector("~start"),
                    mutate,
                    VERIFIER.prove_start_constants,
                    "module-start acquired a direct protected-memory write",
                    refresh_helper_key="start",
                )

        cases = [
            (
                "TypedMapEntry array push appends the receiver instead of the input entry",
                "TypedMapEntry<~lib/string/String_~lib/@graphprotocol/graph-ts/common/value/Value>>#push",
                push_wrong_operand,
                VERIFIER.prove_typed_map_collection_runtime,
                "Array<TypedMapEntry>#push receiver/length/appended-operand drift",
            ),
            (
                "TypedMap set existing-entry branch stores the key as value",
                VERIFIER.TYPED_MAP_SET_CALL,
                typed_set_update_value,
                VERIFIER.prove_typed_map_collection_runtime,
                "TypedMap#set key/value/entry/push operand drift",
            ),
            (
                "TypedMap set new-entry branch stores the key as value",
                VERIFIER.TYPED_MAP_SET_CALL,
                typed_set_insert_value,
                VERIFIER.prove_typed_map_collection_runtime,
                "TypedMap#set key/value/entry/push operand drift",
            ),
            (
                "TypedMap set new-entry branch stores the value as key",
                VERIFIER.TYPED_MAP_SET_CALL,
                typed_set_insert_key,
                VERIFIER.prove_typed_map_collection_runtime,
                "TypedMap#set key/value/entry/push operand drift",
            ),
            (
                "ensureCapacity commits the old byte capacity",
                "~lib/array/ensureCapacity",
                ensure_wrong_capacity_commit,
                VERIFIER.prove_typed_map_collection_runtime,
                "ensureCapacity committed capacity/backing behavior drift",
            ),
            (
                "ensureCapacity commits the old backing pointer",
                "~lib/array/ensureCapacity",
                ensure_wrong_backing_commit,
                VERIFIER.prove_typed_map_collection_runtime,
                "ensureCapacity committed capacity/backing behavior drift",
            ),
            (
                "ensureCapacity reverses its growth selection comparison",
                "~lib/array/ensureCapacity",
                ensure_wrong_growth_selection,
                VERIFIER.prove_typed_map_collection_runtime,
                "fixed retained ensureCapacity body drift",
            ),
            (
                "stub new returns the allocation header instead of payload",
                "~lib/rt/stub/__new",
                stub_new_wrong_return,
                VERIFIER.prove_allocator_identity,
                "stub/__new allocation/header/return identity drift",
            ),
            (
                "stub alloc returns the allocation header instead of aligned payload",
                "~lib/rt/stub/__alloc",
                stub_alloc_wrong_return,
                VERIFIER.prove_allocator_identity,
                "stub/__alloc aligned extent/header/return identity drift",
            ),
            (
                "Entity constructor stores itself instead of its fresh map array",
                "common/collections/Entity#constructor",
                entity_wrong_map_operand,
                VERIFIER.prove_typed_map_collection_runtime,
                "Entity constructor TypedMap array/backing/return drift",
            ),
            (
                "Entity constructor loses its second null-receiver allocation",
                "common/collections/Entity#constructor",
                entity_second_null_allocation_wrong_receiver,
                VERIFIER.prove_typed_map_collection_runtime,
                "Entity constructor TypedMap array/backing/return drift",
            ),
            (
                "memory fill widens its first zero store",
                "~lib/memory/memory.fill",
                memory_fill_wider_store,
                VERIFIER.prove_typed_map_collection_runtime,
                "fixed retained ~lib/memory/memory.fill body drift",
            ),
            (
                "memory copy forces the memcpy length to zero",
                "~lib/memory/memory.copy",
                memory_copy_zero_length,
                VERIFIER.prove_typed_map_collection_runtime,
                "fixed retained ~lib/memory/memory.copy body drift",
            ),
            (
                "memcpy widens its byte load",
                "~lib/util/memory/memcpy",
                memcpy_wider_load,
                VERIFIER.prove_typed_map_collection_runtime,
                "fixed retained ~lib/util/memory/memcpy body drift",
            ),
        ]
        for label, suffix, mutate, check, expected in cases:
            with self.subTest(label=label):
                self.assert_valid_wat_mutation_rejected(
                    label,
                    self.function_selector(suffix),
                    mutate,
                    check,
                    expected,
                    refresh_reachable_body_authority=True,
                )

    def test_shared_modern_declaration_identity_survives_outer_body_refresh(self) -> None:
        def swap_names(index: int, first: str, second: str) -> Mutator:
            def mutate(lines: list[str], _context: dict[str, Any]) -> None:
                line = VERIFIER.normalized(lines[index])
                self.assertEqual(line.count(first), 1)
                self.assertEqual(line.count(second), 1)
                changed = line.replace(first, "$signature_swap", 1)
                changed = changed.replace(second, first, 1)
                changed = changed.replace("$signature_swap", second, 1)
                self.set_normalized(lines, index, changed)

            return mutate

        cases = (
            (
                "Factory TypedMap setter key/value parameter labels swap",
                VERIFIER.TYPED_MAP_SET_CALL,
                swap_names(0, "$p1", "$p2"),
                "typed_map_set",
            ),
            (
                "Factory Entity constructor local identities swap",
                "common/collections/Entity#constructor",
                swap_names(1, "$l1", "$l2"),
                "entity_constructor",
            ),
        )
        for label, suffix, mutate, authority_id in cases:
            with self.subTest(label=label):
                self.assert_valid_wat_mutation_rejected(
                    label,
                    self.function_selector(suffix),
                    mutate,
                    self.public_collection_capsule_check,
                    f"exact {authority_id} function declaration drift",
                    refresh_reachable_body_authority=True,
                )

    def test_direct_memory_write_opcode_inventory_covers_all_writer_families(self) -> None:
        for instruction in (
            "i32.store",
            "i64.store32 offset=4",
            "f32.store",
            "f64.store align=2",
            "v128.store",
            "v128.store64_lane 1",
            "i32.atomic.store",
            "i64.atomic.store32",
            "i32.atomic.rmw.add",
            "i64.atomic.rmw16.cmpxchg_u",
            "memory.copy",
            "memory.fill",
            "memory.init 0",
            "memory.discard",
        ):
            with self.subTest(instruction=instruction):
                self.assertTrue(VERIFIER.is_direct_memory_write(instruction))
        for instruction in (
            "i32.load",
            "v128.load",
            "i32.atomic.load",
            "memory.atomic.notify",
            "memory.atomic.wait32",
            "memory.size",
            "memory.grow",
            "call $index/store.set",
        ):
            with self.subTest(instruction=instruction):
                self.assertFalse(VERIFIER.is_direct_memory_write(instruction))

    def test_initializer_dispatch_and_critical_global_writer_mutations_fail_closed(self) -> None:
        def unchanged_body(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 2, VERIFIER.normalized(lines[2]))

        def rebind_start_export(wat: str) -> str:
            old = '(export "_start" (func $~start))'
            new = '(export "_start" (func $~lib/rt/stub/__alloc))'
            self.assertEqual(wat.count(old), 1)
            return wat.replace(old, new, 1)

        def initialize_started_true(wat: str) -> str:
            old = '(global $~started (mut i32) (i32.const 0))'
            new = '(global $~started (mut i32) (i32.const 1))'
            self.assertEqual(wat.count(old), 1)
            return wat.replace(old, new, 1)

        def add_native_start_section(wat: str) -> str:
            body = wat.rstrip()
            self.assertTrue(body.endswith(")"))
            return f"{body[:-1]}\n  (start $~start)\n)\n"

        for label, module_mutation, expected in (
            ("_start export rebound", rebind_start_export, "_start export binding drift"),
            (
                "$~started initializes true",
                initialize_started_true,
                "$~started zero initializer drift",
            ),
            (
                "native start section introduced",
                add_native_start_section,
                "unexpected native WebAssembly start section",
            ),
        ):
            with self.subTest(label=label):
                self.assert_valid_wat_mutation_rejected(
                    label,
                    self.function_selector("~start"),
                    unchanged_body,
                    VERIFIER.prove_start_constants,
                    expected,
                    mutate_module=module_mutation,
                )

        def reset_allocator_late(lines: list[str], _context: dict[str, Any]) -> None:
            self.insert_normalized(
                lines,
                48,
                ["i32.const 0", "global.set $~lib/rt/stub/offset"],
            )

        self.assert_valid_wat_mutation_rejected(
            "initializer resets allocator after all allocations",
            self.function_selector("~start"),
            reset_allocator_late,
            VERIFIER.prove_start_constants,
            "critical mutable-global writer inventory drift",
            refresh_helper_key="start",
        )

        def overwrite_zero_bigint(
            lines: list[str], _context: dict[str, Any]
        ) -> None:
            self.insert_normalized(
                lines,
                11,
                [
                    "global.get $src/utils/constants/ONE_BI",
                    "global.set $src/utils/constants/ZERO_BI",
                ],
            )

        self.assert_valid_wat_mutation_rejected(
            "reachable Value decoder overwrites ZERO_BI",
            self.function_selector("ethereum.Value#toAddress"),
            overwrite_zero_bigint,
            VERIFIER.prove_start_constants,
            "critical mutable-global writer inventory drift",
            refresh_reachable_body_authority=True,
        )

    def test_total_supply_success_value_substitution_is_valid_and_rejected(self) -> None:
        def substitute_decoded_value(lines: list[str], _context: dict[str, Any]) -> None:
            decode = next(
                index
                for index, line in enumerate(lines)
                if (VERIFIER.call_name(line) or "").endswith("ethereum.Value#toBigInt")
            )
            self.insert_normalized(lines, decode + 1, ["drop", "local.get $l1"])

        self.assert_valid_wat_mutation_rejected(
            "totalSupply decoded value substituted",
            self.function_selector("/fetchTokenTotalSupply"),
            substitute_decoded_value,
            self.total_supply_dataflow_check,
            "total-supply",
        )

    def test_self_rehashed_contract_cannot_promote_residual_gates(self) -> None:
        mutations: list[tuple[str, dict[str, Any]]] = []
        for gate in sorted(VERIFIER.FALSE_FLAGS):
            changed = copy.deepcopy(self.contract)
            changed["truth_boundary"][gate] = True
            mutations.append((f"promoted residual gate {gate}", changed))
        changed_scope = copy.deepcopy(self.contract)
        changed_scope["scope"]["residual_after_this_supplement"] = 0
        mutations.append(("promoted residual path count", changed_scope))
        changed_field = copy.deepcopy(self.contract)
        changed_field["modern_factory_static_proofs"][0]["field_contract"][
            "required_absent_fields"
        ] = []
        mutations.append(("promoted required absence", changed_field))
        for label, changed in mutations:
            with self.subTest(label=label):
                with self.assertRaises(VERIFIER.VerificationError):
                    VERIFIER.verify_contract(ROOT, changed)


if __name__ == "__main__":
    unittest.main()
