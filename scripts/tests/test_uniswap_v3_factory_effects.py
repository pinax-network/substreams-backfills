from __future__ import annotations

import copy
import hashlib
import importlib.util
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Callable
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
VERIFIER_PATH = ROOT / "scripts/verify-uniswap-v3-factory-effects.py"
SPEC = importlib.util.spec_from_file_location("uniswap_v3_factory_effects", VERIFIER_PATH)
assert SPEC is not None and SPEC.loader is not None
VERIFIER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VERIFIER
SPEC.loader.exec_module(VERIFIER)


Mutator = Callable[[list[str], dict[str, Any]], None]


class FactoryEffectsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contexts = VERIFIER.load_contexts(ROOT)
        cls.by_profile = {context["profile"]["profile_id"]: context for context in cls.contexts}
        cls.proofs = [VERIFIER.prove_factory_effects(context) for context in cls.contexts]
        cls.contract = VERIFIER.load_json(ROOT / VERIFIER.CONTRACT_PATH)
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
        cls.full_wat: dict[str, str] = {}
        for profile, context in cls.by_profile.items():
            artifact = ROOT / f"uniswap-v3/graft-ancestry/v1/artifacts/{context['cid']}"
            executable = VERIFIER.WRITER.resolve_wasm2wat(None)
            cls.full_wat[profile] = VERIFIER.WRITER.run_wasm2wat(executable, artifact).decode()

    @staticmethod
    def set_normalized(lines: list[str], index: int, value: str) -> None:
        indent = lines[index][: len(lines[index]) - len(lines[index].lstrip())]
        lines[index] = f"{indent}{value}"

    @staticmethod
    def insert_normalized(lines: list[str], index: int, values: list[str]) -> None:
        indent = lines[index][: len(lines[index]) - len(lines[index].lstrip())]
        lines[index:index] = [f"{indent}{value}" for value in values]

    @staticmethod
    def function_by_suffix(context: dict[str, Any], suffix: str) -> Any:
        matches = [
            function
            for name, function in context["functions"].items()
            if name.replace("generated/schema/", "src/types/schema/").endswith(suffix)
        ]
        if len(matches) != 1:
            raise AssertionError(f"function suffix {suffix!r} matched {len(matches)} functions")
        return matches[0]

    def assert_valid_wat_mutation_rejected(
        self,
        label: str,
        profile: str,
        selector: Callable[[dict[str, Any]], Any],
        mutate: Mutator,
        expected_error: str,
        semantic_check: Callable[[dict[str, Any]], None] | None = None,
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
        with tempfile.TemporaryDirectory(prefix="factory-effects-wat-") as directory:
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
                f"{label} fixture must remain WAT-valid: {validation.stderr.decode('utf-8', 'replace')}",
            )
            changed_wasm = wasm_path.read_bytes()
        memory, functions, indirect, exports = VERIFIER.WRITER.parse_wat(changed_wat)
        parsed = VERIFIER.WRITER.resolve_handler(functions, exports, "handlePoolCreated")
        handler = VERIFIER.WRITER.WatFunction(
            parsed.name,
            base["handler"].start_line,
            parsed.lines,
            parsed.function_index,
        )
        functions[parsed.name] = handler
        analysis = copy.deepcopy(base["analysis"])
        analysis["sha256"] = hashlib.sha256(changed_wasm).hexdigest()
        analysis["wat_sha256"] = hashlib.sha256(changed_wat.encode()).hexdigest()
        analysis["registered_handlers"]["handlePoolCreated"]["body_sha256"] = hashlib.sha256(handler.payload).hexdigest()
        expected = copy.deepcopy(VERIFIER.EXPECTED_ARTIFACTS[base["cid"]])
        expected["wasm_sha256"] = analysis["sha256"]
        expected["wat_sha256"] = analysis["wat_sha256"]
        expected["handler_sha256"] = analysis["registered_handlers"]["handlePoolCreated"]["body_sha256"]
        changed = {
            **base,
            "analysis": analysis,
            "memory": memory,
            "functions": functions,
            "handler": handler,
            "indirect": indirect,
            "expected": expected,
        }
        observed_inventory = VERIFIER.observed_instruction_inventory(handler)
        with (
            mock.patch.dict(VERIFIER.EXPECTED_ARTIFACTS, {base["cid"]: expected}),
            mock.patch.dict(
                VERIFIER.GENERATION_INVENTORY[expected["generation"]],
                observed_inventory,
                clear=False,
            ),
        ):
            # The semantic mutation path first rebinds exact mutated WAT/WASM,
            # handler authority, and the complete handler-local syntax inventory.
            # Rejection must then come from the named semantic stage, never a
            # stale digest or syntactic-inventory pin.
            VERIFIER.verify_factory_authority(changed)
            VERIFIER.instruction_inventory(handler, expected["generation"])
            with self.assertRaises(VERIFIER.VerificationError, msg=label) as caught:
                (semantic_check or VERIFIER.prove_factory_effects)(changed)
            message = str(caught.exception)
            self.assertIn(expected_error, message, f"{label}: {message}")
            self.assertNotIn("digest drift", message, f"{label} stopped at a digest pin")

    def handler_selector(self, context: dict[str, Any]) -> Any:
        return context["handler"]

    def token_helper_selector(self, context: dict[str, Any]) -> Any:
        return self.function_by_suffix(context, "schema/Token#save")

    def legacy_constructor_selector(self, context: dict[str, Any]) -> Any:
        return self.function_by_suffix(context, "schema/Factory#constructor")

    def modern_token_constructor_selector(self, context: dict[str, Any]) -> Any:
        return self.function_by_suffix(context, "schema/Token#constructor")

    def indirect_target_selector(self, context: dict[str, Any]) -> Any:
        return self.function_by_suffix(context, "Value#displayData~anonymous|0")

    @staticmethod
    def template_semantic_check(context: dict[str, Any]) -> None:
        sites = VERIFIER.observed_selected_handler_effects(context)
        pool_sites = [index for index, identity in sites if identity == "Pool.save"]
        create_sites = [index for index, identity in sites if identity == "PoolTemplate.create"]
        if len(pool_sites) != 1 or len(create_sites) != 1:
            raise AssertionError(f"unexpected template test effect sites: {sites}")
        VERIFIER.prove_template(context, pool_sites[0], create_sites[0])

    @staticmethod
    def effect_region_semantic_check(context: dict[str, Any]) -> None:
        VERIFIER.prove_handler_effect_region_policy(
            context,
            dict(VERIFIER.observed_selected_handler_effects(context)),
        )

    @staticmethod
    def pool_present_id_semantic_check(context: dict[str, Any]) -> None:
        lines = [VERIFIER.normalized(line) for line in context["handler"].lines]
        frames, _ = VERIFIER.parse_structured_control(lines)
        starts = {frame["label"]: frame["start"] for frame in frames}
        pool_store = next(
            index
            for index, identity in VERIFIER.observed_selected_handler_effects(context)
            if identity == "Pool.save"
        )
        VERIFIER.prove_present_id_branch(
            context,
            "Pool",
            "$l6",
            "$l1",
            1886,
            starts["$I31"],
            starts["$I32"],
            starts["$I33"],
            pool_store,
        )

    def test_committed_contract_is_deterministic_projection(self) -> None:
        self.assertEqual(self.contract, VERIFIER.expected_contract(ROOT))
        self.assertEqual(self.contract, VERIFIER.verify_contract(ROOT))

    def test_scope_closes_only_six_effect_paths(self) -> None:
        scope = self.contract["scope"]
        self.assertEqual(
            (
                scope["factory_upstream_path_count"],
                scope["closed_before_this_supplement"],
                scope["newly_closed_factory_effect_paths"],
                scope["cumulative_closed_after_this_supplement"],
                scope["residual_after_this_supplement"],
            ),
            (18, 6, 6, 12, 6),
        )
        truth = self.contract["truth_boundary"]
        self.assertEqual({key for key, value in truth.items() if value}, VERIFIER.TRUE_FLAGS)
        self.assertEqual({key for key, value in truth.items() if not value}, VERIFIER.FALSE_FLAGS)
        self.assertFalse(truth["graph_handler_rollback_proven_by_retained_wat"])
        self.assertFalse(truth["factory_complete_static_handler_contract_proven"])
        self.assertFalse(truth["backfill_ready"])
        self.assertFalse(truth["production_ready"])

    def test_every_mapping_has_exact_handler_local_trace_certificate(self) -> None:
        self.assertEqual(len(self.proofs), 6)
        self.assertEqual({proof["generation"] for proof in self.proofs}, {"legacy", "modern"})
        for proof in self.proofs:
            traces = proof["effect_trace_proof"]
            self.assertEqual(
                traces["normal_exit_traces"],
                [[], list(VERIFIER.EXPECTED_EFFECT_TRACE)],
            )
            self.assertTrue(traces["same_path_and_order_machine_proven"])
            self.assertTrue(traces["all_handler_local_normal_and_explicit_trap_exits_machine_checked"])
            self.assertTrue(traces["reviewed_save_helper_pre_store_trap_boundaries_projected"])
            self.assertTrue(proof["argument_identity_machine_proven"])
            self.assertTrue(
                proof["generation_frontend"]["effect_argument_definition_identities"]
                ["every_alternative_reaching_definition_identity_proven"]
            )
            self.assertTrue(proof["template_identity_and_argument_machine_proven"])
            self.assertFalse(proof["graph_handler_rollback_proven_by_retained_wat"])
            closure = proof["reachable_effect_closure"]
            self.assertEqual(closure["reachable_store_set_targets"], ["Bundle", "Factory", "Pool", "Token"])
            self.assertEqual(len(closure["reachable_data_source_create_sites"]), 1)
            self.assertEqual(closure["dynamic_persistent_target_count"], 0)

    def test_eight_reviewed_counterexamples_are_wat_valid_and_rejected(self) -> None:
        def legacy_pool_local_overwrite(lines: list[str], _context: dict[str, Any]) -> None:
            for index, value in enumerate(["i32.const 0", "local.set $l1", "nop", "nop", "nop"], 414):
                self.set_normalized(lines, index, value)

        def legacy_template_alias_write(lines: list[str], _context: dict[str, Any]) -> None:
            self.insert_normalized(
                lines,
                435,
                ["local.get $l1", "i32.load", "i32.const 0", "i32.store offset=8"],
            )

        def legacy_extra_direct_token_store(lines: list[str], context: dict[str, Any]) -> None:
            helper = self.function_by_suffix(context, "schema/Token#save")
            token_constant = VERIFIER.normalized(helper.lines[27])
            replacement = [
                token_constant,
                "local.get $l2",
                VERIFIER.normalized(helper.lines[29]),
                "local.get $l2",
                "call $~lib/@graphprotocol/graph-ts/index/store.set",
            ]
            for index, value in enumerate(replacement, 414):
                self.set_normalized(lines, index, value)

        def modern_pool_local_overwrite(lines: list[str], _context: dict[str, Any]) -> None:
            for index, value in enumerate(["i32.const 0", "local.set $l6", "nop", "nop"], 1882):
                self.set_normalized(lines, index, value)

        def modern_template_alias_write(lines: list[str], _context: dict[str, Any]) -> None:
            self.insert_normalized(
                lines,
                1966,
                ["local.get $l1", "i32.load offset=4", "i32.const 0", "i32.store"],
            )

        def token_store_else_bypass(lines: list[str], _context: dict[str, Any]) -> None:
            self.insert_normalized(lines, 45, ["else"])

        def token_target_factory(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 45, "i32.const 2128")

        def token_early_return(lines: list[str], _context: dict[str, Any]) -> None:
            self.insert_normalized(lines, 45, ["return"])

        cases = [
            ("legacy Pool receiver local overwrite", "legacy-mainnet-root", self.handler_selector, legacy_pool_local_overwrite, "legacy Pool.save mutable-local dataflow drift", None),
            ("legacy template backing-slot mutation", "legacy-mainnet-root", self.handler_selector, legacy_template_alias_write, "legacy template heap-write inventory drift", self.template_semantic_check),
            ("legacy hidden direct Token store", "legacy-mainnet-root", self.handler_selector, legacy_extra_direct_token_store, "unexpected direct Token store", None),
            ("modern Pool receiver local overwrite", "modern-mainnet", self.handler_selector, modern_pool_local_overwrite, "modern Pool.save mutable-local dataflow drift", None),
            ("modern template backing-slot mutation", "modern-mainnet", self.handler_selector, modern_template_alias_write, "modern template heap-write inventory drift", self.template_semantic_check),
            ("modern Token helper else bypass", "modern-mainnet", self.token_helper_selector, token_store_else_bypass, "modern Token save helper acquired an alternative branch", None),
            ("modern Token helper target substitution", "modern-mainnet", self.token_helper_selector, token_target_factory, "modern Token save target drift", None),
            ("modern Token helper early return", "modern-mainnet", self.token_helper_selector, token_early_return, "modern Token save helper acquired an early normal return", None),
        ]
        for label, profile, selector, mutate, expected_error, semantic_check in cases:
            with self.subTest(label=label):
                self.assert_valid_wat_mutation_rejected(
                    label, profile, selector, mutate, expected_error, semantic_check
                )

    def test_receiver_id_argument_and_template_mutations_are_valid_and_rejected(self) -> None:
        def swap_tokens(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 1969, "local.get $l5")
            self.set_normalized(lines, 1971, "local.get $l3")

        def overwrite_factory(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 2019, "i32.const 0")

        def template_event_index(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 1947, "i32.const 0")

        def active_template_literal_with_dead_pool(lines: list[str], _context: dict[str, Any]) -> None:
            self.insert_normalized(lines, 1966, ["i32.const 15024", "drop"])
            self.set_normalized(lines, 1968, "i32.const 2128")

        def pool_target_factory(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 1929, "i32.const 2128")

        def factory_target_pool(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 2016, "i32.const 15024")

        def pool_id_value_substitution(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 1930, "local.get $l6")

        def token_helper_receiver_substitution(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 48, "local.get $l1")

        def token_helper_id_key_substitution(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 3, "i32.const 10208")

        cases = [
            ("token0/token1 arguments swapped", self.handler_selector, swap_tokens, "modern Token[token0].save argument read drift", None),
            ("Factory receiver overwritten", self.handler_selector, overwrite_factory, "direct store local argument drift at 2020", None),
            ("template event index changed", self.handler_selector, template_event_index, "modern template event.pool getter drift", self.template_semantic_check),
            ("dead Pool literal with active Factory template", self.handler_selector, active_template_literal_with_dead_pool, "modern template array value dataflow drift", self.template_semantic_check),
            ("Pool store target changed", self.handler_selector, pool_target_factory, "Pool direct-store operands drift", None),
            ("Factory store target changed", self.handler_selector, factory_target_pool, "Factory direct-store operands drift", None),
            ("Pool ID value substituted", self.handler_selector, pool_id_value_substitution, "Pool direct-store operands drift", None),
            ("Token helper receiver substituted", self.token_helper_selector, token_helper_receiver_substitution, "modern Token normal store path drift", None),
            ("Token helper ID key substituted", self.token_helper_selector, token_helper_id_key_substitution, "modern Token save ID key drift", None),
        ]
        for label, selector, mutate, expected_error, semantic_check in cases:
            with self.subTest(label=label):
                self.assert_valid_wat_mutation_rejected(
                    label,
                    "modern-mainnet",
                    selector,
                    mutate,
                    expected_error,
                    semantic_check,
                )

    def test_every_receiver_definition_alternative_is_bound_and_mutation_checked(self) -> None:
        for proof in self.proofs:
            frontend = proof["generation_frontend"]
            reaching = frontend["effect_argument_reaching_definitions"]
            expected = {
                (item["identity"], definition)
                for item in reaching
                if item["identity"]
                in {"Pool.save", "Token[token0].save", "Token[token1].save", "Factory.save"}
                for definition in item["reaching_definition_wat_lines"]
            }
            actual = {
                (item["identity"], item["reaching_definition_wat_line"])
                for item in frontend["effect_argument_definition_identities"]
                ["receiver_definition_proofs"]
            }
            self.assertEqual(actual, expected, proof["profile_id"])
            constructor_alternatives = [
                item
                for item in frontend["effect_argument_definition_identities"]
                ["receiver_definition_proofs"]
                if "constructor" in item["definition_kind"]
            ]
            self.assertTrue(constructor_alternatives, proof["profile_id"])
            self.assertTrue(
                all(
                    item.get("inline_constructor_id_and_receiver_machine_proven")
                    or item.get("constructor_body_certificate", {}).get(
                        "constructor_id_and_receiver_machine_proven"
                    )
                    for item in constructor_alternatives
                ),
                proof["profile_id"],
            )

        def legacy_pool_constructor_uses_token0(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 86, "call $src/types/Factory/Factory/PoolCreated__Params#get:token0")

        def legacy_token0_constructor_uses_token1(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 107, "call $src/types/Factory/Factory/PoolCreated__Params#get:token1")

        def legacy_token1_constructor_uses_token0(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 181, "call $src/types/Factory/Factory/PoolCreated__Params#get:token0")

        def legacy_factory_constructor_id_changes(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 16, "i32.const 8")

        def modern_pool_constructor_uses_token0(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 512, "i32.const 0")

        def modern_token0_constructor_uses_token1(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 594, "i32.const 1")

        def modern_token1_constructor_uses_token0(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 927, "i32.const 0")

        def modern_factory_constructor_id_changes(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 167, "i64.const 5424")

        cases = [
            ("legacy Pool constructor event identity", "legacy-mainnet-root", legacy_pool_constructor_uses_token0, "legacy pool identity binding drift"),
            ("legacy token0 constructor event identity", "legacy-mainnet-root", legacy_token0_constructor_uses_token1, "legacy Token[token0].save event field call target drift"),
            ("legacy token1 constructor event identity", "legacy-mainnet-root", legacy_token1_constructor_uses_token0, "legacy Token[token1].save event field call target drift"),
            ("legacy Factory constructor immutable ID", "legacy-mainnet-root", legacy_factory_constructor_id_changes, "legacy Factory constructor ID drift"),
            ("modern Pool constructor event identity", "modern-mainnet", modern_pool_constructor_uses_token0, "modern Pool event.pool-to-entity binding drift"),
            ("modern token0 constructor event identity", "modern-mainnet", modern_token0_constructor_uses_token1, "modern Token[token0].save constructor event-index flow drift"),
            ("modern token1 constructor event identity", "modern-mainnet", modern_token1_constructor_uses_token0, "modern Token[token1].save constructor event-index flow drift"),
            ("modern Factory constructor immutable ID", "modern-mainnet", modern_factory_constructor_id_changes, "modern Factory constructor ID field flow drift"),
        ]
        for label, profile, mutate, expected_error in cases:
            with self.subTest(label=label):
                self.assert_valid_wat_mutation_rejected(
                    label,
                    profile,
                    self.handler_selector,
                    mutate,
                    expected_error,
                )

    def test_constructor_helper_semantics_are_checked_before_closure_digests(self) -> None:
        def legacy_constructor_key_changes(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 6, "i32.const 328")

        def legacy_constructor_drops_input_id(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 7, "i32.const 0")

        def legacy_constructor_returns_id(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 10, "local.get $p0)")

        def modern_constructor_key_changes(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 7, "i32.const 10208")

        def modern_constructor_drops_input_id(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 9, "i32.const 0")

        def modern_constructor_returns_value(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 24, "local.get $p0)")

        cases = [
            ("legacy constructor ID key", "legacy-mainnet-root", self.legacy_constructor_selector, legacy_constructor_key_changes, "legacy entity constructor ID key drift"),
            ("legacy constructor input ID", "legacy-mainnet-root", self.legacy_constructor_selector, legacy_constructor_drops_input_id, "legacy entity constructor ID input drift"),
            ("legacy constructor returned receiver", "legacy-mainnet-root", self.legacy_constructor_selector, legacy_constructor_returns_id, "legacy entity constructor did not return the same receiver"),
            ("modern Token constructor ID key", "modern-mainnet", self.modern_token_constructor_selector, modern_constructor_key_changes, "modern Token constructor ID key drift"),
            ("modern Token constructor input ID", "modern-mainnet", self.modern_token_constructor_selector, modern_constructor_drops_input_id, "modern Token constructor ID String-Value payload/kind flow drift"),
            ("modern Token constructor returned receiver", "modern-mainnet", self.modern_token_constructor_selector, modern_constructor_returns_value, "modern Token constructor did not return the same receiver"),
        ]
        for label, profile, selector, mutate, expected_error in cases:
            with self.subTest(label=label):
                self.assert_valid_wat_mutation_rejected(
                    label,
                    profile,
                    selector,
                    mutate,
                    expected_error,
                )

    def test_control_select_call_and_hidden_effect_mutations_are_valid_and_rejected(self) -> None:
        def invert_present_branch(lines: list[str], _context: dict[str, Any]) -> None:
            self.insert_normalized(lines, 1900, ["i32.eqz"])

        def partial_normal_return(lines: list[str], _context: dict[str, Any]) -> None:
            self.set_normalized(lines, 1935, "return")

        def select_token_identity(lines: list[str], _context: dict[str, Any]) -> None:
            indent = lines[1969][: len(lines[1969]) - len(lines[1969].lstrip())]
            lines[1969:1970] = [
                f"{indent}local.get $l3",
                f"{indent}local.get $l5",
                f"{indent}i32.const 0",
                f"{indent}select",
            ]

        def extra_datasource_create(lines: list[str], _context: dict[str, Any]) -> None:
            self.insert_normalized(
                lines,
                1969,
                [
                    "i32.const 15024",
                    "local.get $l1",
                    "call $~lib/@graphprotocol/graph-ts/common/datasource/dataSource.create",
                ],
            )

        def inserted_call_indirect(lines: list[str], _context: dict[str, Any]) -> None:
            self.insert_normalized(
                lines,
                1969,
                [
                    "i32.const 0",
                    "i32.const 0",
                    "i32.const 0",
                    "i32.const 0",
                    "call_indirect $0 (type $t3)",
                    "drop",
                ],
            )

        def raw_pool_entity_heap_write(lines: list[str], _context: dict[str, Any]) -> None:
            self.insert_normalized(lines, 539, ["local.get $l6", "i32.const 0", "i32.store"])

        cases = [
            ("present-ID branch inverted", invert_present_branch, "Pool present-ID condition acquired a transform", self.pool_present_id_semantic_check),
            ("normal return after Pool only", partial_normal_return, "selected effect region acquired a normal-return bypass", self.effect_region_semantic_check),
            ("select smuggles Token identity", select_token_identity, "selected effect region acquired select-based identity control", self.effect_region_semantic_check),
            ("extra dataSource.create", extra_datasource_create, "dataSource.create closure drift", VERIFIER.scan_reachable_effects),
            ("extra call_indirect", inserted_call_indirect, "handler acquired call_indirect control", self.effect_region_semantic_check),
            ("raw heap write aliases Pool entity", raw_pool_entity_heap_write, "live entity receiver acquired a direct raw heap-store alias", self.effect_region_semantic_check),
        ]
        for label, mutate, expected_error, semantic_check in cases:
            with self.subTest(label=label):
                self.assert_valid_wat_mutation_rejected(
                    label,
                    "modern-mainnet",
                    self.handler_selector,
                    mutate,
                    expected_error,
                    semantic_check,
                )

    def test_helper_call_target_and_indirect_target_mutations_are_valid_and_rejected(self) -> None:
        def replace_token_store_call(lines: list[str], _context: dict[str, Any]) -> None:
            self.insert_normalized(lines, 49, ["i32.const 0"])
            self.set_normalized(lines, 50, "call $~lib/builtins/abort")

        def indirect_target_adds_store(lines: list[str], _context: dict[str, Any]) -> None:
            self.insert_normalized(
                lines,
                1,
                [
                    "i32.const 10208",
                    "i32.const 2128",
                    "i32.const 0",
                    "call $~lib/@graphprotocol/graph-ts/index/store.set",
                ],
            )

        self.assert_valid_wat_mutation_rejected(
            "Token helper call target replaced",
            "modern-mainnet",
            self.token_helper_selector,
            replace_token_store_call,
            "modern Token save helper persistent-store count drift",
        )
        self.assert_valid_wat_mutation_rejected(
            "indirect table target acquires persistent store",
            "modern-mainnet",
            self.indirect_target_selector,
            indirect_target_adds_store,
            "dynamic or unexpected store.set target",
            VERIFIER.scan_reachable_effects,
        )

    def test_trace_engine_distinguishes_trap_prefix_from_normal_prefix(self) -> None:
        fake = VERIFIER.WRITER.WatFunction(
            "fake",
            0,
            (
                "(func $fake",
                "  (local $l1 i32)",
                "  nop",
                "  unreachable",
                "  nop",
                "  nop",
                "  nop",
                "  nop",
                "  nop)",
            ),
        )
        trap = VERIFIER.prove_effect_traces(
            fake,
            {
                2: (3, 4),
                3: (VERIFIER.TRAP_EXIT,),
                4: (5,),
                5: (6,),
                6: (7,),
                7: (8,),
                8: (VERIFIER.NORMAL_EXIT,),
            },
            {
                2: "Pool.save",
                4: "PoolTemplate.create",
                5: "Token[token0].save",
                6: "Token[token1].save",
                7: "Factory.save",
            },
            set(),
        )
        self.assertEqual(trap["modeled_trap_boundary_traces"], [["Pool.save"]])
        with self.assertRaises(VERIFIER.VerificationError):
            VERIFIER.prove_effect_traces(
                fake,
                {2: (VERIFIER.NORMAL_EXIT,)},
                {2: "Pool.save"},
                set(),
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
        changed_proof = copy.deepcopy(self.contract)
        changed_proof["factory_effect_proofs"][0]["graph_handler_rollback_proven_by_retained_wat"] = True
        mutations.append(("self-rehashed rollback claim", changed_proof))
        for label, changed in mutations:
            with self.subTest(label=label):
                with self.assertRaises(VERIFIER.VerificationError):
                    VERIFIER.verify_contract(ROOT, changed)


if __name__ == "__main__":
    unittest.main()
