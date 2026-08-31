#!/usr/bin/env python3
"""Hermetic tests for the Uniswap V3 NPM provider executor contract."""

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
VERIFIER_PATH = ROOT / "scripts/verify-uniswap-v3-npm-provider-executor.py"
SPEC = importlib.util.spec_from_file_location("npm_provider_executor_verifier", VERIFIER_PATH)
assert SPEC and SPEC.loader
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)
PLAN = VERIFIER.load_plan_verifier(ROOT)
FIELD = VERIFIER.load_field_verifier(ROOT)


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


class NpmProviderExecutorContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = VERIFIER.load_contract(ROOT)
        cls.semantics = VERIFIER.load_semantics(ROOT)
        cls.resolved, cls.joint, cls.writer, _ = VERIFIER.verify_dependencies(ROOT, PLAN, FIELD)

    def test_only_the_three_audited_direct_dependencies_are_bound(self) -> None:
        expected = VERIFIER.expected_dependencies()
        self.assertEqual(self.contract["direct_dependencies"], expected)
        self.assertEqual(self.semantics["direct_dependencies"], expected)
        serialized = json.dumps(expected, sort_keys=True).lower()
        self.assertNotIn("segment-field-semantics/v2", serialized)
        self.assertNotIn("factory", " ".join(expected))

    def test_truth_boundary_promotes_only_the_host_execution_slice(self) -> None:
        truth = self.contract["truth_boundary"]
        self.assertEqual(truth, VERIFIER.expected_truth())
        self.assertEqual(
            {key for key, value in truth.items() if value},
            {
                "host_provider_executor_implemented",
                "all_planned_conservative_observations_evaluated",
                "post_fatal_reducer_suffix_evaluated",
                "phased_provider_order_enforced",
                "exact_plan_resolved_frame_key_equality_enforced",
                "certified_joint_reducer_invoked_after_preflight",
                "canonical_observation_execution_audit_returned",
                "all_eight_npm_segment_profiles_exercised",
            },
        )
        self.assertEqual(self.semantics["truth_boundary"], truth)
        self.assertEqual(
            self.semantics["execution_contract"]["provider_error_handling"],
            "provider error payloads are discarded; only a sanitized error kind, phase, "
            "and optional canonical request index appear in the host error",
        )

    def test_static_executor_contract_and_adversarial_inventory(self) -> None:
        VERIFIER.verify_overlay_static(ROOT)

    def test_materialization_is_deterministic_and_changes_only_the_executor_delta(self) -> None:
        with tempfile.TemporaryDirectory(prefix="npm-provider-executor-materialize-") as temporary:
            temporary_path = Path(temporary)
            first = temporary_path / "first"
            second = temporary_path / "second"
            VERIFIER.materialize_expected(ROOT, first, PLAN, self.resolved, self.joint, self.writer)
            VERIFIER.materialize_expected(ROOT, second, PLAN, self.resolved, self.joint, self.writer)
            self.assertEqual(tree_digest(first), tree_digest(second))
            VERIFIER.verify_runtime(
                ROOT,
                first,
                self.contract,
                PLAN,
                self.resolved,
                self.joint,
                self.writer,
            )
            self.assertTrue((first / "tests/npm_provider_executor.rs").is_file())
            self.assertFalse((first / "tests/npm_observation_plan.rs").exists())
            self.assertFalse((first / "proto/uniswap/npm/plan").exists())

    def test_runtime_verifier_rejects_content_file_set_and_mode_drift(self) -> None:
        for mutation in ("content", "extra", "mode"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory(
                prefix="npm-provider-executor-runtime-drift-"
            ) as temporary:
                runtime = Path(temporary) / "runtime"
                VERIFIER.materialize_expected(ROOT, runtime, PLAN, self.resolved, self.joint, self.writer)
                if mutation == "content":
                    target = runtime / "src/npm_provider_executor.rs"
                    target.write_text(target.read_text() + "\n")
                elif mutation == "extra":
                    (runtime / "unexpected.txt").write_text("drift\n")
                else:
                    target = runtime / "tests/npm_provider_executor.rs"
                    target.chmod(target.stat().st_mode | 0o111)
                with self.assertRaises(VERIFIER.VerificationError):
                    VERIFIER.verify_runtime(
                        ROOT,
                        runtime,
                        self.contract,
                        PLAN,
                        self.resolved,
                        self.joint,
                        self.writer,
                    )

    def test_fixed_contract_and_semantic_digests_reject_self_rehash(self) -> None:
        with tempfile.TemporaryDirectory(prefix="npm-provider-executor-contract-drift-") as temporary:
            root = Path(temporary)
            target = root / VERIFIER.CONTRACT_PATH
            target.parent.mkdir(parents=True)
            mutated = copy.deepcopy(self.contract)
            mutated["truth_boundary"]["production_ready"] = True
            target.write_text(json.dumps(mutated, indent=2) + "\n")
            with self.assertRaisesRegex(VERIFIER.VerificationError, "raw digest drift"):
                VERIFIER.load_contract(root)
        with tempfile.TemporaryDirectory(prefix="npm-provider-executor-semantics-drift-") as temporary:
            root = Path(temporary)
            target = root / VERIFIER.OVERLAY / "npm-provider-executor-v1.json"
            target.parent.mkdir(parents=True)
            mutated = copy.deepcopy(self.semantics)
            mutated["direct_dependencies"]["factory_supplement"] = {
                "path": "uniswap-v3/factory-static/v1/contract.json",
                "contract_version": "forbidden",
                "raw_sha256": "0" * 64,
            }
            target.write_text(json.dumps(mutated, indent=2) + "\n")
            with self.assertRaisesRegex(VERIFIER.VerificationError, "raw digest drift"):
                VERIFIER.load_semantics(root)

    def test_materializer_refuses_nonempty_repository_and_symlink_destinations(self) -> None:
        script = ROOT / "scripts/materialize-uniswap-v3-npm-provider-executor.sh"
        with tempfile.TemporaryDirectory(prefix="npm-provider-executor-nonempty-") as temporary:
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
        forbidden = ROOT / "npm-provider-executor-forbidden"
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
        with tempfile.TemporaryDirectory(prefix="npm-provider-executor-symlink-") as temporary:
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

    def test_cli_refuses_incomplete_runtime_and_package_authority(self) -> None:
        cases = [
            (
                ["--writer-runtime", "/tmp/not-used"],
                "writer-runtime comparison requires --runtime",
            ),
            (
                ["--mainnet-spkg", "/tmp/not-used"],
                "--mainnet-spkg and --base-spkg must be passed together",
            ),
            (
                [
                    "--writer-mainnet-spkg",
                    "/tmp/not-used-mainnet",
                    "--writer-base-spkg",
                    "/tmp/not-used-base",
                ],
                "writer package comparison requires executor package arguments",
            ),
        ]
        for arguments, message in cases:
            with self.subTest(arguments=arguments):
                result = subprocess.run(
                    [sys.executable, str(VERIFIER_PATH), *arguments],
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stdout)

    def test_docs_are_local_conservative_and_plan_documentation_digest_is_exact(self) -> None:
        overlay = ROOT / VERIFIER.OVERLAY
        eligibility = (overlay / "docs/eligibility.md").read_text()
        provenance = (overlay / "docs/provenance.md").read_text()
        plan_provenance = (ROOT / "uniswap-v3/npm-observation-plan/docs/provenance.md").read_text()
        self.assertFalse((overlay / "evidence").exists())
        self.assertFalse((overlay / "provenance").exists())
        self.assertIn("canonical conservative request-evaluation trace", eligibility)
        self.assertIn("not an exact Graph call trace", eligibility)
        self.assertIn(VERIFIER.FIELD_SEMANTICS_V1_SHA256, provenance)
        self.assertIn(VERIFIER.PLAN_SEMANTICS_SHA256, plan_provenance)
        for stale in VERIFIER.STALE_PLAN_DOCUMENTATION_SHA256S:
            self.assertNotIn(stale, plan_provenance)


if __name__ == "__main__":
    unittest.main()
