from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[2]
VERIFIER = REPOSITORY / "scripts/verify-aerodrome-slipstream-base-target.py"
LOCK_PATH = Path("docs/provenance/aerodrome-slipstream-base-target.json")
PROFILE_PATH = Path("aerodrome-slipstream-base/layout-profile-v1.json")
BINDING_NAME = "QmasYjypV6nTLp4iNH4Vjf7fksRNxAkAskqDdKf2DCsQkV.yaml"
QMA8_SCHEMA_PATH = Path(
    "uniswap-v3/graft-ancestry/v1/artifacts/"
    "Qma8a81T9XoX5Pbkrk8J3kxMhWdXJzFSYZge1wGi3QZBru"
)


class AerodromeSlipstreamBaseTargetTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        shutil.copytree(
            REPOSITORY / "aerodrome-slipstream-base",
            self.root / "aerodrome-slipstream-base",
        )
        qma8_destination = self.root / QMA8_SCHEMA_PATH
        qma8_destination.parent.mkdir(parents=True)
        shutil.copy2(REPOSITORY / QMA8_SCHEMA_PATH, qma8_destination)
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

    def load_json(self, relative_path: Path) -> dict:
        return json.loads((self.root / relative_path).read_text())

    def write_json(self, relative_path: Path, value: dict) -> None:
        (self.root / relative_path).write_text(json.dumps(value, indent=2) + "\n")

    def test_exact_baseline_passes(self) -> None:
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_artifact_byte_drift_is_rejected(self) -> None:
        mapping = self.root / "aerodrome-slipstream-base/reference/mappings/Pool.wasm"
        payload = bytearray(mapping.read_bytes())
        payload[-1] ^= 1
        mapping.write_bytes(payload)
        self.assertNotEqual(self.verify().returncode, 0)

    def test_manifest_target_drift_is_rejected(self) -> None:
        manifest = self.root / "aerodrome-slipstream-base/reference/deployment.yaml"
        manifest.write_text(
            manifest.read_text().replace(
                "0x5e7bb104d84c7cb9b682aac2f3d509f5f406809a",
                "0x0000000000000000000000000000000000000000",
                1,
            )
        )
        self.assertNotEqual(self.verify().returncode, 0)

    def test_retained_qma8_schema_drift_is_rejected(self) -> None:
        schema = self.root / QMA8_SCHEMA_PATH
        schema.write_text(schema.read_text().replace("type Bundle", "type BundleDrift", 1))
        self.assertNotEqual(self.verify().returncode, 0)

    def test_binding_eligibility_promotion_is_rejected(self) -> None:
        binding = self.root / "aerodrome-slipstream-base" / BINDING_NAME
        binding.write_text(
            binding.read_text().replace("decision: indeterminate", "decision: eligible", 1)
        )
        self.assertNotEqual(self.verify().returncode, 0)

    def test_binding_runtime_gate_promotion_is_rejected(self) -> None:
        binding = self.root / "aerodrome-slipstream-base" / BINDING_NAME
        binding.write_text(
            binding.read_text().replace("runtime_complete: false", "runtime_complete: true", 1)
        )
        self.assertNotEqual(self.verify().returncode, 0)

    def test_gateway_query_fees_cannot_be_mislabeled_as_generic_grt(self) -> None:
        binding = self.root / "aerodrome-slipstream-base" / BINDING_NAME
        binding.write_text(
            binding.read_text().replace("query_fees_grt_24h", "grt_24h", 1)
        )
        self.assertNotEqual(self.verify().returncode, 0)

    def test_fabricated_source_revision_and_reproduction_are_rejected(self) -> None:
        lock = self.load_json(LOCK_PATH)
        lock["source_provenance"]["exact_repository"] = "https://example.invalid/fork"
        lock["source_provenance"]["exact_commit"] = "0" * 40
        lock["source_provenance"]["exact_tree"] = "1" * 40
        lock["source_provenance"]["exact_toolchain"] = {"node": "invented"}
        lock["source_provenance"]["byte_reproduction"] = True
        lock["source_provenance"]["reproduction_attempted"] = True
        self.write_json(LOCK_PATH, lock)
        self.assertNotEqual(self.verify().returncode, 0)

    def test_source_search_scope_drift_is_rejected(self) -> None:
        lock = self.load_json(LOCK_PATH)
        lock["source_provenance"]["search_scope"]["result"] = "exact_source_found"
        self.write_json(LOCK_PATH, lock)
        self.assertNotEqual(self.verify().returncode, 0)

    def test_profile_source_and_runtime_promotion_is_rejected(self) -> None:
        profile = self.load_json(PROFILE_PATH)
        profile["source_provenance"]["status"] = "reproducible"
        profile["source_provenance"]["exact_commit"] = "0" * 40
        profile["source_provenance"]["byte_reproduction"] = True
        profile["truth_gates"]["source_reproducible"] = True
        profile["truth_gates"]["runtime_complete"] = True
        self.write_json(PROFILE_PATH, profile)
        self.assertNotEqual(self.verify().returncode, 0)

    def test_incomplete_truth_gate_inventory_is_rejected(self) -> None:
        lock = self.load_json(LOCK_PATH)
        del lock["truth_gates"]["poi_parity"]
        self.write_json(LOCK_PATH, lock)
        self.assertNotEqual(self.verify().returncode, 0)

    def test_unrecognized_provenance_promotion_is_rejected(self) -> None:
        lock = self.load_json(LOCK_PATH)
        lock["runtime_ready"] = True
        self.write_json(LOCK_PATH, lock)
        self.assertNotEqual(self.verify().returncode, 0)

    def test_wrong_protocol_identity_is_rejected(self) -> None:
        lock = self.load_json(LOCK_PATH)
        lock["protocol"] = "uniswap-v3"
        lock["protocol_identity"]["classification"] = "canonical_uniswap_v3"
        self.write_json(LOCK_PATH, lock)
        self.assertNotEqual(self.verify().returncode, 0)

    def test_artifact_path_escape_is_rejected(self) -> None:
        lock = self.load_json(LOCK_PATH)
        record = next(item for item in lock["artifact_lock"] if item["role"] == "schema")
        record["path"] = "../../schema.graphql"
        self.write_json(LOCK_PATH, lock)
        self.assertNotEqual(self.verify().returncode, 0)

    def test_m7_milestone_drift_is_rejected(self) -> None:
        binding = self.root / "aerodrome-slipstream-base" / BINDING_NAME
        binding.write_text(binding.read_text().replace("milestone: M7", "milestone: M8"))
        self.assertNotEqual(self.verify().returncode, 0)


if __name__ == "__main__":
    unittest.main()
