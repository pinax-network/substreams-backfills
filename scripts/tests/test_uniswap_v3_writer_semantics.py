from __future__ import annotations

import copy
import importlib.util
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[2]
VERIFIER = REPOSITORY / "scripts/verify-uniswap-v3-writer-semantics.py"
SPEC = importlib.util.spec_from_file_location("uniswap_v3_writer_semantics", VERIFIER)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
CONTRACT_PATH = REPOSITORY / MODULE.CONTRACT_PATH


class UniswapV3WriterSemanticsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = MODULE.verify(REPOSITORY)

    def mutated_contract(self, mutate) -> tempfile.TemporaryDirectory[str]:
        temporary = tempfile.TemporaryDirectory()
        contract = copy.deepcopy(self.contract)
        mutate(contract)
        contract_path = Path(temporary.name) / "writer-compatibility.json"
        contract_path.write_text(MODULE.render(contract), encoding="utf-8")
        temporary.contract_path = contract_path  # type: ignore[attr-defined]
        return temporary

    def test_exact_contract_is_deterministic_and_recomputes_every_mapping(self) -> None:
        self.assertEqual(
            CONTRACT_PATH.read_text(encoding="utf-8"),
            MODULE.render(MODULE.build_contract(REPOSITORY)),
        )
        closure = self.contract["global_store_set_closure"]
        self.assertEqual(closure["mapping_count"], 20)
        self.assertEqual(closure["registered_handler_count"], 70)
        self.assertEqual(closure["store_set_callsite_count"], 162)
        self.assertEqual(closure["fixed_target_callsite_count"], 162)
        self.assertEqual(closure["dynamic_target_callsite_count"], 0)
        self.assertEqual(closure["indirect_store_set_reference_count"], 0)
        self.assertEqual(len(self.contract["npm_semantic_profiles"]), 5)
        self.assertEqual(len(self.contract["segments"]), 8)
        for mapping in self.contract["mapping_analyses"]:
            self.assertEqual(mapping["store_set_import_count"], 1)
            self.assertEqual(
                mapping["store_set_callsite_count"],
                len(mapping["store_set_callsites"]),
            )
            for site in mapping["store_set_callsites"]:
                self.assertTrue(site["target_argument_shape"].startswith("i32.const"))

    def test_required_absence_is_backed_by_complete_global_callsite_closure(self) -> None:
        closure = self.contract["global_store_set_closure"]
        self.assertTrue(closure["complete_all_function_scan"])
        self.assertTrue(set(MODULE.REQUIRED_ABSENT).isdisjoint(closure["fixed_targets"]))
        for item in self.contract["required_absence_certifications"]:
            self.assertEqual(item["matching_store_set_callsite_count"], 0)
            self.assertEqual(item["dynamic_store_set_target_count"], 0)
            self.assertEqual(item["indirect_store_set_reference_count"], 0)
            self.assertTrue(item["static_writer_absence_certified"])
            self.assertFalse(item["runtime_population_certified"])
        for profile in self.contract["npm_semantic_profiles"]:
            for evidence in profile["mapping_evidence"]:
                self.assertEqual(
                    evidence["collect_reachability"]["reachable_store_set_targets"],
                    ["Position", "PositionSnapshot", "Transaction"],
                )
        for evidence in self.contract["pool_flash_evidence"]:
            self.assertEqual(
                evidence["reachable_writers"]["reachable_store_set_targets"],
                ["Pool"],
            )

    def test_profiles_guards_features_and_failure_policies_are_segment_specific(self) -> None:
        segments = self.contract["segments"]
        effective = [
            (item["network"], item["deployment"])
            for item in segments
            if item["historical_guard"]["effective_in_segment"]
        ]
        self.assertEqual(
            effective,
            [("base", "QmPWDTWRfS8XewMJhxXoQiZX6RkrUMYH7BFnnB846v6wzR")],
        )
        nonfatal = [
            item["deployment"]
            for item in segments
            if "nonFatalErrors" in item["manifest_features"]
        ]
        self.assertEqual(
            nonfatal,
            [
                "QmTZ8ejXJxRo7vDBS4uwqBeGoxLSWbhaA7oXa1RvxunLy7",
                "QmPWDTWRfS8XewMJhxXoQiZX6RkrUMYH7BFnnB846v6wzR",
                "Qmb4VUcAY9LsVgeCuCCMs7X1XrkbRcaiuAbSK8SqhmsAfP",
            ],
        )
        for segment in segments:
            self.assertEqual(
                segment["npm_profile_id"],
                MODULE.PROFILE_BY_MAPPING[segment["npm_mapping_cid"]],
            )
            self.assertEqual(
                [
                    item["handler"]
                    for item in segment["npm_event_handlers_in_manifest_order"]
                ],
                list(MODULE.NPM_HANDLERS),
            )

    def test_graph_node_source_model_is_exactly_bound_but_runtime_is_not(self) -> None:
        evidence = self.contract["graph_node_source_evidence"]
        self.assertEqual(evidence["version"], "v0.44.0")
        self.assertEqual(evidence["commit"], MODULE.GRAPH_NODE_COMMIT)
        self.assertEqual(evidence["tree"], MODULE.GRAPH_NODE_TREE)
        self.assertEqual(evidence["files"], MODULE.graph_node_source_evidence()["files"])
        self.assertFalse(evidence["target_runtime_binary_or_source_identity_bound"])
        self.assertFalse(
            self.contract["truth_boundary"]["target_graph_node_runtime_identity_bound"]
        )

    def test_target_drift_is_rejected(self) -> None:
        def mutate(contract) -> None:
            contract["mapping_analyses"][0]["store_set_callsites"][0][
                "target"
            ] = "Flash"

        with self.mutated_contract(mutate) as temporary:
            with self.assertRaises(MODULE.VerificationError):
                MODULE.verify(REPOSITORY, Path(temporary) / "writer-compatibility.json")

    def test_unrelated_literal_cannot_hide_a_dynamic_store_target(self) -> None:
        memory = bytearray(65_536)
        pointer = 64
        value = "Position"
        encoded = value.encode("utf-16le")
        struct.pack_into("<I", memory, pointer, len(value))
        memory[pointer + 4 : pointer + 4 + len(encoded)] = encoded
        function = MODULE.WatFunction(
            "synthetic/dynamic",
            1,
            (
                "  (func $synthetic/dynamic (param $p0 i32) (param $p1 i32) (param $p2 i32)",
                f"    i32.const {pointer}",
                "    drop",
                "    local.get $p0",
                "    local.get $p1",
                "    call $~lib/@graphprotocol/graph-ts/index/Value#toString",
                "    local.get $p2",
                f"    call ${MODULE.STORE_SET_CALL})",
            ),
        )
        sites = MODULE.extract_store_set_callsites({function.name: function}, memory)
        self.assertEqual(sites[0]["candidate_entity_literals"], ["Position"])
        self.assertIsNone(sites[0]["target"])
        with self.assertRaisesRegex(MODULE.VerificationError, "dynamic store.set"):
            MODULE.require_fixed_callsites(sites, "synthetic")

    def test_indirect_store_target_is_rejected(self) -> None:
        def mutate(contract) -> None:
            contract["mapping_analyses"][0]["indirect_store_set_reference_count"] = 1
            contract["global_store_set_closure"]["indirect_store_set_reference_count"] = 1

        with self.mutated_contract(mutate) as temporary:
            with self.assertRaisesRegex(MODULE.VerificationError, "indirect"):
                MODULE.verify(REPOSITORY, Path(temporary) / "writer-compatibility.json")

    def test_call_indirect_writer_is_in_the_conservative_handler_closure(self) -> None:
        memory = bytearray(65_536)
        pointer = 64
        value = "Position"
        encoded = value.encode("utf-16le")
        struct.pack_into("<I", memory, pointer, len(value))
        memory[pointer + 4 : pointer + 4 + len(encoded)] = encoded
        handler = MODULE.WatFunction(
            "synthetic/handleCollect",
            1,
            (
                "  (func $synthetic/handleCollect (param $p0 i32)",
                "    i32.const 1",
                "    call_indirect $0 (type $t0))",
            ),
        )
        writer = MODULE.WatFunction(
            "synthetic/table-writer",
            4,
            (
                "  (func $synthetic/table-writer (param $p0 i32) (param $p1 i32)",
                f"    i32.const {pointer}",
                "    local.get $p0",
                "    call $~lib/@graphprotocol/graph-ts/index/Value#toString",
                "    local.get $p1",
                f"    call ${MODULE.STORE_SET_CALL})",
            ),
        )
        functions = {handler.name: handler, writer.name: writer}
        analysis = {
            "store_set_callsites": MODULE.extract_store_set_callsites(
                functions, memory
            ),
            "call_indirect_table_targets": [writer.name],
        }
        reachability = MODULE.critical_reachability(
            analysis, functions, "handleCollect"
        )
        self.assertEqual(reachability["reachable_function_count"], 2)
        self.assertEqual(
            reachability["conservative_call_indirect_table_targets"],
            [writer.name],
        )
        self.assertEqual(
            reachability["reachable_store_set_targets"], ["Position"]
        )

    def test_indirect_table_imports_and_mutation_are_rejected(self) -> None:
        imported = '(import "env" "table" (table $0 2 funcref))'
        with self.assertRaisesRegex(MODULE.VerificationError, "imports"):
            MODULE.verify_closed_indirect_table(
                imported,
                1,
                ("synthetic/table-target",),
                "synthetic",
            )

        for instruction in MODULE.TABLE_MUTATION_INSTRUCTIONS:
            with self.subTest(instruction=instruction):
                wat = f"  (table $0 2 funcref)\n    {instruction}"
                with self.assertRaisesRegex(MODULE.VerificationError, "mutable"):
                    MODULE.verify_closed_indirect_table(
                        wat,
                        1,
                        ("synthetic/table-target",),
                        "synthetic",
                    )

        with self.assertRaisesRegex(MODULE.VerificationError, "call_ref"):
            MODULE.verify_closed_indirect_table(
                "    call_ref $t0",
                0,
                (),
                "synthetic",
            )

    def test_historical_guard_requires_block_load_comparison_and_early_return(self) -> None:
        old_prefix = [
            "    local.get $p0",
            "    i32.load offset=16",
            "    i32.load offset=28",
            f"    i32.const {MODULE.HISTORICAL_GUARD_BLOCK}",
            "    call $~lib/@graphprotocol/graph-ts/index/ByteArray.fromI32",
            "    call $~lib/@graphprotocol/graph-ts/index/BigInt#equals",
            "    if $I0",
            "      return",
            "    end",
        ]

        def function(prefix: list[str]) -> object:
            return MODULE.WatFunction(
                "synthetic/handleIncreaseLiquidity",
                1,
                tuple(
                    [
                        "  (func $synthetic/handleIncreaseLiquidity (param $p0 i32)",
                        "    (local $l1 i32)",
                    ]
                    + prefix
                    + ["    nop)"]
                ),
            )

        proof = MODULE.historical_guard_proof(function(old_prefix))
        self.assertIsNotNone(proof)
        assert proof is not None
        self.assertEqual(proof["block_number_load_offset"], 28)
        self.assertTrue(proof["conditional_early_return"])

        broken_prefixes = []
        for index, replacement in (
            (2, "    i32.load offset=24"),
            (5, "    drop"),
            (7, "      nop"),
        ):
            candidate = old_prefix.copy()
            candidate[index] = replacement
            broken_prefixes.append(candidate)
        for prefix in broken_prefixes:
            with self.subTest(prefix=prefix):
                with self.assertRaisesRegex(
                    MODULE.VerificationError, "historical guard"
                ):
                    MODULE.historical_guard_proof(function(prefix))

    def test_collect_or_flash_reachability_drift_is_rejected(self) -> None:
        for collection, reachability_key in (
            ("npm_semantic_profiles", "collect_reachability"),
            ("pool_flash_evidence", "reachable_writers"),
        ):
            with self.subTest(collection=collection):
                def mutate(contract) -> None:
                    record = contract[collection][0]
                    if collection == "npm_semantic_profiles":
                        record = record["mapping_evidence"][0]
                    record[reachability_key]["reachable_store_set_targets"] = ["Flash"]

                with self.mutated_contract(mutate) as temporary:
                    with self.assertRaisesRegex(MODULE.VerificationError, "reachability"):
                        MODULE.verify(
                            REPOSITORY,
                            Path(temporary) / "writer-compatibility.json",
                        )

    def test_profile_or_segment_misselection_is_rejected(self) -> None:
        def mutate_profile(contract) -> None:
            contract["npm_semantic_profiles"][0]["mapping_cids"] = [
                "QmPjhEuGqknJJ2LfJCi6XTLFLtiymYfZAtjTLfkmJJGMEj"
            ]

        def mutate_segment(contract) -> None:
            contract["segments"][0]["npm_profile_id"] = "current-amount0-to-both"

        for mutate in (mutate_profile, mutate_segment):
            with self.subTest(mutate=mutate.__name__):
                with self.mutated_contract(mutate) as temporary:
                    with self.assertRaisesRegex(MODULE.VerificationError, "profile"):
                        MODULE.verify(
                            REPOSITORY,
                            Path(temporary) / "writer-compatibility.json",
                        )

    def test_tool_identity_wat_hash_and_handler_identity_drift_are_rejected(self) -> None:
        def mutate_archive(contract) -> None:
            contract["toolchain"]["official_linux_archive"]["sha256"] = "0" * 64

        def mutate_wat(contract) -> None:
            contract["mapping_analyses"][0]["wat_sha256"] = "0" * 64

        def mutate_handler_identity(contract) -> None:
            contract["handler_identity_groups"][0]["shared_sha256"] = "0" * 64

        for mutate in (mutate_archive, mutate_wat, mutate_handler_identity):
            with self.subTest(mutate=mutate.__name__):
                with self.mutated_contract(mutate) as temporary:
                    with self.assertRaises(MODULE.VerificationError):
                        MODULE.verify(
                            REPOSITORY,
                            Path(temporary) / "writer-compatibility.json",
                        )

    def test_wrong_wasm2wat_version_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "wasm2wat"
            executable.write_text("#!/bin/sh\nprintf '0.0.0\\n'\n", encoding="utf-8")
            os.chmod(executable, 0o755)
            with self.assertRaisesRegex(MODULE.VerificationError, "WABT version drift"):
                MODULE.resolve_wasm2wat(executable)

    def test_false_certification_is_rejected(self) -> None:
        false_gates = [
            key
            for key, value in self.contract["truth_boundary"].items()
            if value is False
        ]
        for gate in false_gates:
            with self.subTest(gate=gate):
                def mutate(contract) -> None:
                    contract["truth_boundary"][gate] = True

                with self.mutated_contract(mutate) as temporary:
                    with self.assertRaises(MODULE.VerificationError):
                        MODULE.verify(
                            REPOSITORY,
                            Path(temporary) / "writer-compatibility.json",
                        )

        def certify_runtime_population(contract) -> None:
            contract["required_absence_certifications"][0][
                "runtime_population_certified"
            ] = True

        def certify_complete_profile(contract) -> None:
            contract["npm_semantic_profiles"][0][
                "full_handler_or_field_writer_audit_complete"
            ] = True

        def bind_unproved_runtime(contract) -> None:
            contract["graph_node_source_evidence"][
                "target_runtime_binary_or_source_identity_bound"
            ] = True

        for mutate in (
            certify_runtime_population,
            certify_complete_profile,
            bind_unproved_runtime,
        ):
            with self.subTest(mutate=mutate.__name__):
                with self.mutated_contract(mutate) as temporary:
                    with self.assertRaises(MODULE.VerificationError):
                        MODULE.verify(
                            REPOSITORY,
                            Path(temporary) / "writer-compatibility.json",
                        )


if __name__ == "__main__":
    unittest.main()
