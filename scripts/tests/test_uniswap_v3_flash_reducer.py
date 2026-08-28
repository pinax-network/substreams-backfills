#!/usr/bin/env python3
"""Hermetic tests for the host-only Uniswap V3 Pool Flash reducer overlay."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
VERIFIER_PATH = ROOT / "scripts/verify-uniswap-v3-flash-reducer.py"
SPEC = importlib.util.spec_from_file_location("flash_reducer_verifier", VERIFIER_PATH)
assert SPEC and SPEC.loader
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)
WRITER = VERIFIER.load_writer_verifier(ROOT)


def tree_digest(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(directory.rglob("*")):
        relative = path.relative_to(directory)
        if not path.is_file() or "target" in relative.parts:
            continue
        digest.update(relative.as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
        digest.update(b"x" if path.stat().st_mode & 0o111 else b"-")
    return digest.hexdigest()


class FlashReducerContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = VERIFIER.load_contract(ROOT)
        cls.semantics = VERIFIER.load_semantics(ROOT)

    def test_exact_corrected_writer_runtime_and_retained_profiles_are_bound(self) -> None:
        self.assertEqual(
            self.semantics["source_writer_runtime"],
            {
                "path": "uniswap-v3/writer-runtime/contract-v1.json",
                "contract_version": "uniswap-v3-writer-runtime/v1",
                "sha256": VERIFIER.WRITER_RUNTIME_SHA256,
                "writer_descriptor_sha256": VERIFIER.WRITER_DESCRIPTOR_SHA256,
            },
        )
        self.assertEqual(
            self.semantics["source_segment_profiles"]["sha256"],
            VERIFIER.PROFILE_SHA256,
        )
        self.assertNotEqual(
            VERIFIER.WRITER_RUNTIME_SHA256,
            "cb42869042a6477a50a534b3abddf2e6d8c9ab91ea6c532a825fb378234ae2be",
        )

    def test_graph_node_execution_order_supplement_is_raw_bound_not_implemented(self) -> None:
        semantic_binding = {
            "path": VERIFIER.EXECUTION_ORDER_PATH.as_posix(),
            "contract_version": VERIFIER.EXECUTION_ORDER_VERSION,
            "raw_sha256": VERIFIER.EXECUTION_ORDER_SHA256,
        }
        runtime_binding = {
            "path": VERIFIER.EXECUTION_ORDER_PATH.as_posix(),
            "contract_version": VERIFIER.EXECUTION_ORDER_VERSION,
            "sha256": VERIFIER.EXECUTION_ORDER_SHA256,
        }
        self.assertEqual(
            self.semantics["source_execution_order_contract"],
            semantic_binding,
        )
        self.assertEqual(
            self.contract["repository_artifacts"]["source_execution_order_contract"],
            runtime_binding,
        )
        self.assertEqual(
            hashlib.sha256((ROOT / VERIFIER.EXECUTION_ORDER_PATH).read_bytes()).hexdigest(),
            VERIFIER.EXECUTION_ORDER_SHA256,
        )
        VERIFIER.verify_execution_order_binding(ROOT, self.semantics, self.contract)

        reference = json.loads((ROOT / VERIFIER.EXECUTION_ORDER_PATH).read_text())
        dynamic = reference["execution_model"]["dynamic_data_sources"]
        self.assertEqual(dynamic["stage_scope"], "stage_local")
        self.assertEqual(dynamic["traversal"], "breadth_first")
        self.assertFalse(dynamic["raw_global_flattening"])
        self.assertFalse(dynamic["creation_log_ordinal_gate"])

    def test_all_eight_segments_cross_bind_pool_profiles_and_failure_modes(self) -> None:
        source = json.loads(
            (ROOT / "uniswap-v3/writer-runtime/segment-profiles-v1.json").read_text()
        )["profiles"]
        reducer = self.semantics["segments"]
        self.assertEqual(len(source), len(reducer), 8)
        self.assertEqual(
            [segment["nonfatal_errors"] for segment in reducer],
            [False, False, False, False, False, True, True, True],
        )
        for source_segment, reducer_segment in zip(source, reducer):
            self.assertEqual(
                reducer_segment["pool_mapping_cid"],
                source_segment["pool_mapping_cid"],
            )
            self.assertEqual(
                reducer_segment["pool_profile_id"],
                source_segment["pool_profile_id"],
            )
            self.assertEqual(
                reducer_segment["semantic_contract_sha256"],
                source_segment["semantic_contract_sha256"],
            )

    def test_exact_two_call_atomic_contract_and_membership_are_explicit(self) -> None:
        execution = self.semantics["execution_contract"]
        self.assertEqual(execution["fee_growth_0_calldata"], "f3058399")
        self.assertEqual(execution["fee_growth_1_calldata"], "46141319")
        self.assertIn("only after success", execution["call_order"])
        self.assertIn("both Pool fee-growth fields", execution["atomicity"])
        self.assertIn("diagnostic input convention", execution["event_order"])
        self.assertIn("supplied PoolCreated/Flash envelope", execution["event_order"])
        self.assertIn("diagnostic creation-ordinal input convention", execution["membership"])
        self.assertIn("does not model Graph Node block-scoped activation", execution["membership"])
        self.assertIn("does not model Graph Node dynamic-datasource stage order", execution["graph_node_order_scope"])
        self.assertIn("no same-path or cross-component order claim", execution["graph_node_order_scope"])
        for excluded in ("VID", "PoI", "persisted-data-source", "deterministic-error-stream", "physical"):
            self.assertIn(excluded, execution["fatal_error"])
        self.assertIn("do not attempt fee1", execution["first_call_failure"])
        self.assertIn("discard fee0 scratch", execution["second_call_failure"])
        self.assertEqual(execution["flash_specific_guards"], [])
        self.assertEqual(execution["emitted_row_types"], ["Pool"])
        self.assertEqual(execution["synthetic_row_types"], [])

    def test_every_promotion_runtime_oracle_and_parity_flag_stays_false(self) -> None:
        truth = self.contract["truth_boundary"]
        self.assertTrue(truth["diagnostic_only"])
        self.assertTrue(truth["graph_node_execution_order_supplement_bound"])
        self.assertFalse(truth["dynamic_datasource_stage_order_implemented"])
        self.assertFalse(truth["combined_handler_order_implemented"])
        self.assertFalse(truth["runtime_consumes_execution_order_contract"])
        self.assertFalse(truth["cross_component_order_proven"])
        self.assertFalse(truth["live_rpc_added"])
        self.assertFalse(truth["same_path_order_machine_proven"])
        self.assertFalse(truth["full_pool_handler_semantics"])
        self.assertFalse(truth["target_runtime_identity_bound"])
        self.assertTrue(
            all(
                value is False
                for key, value in truth.items()
                if key
                not in {
                    "diagnostic_only",
                    "graph_node_execution_order_supplement_bound",
                }
            )
        )

    def test_relocked_truth_promotion_is_rejected(self) -> None:
        for flag in (
            "dynamic_datasource_stage_order_implemented",
            "combined_handler_order_implemented",
            "runtime_consumes_execution_order_contract",
            "same_path_order_machine_proven",
            "cross_component_order_proven",
            "physical_parity_complete",
            "poi_parity_complete",
            "backfill_ready",
            "production_ready",
        ):
            with self.subTest(flag=flag), tempfile.TemporaryDirectory(
                prefix="flash-truth-promotion-"
            ) as temporary:
                mutated = copy.deepcopy(self.semantics)
                mutated["truth_boundary"][flag] = True
                root = Path(temporary)
                target = root / VERIFIER.OVERLAY / "flash-reducer-v1.json"
                target.parent.mkdir(parents=True)
                target.write_text(json.dumps(mutated, indent=2) + "\n")
                relocked = hashlib.sha256(target.read_bytes()).hexdigest()
                with mock.patch.object(VERIFIER, "REDUCER_SEMANTICS_SHA256", relocked):
                    with self.assertRaisesRegex(VERIFIER.VerificationError, "promoted"):
                        VERIFIER.load_semantics(root)

    def test_relocked_or_outer_supplement_binding_removal_is_rejected(self) -> None:
        mutated = copy.deepcopy(self.semantics)
        mutated.pop("source_execution_order_contract")
        with tempfile.TemporaryDirectory(prefix="flash-binding-removal-") as temporary:
            root = Path(temporary)
            target = root / VERIFIER.OVERLAY / "flash-reducer-v1.json"
            target.parent.mkdir(parents=True)
            target.write_text(json.dumps(mutated, indent=2) + "\n")
            relocked = hashlib.sha256(target.read_bytes()).hexdigest()
            with mock.patch.object(VERIFIER, "REDUCER_SEMANTICS_SHA256", relocked):
                with self.assertRaisesRegex(VERIFIER.VerificationError, "field set drift"):
                    VERIFIER.load_semantics(root)

        outer = copy.deepcopy(self.contract)
        outer["repository_artifacts"].pop("source_execution_order_contract")
        with self.assertRaisesRegex(VERIFIER.VerificationError, "binding removed"):
            VERIFIER.verify_execution_order_binding(ROOT, self.semantics, outer)

    def test_execution_order_raw_source_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="flash-execution-order-drift-") as temporary:
            root = Path(temporary)
            target = root / VERIFIER.EXECUTION_ORDER_PATH
            target.parent.mkdir(parents=True)
            target.write_bytes((ROOT / VERIFIER.EXECUTION_ORDER_PATH).read_bytes() + b"\n")
            with self.assertRaisesRegex(VERIFIER.VerificationError, "raw digest drift"):
                VERIFIER.verify_execution_order_binding(root, self.semantics, self.contract)

    def test_patch_applies_as_the_final_host_only_layer(self) -> None:
        patch = (ROOT / VERIFIER.OVERLAY / "runtime.patch").read_text()
        with tempfile.TemporaryDirectory(prefix="flash-patch-order-") as temporary:
            writer_runtime = Path(temporary) / "writer"
            WRITER.materialize_expected(ROOT, writer_runtime)
            accepted = subprocess.run(
                [
                    "patch",
                    "--directory",
                    str(writer_runtime),
                    "--strip",
                    "1",
                    "--forward",
                    "--batch",
                    "-F",
                    "0",
                    "--dry-run",
                ],
                input=patch,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            self.assertEqual(accepted.returncode, 0, accepted.stdout)

    def test_materializer_refuses_nonempty_and_repository_destinations(self) -> None:
        script = ROOT / "scripts/materialize-uniswap-v3-flash-reducer.sh"
        with tempfile.TemporaryDirectory(prefix="flash-nonempty-") as temporary:
            destination = Path(temporary)
            sentinel = destination / "keep.txt"
            sentinel.write_text("preserve\n")
            result = subprocess.run(
                ["bash", str(script), str(destination)],
                env={**os.environ, "PYTHON": sys.executable},
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("destination must be empty", result.stdout)
            self.assertEqual(sentinel.read_text(), "preserve\n")
        forbidden = ROOT / "flash-reducer-forbidden"
        self.assertFalse(forbidden.exists())
        result = subprocess.run(
            ["bash", str(script), str(forbidden)],
            env={**os.environ, "PYTHON": sys.executable},
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("destination must be outside the repository", result.stdout)
        self.assertFalse(forbidden.exists())

    def test_exact_materialization_preserves_frozen_source(self) -> None:
        before = tree_digest(ROOT / "uniswap-v3/source")
        with tempfile.TemporaryDirectory(prefix="flash-materializer-") as temporary:
            destination = Path(temporary) / "runtime"
            subprocess.run(
                [
                    "bash",
                    str(ROOT / "scripts/materialize-uniswap-v3-flash-reducer.sh"),
                    str(destination),
                ],
                env={**os.environ, "PYTHON": sys.executable},
                text=True,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            VERIFIER.verify_runtime(ROOT, destination, self.contract, WRITER)
        self.assertEqual(tree_digest(ROOT / "uniswap-v3/source"), before)

    def test_runtime_verifier_rejects_content_and_file_set_drift(self) -> None:
        for mutation in ("content", "extra"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory(
                prefix="flash-runtime-drift-"
            ) as temporary:
                runtime = Path(temporary) / "runtime"
                VERIFIER.materialize_expected(ROOT, runtime, WRITER)
                if mutation == "content":
                    source = runtime / "src/flash_reducer.rs"
                    source.write_text(source.read_text() + "\n")
                else:
                    (runtime / "unexpected.txt").write_text("drift\n")
                with self.assertRaises(VERIFIER.VerificationError):
                    VERIFIER.verify_runtime(ROOT, runtime, self.contract, WRITER)

    def test_semantics_self_rehash_cannot_escape_fixed_digest(self) -> None:
        with tempfile.TemporaryDirectory(prefix="flash-semantics-drift-") as temporary:
            root = Path(temporary)
            target = root / VERIFIER.OVERLAY / "flash-reducer-v1.json"
            target.parent.mkdir(parents=True)
            mutated = copy.deepcopy(self.semantics)
            mutated["truth_boundary"]["production_ready"] = True
            target.write_text(json.dumps(mutated, indent=2) + "\n")
            with self.assertRaisesRegex(VERIFIER.VerificationError, "digest drift"):
                VERIFIER.load_semantics(root)

    def test_runtime_contract_self_rehash_cannot_escape_fixed_digest(self) -> None:
        with tempfile.TemporaryDirectory(prefix="flash-runtime-contract-relock-") as temporary:
            root = Path(temporary)
            target = root / VERIFIER.CONTRACT_PATH
            target.parent.mkdir(parents=True)
            mutated = copy.deepcopy(self.contract)
            mutated["reducer_contract"]["call_order"] = ["46141319", "f3058399"]
            mutated["truth_boundary"]["same_path_order_machine_proven"] = True
            target.write_text(json.dumps(mutated, indent=2) + "\n")
            with self.assertRaisesRegex(VERIFIER.VerificationError, "raw digest drift"):
                VERIFIER.load_contract(root)

    def test_source_semantics_and_runtime_contract_co_relock_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="flash-co-relock-") as temporary:
            root = Path(temporary)
            overlay = root / VERIFIER.OVERLAY
            (overlay / "src").mkdir(parents=True)
            (overlay / "runtime.patch").write_bytes(
                (ROOT / VERIFIER.OVERLAY / "runtime.patch").read_bytes()
            )

            source = (ROOT / VERIFIER.OVERLAY / "src/flash_reducer.rs").read_text()
            source = source.replace(
                "const FEE_GROWTH_0_CALLDATA: [u8; 4] = [0xf3, 0x05, 0x83, 0x99];",
                "const FEE_GROWTH_RELOCK_TMP: [u8; 4] = [0xf3, 0x05, 0x83, 0x99];",
                1,
            )
            source = source.replace(
                "const FEE_GROWTH_1_CALLDATA: [u8; 4] = [0x46, 0x14, 0x13, 0x19];",
                "const FEE_GROWTH_1_CALLDATA: [u8; 4] = [0xf3, 0x05, 0x83, 0x99];",
                1,
            )
            source = source.replace(
                "const FEE_GROWTH_RELOCK_TMP: [u8; 4] = [0xf3, 0x05, 0x83, 0x99];",
                "const FEE_GROWTH_0_CALLDATA: [u8; 4] = [0x46, 0x14, 0x13, 0x19];",
                1,
            )
            self.assertIn(
                "const FEE_GROWTH_0_CALLDATA: [u8; 4] = [0x46, 0x14, 0x13, 0x19];",
                source,
            )
            self.assertIn(
                "const FEE_GROWTH_1_CALLDATA: [u8; 4] = [0xf3, 0x05, 0x83, 0x99];",
                source,
            )
            source_target = overlay / "src/flash_reducer.rs"
            source_target.write_text(source)

            semantics = copy.deepcopy(self.semantics)
            semantics["execution_contract"]["fee_growth_0_calldata"] = "46141319"
            semantics["execution_contract"]["fee_growth_1_calldata"] = "f3058399"
            semantics_target = overlay / "flash-reducer-v1.json"
            semantics_target.write_text(json.dumps(semantics, indent=2) + "\n")

            runtime_contract = copy.deepcopy(self.contract)
            runtime_contract["repository_artifacts"]["reducer_source"]["sha256"] = hashlib.sha256(
                source_target.read_bytes()
            ).hexdigest()
            runtime_contract["repository_artifacts"]["reducer_contract"]["sha256"] = hashlib.sha256(
                semantics_target.read_bytes()
            ).hexdigest()
            runtime_contract["materialized_runtime_artifacts"]["src/flash_reducer.rs"] = runtime_contract[
                "repository_artifacts"
            ]["reducer_source"]["sha256"]
            runtime_contract["materialized_runtime_artifacts"]["configs/flash-reducer-v1.json"] = runtime_contract[
                "repository_artifacts"
            ]["reducer_contract"]["sha256"]
            runtime_contract["reducer_contract"]["call_order"] = ["46141319", "f3058399"]
            contract_target = root / VERIFIER.CONTRACT_PATH
            contract_target.parent.mkdir(parents=True, exist_ok=True)
            contract_target.write_text(json.dumps(runtime_contract, indent=2) + "\n")

            with self.assertRaisesRegex(VERIFIER.VerificationError, "raw digest drift"):
                VERIFIER.load_contract(root)
            with self.assertRaisesRegex(VERIFIER.VerificationError, "semantics digest drift"):
                VERIFIER.load_semantics(root)
            with self.assertRaisesRegex(VERIFIER.VerificationError, "source digest drift"):
                VERIFIER.verify_overlay_static(root, WRITER)

    def test_independent_verifier_pins_are_exact_literals(self) -> None:
        self.assertEqual(
            VERIFIER.WRITER_RUNTIME_SHA256,
            "765806bf19fca7695ef4d97f557593e4f791759589fe55c20f18c6523a5d07ca",
        )
        self.assertEqual(
            VERIFIER.PROFILE_SHA256,
            "2b6635c061a7a0bfce39430c71c41dacc1567f095fe41134e890a697aa27f823",
        )
        self.assertEqual(
            VERIFIER.WRITER_SOURCE_SHA256,
            "259481724561d5aa725c17f90b5a19ea93ad6f7cd6074cf2cb8a8661c39f81c4",
        )
        self.assertEqual(
            VERIFIER.EXECUTION_ORDER_SHA256,
            "241e970cfcec4d76610b29a10141d3bff2512d80454a6308594f3db23621cde2",
        )
        self.assertEqual(
            VERIFIER.REDUCER_SEMANTICS_SHA256,
            "85a3eb1037223dc7794706f860723df0f2897dd043e5e4a9db23f4a2de52af4f",
        )
        self.assertEqual(
            VERIFIER.REDUCER_SOURCE_SHA256,
            "751df82569aff4a232e3c2bbb93d97abe2c6057bb857c08a69f7b832bda40a3f",
        )

    def test_source_profile_relabel_cannot_pass_cross_binding(self) -> None:
        mutated = copy.deepcopy(self.semantics)
        mutated["segments"][0]["pool_profile_id"] = "modern-mainnet"
        with tempfile.TemporaryDirectory(prefix="flash-profile-relabel-") as temporary:
            root = Path(temporary)
            profile_target = root / "uniswap-v3/writer-runtime/segment-profiles-v1.json"
            profile_target.parent.mkdir(parents=True)
            profile_target.write_bytes(
                (ROOT / "uniswap-v3/writer-runtime/segment-profiles-v1.json").read_bytes()
            )
            with self.assertRaises(VERIFIER.VerificationError):
                VERIFIER.verify_segment_binding(root, mutated)

    def test_static_verifier_rejects_live_capabilities_and_call_reordering(self) -> None:
        source_path = ROOT / VERIFIER.OVERLAY / "src/flash_reducer.rs"
        original = source_path.read_text()
        self.assertLess(
            original.index("&FEE_GROWTH_0_CALLDATA"),
            original.index("&FEE_GROWTH_1_CALLDATA"),
        )
        for forbidden in (
            "#[substreams::handlers",
            "rpc::eth_call",
            "StoreSet",
            "EntityChanges",
        ):
            self.assertNotIn(forbidden, original)

    def test_package_shape_remains_the_consumerless_23_module_writer_graph(self) -> None:
        configs = WRITER.load_configs(ROOT)
        manifests = WRITER.load_manifests(ROOT, configs)
        for network, manifest in manifests.items():
            self.assertEqual(len(manifest["modules"]), 23, network)
            graph_out = next(
                module for module in manifest["modules"] if module["name"] == "graph_out"
            )
            self.assertEqual(
                graph_out["output"]["type"],
                "proto:sf.substreams.entity.v1.EntityChanges",
            )
            self.assertFalse(
                any(
                    item.get("map") == "map_writer_events"
                    or item.get("store") == "map_writer_events"
                    for module in manifest["modules"]
                    for item in module.get("inputs", [])
                )
            )
            self.assertNotIn(
                "map_flash_reducer",
                {module["name"] for module in manifest["modules"]},
            )


if __name__ == "__main__":
    unittest.main()
