from __future__ import annotations

import copy
import importlib.util
import re
import sys
import unittest
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[2]
VERIFIER = REPOSITORY / "scripts/verify-uniswap-v3-segment-writer-matrix.py"
SPEC = importlib.util.spec_from_file_location(
    "uniswap_v3_segment_writer_matrix", VERIFIER
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
CONTRACT_PATH = REPOSITORY / MODULE.CONTRACT_PATH


class UniswapV3SegmentWriterMatrixTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ancestry = MODULE.ANCESTRY.verify(REPOSITORY)
        cls.writer = MODULE.WRITER.validate_internal_contract(
            MODULE.ANCESTRY.load_json(REPOSITORY / MODULE.WRITER.CONTRACT_PATH),
            cls.ancestry,
            REPOSITORY,
        )
        cls.contract = MODULE.verify(REPOSITORY)

    def validate_mutation(self, mutate) -> None:
        contract = copy.deepcopy(self.contract)
        mutate(contract)
        MODULE.validate_internal_contract(
            contract,
            self.ancestry,
            self.writer,
            REPOSITORY,
        )

    def test_contract_is_deterministic_and_closes_every_segment_surface(self) -> None:
        self.assertEqual(
            CONTRACT_PATH.read_text(encoding="utf-8"),
            MODULE.render(MODULE.build_contract(REPOSITORY)),
        )
        self.assertEqual(self.contract["format_version"], 1)
        self.assertEqual(
            self.contract["contract_version"],
            "uniswap-v3-segment-writer-matrix/v1",
        )
        self.assertEqual(len(self.contract["segments"]), 8)
        self.assertEqual(
            sum(len(segment["handlers"]) for segment in self.contract["segments"]),
            80,
        )
        self.assertEqual(
            sum(
                len(segment["entity_field_matrix"])
                for segment in self.contract["segments"]
            ),
            160,
        )
        self.assertEqual(
            sum(
                len(entity["fields"])
                for segment in self.contract["segments"]
                for entity in segment["entity_field_matrix"]
            ),
            2392,
        )
        self.assertEqual(len(self.contract["segment_diffs"]), 28)
        self.assertEqual(
            sum(
                diff["relation"] == "adjacent_graft"
                for diff in self.contract["segment_diffs"]
            ),
            6,
        )

    def test_every_handler_is_bound_to_manifest_wasm_wat_and_body(self) -> None:
        for segment in self.contract["segments"]:
            self.assertEqual(
                [component["name"] for component in segment["artifact_bindings"]["components"]],
                list(MODULE.COMPONENT_ORDER),
            )
            bound_handlers = [
                handler
                for component in segment["artifact_bindings"]["components"]
                for handler in component["handlers_in_manifest_order"]
            ]
            self.assertEqual(len(bound_handlers), 10)
            for component in segment["artifact_bindings"]["components"]:
                self.assertRegex(component["mapping_wat_sha256"], r"^[0-9a-f]{64}$")
                self.assertRegex(
                    component["mapping_analysis_sha256"], r"^[0-9a-f]{64}$"
                )
                self.assertTrue(component["abi_artifacts"])
                for handler in component["handlers_in_manifest_order"]:
                    self.assertEqual(
                        handler["numeric_export_function_index"],
                        handler["body_binding"]["wat_function_index"],
                    )
                    self.assertEqual(
                        handler["exact_wat_export_target"],
                        handler["body_binding"]["function"],
                    )
                    self.assertRegex(
                        handler["body_binding"]["body_sha256"], r"^[0-9a-f]{64}$"
                    )

    def test_population_and_execution_contracts_do_not_overclaim(self) -> None:
        taxonomy = self.contract["population_taxonomy"]
        self.assertEqual(taxonomy["required_nonempty_certified_entities"], [])
        self.assertEqual(
            taxonomy["required_absent_entities"],
            ["Collect", "Flash", "TickHourData"],
        )
        for segment in self.contract["segments"]:
            populations = {
                item["entity"]: item["population_contract"]
                for item in segment["entity_field_matrix"]
            }
            self.assertEqual(
                {
                    entity
                    for entity, contract in populations.items()
                    if contract["required_absent"]
                },
                set(MODULE.REQUIRED_ABSENT),
            )
            self.assertTrue(
                all(not item["required_nonempty"] for item in populations.values())
            )
            self.assertFalse(segment["boundary_state_continuity_certified"])
            self.assertFalse(segment["graph_oracle_evidence_bound"])
            self.assertEqual(segment["execution_model"], "undecided")
            self.assertFalse(segment["backfill_allowed"])
        execution = self.contract["execution_model_contract"]
        self.assertFalse(execution["all_segments_decided"])
        self.assertTrue(all(not item["eligible"] for item in execution["allowed_models"]))
        self.assertTrue(
            all(
                item["selected_model"] == "undecided"
                and not item["selection_certified"]
                and not item["backfill_allowed"]
                for item in execution["segment_selections"]
            )
        )

    def test_base_root_distinguishes_runtime_factory_origin_from_npm_gate(self) -> None:
        base_root = next(
            segment
            for segment in self.contract["segments"]
            if segment["deployment"]
            == "QmPWDTWRfS8XewMJhxXoQiZX6RkrUMYH7BFnnB846v6wzR"
        )
        components = {
            item["name"]: item
            for item in base_root["artifact_bindings"]["components"]
        }
        self.assertEqual(base_root["start_block_inclusive"], 1_371_679)
        self.assertEqual(components["Factory"]["source"]["start_block"], 1_371_679)
        self.assertEqual(
            components["NonfungiblePositionManager"]["source"]["start_block"],
            1_371_713,
        )
        self.assertNotEqual(
            components["Factory"]["source"]["start_block"],
            components["NonfungiblePositionManager"]["source"]["start_block"],
        )

    def test_pairwise_diffs_keep_artifact_provenance_semantics_and_state_separate(self) -> None:
        semantic_paths = [
            path
            for diff in self.contract["segment_diffs"]
            for path in diff["semantic_diff_paths"]
        ]
        self.assertEqual(len(semantic_paths), 609)
        self.assertFalse(
            any(
                re.search(
                    r"(?:wat_line|site_id|profile_id|sha256|\.call(?:$|\.)|\.function(?:$|\.))",
                    path,
                )
                for path in semantic_paths
            )
        )
        for diff in self.contract["segment_diffs"]:
            self.assertRegex(diff["left_artifact_bindings_sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(diff["left_provenance_surface_sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(diff["left_semantic_surface_sha256"], r"^[0-9a-f]{64}$")
            self.assertFalse(diff["boundary_state_compared"])
            self.assertFalse(diff["graph_oracle_compared"])
        fee_spacing_only = next(
            diff
            for diff in self.contract["segment_diffs"]
            if diff["left_segment_id"].startswith("mainnet:QmS134")
            and diff["right_segment_id"].startswith("mainnet:QmSL")
        )
        self.assertEqual(
            fee_spacing_only["semantic_diff_paths"],
            [
                "$.handlers[6].fee_spacing_mode",
                "$.handlers[6].fee_tier_to_tick_spacing[3]",
                "$.quirks.pool.fee_spacing_mode",
            ],
        )

    def test_coordinates_and_implementation_spellings_are_provenance_not_semantics(self) -> None:
        legacy = self.contract["segments"][0]
        modern = self.contract["segments"][5]

        def assert_provenance_only(segment, mutate) -> None:
            candidate = copy.deepcopy(segment)
            semantic_before = MODULE.canonical_sha256(
                MODULE.semantic_surface(candidate)
            )
            provenance_before = MODULE.canonical_sha256(
                MODULE.provenance_surface(candidate)
            )
            mutate(candidate)
            self.assertEqual(
                MODULE.canonical_sha256(MODULE.semantic_surface(candidate)),
                semantic_before,
            )
            self.assertNotEqual(
                MODULE.canonical_sha256(MODULE.provenance_surface(candidate)),
                provenance_before,
            )

        assert_provenance_only(
            legacy,
            lambda segment: segment["handlers"][0]["reviewed_semantics"][
                "effect_order"
            ]["machine_checked_lexical_tail"][0].__setitem__("wat_line", 999_999),
        )
        assert_provenance_only(
            legacy,
            lambda segment: segment["handlers"][0]["reviewed_semantics"][
                "effect_order"
            ]["machine_checked_lexical_tail"][0].__setitem__(
                "call", "renamed/implementation#persist"
            ),
        )
        assert_provenance_only(
            legacy,
            lambda segment: segment["handlers"][6]["reviewed_semantics"][
                "fee_spacing"
            ].__setitem__("function", "renamed/feeSpacingImplementation"),
        )
        assert_provenance_only(
            modern,
            lambda segment: next(
                item
                for item in segment["handlers"][0]["reviewed_semantics"][
                    "effect_order"
                ]["machine_checked_lexical_tail"]
                if "site_id" in item
            ).__setitem__("site_id", "renumbered#999"),
        )

        moved_wat = copy.deepcopy(legacy)
        semantic_before = MODULE.canonical_sha256(MODULE.semantic_surface(moved_wat))
        artifact_before = MODULE.canonical_sha256(moved_wat["artifact_bindings"])
        moved_wat["artifact_bindings"]["components"][0][
            "handlers_in_manifest_order"
        ][0]["body_binding"]["wat_start_line"] += 100
        self.assertEqual(
            MODULE.canonical_sha256(MODULE.semantic_surface(moved_wat)),
            semantic_before,
        )
        self.assertNotEqual(
            MODULE.canonical_sha256(moved_wat["artifact_bindings"]),
            artifact_before,
        )

        real_semantic_change = copy.deepcopy(legacy)
        semantic_before = MODULE.canonical_sha256(
            MODULE.semantic_surface(real_semantic_change)
        )
        reviewed_order = real_semantic_change["handlers"][0][
            "reviewed_semantics"
        ]["effect_order"]["reviewed_order"]
        reviewed_order[0], reviewed_order[1] = reviewed_order[1], reviewed_order[0]
        self.assertNotEqual(
            MODULE.canonical_sha256(MODULE.semantic_surface(real_semantic_change)),
            semantic_before,
        )

    def test_adversarial_drift_missing_segment_unbound_matrix_and_false_claims_fail_closed(self) -> None:
        def source_contract_drift(contract) -> None:
            contract["source_contracts"]["writer"]["raw_sha256"] = "0" * 64

        def missing_segment(contract) -> None:
            contract["segments"].pop()

        def unbound_mapping_artifact(contract) -> None:
            segment = contract["segments"][0]
            mapping = segment["artifact_bindings"]["components"][0][
                "mapping_artifact"
            ]
            mapping["sha256"] = "0" * 64
            segment["artifact_bindings_sha256"] = MODULE.canonical_sha256(
                segment["artifact_bindings"]
            )
            segment["matrix_sha256"] = MODULE.canonical_sha256(
                {
                    key: value
                    for key, value in segment.items()
                    if key != "matrix_sha256"
                }
            )

        def rehashed_profile_binding_drift(contract) -> None:
            segment = contract["segments"][0]
            segment["profile_bindings"]["factory"]["source_record_sha256"] = (
                "1" * 64
            )
            segment["provenance_surface_sha256"] = MODULE.canonical_sha256(
                MODULE.provenance_surface(segment)
            )
            segment["matrix_sha256"] = MODULE.canonical_sha256(
                {
                    key: value
                    for key, value in segment.items()
                    if key != "matrix_sha256"
                }
            )

        def rehashed_semantic_quirk_drift(contract) -> None:
            segment = contract["segments"][0]
            segment["quirks"]["nonfungible_position_manager"][
                "collected_fees_token1"
            ] = "silently corrected"
            segment["semantic_surface_sha256"] = MODULE.canonical_sha256(
                MODULE.semantic_surface(segment)
            )
            segment["matrix_sha256"] = MODULE.canonical_sha256(
                {
                    key: value
                    for key, value in segment.items()
                    if key != "matrix_sha256"
                }
            )

        def false_handler_semantic_claim(contract) -> None:
            contract["segments"][0]["handlers"][0][
                "complete_field_output_semantics"
            ] = True

        def false_required_nonempty_claim(contract) -> None:
            entity = contract["segments"][0]["entity_field_matrix"][0]
            entity["population_contract"]["required_nonempty"] = True

        def selected_execution_model(contract) -> None:
            contract["execution_model_contract"]["segment_selections"][0].update(
                {
                    "selected_model": "emulate_deployed_segment_writers",
                    "selection_certified": True,
                    "backfill_allowed": True,
                }
            )

        def false_boundary_claim(contract) -> None:
            contract["segment_diffs"][0]["boundary_state_compared"] = True

        def missing_pairwise_diff(contract) -> None:
            contract["segment_diffs"].pop()

        def runtime_consumer_overclaim(contract) -> None:
            contract["truth_boundary"]["writer_runtime_consumes_this_matrix"] = True

        for mutate in (
            source_contract_drift,
            missing_segment,
            unbound_mapping_artifact,
            rehashed_profile_binding_drift,
            rehashed_semantic_quirk_drift,
            false_handler_semantic_claim,
            false_required_nonempty_claim,
            selected_execution_model,
            false_boundary_claim,
            missing_pairwise_diff,
            runtime_consumer_overclaim,
        ):
            with self.subTest(mutate=mutate.__name__):
                with self.assertRaises(MODULE.VerificationError):
                    self.validate_mutation(mutate)


if __name__ == "__main__":
    unittest.main()
