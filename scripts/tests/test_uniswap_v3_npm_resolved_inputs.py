#!/usr/bin/env python3
"""Hermetic tests for host-only resolved Uniswap V3 NPM inputs."""

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
VERIFIER_PATH = ROOT / "scripts/verify-uniswap-v3-npm-resolved-inputs.py"
SPEC = importlib.util.spec_from_file_location("npm_resolved_input_verifier", VERIFIER_PATH)
assert SPEC and SPEC.loader
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)
SOURCE = VERIFIER.load_source_verifier(ROOT)
JOINT = VERIFIER.load_joint_verifier(ROOT)
WRITER = JOINT.load_writer_verifier(ROOT)


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


class NpmResolvedInputContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = VERIFIER.load_contract(ROOT)
        cls.semantics = VERIFIER.load_semantics(ROOT)

    def test_exact_source_joint_writer_matrix_and_execution_bindings(self) -> None:
        expected = {
            "source_npm_source_runtime_sha256": VERIFIER.SOURCE_RUNTIME_SHA256,
            "source_npm_source_semantics_sha256": VERIFIER.SOURCE_SEMANTICS_SHA256,
            "source_npm_source_proto_sha256": VERIFIER.SOURCE_PROTO_SHA256,
            "source_npm_source_validator_sha256": VERIFIER.SOURCE_VALIDATOR_SHA256,
            "source_npm_source_binding_sha256": VERIFIER.SOURCE_BINDING_SHA256,
            "source_npm_handler_reducer_runtime_sha256": VERIFIER.JOINT_RUNTIME_SHA256,
            "source_npm_handler_reducer_semantics_sha256": VERIFIER.JOINT_SEMANTICS_SHA256,
            "source_writer_runtime_sha256": VERIFIER.WRITER_RUNTIME_SHA256,
            "source_writer_profiles_sha256": VERIFIER.WRITER_PROFILE_SHA256,
            "source_writer_compatibility_sha256": VERIFIER.WRITER_COMPATIBILITY_SHA256,
            "source_writer_proto_sha256": VERIFIER.WRITER_PROTO_SHA256,
            "source_segment_matrix_sha256": VERIFIER.SEGMENT_MATRIX_SHA256,
            "source_execution_order_sha256": VERIFIER.EXECUTION_ORDER_SHA256,
        }
        self.assertEqual({key: self.semantics[key] for key in expected}, expected)
        VERIFIER.verify_upstream(ROOT, SOURCE, JOINT, WRITER)

    def test_truth_boundary_promotes_only_the_disconnected_resolved_frame(self) -> None:
        truth = self.contract["truth_boundary"]
        self.assertEqual(
            {key for key, value in truth.items() if value},
            {
                "all_eight_npm_segments_executable",
                "diagnostic_only",
                "host_resolved_input_frame_implemented",
            },
        )
        for gate in (
            "integrated_host_engine_added",
            "post_fatal_execution_modeled",
            "all_required_observations_evaluated",
            "graph_execution_trace_complete",
            "checkpoint_or_graph_block_success_authorized",
            "boundary_state_continuity_complete",
            "physical_parity_complete",
            "poi_parity_complete",
            "backfill_ready",
            "production_ready",
        ):
            self.assertFalse(truth[gate])

    def test_schema_binding_and_overlay_are_resolved_only(self) -> None:
        VERIFIER.verify_proto(ROOT, self.contract)
        VERIFIER.verify_overlay_static(ROOT)
        overlay = ROOT / VERIFIER.OVERLAY
        content = b"\n".join(path.read_bytes() for path in overlay.rglob("*") if path.is_file())
        sentinel = ("Provider" + "Unavailable").encode()
        self.assertNotIn(sentinel, content)
        self.assertNotIn(("Position" + "NullKind").encode(), content)
        self.assertFalse((ROOT / "uniswap-v3/source/proto/uniswap/npm/inputs/v1/npm_resolved_inputs.proto").exists())

    def test_transposed_base_factory_literal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="npm-resolved-base-factory-drift-") as temporary:
            root = Path(temporary)
            target = root / VERIFIER.OVERLAY
            shutil.copytree(ROOT / VERIFIER.OVERLAY, target)
            source = target / "src/npm_resolved_inputs.rs"
            source.write_text(
                source.read_text().replace(
                    "0x21, 0xf6, 0xfd,\n    0xfd,",
                    "0x21, 0xf6, 0xdf,\n    0xd0,",
                )
            )
            with self.assertRaisesRegex(VERIFIER.VerificationError, "Base Factory"):
                VERIFIER.verify_overlay_static(root)

    def test_semantics_use_complete_source_and_exact_initial_blocks(self) -> None:
        mapping = self.semantics["mapping_contract"]
        self.assertIn("complete validated", mapping["source"])
        self.assertFalse(mapping["source_recomputed"])
        self.assertFalse(mapping["writer_events_supplied_separately"])
        self.assertFalse(mapping["raw_block_consumed"])
        self.assertFalse(mapping["chain_config_consumed"])
        self.assertEqual(self.semantics["initial_blocks"], {"mainnet": 12_369_651, "base": 1_371_713})

    def test_materialization_is_exact_and_preserves_every_writer_file(self) -> None:
        before = tree_digest(ROOT / "uniswap-v3/source")
        with tempfile.TemporaryDirectory(prefix="npm-resolved-materialize-") as temporary:
            root = Path(temporary)
            writer_runtime = root / "writer"
            runtime = root / "resolved"
            WRITER.materialize_expected(ROOT, writer_runtime)
            VERIFIER.materialize_expected(ROOT, runtime, JOINT, WRITER)
            VERIFIER.verify_runtime(ROOT, runtime, self.contract, JOINT, WRITER)
            writer_files = WRITER.non_build_files(writer_runtime)
            runtime_files = WRITER.non_build_files(runtime)
            for relative, writer_path in writer_files.items():
                self.assertEqual(runtime_files[relative].read_bytes(), writer_path.read_bytes(), relative)
            self.assertFalse((runtime / "tests/npm_handler_reducer.rs").exists())
            self.assertTrue((runtime / "tests/npm_resolved_inputs.rs").is_file())
            self.assertEqual(
                (runtime / "src/npm_source_block.rs").read_bytes(),
                (ROOT / "uniswap-v3/npm-source-block/runtime/src/npm_source_block.rs").read_bytes(),
            )
            self.assertEqual(
                (runtime / "src/uniswap.npm.source.v1.rs").read_bytes(),
                (ROOT / "uniswap-v3/npm-source-block/runtime/src/pb/uniswap.npm.source.v1.rs").read_bytes(),
            )
            self.assertFalse((runtime / "proto/uniswap/npm").exists())
        self.assertEqual(tree_digest(ROOT / "uniswap-v3/source"), before)

    def test_runtime_verifier_rejects_content_and_file_set_drift(self) -> None:
        for mutation in ("content", "extra"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory(
                prefix="npm-resolved-runtime-drift-"
            ) as temporary:
                runtime = Path(temporary) / "runtime"
                VERIFIER.materialize_expected(ROOT, runtime, JOINT, WRITER)
                if mutation == "content":
                    target = runtime / "src/npm_resolved_inputs.rs"
                    target.write_text(target.read_text() + "\n")
                else:
                    (runtime / "unexpected.txt").write_text("drift\n")
                with self.assertRaises(VERIFIER.VerificationError):
                    VERIFIER.verify_runtime(ROOT, runtime, self.contract, JOINT, WRITER)

    def test_fixed_runtime_and_semantic_digests_reject_self_rehash(self) -> None:
        with tempfile.TemporaryDirectory(prefix="npm-resolved-contract-drift-") as temporary:
            root = Path(temporary)
            target = root / VERIFIER.CONTRACT_PATH
            target.parent.mkdir(parents=True)
            mutated = copy.deepcopy(self.contract)
            mutated["truth_boundary"]["production_ready"] = True
            target.write_text(json.dumps(mutated, indent=2) + "\n")
            with self.assertRaisesRegex(VERIFIER.VerificationError, "raw digest drift"):
                VERIFIER.load_contract(root)
        with tempfile.TemporaryDirectory(prefix="npm-resolved-semantics-drift-") as temporary:
            root = Path(temporary)
            target = root / VERIFIER.OVERLAY / "npm-resolved-inputs-v1.json"
            target.parent.mkdir(parents=True)
            mutated = copy.deepcopy(self.semantics)
            mutated["truth_boundary"]["production_ready"] = True
            target.write_text(json.dumps(mutated, indent=2) + "\n")
            with self.assertRaisesRegex(VERIFIER.VerificationError, "raw digest drift"):
                VERIFIER.load_semantics(root)

    def test_materializer_refuses_nonempty_repository_and_symlink_escape_destinations(self) -> None:
        script = ROOT / "scripts/materialize-uniswap-v3-npm-resolved-inputs.sh"
        with tempfile.TemporaryDirectory(prefix="npm-resolved-nonempty-") as temporary:
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
        forbidden = ROOT / "npm-resolved-input-forbidden"
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
        with tempfile.TemporaryDirectory(prefix="npm-resolved-symlink-") as temporary:
            link = Path(temporary) / "escape"
            link.symlink_to(ROOT / "uniswap-v3")
            result = subprocess.run(
                ["bash", str(script), str(link)],
                env={**os.environ, "PYTHON": sys.executable},
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("destination must be outside the repository", result.stdout)

    def test_docs_are_artifact_local(self) -> None:
        overlay = ROOT / VERIFIER.OVERLAY
        self.assertTrue((overlay / "docs/eligibility.md").is_file())
        self.assertTrue((overlay / "docs/provenance.md").is_file())
        self.assertFalse((overlay / "evidence").exists())
        self.assertFalse((overlay / "provenance").exists())


if __name__ == "__main__":
    unittest.main()
