from __future__ import annotations

import copy
import dataclasses
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[2]
VERIFIER_PATH = REPOSITORY / "scripts/verify-uniswap-v3-all-handlers-v1-publication.py"
SPEC = importlib.util.spec_from_file_location("uniswap_v3_all_handlers_v1_publication", VERIFIER_PATH)
assert SPEC is not None and SPEC.loader is not None
VERIFIER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VERIFIER
SPEC.loader.exec_module(VERIFIER)


class AllHandlersV1PublicationSealTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary_directory = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary_directory.name)
        cls.git("init", "-q")
        cls.git("config", "user.name", "Publication Seal Test")
        cls.git("config", "user.email", "publication-seal@example.invalid")

        (cls.root / "README.md").write_text("fixture repository\n", encoding="utf-8")
        cls.git("add", "README.md")
        cls.git("commit", "-q", "-m", "fixture parent")
        cls.parent = cls.git("rev-parse", "HEAD")

        contract_path = cls.root / VERIFIER.CONTRACT_PATH
        contract_path.parent.mkdir(parents=True)
        shutil.copyfile(REPOSITORY / VERIFIER.CONTRACT_PATH, contract_path)
        cls.git("add", VERIFIER.CONTRACT_PATH)
        cls.git("commit", "-q", "-m", "tested aggregate candidate")
        cls.candidate = cls.git("rev-parse", "HEAD")
        cls.tree = cls.git("rev-parse", "HEAD^{tree}")
        cls.contract_blob = cls.git("rev-parse", f"HEAD:{VERIFIER.CONTRACT_PATH}")

        completed = subprocess.run(
            ["git", "-C", str(cls.root), "commit-tree", cls.tree, "-p", cls.parent],
            input="canonical aggregate squash\n",
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        cls.canonical = completed.stdout.strip()
        if cls.canonical == cls.candidate:
            raise AssertionError("fixture canonical commit must differ from the candidate")
        cls.git("update-ref", VERIFIER.MAIN_REF, cls.canonical)

        contract_bytes = contract_path.read_bytes()
        contract = json.loads(contract_bytes)
        cls.run_id = 424_242
        cls.ci = cls.build_ci_fixture(cls.canonical, cls.run_id)
        provisional = VERIFIER.Expectations(
            candidate_pr_number=VERIFIER.CANDIDATE_PR_NUMBER,
            candidate_head=cls.candidate,
            candidate_tree=cls.tree,
            canonical_commit=cls.canonical,
            canonical_parent=cls.parent,
            canonical_tree=cls.tree,
            contract_path=VERIFIER.CONTRACT_PATH,
            contract_blob=cls.contract_blob,
            contract_byte_length=len(contract_bytes),
            contract_raw_sha256=hashlib.sha256(contract_bytes).hexdigest(),
            contract_canonical_sha256=VERIFIER.canonical_sha256(contract),
            contract_truth_boundary_sha256=VERIFIER.canonical_sha256(contract["truth_boundary"]),
            main_push_run_id=cls.run_id,
            payload_canonical_sha256="0" * 64,
        )
        cls.seal = VERIFIER.build_seal(provisional, cls.ci)
        cls.expectations = dataclasses.replace(
            provisional,
            payload_canonical_sha256=cls.seal["payload_canonical_sha256"],
        )
        for relative in VERIFIER.PUBLICATION_DOC_PATHS:
            destination = cls.root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPOSITORY / relative, destination)
        provenance = cls.root / VERIFIER.PROVENANCE_DOC_PATH
        provenance.write_text(
            VERIFIER.replace_publication_record(
                provenance.read_text(encoding="utf-8"),
                VERIFIER.publication_record_markdown(cls.expectations),
            ),
            encoding="utf-8",
        )
        cls.write_seal(cls.seal)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary_directory.cleanup()

    @classmethod
    def git(cls, *arguments: str) -> str:
        completed = subprocess.run(
            ["git", "-C", str(cls.root), *arguments],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        return completed.stdout.strip()

    @classmethod
    def build_ci_fixture(cls, canonical: str, run_id: int) -> dict[str, object]:
        totals = {
            "build": 45,
            "exchange-v3-bsc-reference": 11,
            "pancakeswap-infinity-cl-bsc-reference": 11,
            "uniswap-v3-matic-reference": 10,
            "uniswap-v3-reference": 83,
            "uniswap-v4-reference": 18,
        }
        jobs = []
        for index, name in enumerate(VERIFIER.EXPECTED_JOB_NAMES):
            completed_at = "2026-09-01T00:20:00Z" if name == "build" else f"2026-09-01T00:05:{index:02d}Z"
            jobs.append(
                {
                    "job_id": 10_000 + index,
                    "name": name,
                    "status": "completed",
                    "conclusion": "success",
                    "started_at": f"2026-09-01T00:00:{index:02d}Z",
                    "completed_at": completed_at,
                    "step_counts": {
                        "total": totals[name],
                        "successful": totals[name],
                        "failed": 0,
                        "skipped": 0,
                    },
                }
            )
        steps_total = sum(totals.values())
        build = jobs[0]
        return {
            "repository": VERIFIER.EXPECTED_REPOSITORY,
            "run_id": run_id,
            "run_attempt": 1,
            "run_url": f"https://github.com/{VERIFIER.EXPECTED_REPOSITORY}/actions/runs/{run_id}",
            "workflow_name": VERIFIER.EXPECTED_WORKFLOW_NAME,
            "workflow_path": VERIFIER.EXPECTED_WORKFLOW_PATH,
            "event": "push",
            "branch": "main",
            "head_sha": canonical,
            "status": "completed",
            "conclusion": "success",
            "job_window_started_at": "2026-09-01T00:00:00Z",
            "job_window_completed_at": "2026-09-01T00:20:00Z",
            "jobs": jobs,
            "summary": {
                "jobs_total": 6,
                "jobs_successful": 6,
                "jobs_failed": 0,
                "jobs_skipped": 0,
                "steps_total": steps_total,
                "steps_successful": steps_total,
                "steps_failed": 0,
                "steps_skipped": 0,
            },
            "dedicated_all_handlers_validation_step": {
                "job_id": build["job_id"],
                "job_name": "build",
                "number": 30,
                "name": VERIFIER.EXPECTED_AGGREGATE_STEP_NAME,
                "status": "completed",
                "conclusion": "success",
                "started_at": "2026-09-01T00:02:00Z",
                "completed_at": "2026-09-01T00:03:00Z",
            },
        }

    @classmethod
    def write_seal(cls, seal: dict[str, object]) -> None:
        retained = cls.root / VERIFIER.SEAL_PATH
        retained.parent.mkdir(parents=True, exist_ok=True)
        retained.write_text(VERIFIER.render(seal), encoding="utf-8")

    def repinned_mutation(self, mutate) -> tuple[dict[str, object], object]:
        seal = copy.deepcopy(self.seal)
        mutate(seal["payload"])
        seal["payload_canonical_sha256"] = VERIFIER.canonical_sha256(seal["payload"])
        expectations = dataclasses.replace(
            self.expectations,
            payload_canonical_sha256=seal["payload_canonical_sha256"],
        )
        return seal, expectations

    def assert_mutation_rejected(self, mutate, pattern: str) -> None:
        seal, expectations = self.repinned_mutation(mutate)
        with self.assertRaisesRegex(VERIFIER.VerificationError, pattern):
            VERIFIER.verify_seal(self.root, seal, expectations)

    def test_00_production_configuration_is_atomic_and_fail_closed(self) -> None:
        configured = (
            VERIFIER.EXPECTED_CANONICAL_AGGREGATE_COMMIT,
            VERIFIER.EXPECTED_CANONICAL_AGGREGATE_PARENT,
            VERIFIER.EXPECTED_CANONICAL_MAIN_PUSH_RUN_ID,
            VERIFIER.EXPECTED_PAYLOAD_CANONICAL_SHA256,
        )
        configured_count = sum(value is not None for value in configured)
        self.assertIn(configured_count, (0, len(configured)))
        if configured_count == 0:
            with self.assertRaisesRegex(
                VERIFIER.VerificationError,
                "production facts are not configured",
            ):
                VERIFIER.production_expectations()
        else:
            VERIFIER.production_expectations()

    def test_00a_verifier_docstring_has_no_stale_preparation_claim(self) -> None:
        source = VERIFIER_PATH.read_text(encoding="utf-8")
        for stale in (
            "values marked ``None``",
            "must be filled from the real PR #100",
            "intentional fail-closed preparation state",
        ):
            with self.subTest(stale=stale):
                self.assertNotIn(stale, source)
        self.assertIn(
            "production pins below were captured from canonical PR #100",
            source,
        )
        self.assertIn("any unset pin prevents a", source)

    def test_01_exact_synthetic_seal_passes(self) -> None:
        self.write_seal(self.seal)
        self.assertEqual(
            VERIFIER.verify(self.root, VERIFIER.SEAL_PATH, self.expectations),
            self.seal,
        )

    def test_01a_publication_docs_match_the_configured_provenance(self) -> None:
        VERIFIER.verify_publication_docs(self.root, self.expectations)

    def test_01b_stale_present_tense_publication_wording_is_rejected(self) -> None:
        eligibility = self.root / "uniswap-v3/all-handlers/v1/docs/eligibility.md"
        original = eligibility.read_text(encoding="utf-8")
        eligibility.write_text(
            original + "\nIt is not presently a canonical aggregate publication.\n",
            encoding="utf-8",
        )
        try:
            with self.assertRaisesRegex(
                VERIFIER.VerificationError,
                "stale present-tense publication wording",
            ):
                VERIFIER.verify_publication_docs(self.root, self.expectations)
        finally:
            eligibility.write_text(original, encoding="utf-8")

    def test_01c_unresolved_provenance_placeholder_is_rejected(self) -> None:
        provenance = self.root / VERIFIER.PROVENANCE_DOC_PATH
        original = provenance.read_text(encoding="utf-8")
        provenance.write_text(
            original.replace(
                self.canonical,
                "{{EXPECTED_CANONICAL_AGGREGATE_COMMIT}}",
                1,
            ),
            encoding="utf-8",
        )
        try:
            with self.assertRaisesRegex(
                VERIFIER.VerificationError,
                "unresolved production provenance placeholder",
            ):
                VERIFIER.verify_publication_docs(self.root, self.expectations)
        finally:
            provenance.write_text(original, encoding="utf-8")

    def test_01d_provenance_run_link_drift_is_rejected(self) -> None:
        provenance = self.root / VERIFIER.PROVENANCE_DOC_PATH
        original = provenance.read_text(encoding="utf-8")
        provenance.write_text(
            original.replace(
                f"actions/runs/{self.run_id}",
                f"actions/runs/{self.run_id + 1}",
                1,
            ),
            encoding="utf-8",
        )
        try:
            with self.assertRaisesRegex(
                VERIFIER.VerificationError,
                "provenance record differs",
            ):
                VERIFIER.verify_publication_docs(self.root, self.expectations)
        finally:
            provenance.write_text(original, encoding="utf-8")

    def test_02_duplicate_json_key_is_rejected(self) -> None:
        retained = self.root / VERIFIER.SEAL_PATH
        raw = VERIFIER.render(self.seal).replace(
            '  "format_version": 1,',
            '  "format_version": 1,\n  "format_version": 1,',
            1,
        )
        retained.write_text(raw, encoding="utf-8")
        try:
            with self.assertRaisesRegex(VERIFIER.VerificationError, "duplicate JSON key"):
                VERIFIER.verify(self.root, VERIFIER.SEAL_PATH, self.expectations)
        finally:
            self.write_seal(self.seal)

    def test_03_publication_seal_path_escape_is_rejected(self) -> None:
        with self.assertRaisesRegex(VERIFIER.VerificationError, "escapes the repository"):
            VERIFIER.verify(self.root, Path("../publication-seal.json"), self.expectations)

    def test_04_sealed_contract_path_escape_is_rejected(self) -> None:
        self.assert_mutation_rejected(
            lambda payload: payload["sealed_contract"].__setitem__("path", "../contract.json"),
            "sealed contract identity differs|escapes the repository",
        )

    def test_05_candidate_head_drift_is_rejected(self) -> None:
        self.assert_mutation_rejected(
            lambda payload: payload["candidate_anchor"].__setitem__("head", self.parent),
            "candidate anchor differs",
        )

    def test_06_canonical_commit_drift_is_rejected(self) -> None:
        self.assert_mutation_rejected(
            lambda payload: payload["canonical_aggregate"].__setitem__("squash_commit", self.candidate),
            "canonical aggregate anchor differs",
        )

    def test_07_canonical_parent_drift_is_rejected(self) -> None:
        self.assert_mutation_rejected(
            lambda payload: payload["canonical_aggregate"].__setitem__("parent", self.candidate),
            "canonical aggregate anchor differs",
        )

    def test_08_canonical_tree_drift_is_rejected(self) -> None:
        self.assert_mutation_rejected(
            lambda payload: payload["canonical_aggregate"].__setitem__("tree", self.parent),
            "canonical aggregate anchor differs|byte-identical",
        )

    def test_09_contract_metadata_drift_is_rejected(self) -> None:
        self.assert_mutation_rejected(
            lambda payload: payload["sealed_contract"].__setitem__("raw_sha256", "0" * 64),
            "sealed contract identity differs",
        )

    def test_10_working_contract_byte_drift_is_rejected(self) -> None:
        retained = self.root / VERIFIER.CONTRACT_PATH
        original = retained.read_bytes()
        retained.write_bytes(original + b" ")
        try:
            with self.assertRaisesRegex(VERIFIER.VerificationError, "byte length differs"):
                VERIFIER.verify_seal(self.root, self.seal, self.expectations)
        finally:
            retained.write_bytes(original)

    def test_11_canonical_commit_must_remain_on_main(self) -> None:
        self.git("update-ref", VERIFIER.MAIN_REF, self.parent)
        try:
            with self.assertRaisesRegex(VERIFIER.VerificationError, "not reachable"):
                VERIFIER.verify_seal(self.root, self.seal, self.expectations)
        finally:
            self.git("update-ref", VERIFIER.MAIN_REF, self.canonical)

    def test_12_ci_run_id_drift_is_rejected(self) -> None:
        self.assert_mutation_rejected(
            lambda payload: payload["canonical_main_push_ci"].__setitem__("run_id", self.run_id + 1),
            "run ID differs|run URL differs",
        )

    def test_13_ci_head_drift_is_rejected(self) -> None:
        self.assert_mutation_rejected(
            lambda payload: payload["canonical_main_push_ci"].__setitem__("head_sha", self.parent),
            "CI head differs",
        )

    def test_14_ci_event_branch_and_result_drift_are_rejected(self) -> None:
        for key, value, pattern in (
            ("event", "pull_request", "event must be push"),
            ("branch", "feature", "branch must be main"),
            ("conclusion", "failure", "not completed successfully"),
            ("workflow_path", ".github/workflows/other.yaml", "workflow path differs"),
        ):
            with self.subTest(key=key):
                self.assert_mutation_rejected(
                    lambda payload, key=key, value=value: payload["canonical_main_push_ci"].__setitem__(key, value),
                    pattern,
                )

    def test_15_missing_job_is_rejected(self) -> None:
        self.assert_mutation_rejected(
            lambda payload: payload["canonical_main_push_ci"]["jobs"].pop(),
            "bind all six jobs",
        )

    def test_16_duplicate_job_id_is_rejected(self) -> None:
        def mutate(payload) -> None:
            jobs = payload["canonical_main_push_ci"]["jobs"]
            jobs[1]["job_id"] = jobs[0]["job_id"]

        self.assert_mutation_rejected(mutate, "duplicate job ID")

    def test_17_job_name_drift_is_rejected(self) -> None:
        self.assert_mutation_rejected(
            lambda payload: payload["canonical_main_push_ci"]["jobs"][1].__setitem__("name", "unexpected-job"),
            "deterministic name order|job names differ",
        )

    def test_18_failed_or_skipped_step_is_rejected(self) -> None:
        def mutate(payload) -> None:
            ci = payload["canonical_main_push_ci"]
            counts = ci["jobs"][0]["step_counts"]
            counts["successful"] -= 1
            counts["skipped"] = 1
            ci["summary"]["steps_successful"] -= 1
            ci["summary"]["steps_skipped"] = 1

        self.assert_mutation_rejected(mutate, "failed or skipped steps")

    def test_19_invalid_and_inverted_timestamps_are_rejected(self) -> None:
        self.assert_mutation_rejected(
            lambda payload: payload["canonical_main_push_ci"]["jobs"][0].__setitem__("started_at", "2026-02-30T00:00:00Z"),
            "not a valid timestamp",
        )
        self.assert_mutation_rejected(
            lambda payload: payload["canonical_main_push_ci"]["jobs"][0].__setitem__("started_at", "2026-09-01T00:21:00Z"),
            "inverted window",
        )

    def test_20_aggregate_job_window_drift_is_rejected(self) -> None:
        self.assert_mutation_rejected(
            lambda payload: payload["canonical_main_push_ci"].__setitem__("job_window_completed_at", "2026-09-01T00:19:59Z"),
            "not the latest job completion",
        )

    def test_21_dedicated_step_identity_and_result_drift_are_rejected(self) -> None:
        self.assert_mutation_rejected(
            lambda payload: payload["canonical_main_push_ci"]["dedicated_all_handlers_validation_step"].__setitem__("name", "wrong aggregate step"),
            "step identity differs",
        )
        self.assert_mutation_rejected(
            lambda payload: payload["canonical_main_push_ci"]["dedicated_all_handlers_validation_step"].__setitem__("conclusion", "failure"),
            "did not succeed",
        )

    def test_22_semantic_or_delivery_promotion_is_rejected(self) -> None:
        self.assert_mutation_rejected(
            lambda payload: payload["publication_truth"]["unchanged_false_gates"].__setitem__("backfill_ready", True),
            "publication truth differs",
        )

    def test_23_issue_checkbox_or_closure_promotion_is_rejected(self) -> None:
        self.assert_mutation_rejected(
            lambda payload: payload["publication_truth"]["issue_effect"]["38"]["checkboxes_completed_by_this_seal"].append(4),
            "publication truth differs",
        )
        self.assert_mutation_rejected(
            lambda payload: payload["publication_truth"]["issue_effect"]["37"].__setitem__("issue_closed", True),
            "publication truth differs",
        )

    def test_24_third_order_seal_is_rejected(self) -> None:
        self.assert_mutation_rejected(
            lambda payload: payload["publication_truth"].__setitem__("third_order_publication_seal_required", True),
            "publication truth differs",
        )

    def test_25_payload_digest_drift_is_rejected(self) -> None:
        mutated = copy.deepcopy(self.seal)
        mutated["payload_canonical_sha256"] = "f" * 64
        with self.assertRaisesRegex(VERIFIER.VerificationError, "does not match its payload"):
            VERIFIER.verify_seal(self.root, mutated, self.expectations)


if __name__ == "__main__":
    unittest.main()
