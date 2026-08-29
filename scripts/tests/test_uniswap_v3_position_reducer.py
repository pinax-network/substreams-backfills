#!/usr/bin/env python3
"""Hermetic tests for the host-only Uniswap V3 Position reducer overlay."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VERIFIER_PATH = ROOT / "scripts/verify-uniswap-v3-position-reducer.py"
SPEC = importlib.util.spec_from_file_location("position_reducer_verifier", VERIFIER_PATH)
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


class PositionReducerContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = VERIFIER.load_contract(ROOT)
        cls.semantics = VERIFIER.load_semantics(ROOT)

    def test_corrected_writer_runtime_and_descriptor_are_exactly_bound(self) -> None:
        self.assertEqual(
            self.semantics["source_writer_runtime"],
            {
                "path": "uniswap-v3/writer-runtime/contract-v1.json",
                "contract_version": "uniswap-v3-writer-runtime/v1",
                "sha256": VERIFIER.WRITER_RUNTIME_SHA256,
                "writer_descriptor_sha256": VERIFIER.WRITER_DESCRIPTOR_SHA256,
            },
        )
        self.assertNotEqual(
            VERIFIER.WRITER_RUNTIME_SHA256,
            "cb42869042a6477a50a534b3abddf2e6d8c9ab91ea6c532a825fb378234ae2be",
        )

    def test_exact_eight_segments_five_profiles_and_collect_rules(self) -> None:
        self.assertEqual(len(self.semantics["segments"]), 8)
        self.assertEqual(len(self.semantics["npm_profiles"]), 5)
        profiles = {profile["profile_id"]: profile for profile in self.semantics["npm_profiles"]}
        self.assertEqual(profiles["base-root-amount0-to-both"]["collect_token_reads"], ["token0"])
        self.assertEqual(profiles["mainnet-no-collect-amounts"]["collect_token_reads"], [])
        self.assertEqual(
            profiles["mainnet-second-fee0-overwrite"]["collect_mode"],
            "fee0-from-fee1-plus-amount1",
        )

    def test_execution_order_and_fatal_projection_limits_are_exact(self) -> None:
        self.assertEqual(
            self.semantics["source_execution_order"],
            {
                "path": VERIFIER.EXECUTION_ORDER_PATH.as_posix(),
                "contract_version": VERIFIER.EXECUTION_ORDER_VERSION,
                "raw_sha256": VERIFIER.EXECUTION_ORDER_SHA256,
            },
        )
        execution = self.semantics["execution_contract"]
        self.assertIn("final persisted Position and PositionSnapshot user-entity projection", execution["fatal_error"])
        self.assertIn("Graph continues remaining runnable triggers", execution["post_fatal_execution"])
        VERIFIER.verify_execution_order_binding(ROOT)

    def test_split_origins_and_guard_asymmetry_are_explicit(self) -> None:
        networks = {item["network"]: item for item in self.semantics["network_contracts"]}
        self.assertEqual((networks["mainnet"]["runtime_start_block"], networks["mainnet"]["npm_start_block"]), (12_369_621, 12_369_651))
        self.assertEqual((networks["base"]["runtime_start_block"], networks["base"]["npm_start_block"]), (1_371_679, 1_371_713))
        mainnet = next(
            segment
            for segment in self.semantics["segments"]
            if segment["network"] == "mainnet"
            and segment["start_block_inclusive"] <= 14_317_993
            and segment["end_block_inclusive"] >= 14_317_993
        )
        base = next(
            segment
            for segment in self.semantics["segments"]
            if segment["network"] == "base"
            and segment["start_block_inclusive"] <= 14_317_993
            and segment["end_block_inclusive"] >= 14_317_993
        )
        self.assertFalse(mainnet["historical_guard_effective"])
        self.assertTrue(base["historical_guard_effective"])

    def test_every_promotion_and_transaction_effect_flag_stays_false(self) -> None:
        truth = self.contract["truth_boundary"]
        self.assertTrue(truth["diagnostic_only"])
        self.assertFalse(truth["transaction_entity_effects_implemented"])
        self.assertFalse(truth["full_npm_handler_semantics"])
        self.assertFalse(truth["graph_execution_trace_complete"])
        self.assertFalse(truth["post_fatal_execution_modeled"])
        self.assertFalse(truth["checkpoint_or_graph_block_success_authorized"])
        self.assertTrue(all(value is False for key, value in truth.items() if key != "diagnostic_only"))

    def test_patch_applies_as_the_final_host_only_layer(self) -> None:
        patch = (ROOT / VERIFIER.OVERLAY / "runtime.patch").read_text()
        with tempfile.TemporaryDirectory(prefix="position-patch-order-") as temporary:
            temporary_path = Path(temporary)
            writer_runtime = temporary_path / "writer"
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
        script = ROOT / "scripts/materialize-uniswap-v3-position-reducer.sh"
        with tempfile.TemporaryDirectory(prefix="position-nonempty-") as temporary:
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
        forbidden = ROOT / "position-reducer-forbidden"
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
        with tempfile.TemporaryDirectory(prefix="position-materializer-") as temporary:
            destination = Path(temporary) / "runtime"
            subprocess.run(
                [
                    "bash",
                    str(ROOT / "scripts/materialize-uniswap-v3-position-reducer.sh"),
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
                prefix="position-runtime-drift-"
            ) as temporary:
                runtime = Path(temporary) / "runtime"
                VERIFIER.materialize_expected(ROOT, runtime, WRITER)
                if mutation == "content":
                    config = runtime / "configs/position-reducer-v1.json"
                    config.write_text(config.read_text() + "\n")
                else:
                    (runtime / "unexpected.txt").write_text("drift\n")
                with self.assertRaises(VERIFIER.VerificationError):
                    VERIFIER.verify_runtime(ROOT, runtime, self.contract, WRITER)

    def test_semantics_self_rehash_cannot_escape_fixed_digest(self) -> None:
        with tempfile.TemporaryDirectory(prefix="position-semantics-drift-") as temporary:
            root = Path(temporary)
            target = root / VERIFIER.OVERLAY / "position-reducer-v1.json"
            target.parent.mkdir(parents=True)
            mutated = copy.deepcopy(self.semantics)
            mutated["truth_boundary"]["production_ready"] = True
            target.write_text(json.dumps(mutated, indent=2) + "\n")
            with self.assertRaisesRegex(VERIFIER.VerificationError, "digest drift"):
                VERIFIER.load_semantics(root)

    def test_package_shape_remains_the_consumerless_23_module_writer_graph(self) -> None:
        configs = WRITER.load_configs(ROOT)
        manifests = WRITER.load_manifests(ROOT, configs)
        for network, manifest in manifests.items():
            self.assertEqual(len(manifest["modules"]), 23, network)
            graph_out = next(module for module in manifest["modules"] if module["name"] == "graph_out")
            self.assertEqual(graph_out["output"]["type"], "proto:sf.substreams.entity.v1.EntityChanges")
            self.assertFalse(
                any(
                    item.get("map") == "map_writer_events" or item.get("store") == "map_writer_events"
                    for module in manifest["modules"]
                    for item in module.get("inputs", [])
                )
            )
            self.assertNotIn("map_position_reducer", {module["name"] for module in manifest["modules"]})


if __name__ == "__main__":
    unittest.main()
