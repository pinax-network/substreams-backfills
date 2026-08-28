from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[2]
VERIFIER = REPOSITORY / "scripts/verify-pancakeswap-infinity-cl-bsc-target.py"
LOCK_PATH = Path("docs/provenance/pancakeswap-infinity-cl-bsc-target.json")
PROFILE_PATH = Path("pancakeswap-infinity-cl-bsc/layout-profile-v1.json")
BINDING_NAME = "QmVjXU7yQNyyLphPGqoz8iBzqu5YXphooFJn15JqZ6ZMFz.yaml"


class PancakeInfinityClBscTargetTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        shutil.copytree(
            REPOSITORY / "pancakeswap-infinity-cl-bsc",
            self.root / "pancakeswap-infinity-cl-bsc",
        )
        for deployment in (
            "QmS1ehFzXTD9eA1f1EgjZvdyAj2EHtVNMrEN91H3pLuHMy",
            "Qmbsc6XQWbiv4DfLVfaNciScqYLyDWUYjWzrFBbzzmRsMB",
        ):
            destination = self.root / "uniswap-v4/artifacts/deployment" / deployment
            destination.mkdir(parents=True)
            shutil.copy2(
                REPOSITORY / "uniswap-v4/artifacts/deployment" / deployment / "schema.graphql",
                destination / "schema.graphql",
            )
        (self.root / LOCK_PATH.parent).mkdir(parents=True)
        shutil.copy2(REPOSITORY / LOCK_PATH, self.root / LOCK_PATH)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def verify(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(VERIFIER), "--root", str(self.root)],
            check=False,
            capture_output=True,
            text=True,
        )

    def load_lock(self) -> dict:
        return json.loads((self.root / LOCK_PATH).read_text())

    def write_lock(self, lock: dict) -> None:
        (self.root / LOCK_PATH).write_text(json.dumps(lock, indent=2) + "\n")

    def test_exact_baseline_passes(self) -> None:
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_artifact_byte_drift_is_rejected(self) -> None:
        schema = self.root / "pancakeswap-infinity-cl-bsc/reference/schema.graphql"
        schema.write_text(schema.read_text().replace("type Bundle", "type BundleDrift", 1))
        self.assertNotEqual(self.verify().returncode, 0)

    def test_manifest_semantic_drift_is_rejected_after_digest_relock(self) -> None:
        manifest = self.root / "pancakeswap-infinity-cl-bsc/reference/deployment.yaml"
        manifest.write_text(manifest.read_text().replace("network: bsc", "network: mainnet", 1))
        payload = manifest.read_bytes()
        lock = self.load_lock()
        record = next(item for item in lock["artifact_lock"] if item["role"] == "deployment")
        record["bytes"] = len(payload)
        record["sha256"] = hashlib.sha256(payload).hexdigest()
        self.write_lock(lock)
        self.assertNotEqual(self.verify().returncode, 0)

    def test_profile_fee_policy_drift_is_rejected_after_provenance_relock(self) -> None:
        profile_path = self.root / PROFILE_PATH
        profile = json.loads(profile_path.read_text())
        profile["fee_and_protocol"]["swap_event_fee"] = "used_as_effective_fee"
        profile_path.write_text(json.dumps(profile, indent=2) + "\n")
        payload = profile_path.read_bytes()
        lock = self.load_lock()
        lock["layout_profile"]["bytes"] = len(payload)
        lock["layout_profile"]["sha256"] = hashlib.sha256(payload).hexdigest()
        self.write_lock(lock)
        self.assertNotEqual(self.verify().returncode, 0)

    def test_imported_v4_prior_art_schema_drift_is_rejected(self) -> None:
        schema = self.root / (
            "uniswap-v4/artifacts/deployment/"
            "QmS1ehFzXTD9eA1f1EgjZvdyAj2EHtVNMrEN91H3pLuHMy/schema.graphql"
        )
        schema.write_text(schema.read_text().replace("type Position ", "type PositionDrift ", 1))
        self.assertNotEqual(self.verify().returncode, 0)

    def test_runtime_parity_claim_is_rejected(self) -> None:
        lock = self.load_lock()
        lock["runtime_parity"] = True
        lock["implementation_status"] = "runtime_complete"
        self.write_lock(lock)
        self.assertNotEqual(self.verify().returncode, 0)

    def test_exact_source_status_drift_is_rejected(self) -> None:
        lock = self.load_lock()
        lock["exact_source"]["status"] = "candidate"
        self.write_lock(lock)
        self.assertNotEqual(self.verify().returncode, 0)

    def test_historical_ci_cannot_be_conflated_with_reproduction_toolchain(self) -> None:
        lock = self.load_lock()
        lock["exact_source"]["historical_source_ci"]["node"] = "24.13.1"
        lock["exact_source"]["historical_source_ci"]["dependency_install"] = (
            "npm ci --legacy-peer-deps --ignore-scripts"
        )
        self.write_lock(lock)
        self.assertNotEqual(self.verify().returncode, 0)

    def test_m4_milestone_regression_is_rejected(self) -> None:
        binding = self.root / "pancakeswap-infinity-cl-bsc" / BINDING_NAME
        binding.write_text(binding.read_text().replace("milestone: M5", "milestone: M4"))
        self.assertNotEqual(self.verify().returncode, 0)


if __name__ == "__main__":
    unittest.main()
