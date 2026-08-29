#!/usr/bin/env python3
"""Hermetic tests for the host-only Uniswap V3 NPM observation plan."""

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
VERIFIER_PATH = ROOT / "scripts/verify-uniswap-v3-npm-observation-plan.py"
SPEC = importlib.util.spec_from_file_location("npm_observation_plan_verifier", VERIFIER_PATH)
assert SPEC and SPEC.loader
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)
RESOLVED = VERIFIER.load_resolved_verifier(ROOT)
JOINT = RESOLVED.load_joint_verifier(ROOT)
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


class NpmObservationPlanContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = VERIFIER.load_contract(ROOT)
        cls.semantics = VERIFIER.load_semantics(ROOT)

    def test_exact_resolved_source_joint_writer_and_segment_bindings(self) -> None:
        expected = {
            "source_resolved_input_runtime_sha256": VERIFIER.RESOLVED_RUNTIME_SHA256,
            "source_resolved_input_semantics_sha256": VERIFIER.RESOLVED_SEMANTICS_SHA256,
            "source_npm_source_runtime_sha256": VERIFIER.SOURCE_RUNTIME_SHA256,
            "source_npm_handler_reducer_runtime_sha256": VERIFIER.JOINT_RUNTIME_SHA256,
            "source_npm_handler_reducer_semantics_sha256": VERIFIER.JOINT_SEMANTICS_SHA256,
            "source_writer_runtime_sha256": VERIFIER.WRITER_RUNTIME_SHA256,
            "source_writer_profiles_sha256": VERIFIER.WRITER_PROFILE_SHA256,
            "source_writer_compatibility_sha256": VERIFIER.WRITER_COMPATIBILITY_SHA256,
            "source_segment_matrix_sha256": VERIFIER.SEGMENT_MATRIX_SHA256,
            "source_execution_order_sha256": VERIFIER.EXECUTION_ORDER_SHA256,
        }
        self.assertEqual({key: self.semantics[key] for key in expected}, expected)
        VERIFIER.verify_upstream(ROOT, RESOLVED)

    def test_truth_boundary_promotes_only_closed_host_planning(self) -> None:
        truth = self.contract["truth_boundary"]
        self.assertEqual(truth, VERIFIER.expected_truth())
        self.assertEqual(
            {key for key, value in truth.items() if value},
            {
                "host_observation_plan_implemented",
                "complete_conservative_npm_request_closure",
                "post_fatal_writer_event_suffix_in_plan",
                "exact_plan_resolved_frame_key_equality_enforced",
                "all_planned_rows_resolved_before_certified_reducer_path",
                "all_eight_npm_segment_profiles_bound",
            },
        )
        for gate in (
            "integrated_provider_executor_added",
            "all_required_observations_evaluated",
            "exact_graph_call_trace_complete",
            "post_fatal_execution_modeled",
            "graph_execution_trace_complete",
            "factory_pool_combined_schedule_implemented",
            "dynamic_datasource_stage_order_implemented",
            "entity_changes_or_block_changes_implemented",
            "checkpoint_or_graph_block_success_authorized",
            "boundary_state_continuity_complete",
            "physical_parity_complete",
            "poi_parity_complete",
            "backfill_ready",
            "production_ready",
        ):
            self.assertFalse(truth[gate])

    def test_schema_source_and_harness_are_host_only_and_closed(self) -> None:
        VERIFIER.verify_proto(ROOT, self.contract)
        VERIFIER.verify_overlay_static(ROOT)
        overlay = ROOT / VERIFIER.OVERLAY
        content = b"\n".join(path.read_bytes() for path in overlay.rglob("*") if path.is_file())
        self.assertNotIn(("Provider" + "Unavailable").encode(), content)
        source = (overlay / "src/npm_observation_plan.rs").read_text()
        self.assertIn("pub struct PreflightedResolvedFrame", source)
        self.assertNotIn("pub frame: NpmResolvedInputs", source)
        self.assertNotIn("pub plan: NpmObservationPlan", source)
        self.assertFalse((ROOT / "uniswap-v3/source/proto/uniswap/npm/plan").exists())

    def test_materialization_is_exact_and_preserves_resolved_and_writer_files(self) -> None:
        before = tree_digest(ROOT / "uniswap-v3/source")
        with tempfile.TemporaryDirectory(prefix="npm-plan-materialize-") as temporary:
            root = Path(temporary)
            baseline = root / "resolved"
            runtime = root / "planned"
            RESOLVED.materialize_expected(ROOT, baseline, JOINT, WRITER)
            VERIFIER.materialize_expected(ROOT, runtime, RESOLVED, JOINT, WRITER)
            VERIFIER.verify_runtime(ROOT, runtime, self.contract, RESOLVED, JOINT, WRITER)
            baseline_files = WRITER.non_build_files(baseline)
            runtime_files = WRITER.non_build_files(runtime)
            for relative, baseline_path in baseline_files.items():
                if relative == "tests/npm_resolved_inputs.rs":
                    continue
                self.assertEqual(runtime_files[relative].read_bytes(), baseline_path.read_bytes(), relative)
            self.assertFalse((runtime / "tests/npm_resolved_inputs.rs").exists())
            self.assertTrue((runtime / "tests/npm_observation_plan.rs").is_file())
            self.assertFalse((runtime / "proto/uniswap/npm/plan").exists())
        self.assertEqual(tree_digest(ROOT / "uniswap-v3/source"), before)

    def test_runtime_verifier_rejects_content_file_set_and_mode_drift(self) -> None:
        for mutation in ("content", "extra", "mode"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory(
                prefix="npm-plan-runtime-drift-"
            ) as temporary:
                runtime = Path(temporary) / "runtime"
                VERIFIER.materialize_expected(ROOT, runtime, RESOLVED, JOINT, WRITER)
                if mutation == "content":
                    target = runtime / "src/npm_observation_plan.rs"
                    target.write_text(target.read_text() + "\n")
                elif mutation == "extra":
                    (runtime / "unexpected.txt").write_text("drift\n")
                else:
                    target = runtime / "tests/npm_observation_plan.rs"
                    target.chmod(target.stat().st_mode | 0o111)
                with self.assertRaises(VERIFIER.VerificationError):
                    VERIFIER.verify_runtime(ROOT, runtime, self.contract, RESOLVED, JOINT, WRITER)

    def test_fixed_runtime_and_semantic_digests_reject_self_rehash(self) -> None:
        with tempfile.TemporaryDirectory(prefix="npm-plan-contract-drift-") as temporary:
            root = Path(temporary)
            target = root / VERIFIER.CONTRACT_PATH
            target.parent.mkdir(parents=True)
            mutated = copy.deepcopy(self.contract)
            mutated["truth_boundary"]["production_ready"] = True
            target.write_text(json.dumps(mutated, indent=2) + "\n")
            with self.assertRaisesRegex(VERIFIER.VerificationError, "raw digest drift"):
                VERIFIER.load_contract(root)
        with tempfile.TemporaryDirectory(prefix="npm-plan-semantics-drift-") as temporary:
            root = Path(temporary)
            target = root / VERIFIER.OVERLAY / "npm-observation-plan-v1.json"
            target.parent.mkdir(parents=True)
            mutated = copy.deepcopy(self.semantics)
            mutated["truth_boundary"]["production_ready"] = True
            target.write_text(json.dumps(mutated, indent=2) + "\n")
            with self.assertRaisesRegex(VERIFIER.VerificationError, "raw digest drift"):
                VERIFIER.load_semantics(root)

    def test_proto_verifier_rejects_provider_failure_fields(self) -> None:
        with tempfile.TemporaryDirectory(prefix="npm-plan-proto-drift-") as temporary:
            root = Path(temporary)
            target = root / VERIFIER.OVERLAY
            shutil.copytree(ROOT / VERIFIER.OVERLAY, target)
            proto = target / "proto/uniswap/npm/plan/v1/npm_observation_plan.proto"
            proto.write_text(proto.read_text().replace("string network = 4;", "string provider_error = 4;"))
            with self.assertRaisesRegex(VERIFIER.VerificationError, "canonical plan"):
                VERIFIER.verify_proto(root, self.contract)

    def test_materializer_refuses_nonempty_repository_and_symlink_escape_destinations(self) -> None:
        script = ROOT / "scripts/materialize-uniswap-v3-npm-observation-plan.sh"
        with tempfile.TemporaryDirectory(prefix="npm-plan-nonempty-") as temporary:
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
        forbidden = ROOT / "npm-observation-plan-forbidden"
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
        with tempfile.TemporaryDirectory(prefix="npm-plan-symlink-") as temporary:
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

    def test_docs_are_artifact_local_and_name_the_remaining_dependencies(self) -> None:
        overlay = ROOT / VERIFIER.OVERLAY
        eligibility = (overlay / "docs/eligibility.md").read_text()
        self.assertTrue((overlay / "docs/provenance.md").is_file())
        self.assertFalse((overlay / "evidence").exists())
        self.assertFalse((overlay / "provenance").exists())
        for dependency in ("Factory/Pool", "dynamic data-source", "EntityChanges/BlockChanges"):
            self.assertIn(dependency, eligibility)


if __name__ == "__main__":
    unittest.main()
