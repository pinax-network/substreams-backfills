from __future__ import annotations

import copy
import importlib.util
import itertools
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VERIFIER_PATH = ROOT / "scripts/verify-uniswap-v3-segment-field-semantics-v2.py"
SPEC = importlib.util.spec_from_file_location(
    "uniswap_v3_segment_field_semantics_v2", VERIFIER_PATH
)
assert SPEC is not None and SPEC.loader is not None
VERIFIER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VERIFIER
SPEC.loader.exec_module(VERIFIER)


class SegmentFieldSemanticsV2Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # Recompute the retained-WASM projection once. Mutation tests reuse the
        # exact verified source objects so each refusal tests v2 rather than
        # repeatedly paying the WAT conversion cost.
        cls.sources = VERIFIER.load_sources(ROOT, recompute_wat=True)
        cls.contract = VERIFIER.verify_contract(
            ROOT,
            sources=cls.sources,
            recompute_wat=False,
        )
        factory_profiles = cls.sources["writer_compatibility"]["factory_writer_contract"][
            "mapping_bindings"
        ]
        legacy_cid = next(
            item["mapping_cid"]
            for item in factory_profiles
            if item["profile_id"] == "legacy-mainnet-root"
        )
        modern_cid = next(
            item["mapping_cid"]
            for item in factory_profiles
            if item["profile_id"] == "modern-mainnet"
        )
        cls.factory_contexts = {
            "legacy": VERIFIER.load_factory_wat_context(
                ROOT,
                legacy_cid,
                cls.sources["writer_compatibility"],
            ),
            "modern": VERIFIER.load_factory_wat_context(
                ROOT,
                modern_cid,
                cls.sources["writer_compatibility"],
            ),
        }

    def assert_rejected(self, contract: dict[str, object], label: str) -> None:
        with self.assertRaises(VERIFIER.VerificationError, msg=label):
            VERIFIER.verify_contract(
                ROOT,
                contract,
                sources=self.sources,
                recompute_wat=False,
            )

    def assert_factory_wat_rejected(
        self,
        generation: str,
        mutate: object,
        label: str,
    ) -> None:
        context = self.factory_contexts[generation]
        lines = list(context["handler"].lines)
        mutate(lines, context)
        handler = VERIFIER.WRITER.WatFunction(
            context["handler"].name,
            context["handler"].start_line,
            tuple(lines),
            context["handler"].function_index,
        )
        changed = {**context, "handler": handler}
        with self.assertRaises(VERIFIER.VerificationError, msg=label):
            VERIFIER.prove_factory_wat_context(changed)

    def assert_factory_wat_withdrawn(
        self,
        generation: str,
        mutate: object,
        label: str,
    ) -> None:
        context = self.factory_contexts[generation]
        lines = list(context["handler"].lines)
        mutate(lines, context)
        handler = VERIFIER.WRITER.WatFunction(
            context["handler"].name,
            context["handler"].start_line,
            tuple(lines),
            context["handler"].function_index,
        )
        proof = VERIFIER.prove_factory_wat_context({**context, "handler": handler})
        if generation == "modern":
            self.assertIs(
                proof["excluded_pool_guard"][
                    "event_pool_to_comparison_to_early_return_machine_proven"
                ],
                False,
                label,
            )
        effects = proof["normal_return_effect_order_and_arguments"]
        self.assertIs(effects["same_path_or_dataflow_machine_proven"], False, label)
        self.assertIs(effects["argument_identity_machine_proven"], False, label)
        self.assertIs(
            effects["template_identity_and_argument_machine_proven"], False, label
        )

    def assert_factory_total_supply_wat_rejected(
        self,
        mutate: object,
        label: str,
    ) -> None:
        context = self.factory_contexts["modern"]
        helper = VERIFIER.WRITER.resolve_suffix_function(
            context["functions"],
            "/fetchTokenTotalSupply",
            "mutated modern total-supply helper",
        )
        lines = list(helper.lines)
        mutate(lines)
        changed_helper = VERIFIER.WRITER.WatFunction(
            helper.name,
            helper.start_line,
            tuple(lines),
            helper.function_index,
        )
        functions = dict(context["functions"])
        functions[helper.name] = changed_helper
        with self.assertRaises(VERIFIER.VerificationError, msg=label):
            VERIFIER.prove_factory_wat_context({**context, "functions": functions})

    def assert_factory_function_wat_rejected(
        self,
        generation: str,
        function_name: str,
        mutate: object,
        label: str,
    ) -> None:
        context = self.factory_contexts[generation]
        helper = context["functions"][function_name]
        lines = list(helper.lines)
        mutate(lines, context)
        changed_helper = VERIFIER.WRITER.WatFunction(
            helper.name,
            helper.start_line,
            tuple(lines),
            helper.function_index,
        )
        functions = dict(context["functions"])
        functions[helper.name] = changed_helper
        with self.assertRaises(VERIFIER.VerificationError, msg=label):
            VERIFIER.prove_factory_wat_context({**context, "functions": functions})

    def test_committed_contract_is_the_deterministic_full_inventory_projection(self) -> None:
        expected = VERIFIER.expected_contract_from_sources(self.sources)
        self.assertEqual(self.contract, expected)
        self.assertEqual(
            (self.contract["format_version"], self.contract["contract_version"]),
            (2, "uniswap-v3-segment-field-semantics/v2"),
        )
        result = subprocess.run(
            [sys.executable, str(VERIFIER_PATH), "--root", str(ROOT)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("8 segments, 80 handlers, 299 fields, 28 diffs", result.stdout)

    def test_every_schema_field_is_inventoried_without_promoting_the_residual(self) -> None:
        catalog = self.contract["field_catalog"]
        self.assertEqual(len(catalog), 299)
        self.assertEqual(len({(item["entity"], item["field"]) for item in catalog}), 299)
        self.assertEqual(len({item["entity"] for item in catalog}), 20)

        statuses: dict[str, int] = {}
        for item in catalog:
            statuses[item["semantic_status"]] = statuses.get(item["semantic_status"], 0) + 1
        self.assertEqual(
            statuses,
            {
                "certified_required_absent": 33,
                "certified_selected_handler_projection": 34,
                "conservative_reachability_only": 174,
                "digest_bound_reviewed_incomplete": 58,
            },
        )
        self.assertEqual(sum(item["complete_selected_handler_projection"] for item in catalog), 34)
        self.assertEqual(sum(item["complete_entity_history"] for item in catalog), 33)
        residual = [item for item in catalog if not item["semantic_status"].startswith("certified_")]
        self.assertEqual(len(residual), 232)
        self.assertTrue(all(item["blockers"] for item in residual))

    def test_position_relations_and_shared_histories_stay_explicitly_blocked(self) -> None:
        by_identity = {
            (item["entity"], item["field"]): item for item in self.contract["field_catalog"]
        }
        for identity in VERIFIER.POSITION_RELATION_FIELDS:
            field = by_identity[identity]
            self.assertEqual(field["semantic_status"], "conservative_reachability_only")
            self.assertIn("relation-id serialization", field["blockers"][0])
            self.assertFalse(field["complete_entity_history"])

        for entity in ("Transaction", "Pool"):
            fields = [item for item in self.contract["field_catalog"] if item["entity"] == entity]
            self.assertTrue(fields)
            incomplete = [item for item in fields if not item["complete_entity_history"]]
            self.assertTrue(incomplete)
            self.assertTrue(
                all(
                    any("last-writer history" in blocker for blocker in item["blockers"])
                    or item["complete_selected_handler_projection"]
                    for item in incomplete
                )
            )

    def test_all_segments_handlers_fields_and_pairwise_evidence_diffs_are_closed(self) -> None:
        segments = self.contract["segments"]
        self.assertEqual(len(segments), 8)
        ids = [item["segment_id"] for item in segments]
        self.assertEqual(len(set(ids)), 8)
        self.assertEqual(sum(len(item["semantic_surface"]["handlers"]) for item in segments), 80)
        self.assertEqual(sum(len(item["semantic_surface"]["fields"]) for item in segments), 2392)
        for segment in segments:
            self.assertEqual(
                tuple(item["handler_id"] for item in segment["semantic_surface"]["handlers"]),
                VERIFIER.HANDLER_ORDER,
            )
            self.assertEqual(len(segment["semantic_surface"]["fields"]), 299)
            self.assertEqual(segment["execution_model"], "undecided")
            self.assertIs(segment["backfill_allowed"], False)

        diffs = self.contract["segment_diffs"]
        self.assertEqual(len(diffs), 28)
        self.assertEqual(
            {(item["left_segment_id"], item["right_segment_id"]) for item in diffs},
            set(itertools.combinations(ids, 2)),
        )
        by_id = {item["segment_id"]: item for item in segments}
        for item in diffs:
            left = by_id[item["left_segment_id"]]
            right = by_id[item["right_segment_id"]]
            self.assertEqual(
                item["evidence_semantic_diff_paths"],
                VERIFIER.json_diff_paths(left["semantic_surface"], right["semantic_surface"]),
            )
            self.assertEqual(
                item["provenance_diff_paths"],
                VERIFIER.json_diff_paths(left["provenance_surface"], right["provenance_surface"]),
            )
            self.assertIs(item["complete_writer_semantics_compared"], False)
            self.assertIs(item["boundary_state_compared"], False)
            self.assertIs(item["graph_oracle_compared"], False)

    def test_retained_wasm_is_authority_for_all_unique_factory_and_pool_profiles(self) -> None:
        ledger = self.contract["factory_pool_control_dataflow_ledger"]
        self.assertEqual(len(ledger), 14)
        self.assertEqual(sum(item["component"] == "Factory" for item in ledger), 6)
        self.assertEqual(sum(item["component"] == "Pool" for item in ledger), 8)
        self.assertEqual(len({item["mapping_cid"] for item in ledger}), 14)
        for item in ledger:
            retained = item["retained_wasm"]
            artifact = ROOT / retained["path"]
            self.assertTrue(artifact.is_file())
            self.assertEqual(VERIFIER.raw_sha256(artifact), retained["sha256"])
            self.assertIs(retained["artifact_authority"], True)
            self.assertEqual(item["source_corroboration"]["artifact_authority"], "retained_mapping_wasm")
            self.assertIs(item["source_corroboration_authoritative"], False)
            self.assertTrue(item["unresolved_control_dataflow_paths"])
            self.assertTrue(all(path.startswith("$.") for path in item["unresolved_control_dataflow_paths"]))

    def test_factory_effect_metadata_and_failure_evidence_is_bound_but_not_promoted(self) -> None:
        factories = [
            item
            for item in self.contract["factory_pool_control_dataflow_ledger"]
            if item["component"] == "Factory"
        ]
        self.assertEqual(
            {item["profile_id"] for item in factories},
            {
                "legacy-base-root",
                "legacy-mainnet-qmrv",
                "legacy-mainnet-root",
                "legacy-mainnet-stable",
                "modern-base",
                "modern-mainnet",
            },
        )
        expected_order = [
            "Pool.save",
            "PoolTemplate.create",
            "Token[token0].save",
            "Token[token1].save",
            "Factory.save",
        ]
        for item in factories:
            profile = item["profile_record"]
            self.assertEqual(
                profile["pool_created_effect_order_observation"]["reviewed_order"],
                expected_order,
            )
            self.assertIs(
                profile["pool_created_effect_order_observation"][
                    "same_path_or_dataflow_machine_proven"
                ],
                False,
            )
            self.assertIs(
                profile["excluded_pool_guard_observation"][
                    "event_pool_to_comparison_to_early_return_machine_proven"
                ],
                False,
            )
            self.assertIn(
                profile["metadata_evidence"]["total_supply_model"],
                {
                    "decode the ERC20 totalSupply result as BigInt",
                    "on success convert the CallResult pointer/allocation with ByteArray.fromI32 rather than reading the ERC20 result",
                },
            )
            self.assertIs(profile["complete_static_handler_contract"], False)

    def test_factory_retained_wat_closes_only_four_legacy_guard_paths(self) -> None:
        scope = self.contract["scope"]
        self.assertEqual(scope["factory_upstream_unresolved_path_count_before"], 18)
        self.assertEqual(scope["factory_upstream_unresolved_path_count_closed_by_v2"], 4)
        self.assertEqual(scope["factory_upstream_unresolved_path_count_after"], 14)
        factories = [
            item
            for item in self.contract["factory_pool_control_dataflow_ledger"]
            if item["component"] == "Factory"
        ]
        self.assertEqual(len(factories), 6)
        closed = 0
        for item in factories:
            proof = item["v2_retained_wat_cfg_dataflow"]
            generation = item["profile_record"]["metadata_generation"]
            if generation == "legacy":
                self.assertEqual(
                    item["v2_closed_upstream_control_dataflow_paths"],
                    [VERIFIER.FACTORY_GUARD_UPSTREAM_PATH],
                )
                self.assertEqual(
                    set(item["unresolved_control_dataflow_paths"]),
                    {
                        VERIFIER.FACTORY_EFFECT_UPSTREAM_PATH,
                        VERIFIER.FACTORY_STATIC_UPSTREAM_PATH,
                    },
                )
                self.assertIs(
                    proof["excluded_pool_guard"][
                        "event_pool_to_comparison_to_early_return_machine_proven"
                    ],
                    True,
                )
                closed += 1
            else:
                self.assertEqual(item["v2_closed_upstream_control_dataflow_paths"], [])
                self.assertEqual(
                    set(item["unresolved_control_dataflow_paths"]),
                    VERIFIER.FACTORY_UPSTREAM_UNRESOLVED_PATHS,
                )
                self.assertIs(
                    proof["excluded_pool_guard"][
                        "event_pool_to_comparison_to_early_return_machine_proven"
                    ],
                    False,
                )
                self.assertEqual(
                    proof["excluded_pool_guard"]["claim_status"],
                    "withheld_after_independent_review",
                )
            effects = proof["normal_return_effect_order_and_arguments"]
            self.assertEqual(effects["claim_status"], "withheld_after_independent_review")
            self.assertIs(effects["same_path_or_dataflow_machine_proven"], False)
            self.assertIs(effects["argument_identity_machine_proven"], False)
            self.assertIs(effects["template_identity_and_argument_machine_proven"], False)
            self.assertIs(effects["graph_handler_rollback_proven_by_retained_wat"], False)
            total_supply = proof["initialized_field_value_evidence"]["total_supply_helper"]
            self.assertEqual(
                total_supply["claim_status"], "withheld_after_independent_review"
            )
            self.assertIs(total_supply["success_failure_dataflow_machine_proven"], False)
            self.assertIs(
                total_supply["success_result_decode_is_contiguous_into_value_wrapper"],
                False,
            )
            self.assertNotIn("outcomes", total_supply)
            self.assertEqual(
                proof["initialized_field_value_evidence"]["machine_proven_subset"], []
            )
            self.assertIs(
                proof["initialized_field_value_evidence"][
                    "complete_all_initialized_field_values_machine_proven"
                ],
                False,
            )
            self.assertIs(proof["complete_static_handler_contract"], False)
        self.assertEqual(closed, 4)

    def test_factory_total_supply_profiles_are_provenance_only(self) -> None:
        proofs = self.sources["_factory_wat_proofs"]
        legacy = [item for item in proofs if item["generation"] == "legacy"]
        modern = [item for item in proofs if item["generation"] == "modern"]
        self.assertEqual((len(legacy), len(modern)), (4, 2))
        for item in proofs:
            helper = item["initialized_field_value_evidence"]["total_supply_helper"]
            profile = next(
                profile
                for profile in self.sources["writer_compatibility"][
                    "factory_writer_contract"
                ]["mapping_bindings"]
                if profile["mapping_cid"] == item["mapping_cid"]
            )
            self.assertEqual(
                helper["upstream_model"], profile["metadata_evidence"]["total_supply_model"]
            )
            self.assertEqual(
                helper["body_sha256"],
                profile["metadata_evidence"]["total_supply_helper"]["body_sha256"],
            )
            self.assertIs(helper["success_failure_dataflow_machine_proven"], False)
            self.assertNotIn("outcomes", helper)

    def test_legacy_factory_wat_branch_inversion_is_rejected(self) -> None:
        def invert_legacy(lines: list[str], _context: dict[str, object]) -> None:
            guard_if = next(
                index
                for index, line in enumerate(lines)
                if VERIFIER.normalized_wat_line(line).startswith("if $")
            )
            indent = lines[guard_if][: len(lines[guard_if]) - len(lines[guard_if].lstrip())]
            lines.insert(guard_if, f"{indent}i32.eqz")

        self.assert_factory_wat_rejected("legacy", invert_legacy, "legacy guard inversion")

    def test_legacy_factory_guard_rejects_self_equality_and_wrong_active_literal(self) -> None:
        equals_name = "~lib/@graphprotocol/graph-ts/index/ByteArray#equals"
        from_hex_name = "~lib/@graphprotocol/graph-ts/index/ByteArray.fromHexString"

        def self_compare(lines: list[str], _context: dict[str, object]) -> None:
            replacements = 0
            for index, line in enumerate(lines):
                if VERIFIER.normalized_wat_line(line) != "local.get $p1":
                    continue
                indent = line[: len(line) - len(line.lstrip())]
                lines[index] = f"{indent}local.get $p0"
                replacements += 1
            self.assertEqual(replacements, 2)

        self.assert_factory_function_wat_rejected(
            "legacy",
            equals_name,
            self_compare,
            "legacy excluded guard self equality",
        )

        def replace_initial_active_input(
            lines: list[str], context: dict[str, object]
        ) -> None:
            memory = context["memory"]
            active = next(
                index
                for index, line in enumerate(lines)
                if VERIFIER.decoded_wat_constant(line, memory)
                == VERIFIER.WRITER.EXCLUDED_POOL
                and index + 1 < len(lines)
                and VERIFIER.normalized_wat_line(lines[index + 1]).startswith("local.set $")
            )
            diagnostic = next(
                VERIFIER.normalized_wat_line(line)
                for line in lines
                if VERIFIER.decoded_wat_constant(line, memory) == "input "
            )
            indent = lines[active][: len(lines[active]) - len(lines[active].lstrip())]
            lines[active] = f"{indent}{diagnostic}"

        self.assert_factory_function_wat_rejected(
            "legacy",
            from_hex_name,
            replace_initial_active_input,
            "legacy excluded helper initial input substitution",
        )

        def replace_substring_active_input(
            lines: list[str], context: dict[str, object]
        ) -> None:
            memory = context["memory"]
            active = next(
                index
                for index, line in enumerate(lines)
                if VERIFIER.decoded_wat_constant(line, memory)
                == VERIFIER.WRITER.EXCLUDED_POOL
                and index + 3 < len(lines)
                and (VERIFIER.wat_call_name(lines[index + 3]) or "").endswith(
                    "String#substr"
                )
            )
            diagnostic = next(
                VERIFIER.normalized_wat_line(line)
                for line in lines
                if VERIFIER.decoded_wat_constant(line, memory) == "input "
            )
            indent = lines[active][: len(lines[active]) - len(lines[active].lstrip())]
            lines[active] = f"{indent}{diagnostic}"

        self.assert_factory_function_wat_rejected(
            "legacy",
            from_hex_name,
            replace_substring_active_input,
            "legacy excluded helper substring input substitution",
        )

    def test_modern_guard_counterexamples_do_not_promote_withdrawn_claim(self) -> None:
        def wrong_parsed_literal_with_dead_excluded_use(
            lines: list[str], context: dict[str, object]
        ) -> None:
            memory = context["memory"]
            excluded_sites = [
                index
                for index, line in enumerate(lines)
                if VERIFIER.decoded_wat_constant(line, memory) == VERIFIER.WRITER.EXCLUDED_POOL
            ]
            parse_site = next(
                index
                for index in excluded_sites
                if index + 3 < len(lines)
                and (VERIFIER.wat_call_name(lines[index + 3]) or "").endswith("String#substr")
            )
            factory_constant = next(
                VERIFIER.normalized_wat_line(line)
                for line in lines
                if VERIFIER.decoded_wat_constant(line, memory) == "Factory"
            )
            indent = lines[parse_site][
                : len(lines[parse_site]) - len(lines[parse_site].lstrip())
            ]
            lines[parse_site] = f"{indent}{factory_constant}"
            event_getter = next(
                index
                for index, line in enumerate(lines)
                if (VERIFIER.wat_call_name(line) or "").endswith(
                    "ethereum.EventParam>#__get"
                )
                and index > 0
                and VERIFIER.normalized_wat_line(lines[index - 1]) == "i32.const 4"
            )
            insert_at = event_getter + 4
            lines[insert_at:insert_at] = [
                f"{indent}{VERIFIER.normalized_wat_line(context['handler'].lines[excluded_sites[0]])}",
                f"{indent}drop",
            ]

        self.assert_factory_wat_withdrawn(
            "modern",
            wrong_parsed_literal_with_dead_excluded_use,
            "modern guard dead-literal camouflage",
        )

        def wrong_event_source(lines: list[str], context: dict[str, object]) -> None:
            memory = context["memory"]
            getter = next(
                index
                for index, line in enumerate(lines)
                if (VERIFIER.wat_call_name(line) or "").endswith(
                    "ethereum.EventParam>#__get"
                )
                and index > 0
                and VERIFIER.normalized_wat_line(lines[index - 1]) == "i32.const 4"
            )
            event_pointer = getter - 6
            self.assertEqual(
                VERIFIER.normalized_wat_line(lines[event_pointer]), "local.get $p0"
            )
            factory_constant = next(
                VERIFIER.normalized_wat_line(line)
                for line in lines
                if VERIFIER.decoded_wat_constant(line, memory) == "Factory"
            )
            indent = lines[event_pointer][
                : len(lines[event_pointer]) - len(lines[event_pointer].lstrip())
            ]
            lines[event_pointer] = f"{indent}{factory_constant}"

        self.assert_factory_wat_withdrawn(
            "modern",
            wrong_event_source,
            "modern guard non-event source",
        )

    def test_modern_pool_id_counterexample_does_not_promote_effect_claim(self) -> None:
        def wrong_pool_id_source(lines: list[str], context: dict[str, object]) -> None:
            memory = context["memory"]
            getter = next(
                index
                for index, line in enumerate(lines)
                if (VERIFIER.wat_call_name(line) or "").endswith("ethereum.EventParam>#__get")
                and index > 0
                and VERIFIER.normalized_wat_line(lines[index - 1]) == "i32.const 4"
                and index > 400
            )
            conversion = getter + 3
            self.assertTrue(
                (VERIFIER.wat_call_name(lines[conversion]) or "").endswith(
                    "typeConversion.bytesToHex"
                )
            )
            pool_id_local = VERIFIER.wat_local(lines[conversion + 1], "set")
            self.assertIsNotNone(pool_id_local)
            source = next(
                index
                for index in range(conversion + 2, conversion + 20)
                if VERIFIER.normalized_wat_line(lines[index])
                == f"local.get {pool_id_local}"
            )
            factory_constant = next(
                VERIFIER.normalized_wat_line(line)
                for line in lines
                if VERIFIER.decoded_wat_constant(line, memory) == "Factory"
            )
            indent = lines[source][: len(lines[source]) - len(lines[source].lstrip())]
            lines[source] = f"{indent}{factory_constant}"

        self.assert_factory_wat_withdrawn(
            "modern",
            wrong_pool_id_source,
            "modern Pool.id non-event source",
        )

    def test_factory_effect_counterexamples_do_not_promote_withdrawn_claims(self) -> None:
        def wrap_first_token_save(lines: list[str], _context: dict[str, object]) -> None:
            site = next(
                index
                for index, line in enumerate(lines)
                if (VERIFIER.wat_call_name(line) or "").endswith("schema/Token#save")
            )
            start = site - 1
            indent = lines[start][: len(lines[start]) - len(lines[start].lstrip())]
            lines[start:start] = [f"{indent}i32.const 0", f"{indent}if"]
            lines.insert(site + 3, f"{indent}end")

        for generation in ("legacy", "modern"):
            self.assert_factory_wat_withdrawn(
                generation,
                wrap_first_token_save,
                f"{generation} conditional Token.save bypass",
            )

        def wrap_modern_pool_store(lines: list[str], context: dict[str, object]) -> None:
            memory = context["memory"]
            site = next(
                index
                for index, line in enumerate(lines)
                if VERIFIER.wat_call_name(line) == VERIFIER.WRITER.STORE_SET_CALL
                and index >= 4
                and VERIFIER.decoded_wat_constant(lines[index - 4], memory) == "Pool"
            )
            start = site - 4
            indent = lines[start][: len(lines[start]) - len(lines[start].lstrip())]
            lines[start:start] = [f"{indent}i32.const 0", f"{indent}if"]
            lines.insert(site + 3, f"{indent}end")

        self.assert_factory_wat_withdrawn(
            "modern",
            wrap_modern_pool_store,
            "modern conditional Pool.store bypass",
        )

        def move_modern_pool_store_to_else(
            lines: list[str], context: dict[str, object]
        ) -> None:
            memory = context["memory"]
            site = next(
                index
                for index, line in enumerate(lines)
                if VERIFIER.wat_call_name(line) == VERIFIER.WRITER.STORE_SET_CALL
                and index >= 4
                and VERIFIER.decoded_wat_constant(lines[index - 4], memory) == "Pool"
            )
            arguments = site - 4
            indent = lines[arguments][
                : len(lines[arguments]) - len(lines[arguments].lstrip())
            ]
            lines.insert(arguments, f"{indent}else")

        self.assert_factory_wat_withdrawn(
            "modern",
            move_modern_pool_store_to_else,
            "modern Pool.store absent-id alternative",
        )

    def test_modern_total_supply_byte_drift_is_rejected_without_promoting_dataflow(self) -> None:
        def substitute_fallback_after_decode(lines: list[str]) -> None:
            decode = next(
                index
                for index, line in enumerate(lines)
                if (VERIFIER.wat_call_name(line) or "").endswith("ethereum.Value#toBigInt")
            )
            indent = lines[decode][: len(lines[decode]) - len(lines[decode].lstrip())]
            lines[decode + 1 : decode + 1] = [f"{indent}drop", f"{indent}local.get $l1"]

        self.assert_factory_total_supply_wat_rejected(
            substitute_fallback_after_decode,
            "modern totalSupply decoded value substitution",
        )

        def zero_wrapper_local_before_tail(lines: list[str]) -> None:
            tail_load = next(
                index
                for index in range(len(lines) - 1, 0, -1)
                if VERIFIER.normalized_wat_line(lines[index]) == "i32.load"
                and VERIFIER.normalized_wat_line(lines[index - 1])
                == "local.tee $p0"
            )
            indent = lines[tail_load][
                : len(lines[tail_load]) - len(lines[tail_load].lstrip())
            ]
            lines[tail_load:tail_load] = [
                f"{indent}i32.const 0",
                f"{indent}local.set $p0",
            ]

        self.assert_factory_total_supply_wat_rejected(
            zero_wrapper_local_before_tail,
            "modern totalSupply wrapper local reset before final tail",
        )

    def test_reordered_or_wrong_effects_do_not_promote_withdrawn_claims(self) -> None:
        def reorder_token_saves(lines: list[str], _context: dict[str, object]) -> None:
            sites = [
                index
                for index, line in enumerate(lines)
                if (VERIFIER.wat_call_name(line) or "").endswith("schema/Token#save")
            ]
            self.assertEqual(len(sites), 2)
            first_pair = lines[sites[0] - 1 : sites[0] + 1]
            second_pair = lines[sites[1] - 1 : sites[1] + 1]
            lines[sites[0] - 1 : sites[0] + 1] = second_pair
            lines[sites[1] - 1 : sites[1] + 1] = first_pair

        def wrong_token0_argument(lines: list[str], context: dict[str, object]) -> None:
            sites = [
                index
                for index, line in enumerate(lines)
                if (VERIFIER.wat_call_name(line) or "").endswith("schema/Token#save")
            ]
            second_local = VERIFIER.wat_local(lines[sites[1] - 1])
            self.assertIsNotNone(second_local)
            indent = lines[sites[0] - 1][: len(lines[sites[0] - 1]) - len(lines[sites[0] - 1].lstrip())]
            lines[sites[0] - 1] = f"{indent}local.get {second_local}"

        def wrong_pool_argument(lines: list[str], context: dict[str, object]) -> None:
            token_site = next(
                index
                for index, line in enumerate(lines)
                if (VERIFIER.wat_call_name(line) or "").endswith("schema/Token#save")
            )
            token_local = VERIFIER.wat_local(lines[token_site - 1])
            self.assertIsNotNone(token_local)
            pool_site = next(
                index
                for index, line in enumerate(lines)
                if (VERIFIER.wat_call_name(line) or "").endswith("schema/Pool#save")
                or (
                    VERIFIER.wat_call_name(line) == VERIFIER.WRITER.STORE_SET_CALL
                    and index >= 4
                    and VERIFIER.decoded_wat_constant(lines[index - 4], context["memory"])
                    == "Pool"
                )
            )
            argument_index = pool_site - 1
            indent = lines[argument_index][
                : len(lines[argument_index]) - len(lines[argument_index].lstrip())
            ]
            lines[argument_index] = f"{indent}local.get {token_local}"

        for generation in ("legacy", "modern"):
            self.assert_factory_wat_withdrawn(
                generation,
                reorder_token_saves,
                f"{generation} reordered Token saves",
            )
            self.assert_factory_wat_withdrawn(
                generation,
                wrong_token0_argument,
                f"{generation} wrong token0 save argument",
            )
            self.assert_factory_wat_withdrawn(
                generation,
                wrong_pool_argument,
                f"{generation} wrong Pool save argument",
            )

    def test_wrong_dynamic_template_does_not_promote_withdrawn_claim(self) -> None:
        def wrong_template(lines: list[str], context: dict[str, object]) -> None:
            memory = context["memory"]
            template_call = next(
                index
                for index, line in enumerate(lines)
                if (VERIFIER.wat_call_name(line) or "").endswith("dataSource.create")
            )
            pool_literal = [
                index
                for index in range(template_call - 40, template_call)
                if VERIFIER.decoded_wat_constant(lines[index], memory) == "Pool"
            ][-1]
            factory_constant = next(
                VERIFIER.normalized_wat_line(line)
                for line in lines
                if VERIFIER.decoded_wat_constant(line, memory) == "Factory"
            )
            indent = lines[pool_literal][: len(lines[pool_literal]) - len(lines[pool_literal].lstrip())]
            lines[pool_literal] = f"{indent}{factory_constant}"

        for generation in ("legacy", "modern"):
            self.assert_factory_wat_withdrawn(
                generation,
                wrong_template,
                f"{generation} wrong dynamic template",
            )

    def test_pool_generation_initialize_fee_spacing_pricing_and_relation_axes_are_bound(self) -> None:
        pools = [
            item
            for item in self.contract["factory_pool_control_dataflow_ledger"]
            if item["component"] == "Pool"
        ]
        self.assertEqual({item["profile_record"]["control_generation"] for item in pools}, {"legacy", "modern"})
        self.assertEqual(
            {item["profile_record"]["fee_spacing_mode"] for item in pools},
            {"no_fee_tier_100", "fee_tier_100_spacing_1", "fee_tier_1_spacing_1"},
        )
        self.assertEqual(
            {item["profile_record"]["initialize_persistence_observation"]["pool_save_callsite_count"] for item in pools},
            {0, 1},
        )
        self.assertEqual({item["profile_record"]["explicit_hour_resaves"] for item in pools}, {False, True})
        self.assertGreater(
            len({item["profile_record"]["pricing_profile"] for item in pools}),
            1,
        )
        for item in pools:
            profile = item["profile_record"]
            self.assertIs(profile["complete_static_handler_contract"], False)
            self.assertIs(profile["profile_axis_binding_complete"], False)
            self.assertIs(
                profile["initialize_persistence_observation"]["same_path_machine_proven"],
                False,
            )
            self.assertIs(
                profile["tick_day_relation_evidence"]["relation_semantics_machine_checked"],
                False,
            )

    def test_calls_failures_exclusions_dynamic_sources_and_order_stay_fail_closed(self) -> None:
        policies = set()
        for segment in self.contract["segments"]:
            surface = segment["semantic_surface"]
            self.assertIs(surface["calls"]["complete_call_inventory_and_value_semantics"], False)
            self.assertEqual(len(surface["calls"]["observations"]), 5)
            self.assertIs(surface["exclusions"]["complete_exclusion_control_flow"], False)
            self.assertIs(surface["ordering"]["complete_runtime_ordering_contract"], False)
            self.assertIs(surface["ordering"]["same_block_dynamic_data_source_causality_certified"], False)
            self.assertIs(surface["ordering"]["target_runtime_identity_bound"], False)
            policies.add(surface["deterministic_handler_error_policy_under_source_model"])
            self.assertIs(surface["quirks"]["silent_normalization_allowed"], False)
        self.assertEqual(
            policies,
            {
                "nonFatalErrors is absent; a deterministic handler error fails the deployment at that block",
                "discard the failing handler's data-source and entity-cache changes, continue other successful handlers, and write a deterministic proof-of-indexing error",
            },
        )

    def test_only_inventory_and_inherited_static_evidence_gates_are_true(self) -> None:
        truth = self.contract["truth_boundary"]
        self.assertEqual({key for key, value in truth.items() if value}, set(VERIFIER.TRUE_FLAGS))
        self.assertEqual({key for key, value in truth.items() if not value}, set(VERIFIER.FALSE_FLAGS))
        for gate in (
            "both_modern_factory_excluded_pool_guard_cfg_dataflow_proven",
            "all_six_factory_normal_return_effect_order_and_arguments_proven",
            "all_six_factory_total_supply_success_failure_profiles_proven",
            "modern_factory_total_supply_success_dataflow_proven",
            "all_manifest_handler_field_semantics_complete",
            "all_stored_fields_exact",
            "factory_handler_semantics_complete",
            "pool_non_flash_handler_semantics_complete",
            "contract_call_semantics_complete_for_all_handlers",
            "full_entity_histories_complete",
            "all_pairwise_complete_writer_semantic_diffs_present",
            "combined_handler_order_implemented",
            "dynamic_datasource_stage_order_implemented",
            "post_fatal_execution_modeled",
            "runtime_population_complete",
            "graph_oracle_complete",
            "backfill_ready",
            "production_ready",
        ):
            self.assertIs(truth[gate], False, gate)

    def test_v1_and_writer_v3_are_pinned_and_unchanged(self) -> None:
        for name in ("segment_field_semantics_v1", "writer_compatibility"):
            path, _version, digest = VERIFIER.SOURCE_SPECS[name]
            self.assertEqual(VERIFIER.raw_sha256(ROOT / path), digest)

    def test_adversarial_contract_mutations_fail_closed(self) -> None:
        mutations = []

        promoted = copy.deepcopy(self.contract)
        promoted["truth_boundary"]["factory_handler_semantics_complete"] = True
        mutations.append(("promoted Factory semantics", promoted))

        promoted_initialized_values = copy.deepcopy(self.contract)
        promoted_initialized_values["truth_boundary"][
            "factory_all_initialized_field_values_proven"
        ] = True
        mutations.append(
            ("promoted Factory initialized-field proof", promoted_initialized_values)
        )

        for gate in (
            "both_modern_factory_excluded_pool_guard_cfg_dataflow_proven",
            "all_six_factory_normal_return_effect_order_and_arguments_proven",
            "all_six_factory_total_supply_success_failure_profiles_proven",
            "modern_factory_total_supply_success_dataflow_proven",
        ):
            promoted_withdrawn_gate = copy.deepcopy(self.contract)
            promoted_withdrawn_gate["truth_boundary"][gate] = True
            mutations.append((f"promoted withdrawn truth gate {gate}", promoted_withdrawn_gate))

        promoted_modern_guard = copy.deepcopy(self.contract)
        modern = next(
            item
            for item in promoted_modern_guard["factory_pool_control_dataflow_ledger"]
            if item["component"] == "Factory"
            and item["v2_retained_wat_cfg_dataflow"]["generation"] == "modern"
        )
        modern["v2_retained_wat_cfg_dataflow"]["excluded_pool_guard"][
            "event_pool_to_comparison_to_early_return_machine_proven"
        ] = True
        mutations.append(("promoted withdrawn modern guard", promoted_modern_guard))

        promoted_effect = copy.deepcopy(self.contract)
        factory = next(
            item
            for item in promoted_effect["factory_pool_control_dataflow_ledger"]
            if item["component"] == "Factory"
        )
        factory["v2_retained_wat_cfg_dataflow"][
            "normal_return_effect_order_and_arguments"
        ]["same_path_or_dataflow_machine_proven"] = True
        mutations.append(("promoted withdrawn Factory effect", promoted_effect))

        promoted_total_supply = copy.deepcopy(self.contract)
        modern = next(
            item
            for item in promoted_total_supply["factory_pool_control_dataflow_ledger"]
            if item["component"] == "Factory"
            and item["v2_retained_wat_cfg_dataflow"]["generation"] == "modern"
        )
        modern["v2_retained_wat_cfg_dataflow"]["initialized_field_value_evidence"][
            "total_supply_helper"
        ]["success_failure_dataflow_machine_proven"] = True
        mutations.append(
            ("promoted withdrawn modern totalSupply dataflow", promoted_total_supply)
        )

        promoted_closure_count = copy.deepcopy(self.contract)
        promoted_closure_count["scope"][
            "factory_upstream_unresolved_path_count_closed_by_v2"
        ] = 12
        promoted_closure_count["scope"]["factory_upstream_unresolved_path_count_after"] = 6
        mutations.append(("promoted withdrawn closure aggregate", promoted_closure_count))

        numeric_false = copy.deepcopy(self.contract)
        numeric_false["truth_boundary"]["backfill_ready"] = 0
        mutations.append(("numeric false gate", numeric_false))

        source_promoted = copy.deepcopy(self.contract)
        source_promoted["factory_pool_control_dataflow_ledger"][0][
            "source_corroboration_authoritative"
        ] = True
        mutations.append(("source promoted over WASM", source_promoted))

        removed_field = copy.deepcopy(self.contract)
        removed_field["field_catalog"].pop()
        mutations.append(("removed field", removed_field))

        removed_segment_field = copy.deepcopy(self.contract)
        removed_segment_field["segments"][0]["semantic_surface"]["fields"].pop()
        removed_segment_field["segments"][0]["semantic_surface_sha256"] = VERIFIER.canonical_sha256(
            removed_segment_field["segments"][0]["semantic_surface"]
        )
        mutations.append(("self-rehashed missing segment field", removed_segment_field))

        removed_handler = copy.deepcopy(self.contract)
        removed_handler["segments"][0]["semantic_surface"]["handlers"].pop()
        removed_handler["segments"][0]["semantic_surface_sha256"] = VERIFIER.canonical_sha256(
            removed_handler["segments"][0]["semantic_surface"]
        )
        mutations.append(("self-rehashed missing handler", removed_handler))

        cleared_blocker = copy.deepcopy(self.contract)
        cleared_blocker["factory_pool_control_dataflow_ledger"][0][
            "unresolved_control_dataflow_paths"
        ] = []
        mutations.append(("cleared CFG blocker", cleared_blocker))

        changed_profile = copy.deepcopy(self.contract)
        changed_profile["factory_pool_control_dataflow_ledger"][0]["profile_record"][
            "safe_literal_array"
        ] = True
        changed_profile["factory_pool_control_dataflow_ledger"][0][
            "profile_record_sha256"
        ] = VERIFIER.canonical_sha256(
            changed_profile["factory_pool_control_dataflow_ledger"][0]["profile_record"]
        )
        mutations.append(("self-rehashed deployed quirk", changed_profile))

        removed_diff = copy.deepcopy(self.contract)
        removed_diff["segment_diffs"].pop()
        mutations.append(("removed pairwise diff", removed_diff))

        changed_diff = copy.deepcopy(self.contract)
        changed_diff["segment_diffs"][0]["evidence_semantic_diff_paths"] = []
        changed_diff["segment_diffs"][0]["evidence_semantic_equal"] = True
        mutations.append(("self-consistent but false pairwise diff", changed_diff))

        for label, mutation in mutations:
            with self.subTest(label=label):
                self.assert_rejected(mutation, label)

    def test_duplicate_json_keys_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="segment-field-semantics-v2-json-") as temporary:
            path = Path(temporary) / "duplicate.json"
            path.write_text('{"format_version": 1, "format_version": 2}\n')
            with self.assertRaisesRegex(VERIFIER.VerificationError, "duplicate JSON key"):
                VERIFIER.load_json_strict(path)


if __name__ == "__main__":
    unittest.main()
