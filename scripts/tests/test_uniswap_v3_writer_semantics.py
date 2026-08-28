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
        self.assertEqual(self.contract["format_version"], 2)
        self.assertEqual(
            self.contract["contract_version"],
            "uniswap-v3-writer-compatibility/v2",
        )
        for mapping in self.contract["mapping_analyses"]:
            self.assertEqual(mapping["store_set_import_count"], 1)
            self.assertEqual(
                mapping["store_set_callsite_count"],
                len(mapping["store_set_callsites"]),
            )
            for site in mapping["store_set_callsites"]:
                self.assertTrue(site["target_argument_shape"].startswith("i32.const"))

    def test_factory_pool_profiles_source_bindings_and_segment_diffs_are_closed(self) -> None:
        factory = self.contract["factory_writer_contract"]
        pool = self.contract["pool_writer_contract"]
        self.assertEqual(factory["mapping_count"], 6)
        self.assertEqual(factory["registered_handler_count"], 6)
        self.assertEqual(pool["mapping_count"], 8)
        self.assertEqual(pool["registered_handler_count"], 40)
        self.assertEqual(
            {item["mapping_cid"] for item in factory["mapping_bindings"]},
            set(MODULE.FACTORY_PROFILE_BY_MAPPING),
        )
        self.assertEqual(
            {item["mapping_cid"] for item in pool["mapping_bindings"]},
            set(MODULE.POOL_PROFILE_BY_MAPPING),
        )
        every_update = [
            item["mapping_cid"]
            for item in pool["mapping_bindings"]
            if item["tick_day_relation_evidence"]["mode"] == "every_update"
        ]
        self.assertEqual(
            every_update,
            ["QmWuomVAQCdEXdCRavcsmRz4BNqPx2nppqe8S6AXid66xw"],
        )
        hour_resaves = {
            item["mapping_cid"]: item["hour_resave_evidence"][
                "direct_resave_callsite_count"
            ]
            for item in pool["mapping_bindings"]
            if item["explicit_hour_resaves"]
        }
        self.assertEqual(
            hour_resaves,
            {
                "QmZPiDeH1j95mozzb5AjKCHn6zgpnhMu77kNAitPbi4Vt3": 1,
                "QmPZCHE1URf4oviX7Tbrkw3aMENo1qAeEGa1AS2gMumG7P": 2,
                "QmSaGgPnyhStviGQSGTokQYRgVqLFNvnGWfnv8tSfuvpWD": 2,
            },
        )
        self.assertTrue(
            all(
                item["hour_resave_evidence"][
                    "all_direct_resaves_lexically_after_helper"
                ]
                for item in pool["mapping_bindings"]
            )
        )

        provenance = self.contract["source_provenance_bindings"]
        self.assertEqual(len(provenance), 14)
        self.assertEqual(
            {
                item["mapping_cid"]
                for item in provenance
                if item["match_kind"] == "exact_entry_blob_anchor"
            },
            set(MODULE.ENTRY_BLOB_ANCHOR_BY_MAPPING),
        )
        self.assertTrue(
            all(item["artifact_authority"] == "retained_mapping_wasm" for item in provenance)
        )
        self.assertTrue(
            all(item["mapping_assignment"] is None for item in self.contract["semantic_source_anchors"])
        )

        segments = self.contract["segment_writer_contracts"]
        diffs = self.contract["segment_writer_diffs"]
        self.assertEqual(len(segments), 8)
        self.assertEqual(len(diffs), 28)
        self.assertEqual(
            sum(item["relation"] == "adjacent_graft" for item in diffs), 6
        )
        for segment in segments:
            self.assertEqual(segment["execution_model"], "undecided")
            self.assertFalse(segment["backfill_allowed"])
            self.assertEqual(
                segment["artifact_identity_sha256"],
                MODULE.canonical_sha256(segment["artifact_bindings"]),
            )
            self.assertEqual(
                segment["semantic_contract_sha256"],
                MODULE.canonical_sha256(segment["semantic_contract"]),
            )

    def test_v2_writer_contract_mutations_fail_closed(self) -> None:
        def pool_tick_zero(contract) -> None:
            contract["factory_writer_contract"]["mapping_bindings"][0][
                "pool_tick_write"
            ] = "zero"

        def reorder_factory_effects(contract) -> None:
            effects = contract["factory_writer_contract"]["mapping_bindings"][0][
                "pool_created_effect_order_observation"
            ]["reviewed_order"]
            effects[0], effects[1] = effects[1], effects[0]

        def initialize_persistence_drift(contract) -> None:
            binding = contract["pool_writer_contract"]["mapping_bindings"][0]
            evidence = binding["initialize_persistence_observation"]
            evidence["lexical_pool_save_callsite_present"] = not evidence[
                "lexical_pool_save_callsite_present"
            ]

        def tick_day_mode_drift(contract) -> None:
            contract["pool_writer_contract"]["mapping_bindings"][0][
                "tick_day_relation_evidence"
            ]["mode"] = "every_update"

        def fee_spacing_mode_drift(contract) -> None:
            contract["pool_writer_contract"]["mapping_bindings"][0][
                "fee_spacing_evidence"
            ]["mode"] = "fee_tier_1_spacing_1"

        def duplicate_factory_profile(contract) -> None:
            bindings = contract["factory_writer_contract"]["mapping_bindings"]
            bindings[0]["mapping_cid"] = bindings[1]["mapping_cid"]

        def source_overclaim(contract) -> None:
            binding = next(
                item
                for item in contract["source_provenance_bindings"]
                if item["mapping_cid"] not in MODULE.ENTRY_BLOB_ANCHOR_BY_MAPPING
            )
            binding["match_kind"] = "exact_entry_blob_anchor"
            binding["commit"] = "0" * 40

        def missing_segment_diff(contract) -> None:
            contract["segment_writer_diffs"].pop()

        def segment_hash_drift(contract) -> None:
            contract["segment_writer_contracts"][0][
                "semantic_contract_sha256"
            ] = "0" * 64

        def export_retarget(contract) -> None:
            mapping = next(
                item
                for item in contract["mapping_analyses"]
                if len(item["registered_handler_export_targets"]) > 1
            )
            handlers = list(mapping["registered_handler_export_targets"])
            mapping["registered_handler_export_targets"][handlers[0]] = mapping[
                "registered_handler_export_targets"
            ][handlers[1]]

        def rehashed_segment_threshold_drift(contract) -> None:
            segment = contract["segment_writer_contracts"][0]
            segment["semantic_contract"]["pool"]["tracked_amount_threshold"] += 1
            segment["semantic_contract_sha256"] = MODULE.canonical_sha256(
                segment["semantic_contract"]
            )

        def rehashed_segment_identity_drift(contract) -> None:
            segment = contract["segment_writer_contracts"][0]
            segment["segment_id"] = "mainnet:QmFabricated"
            segment["start_block_inclusive"] += 1

        def rehashed_segment_cid_drift(contract) -> None:
            segment = contract["segment_writer_contracts"][0]
            replacement_cid = "QmadCQv7VPgNXhQTNkcDyzmiWZpWexynUH4XuuaMrsAbJY"
            replacement = MODULE.POOL_PROFILE_BY_MAPPING[replacement_cid]
            segment["artifact_bindings"]["pool"] = {
                "mapping_cid": replacement_cid,
                "profile_id": replacement["profile_id"],
            }
            segment["semantic_contract"]["pool"] = {
                key: value
                for key, value in replacement.items()
                if key != "profile_id"
            }
            segment["artifact_identity_sha256"] = MODULE.canonical_sha256(
                segment["artifact_bindings"]
            )
            segment["semantic_contract_sha256"] = MODULE.canonical_sha256(
                segment["semantic_contract"]
            )

        def inline_flash_shared_getter_result(contract) -> None:
            evidence = next(
                item
                for item in contract["pool_flash_evidence"]
                if item["field_flow_evidence"]["codegen_model"] == "inline"
            )["field_flow_evidence"]
            evidence["fee_growth_1_flow"]["getter_wat_line"] = evidence[
                "fee_growth_0_flow"
            ]["getter_wat_line"]
            evidence["fee_growth_1_flow"]["result_local"] = evidence[
                "fee_growth_0_flow"
            ]["result_local"]

        def self_referential_segment_layers(contract) -> None:
            segment = contract["segments"][0]
            segment["deployment"] = "QmFabricatedDeployment"
            segment["start_block_inclusive"] += 1
            start = segment["start_block_inclusive"]
            end = segment["end_block_inclusive"]
            in_range = start <= MODULE.HISTORICAL_GUARD_BLOCK and (
                end is None or MODULE.HISTORICAL_GUARD_BLOCK <= end
            )
            segment["historical_guard"]["block_in_segment"] = in_range
            segment["historical_guard"]["effective_in_segment"] = (
                segment["historical_guard"]["present_in_mapping"] and in_range
            )
            contract["segment_writer_contracts"] = [
                MODULE.segment_writer_contract_from_record(item)
                for item in contract["segments"]
            ]
            contract["segment_writer_diffs"] = MODULE.build_segment_writer_diffs(
                contract["segment_writer_contracts"]
            )

        def fabricated_full_source_tuple(contract) -> None:
            binding = next(
                item
                for item in contract["source_provenance_bindings"]
                if item["match_kind"] == "none_found"
            )
            binding.update(
                {
                    "match_kind": "exact_entry_blob_anchor",
                    "repository": MODULE.SOURCE_REPOSITORY,
                    "commit": "1" * 40,
                    "entry_path": "src/mappings/fabricated.ts",
                    "entry_blob_sha1": "2" * 40,
                    "limitations": [
                        "the commit and mapping entry blob are exact source anchors only; no reproducible source-to-WASM build correspondence is proved",
                        "retained deployed WASM remains authoritative",
                    ],
                }
            )

        def ancestry_metadata_drift(contract) -> None:
            contract["ancestry_contract"]["sha256"] = "0" * 64

        def dormant_pool_helper_claim(contract) -> None:
            binding = contract["pool_writer_contract"]["mapping_bindings"][0]
            binding["fee_spacing_evidence"][
                "reachable_from_exact_exported_handle_swap"
            ] = False

        for mutate in (
            pool_tick_zero,
            reorder_factory_effects,
            initialize_persistence_drift,
            tick_day_mode_drift,
            fee_spacing_mode_drift,
            duplicate_factory_profile,
            source_overclaim,
            missing_segment_diff,
            segment_hash_drift,
            export_retarget,
            rehashed_segment_threshold_drift,
            rehashed_segment_identity_drift,
            rehashed_segment_cid_drift,
            inline_flash_shared_getter_result,
            self_referential_segment_layers,
            fabricated_full_source_tuple,
            ancestry_metadata_drift,
            dormant_pool_helper_claim,
        ):
            with self.subTest(mutate=mutate.__name__):
                contract = copy.deepcopy(self.contract)
                mutate(contract)
                with self.assertRaises(MODULE.VerificationError):
                    MODULE.validate_internal_contract(contract)

    def test_tick_day_relation_requires_tick_writer_inside_the_creation_branch(self) -> None:
        memory = bytearray(65_536)
        pointer = 64
        value = "tick"
        encoded = value.encode("utf-16le")
        struct.pack_into("<I", memory, pointer, len(value))
        memory[pointer + 4 : pointer + 4 + len(encoded)] = encoded
        wrong_pointer = 128
        wrong_value = "wrongKey"
        wrong_encoded = wrong_value.encode("utf-16le")
        struct.pack_into("<I", memory, wrong_pointer, len(wrong_value))
        memory[
            wrong_pointer + 4 : wrong_pointer + 4 + len(wrong_encoded)
        ] = wrong_encoded

        def function(create_only: bool) -> object:
            setter = [
                "    local.get $p1",
                f"    i32.const {pointer}",
                "    local.get $p0",
                "    call $~lib/@graphprotocol/graph-ts/index/Value.fromI32",
                "    call $~lib/@graphprotocol/graph-ts/index/TypedMap<K,V>#set",
            ]
            before_end = setter if create_only else []
            after_end = [] if create_only else setter
            return MODULE.WatFunction(
                "synthetic/updateTickDayData",
                1,
                tuple(
                    [
                        "  (func $synthetic/updateTickDayData (param $p0 i32) (param $p1 i32)",
                        "    local.get $p0",
                        "    call $~lib/@graphprotocol/graph-ts/index/store.get",
                        "    local.tee $p0",
                        "    i32.eqz",
                        "    if $I0",
                    ]
                    + before_end
                    + ["    end"]
                    + after_end
                    + ["    nop)"],
                ),
            )

        create = function(True)
        evidence = MODULE.tick_day_relation_evidence(
            "synthetic", "create_only", {create.name: create}, memory, {create.name}
        )
        self.assertEqual(evidence["mode"], "create_only")
        with self.assertRaisesRegex(MODULE.VerificationError, "not reachable"):
            MODULE.tick_day_relation_evidence(
                "synthetic", "create_only", {create.name: create}, memory, set()
            )
        local_set_drops_store_result = MODULE.WatFunction(
            "synthetic/updateTickDayData",
            1,
            (
                "  (func $synthetic/updateTickDayData (param $p0 i32) (param $p1 i32)",
                "    local.get $p0",
                "    local.get $p1",
                "    call $~lib/@graphprotocol/graph-ts/index/store.get",
                "    local.set $p1",
                "    i32.eqz",
                "    if $creation",
                "      local.get $p1",
                f"      i32.const {pointer}",
                "      local.get $p0",
                "      call $~lib/@graphprotocol/graph-ts/index/Value.fromI32",
                "      call $~lib/@graphprotocol/graph-ts/index/TypedMap<K,V>#set",
                "    end",
                "    nop)",
            ),
        )
        with self.assertRaisesRegex(MODULE.VerificationError, "not bound"):
            MODULE.tick_day_relation_evidence(
                "synthetic",
                "create_only",
                {local_set_drops_store_result.name: local_set_drops_store_result},
                memory,
                {local_set_drops_store_result.name},
            )
        selected_wrong_key = MODULE.WatFunction(
            "synthetic/updateTickDayData",
            1,
            (
                "  (func $synthetic/updateTickDayData (param $p0 i32) (param $p1 i32)",
                "    local.get $p0",
                "    call $~lib/@graphprotocol/graph-ts/index/store.get",
                "    local.tee $p0",
                "    i32.eqz",
                "    if $creation",
                "      local.get $p1",
                f"      i32.const {pointer}",
                f"      i32.const {wrong_pointer}",
                "      local.get $p0",
                "      select",
                "      local.get $p0",
                "      call $~lib/@graphprotocol/graph-ts/index/Value.fromI32",
                "      call $~lib/@graphprotocol/graph-ts/index/TypedMap<K,V>#set",
                "    end",
                "    nop)",
            ),
        )
        selected = MODULE.tick_day_relation_evidence(
            "synthetic",
            "create_only",
            {selected_wrong_key.name: selected_wrong_key},
            memory,
            {selected_wrong_key.name},
        )
        self.assertFalse(selected["relation_semantics_machine_checked"])
        self.assertFalse(
            selected["tick_setter_binding"][
                "decoded_key_to_setter_machine_checked"
            ]
        )
        every = function(False)
        evidence = MODULE.tick_day_relation_evidence(
            "synthetic", "every_update", {every.name: every}, memory, {every.name}
        )
        self.assertEqual(evidence["mode"], "every_update")
        with self.assertRaisesRegex(MODULE.VerificationError, "relation mode"):
            MODULE.tick_day_relation_evidence(
                "synthetic", "create_only", {every.name: every}, memory, {every.name}
            )

        dropped = MODULE.WatFunction(
            "synthetic/updateTickDayData",
            1,
            (
                "  (func $synthetic/updateTickDayData (param $p0 i32) (param $p1 i32)",
                "    local.get $p0",
                "    call $~lib/@graphprotocol/graph-ts/index/store.get",
                "    local.tee $p0",
                "    i32.eqz",
                "    if $I0",
                "      local.get $p1",
                f"      i32.const {pointer}",
                "      drop",
                "      local.get $p0",
                "      call $~lib/@graphprotocol/graph-ts/index/Value.fromI32",
                "      call $~lib/@graphprotocol/graph-ts/index/TypedMap<K,V>#set",
                "    end",
                "    nop)",
            ),
        )
        with self.assertRaisesRegex(MODULE.VerificationError, "discarded"):
            MODULE.tick_day_relation_evidence(
                "synthetic", "create_only", {dropped.name: dropped}, memory, {dropped.name}
            )

        unrelated_branch = MODULE.WatFunction(
            "synthetic/updateTickDayData",
            1,
            (
                "  (func $synthetic/updateTickDayData (param $p0 i32) (param $p1 i32)",
                "    local.get $p0",
                "    i32.eqz",
                "    if $unrelated",
                "      local.get $p1",
                f"      i32.const {pointer}",
                "      local.get $p0",
                "      call $~lib/@graphprotocol/graph-ts/index/Value.fromI32",
                "      call $~lib/@graphprotocol/graph-ts/index/TypedMap<K,V>#set",
                "    end",
                "    local.get $p0",
                "    call $~lib/@graphprotocol/graph-ts/index/store.get",
                "    local.tee $p0",
                "    i32.eqz",
                "    if $creation",
                "      nop",
                "    end",
                "    nop)",
            ),
        )
        with self.assertRaisesRegex(MODULE.VerificationError, "precedes"):
            MODULE.tick_day_relation_evidence(
                "synthetic",
                "every_update",
                {unrelated_branch.name: unrelated_branch},
                memory,
                {unrelated_branch.name},
            )

    def test_handler_proofs_follow_the_exact_wat_export_target(self) -> None:
        wat = "\n".join(
            [
                "(module",
                "  (memory $memory 1)",
                "  (func $src/mappings/core/handleSwap nop)",
                "  (func $retargeted nop)",
                '  (export "handleSwap" (func $retargeted))',
                ")",
            ]
        )
        _, functions, _, exports = MODULE.parse_wat(wat)
        resolved = MODULE.resolve_handler(functions, exports, "handleSwap")
        self.assertEqual(resolved.name, "retargeted")
        self.assertNotEqual(resolved.name, "src/mappings/core/handleSwap")

    def test_factory_lexical_tail_after_return_is_not_promoted_to_proof(self) -> None:
        handler = MODULE.WatFunction(
            "synthetic/handlePoolCreated",
            1,
            (
                "  (func $synthetic/handlePoolCreated",
                "    return",
                "    call $src/types/schema/Pool#save",
                "    call $~lib/@graphprotocol/graph-ts/index/dataSource.create",
                "    call $src/types/schema/Token#save",
                "    call $src/types/schema/Token#save",
                "    call $src/types/schema/Factory#save)",
            ),
        )
        observation = MODULE.factory_effect_order_observation(
            "synthetic", {"store_set_callsites": []}, handler
        )
        self.assertFalse(observation["same_path_or_dataflow_machine_proven"])
        data_source = observation["machine_checked_lexical_tail"][1]
        self.assertNotIn("template", data_source)
        self.assertNotIn("argument", data_source)

    def test_hour_resave_evidence_counts_calls_after_the_helper(self) -> None:
        after = MODULE.WatFunction(
            "synthetic/handleSwap",
            1,
            (
                "  (func $synthetic/handleSwap",
                "    call $src/utils/intervalUpdates/updatePoolHourData",
                "    call $src/types/schema/PoolHourData#save)",
            ),
        )
        evidence = MODULE.hour_resave_evidence("synthetic", True, after)
        self.assertEqual(evidence["hour_helper_callsite_count"], 1)
        self.assertEqual(evidence["direct_resave_callsite_count"], 1)
        before = MODULE.WatFunction(
            "synthetic/handleSwap",
            1,
            (
                "  (func $synthetic/handleSwap",
                "    call $src/types/schema/PoolHourData#save",
                "    call $src/utils/intervalUpdates/updatePoolHourData)",
            ),
        )
        with self.assertRaisesRegex(MODULE.VerificationError, "precedes"):
            MODULE.hour_resave_evidence("synthetic", True, before)

    def test_initialize_dead_save_is_only_a_digest_bound_lexical_observation(self) -> None:
        handler = MODULE.WatFunction(
            "synthetic/handleInitialize",
            1,
            (
                "  (func $synthetic/handleInitialize",
                "    return",
                "    call $src/types/schema/Pool#save)",
            ),
        )
        observation = MODULE.initialize_persistence_observation(
            "synthetic", True, handler
        )
        self.assertTrue(observation["lexical_pool_save_callsite_present"])
        self.assertFalse(observation["same_path_machine_proven"])

    def test_fee_spacing_requires_a_comparison_bound_to_the_spacing_return(self) -> None:
        bound = MODULE.WatFunction(
            "synthetic/feeTierToTickSpacing",
            1,
            (
                "  (func $synthetic/feeTierToTickSpacing (param $p0 i32) (result i32)",
                "    local.get $p0",
                "    i32.const 100",
                "    call $~lib/@graphprotocol/graph-ts/index/ByteArray.fromI32",
                "    call $~lib/@graphprotocol/graph-ts/index/BigInt#equals",
                "    if $I0",
                "      i32.const 1",
                "      call $~lib/@graphprotocol/graph-ts/index/ByteArray.fromI32",
                "      return",
                "    end",
                "    unreachable)",
            ),
        )
        self.assertEqual(MODULE.fee_spacing_pairs(bound), [[100, 1]])
        unbound = MODULE.WatFunction(
            "synthetic/unbound",
            1,
            (
                "  (func $synthetic/unbound",
                "    i32.const 100",
                "    drop",
                "    i32.const 1",
                "    drop)",
            ),
        )
        self.assertEqual(MODULE.fee_spacing_pairs(unbound), [])
        dropped_then_wrong_return = MODULE.WatFunction(
            "synthetic/droppedThenWrongReturn",
            1,
            (
                "  (func $synthetic/droppedThenWrongReturn (param $p0 i32) (result i32)",
                "    local.get $p0",
                "    i32.const 100",
                "    call $~lib/@graphprotocol/graph-ts/index/ByteArray.fromI32",
                "    call $~lib/@graphprotocol/graph-ts/index/BigInt#equals",
                "    if $I0",
                "      i32.const 1",
                "      drop",
                "      i32.const 999",
                "      call $~lib/@graphprotocol/graph-ts/index/ByteArray.fromI32",
                "      return",
                "    end",
                "    unreachable)",
            ),
        )
        self.assertEqual(MODULE.fee_spacing_pairs(dropped_then_wrong_return), [])

        def polarity(comparison: str, include_eqz: bool) -> object:
            condition = ["    i32.eqz"] if include_eqz else []
            return MODULE.WatFunction(
                "synthetic/polarity",
                1,
                tuple(
                    [
                        "  (func $synthetic/polarity (param $p0 i32) (result i32)",
                        "    local.get $p0",
                        "    i32.const 100",
                        "    call $~lib/@graphprotocol/graph-ts/index/ByteArray.fromI32",
                        f"    call $~lib/@graphprotocol/graph-ts/index/{comparison}",
                    ]
                    + condition
                    + [
                        "    if $I0",
                        "      i32.const 1",
                        "      call $~lib/@graphprotocol/graph-ts/index/ByteArray.fromI32",
                        "      return",
                        "    end",
                        "    unreachable)",
                    ]
                ),
            )

        self.assertEqual(MODULE.fee_spacing_pairs(polarity("BigInt#equals", True)), [])
        self.assertEqual(MODULE.fee_spacing_pairs(polarity("BigInt.compare", False)), [])
        self.assertEqual(
            MODULE.fee_spacing_pairs(polarity("BigInt.compare", True)), [[100, 1]]
        )

    def test_flash_field_results_are_bound_to_matching_setters_and_pool_save(self) -> None:
        def function(fee0_value_local: str) -> object:
            return MODULE.WatFunction(
                "synthetic/handleFlash",
                1,
                (
                    "  (func $synthetic/handleFlash",
                    "    local.get $contract",
                    "    call $src/types/Factory/Pool/Pool#feeGrowthGlobal0X128",
                    "    local.set $fee0",
                    "    local.get $contract",
                    "    call $src/types/Factory/Pool/Pool#feeGrowthGlobal1X128",
                    "    local.set $fee1",
                    "    local.get $pool",
                    f"    local.get {fee0_value_local}",
                    "    call $src/types/schema/Pool#set:feeGrowthGlobal0X128",
                    "    local.get $pool",
                    "    local.get $fee1",
                    "    call $src/types/schema/Pool#set:feeGrowthGlobal1X128",
                    "    local.get $pool",
                    "    call $src/types/schema/Pool#save)",
                ),
            )

        valid = MODULE.flash_sequence_evidence(
            "synthetic", function("$fee0"), bytearray(65_536)
        )
        self.assertFalse(valid["ordered_field_flow_machine_checked"])
        self.assertFalse(valid["same_path_machine_proven"])
        self.assertTrue(valid["lexical_call_setter_save_order_checked"])
        self.assertEqual(valid["codegen_model"], "wrapper")
        with self.assertRaisesRegex(MODULE.VerificationError, "not result-bound"):
            MODULE.flash_sequence_evidence(
                "synthetic", function("$fee1"), bytearray(65_536)
            )

        actual_models = {
            item["field_flow_evidence"]["codegen_model"]
            for item in self.contract["pool_flash_evidence"]
        }
        self.assertEqual(actual_models, {"wrapper", "inline"})
        self.assertTrue(
            all(
                item["field_flow_evidence"]["ordered_field_flow_machine_checked"]
                is False
                and item["field_flow_evidence"]["same_path_machine_proven"]
                is False
                for item in self.contract["pool_flash_evidence"]
            )
        )

        dead_tail = MODULE.WatFunction(
            function("$fee0").name,
            1,
            tuple(
                [function("$fee0").lines[0], "    return"]
                + list(function("$fee0").lines[1:])
            ),
        )
        dead_observation = MODULE.flash_sequence_evidence(
            "synthetic", dead_tail, bytearray(65_536)
        )
        self.assertFalse(dead_observation["same_path_machine_proven"])
        self.assertFalse(dead_observation["ordered_field_flow_machine_checked"])

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
            "registered_handler_export_targets": {
                "handleCollect": handler.name,
            },
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
