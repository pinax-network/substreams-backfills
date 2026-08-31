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
VERIFIER_PATH = ROOT / "scripts/verify-uniswap-v3-factory-static-v2.py"
SPEC = importlib.util.spec_from_file_location("uniswap_v3_factory_static_v2", VERIFIER_PATH)
assert SPEC is not None and SPEC.loader is not None
VERIFIER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VERIFIER
SPEC.loader.exec_module(VERIFIER)

Mutation = tuple[str, Callable[[list[str], dict[str, Any]], None]]


class FactoryStaticV2Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sources = VERIFIER.load_sources(ROOT, recompute_wat=True)
        cls.contract = VERIFIER.verify_contract(ROOT, sources=cls.sources, recompute_wat=False)
        cls.contexts = cls.sources["legacy_contexts"]
        cls.by_profile = {item["profile"]["profile_id"]: item for item in cls.contexts}
        cls.price_by_cid = {item["mapping_cid"]: item for item in cls.sources["price_sources"]["legacy_proofs"]}
        cls.fee_by_cid = {item["mapping_cid"]: item for item in cls.sources["fee_sources"]["legacy_proofs"]}
        cls.effect_by_cid = cls.sources["fee_sources"]["upstream_factory_effects"]
        cls.wasm2wat = cls.contexts[0]["wasm2wat"]
        cls.wat2wasm = cls.wasm2wat.with_name("wat2wasm")
        cls.expected_errors = tuple(dict.fromkeys((
            VERIFIER.VerificationError,
            VERIFIER.PRICE.VerificationError,
            VERIFIER.PRICE.PARENT.VerificationError,
            VERIFIER.FEE_INIT.VerificationError,
            VERIFIER.EFFECTS.VerificationError,
            VERIFIER.V2.VerificationError,
            VERIFIER.WRITER.VerificationError,
        )))

    @staticmethod
    def replace(lines: list[str], index: int, instruction: str) -> None:
        indent = lines[index][: len(lines[index]) - len(lines[index].lstrip())]
        closing = ")" if lines[index].rstrip().endswith(")") and not instruction.rstrip().endswith(")") else ""
        lines[index] = f"{indent}{instruction}{closing}"

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
            wat_lines[start:start + length] = replacement
        with tempfile.TemporaryDirectory(prefix="factory-static-v2-wat-") as temporary:
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
        memory, functions, indirect, exports = VERIFIER.WRITER.parse_wat(regenerated)
        handler = VERIFIER.WRITER.resolve_handler(functions, exports, VERIFIER.HANDLER_EXPORT)
        return {
            **context,
            "memory": memory,
            "functions": functions,
            "indirect": tuple(indirect),
            "exports": exports,
            "handler": handler,
            "wat_text": regenerated,
            "module_text": regenerated,
        }

    def assert_semantics_rejected(self, context: dict[str, Any], mutations: list[Mutation]) -> None:
        changed = self.roundtrip(context, mutations)
        cid = context["cid"]
        with self.assertRaises(self.expected_errors):
            VERIFIER.prove_legacy_context(
                changed,
                self.price_by_cid[cid],
                self.fee_by_cid[cid],
                self.effect_by_cid[cid],
                self.sources["written_fields"],
            )

    def mutation(self, function: Any, index: int, instruction: str) -> Mutation:
        return (function.name, lambda lines, _context: self.replace(lines, index, instruction))

    def assert_contract_rejected(self, value: dict[str, Any]) -> None:
        with self.assertRaises(self.expected_errors):
            VERIFIER.verify_contract(ROOT, value, sources=self.sources, recompute_wat=False)

    def test_01_committed_contract_is_deterministic(self) -> None:
        self.assertEqual(self.contract, VERIFIER.expected_contract_from_sources(self.sources))
        result = subprocess.run(
            [sys.executable, str(VERIFIER_PATH), "--root", str(ROOT), "--wasm2wat", str(self.wasm2wat)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("44/44 static sites, 78/78 expanded invocations", result.stdout)
        self.assertIn("no issue checkbox completed", result.stdout)

    def test_02_exact_scope_and_segment_counts(self) -> None:
        scope = self.contract["scope"]
        self.assertEqual((scope["factory_paths_closed_before"], scope["factory_paths_closed_after"]), (14, 18))
        self.assertEqual((scope["stored_field_contract_count"], scope["written_field_count"], scope["required_absent_field_count"]), (60, 59, 1))
        self.assertEqual((len(self.contract["legacy_mapping_proofs"]), len(self.contract["segments"]), len(self.contract["segment_diffs"])), (4, 8, 28))
        self.assertEqual(sum(item["provenance_surface"]["control_generation"] == "legacy" for item in self.contract["segments"]), 6)

    def test_03_every_legacy_collection_capsule_closes(self) -> None:
        for proof in self.contract["legacy_mapping_proofs"]:
            with self.subTest(profile=proof["profile_id"]):
                self.assertTrue(proof["public_factory_collection_capsule"]["legacy_collection_capsule_structurally_closed"])
                self.assertTrue(proof["entity_and_value_runtime"]["constructor_allocation_freshness_bound_by_collection_capsule"])
                self.assertTrue(proof["literal_payloads"]["literal_and_empty_array_payloads_structurally_proven"])
                self.assertEqual([item["length"] for item in proof["literal_payloads"]["empty_whitelist_initializers"]], [0, 0])

    def test_04_complete_site_and_invocation_ledgers_close(self) -> None:
        for proof in self.contract["legacy_mapping_proofs"]:
            sites = proof["static_typed_map_set_closure"]
            ledger = proof["handler_invocation_ledger"]
            self.assertEqual((sites["reachable_static_typed_map_set_site_count"], sites["direct_handler_site_count"], sites["helper_site_count"]), (44, 27, 17))
            self.assertEqual((ledger["expanded_map_write_invocation_count"], ledger["written_field_count"]), (78, 59))
            self.assertEqual(ledger["required_absent_fields"], ["Pool.tick"])
            self.assertTrue(ledger["all_expanded_invocation_receiver_key_kind_payload_flows_structurally_bound"])
            for invocation in ledger["invocations"]:
                self.assertTrue(invocation["exact_receiver_key_kind_payload_and_call_target_structurally_bound"])
                for key in ("entity_instance", "receiver_local", "decoded_key", "value_kind", "payload_source", "operand_slice_normalized_sha256"):
                    self.assertTrue(invocation[key])

    def test_05_all_broad_and_live_gates_remain_false(self) -> None:
        truth = self.contract["truth_boundary"]
        for key in VERIFIER.FALSE_FLAGS:
            with self.subTest(key=key):
                self.assertIs(truth[key], False)
        self.assertIs(self.contract["scope"]["issue_acceptance_checkbox_completed"], False)

    def test_06_legacy_quirks_are_preserved_not_promoted(self) -> None:
        for proof in self.contract["legacy_mapping_proofs"]:
            static = proof["legacy_static_quirks"]
            self.assertIs(static["static_array_safe"], False)
            self.assertIs(static["total_supply_helper"]["erc20_result_data_decoded"], False)

    def test_07_direct_key_mutation_is_rejected(self) -> None:
        context = self.by_profile["legacy-base-root"]
        self.assert_semantics_rejected(context, [self.mutation(context["handler"], 22, "i32.const 1272")])

    def test_08_direct_value_wrapper_mutation_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-root"]
        self.assert_semantics_rejected(
            context,
            [self.mutation(context["handler"], 24, "call $~lib/@graphprotocol/graph-ts/index/Value.fromBigInt")],
        )

    def test_08b_direct_receiver_or_payload_mutation_is_rejected(self) -> None:
        context = self.by_profile["legacy-base-root"]
        self.assert_semantics_rejected(context, [self.mutation(context["handler"], 21, "local.get $l1")])
        self.assert_semantics_rejected(context, [self.mutation(context["handler"], 23, "global.get $g2")])

    def test_09_helper_hidden_key_mutation_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-qmrv"]
        helper = self.function_by_suffix(context, "src/types/schema/Factory#set:poolCount")
        self.assert_semantics_rejected(context, [self.mutation(helper, 2, "i32.const 1240")])

    def test_10_entity_constructor_allocation_mutation_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-stable"]
        entity = self.function_by_suffix(context, "index/Entity#constructor")
        self.assert_semantics_rejected(context, [self.mutation(entity, 4, "i32.const 8")])

    def test_11_array_push_abort_pointer_mutation_is_rejected(self) -> None:
        context = self.by_profile["legacy-base-root"]
        push = self.function_by_suffix(context, "TypedMapEntry<~lib/string/String_~lib/@graphprotocol/graph-ts/index/Value>>#push")
        self.assert_semantics_rejected(context, [self.mutation(push, 22, "i32.const 1180")])

    def test_12_string_array_kind_mutation_is_rejected(self) -> None:
        context = self.by_profile["legacy-mainnet-root"]
        wrapper = self.function_by_suffix(context, "index/Value.fromStringArray")
        self.assert_semantics_rejected(context, [self.mutation(wrapper, 28, "i32.const 0")])

    def test_13_scope_or_checkbox_promotion_is_rejected(self) -> None:
        mutations = []
        changed = copy.deepcopy(self.contract)
        changed["scope"]["factory_paths_closed_after"] = 17
        mutations.append(changed)
        changed = copy.deepcopy(self.contract)
        changed["scope"]["issue_acceptance_checkbox_completed"] = True
        mutations.append(changed)
        changed = copy.deepcopy(self.contract)
        changed["truth_boundary"]["issue_38_acceptance_criterion_complete"] = True
        mutations.append(changed)
        for ordinal, changed in enumerate(mutations):
            with self.subTest(ordinal=ordinal):
                self.assert_contract_rejected(changed)

    def test_14_source_digest_or_transitive_binding_mutation_is_rejected(self) -> None:
        mutations = []
        for path in (
            ("factory_pool_price_initialization", "raw_sha256"),
            ("factory_pool_price_initialization", "transitive_input_manifest_sha256"),
            ("shared_wat_runtime", "raw_sha256"),
        ):
            changed = copy.deepcopy(self.contract)
            changed["source_contracts"][path[0]][path[1]] = "0" * 64
            mutations.append(changed)
        for ordinal, changed in enumerate(mutations):
            with self.subTest(ordinal=ordinal):
                self.assert_contract_rejected(changed)

    def test_15_missing_segment_or_pairwise_diff_is_rejected(self) -> None:
        changed = copy.deepcopy(self.contract)
        changed["segments"].pop()
        self.assert_contract_rejected(changed)
        changed = copy.deepcopy(self.contract)
        changed["segment_diffs"].pop()
        self.assert_contract_rejected(changed)

    def test_16_duplicate_json_keys_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="factory-static-v2-json-") as temporary:
            path = Path(temporary) / "duplicate.json"
            path.write_text('{"scope":{},"scope":{}}\n')
            with self.assertRaises(self.expected_errors):
                VERIFIER.load_json(path)

    def test_17_documentation_and_indexes_preserve_refusals(self) -> None:
        readme = (ROOT / "uniswap-v3/factory-static/v2/README.md").read_text()
        eligibility = (ROOT / "uniswap-v3/factory-static/v2/docs/eligibility.md").read_text()
        provenance = (ROOT / "uniswap-v3/factory-static/v2/docs/provenance.md").read_text()
        indexes = (ROOT / "README.md").read_text() + (ROOT / "uniswap-v3/README.md").read_text()
        combined = readme + eligibility + provenance
        for text in ("44", "78", "59", "Pool.tick", "18/18", "CallResult", "six leading"):
            self.assertIn(text, combined)
        self.assertIn("factory-static/v2", indexes)
        self.assertIn("completes no checkbox", combined.lower())
        self.assertIn("backfill_ready", eligibility)
        self.assertNotIn("static_array_safe` is true", combined)


if __name__ == "__main__":
    unittest.main()
