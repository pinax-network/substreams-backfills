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
VERIFIER = REPOSITORY / "scripts/verify-exchange-v3-bsc-target.py"
LOCK_PATH = Path("provenance/exchange-v3-bsc-target.json")


class ExchangeV3BscTargetTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        shutil.copytree(REPOSITORY / "exchange-v3-bsc", self.root / "exchange-v3-bsc")
        (self.root / "uniswap-v3/source").mkdir(parents=True)
        shutil.copy2(
            REPOSITORY / "uniswap-v3/source/schema.graphql",
            self.root / "uniswap-v3/source/schema.graphql",
        )
        (self.root / "provenance").mkdir()
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

    def relock_artifact(self, role: str) -> None:
        lock = self.load_lock()
        record = next(item for item in lock["artifact_lock"] if item["role"] == role)
        payload = (self.root / record["vendored_path"]).read_bytes()
        record["source_bytes"] = len(payload)
        record["source_sha256"] = hashlib.sha256(payload).hexdigest()
        self.write_lock(lock)

    def test_exact_baseline_passes(self) -> None:
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_artifact_byte_drift_is_rejected(self) -> None:
        schema = self.root / "exchange-v3-bsc/reference/schema.graphql"
        schema.write_text(schema.read_text().replace("type Bundle", "type BundleDrift", 1))
        self.assertNotEqual(self.verify().returncode, 0)

    def test_semantic_manifest_drift_is_rejected_even_if_relocked(self) -> None:
        manifest = self.root / "exchange-v3-bsc/reference/deployment.yaml"
        manifest.write_text(manifest.read_text().replace("network: bsc", "network: mainnet", 1))
        self.relock_artifact("deployment")
        self.assertNotEqual(self.verify().returncode, 0)

    def test_uniswap_schema_reference_drift_is_rejected(self) -> None:
        schema = self.root / "uniswap-v3/source/schema.graphql"
        schema.write_text(schema.read_text().replace("type Position ", "type PositionDrift ", 1))
        self.assertNotEqual(self.verify().returncode, 0)

    def test_exact_source_status_drift_is_rejected(self) -> None:
        lock = self.load_lock()
        lock["exact_source"]["status"] = "candidate"
        self.write_lock(lock)
        self.assertNotEqual(self.verify().returncode, 0)

    def test_exact_source_mapping_output_drift_is_rejected(self) -> None:
        lock = self.load_lock()
        lock["exact_source"]["build"]["pool_wasm_sha256"] = "0" * 64
        self.write_lock(lock)
        self.assertNotEqual(self.verify().returncode, 0)

    def test_install_transport_override_drift_is_rejected(self) -> None:
        lock = self.load_lock()
        lock["exact_source"]["install_transport_override"]["replacement"] = "unreviewed"
        self.write_lock(lock)
        self.assertNotEqual(self.verify().returncode, 0)


if __name__ == "__main__":
    unittest.main()
