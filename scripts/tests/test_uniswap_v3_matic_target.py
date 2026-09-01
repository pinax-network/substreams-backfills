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
VERIFIER = REPOSITORY / "scripts/verify-uniswap-v3-matic-target.py"
LOCK_PATH = Path("docs/provenance/uniswap-v3-matic-target.json")
PROFILE_PATH = Path("uniswap-v3-matic/layout-profile-v1.json")
BINDING_NAME = "QmWqwrVtcTzZzbTLGLgiRSQzbZ7MTH53VwqK4AxXVmf7n3.yaml"
QMA8_REFERENCE_FILES = [
    Path(
        "uniswap-v3/graft-ancestry/v1/artifacts/"
        "Qma8a81T9XoX5Pbkrk8J3kxMhWdXJzFSYZge1wGi3QZBru"
    ),
    Path("docs/provenance/uniswap-v3-qma8a81t-parity.json"),
    Path("docs/provenance/uniswap-v3-qma8a81t-parity-files.json"),
    Path("uniswap-v3/source/schema.graphql"),
    Path("uniswap-v3/source/substreams.yaml"),
    Path("uniswap-v3/graft-ancestry/v2/contract.json"),
    Path("uniswap-v3/graft-ancestry/v2/writer-compatibility.json"),
    Path("uniswap-v3/segment-writer-matrix/v1/contract.json"),
    Path("uniswap-v3/execution-order/v1/contract.json"),
    Path("uniswap-v3/writer-runtime/contract-v1.json"),
    Path("uniswap-v3/writer-runtime/segment-profiles-v1.json"),
    Path("uniswap-v3/chain-config/configs/mainnet-v1.json"),
]


class UniswapV3MaticTargetTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        shutil.copytree(REPOSITORY / "uniswap-v3-matic", self.root / "uniswap-v3-matic")
        for relative_path in QMA8_REFERENCE_FILES:
            destination = self.root / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPOSITORY / relative_path, destination)
        (self.root / LOCK_PATH.parent).mkdir(parents=True, exist_ok=True)
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

    def load_profile(self) -> dict:
        return json.loads((self.root / PROFILE_PATH).read_text())

    def write_profile(self, profile: dict) -> None:
        (self.root / PROFILE_PATH).write_text(json.dumps(profile, indent=2) + "\n")

    def relock_profile(self) -> None:
        payload = (self.root / PROFILE_PATH).read_bytes()
        lock = self.load_lock()
        lock["layout_profile"]["bytes"] = len(payload)
        lock["layout_profile"]["sha256"] = hashlib.sha256(payload).hexdigest()
        self.write_lock(lock)

    def relock_qma8_reference(self, role: str) -> None:
        lock = self.load_lock()
        reference = lock["qma8_reference"]
        if role == "deployed_schema":
            record = reference["deployed_schema"]
        else:
            records = reference["upstream_source"]["records"] + reference["m3_contract_closure"]
            record = next(item for item in records if item["role"] == role)
        payload = (self.root / record["path"]).read_bytes()
        record["bytes"] = len(payload)
        record["sha256"] = hashlib.sha256(payload).hexdigest()
        self.write_lock(lock)

    def relock_artifact(self, role: str) -> None:
        lock = self.load_lock()
        record = next(item for item in lock["artifact_lock"] if item["role"] == role)
        payload = (self.root / record["vendored_path"]).read_bytes()
        record["source_bytes"] = len(payload)
        record["vendored_bytes"] = len(payload)
        digest = hashlib.sha256(payload).hexdigest()
        record["source_sha256"] = digest
        record["vendored_sha256"] = digest
        self.write_lock(lock)

    def test_exact_baseline_passes(self) -> None:
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_artifact_byte_drift_is_rejected(self) -> None:
        schema = self.root / "uniswap-v3-matic/reference/schema.graphql"
        schema.write_text(schema.read_text().replace("type Bundle", "type BundleDrift", 1))
        self.assertNotEqual(self.verify().returncode, 0)

    def test_market_snapshot_contract_drift_is_rejected(self) -> None:
        binding = self.root / "uniswap-v3-matic" / BINDING_NAME
        binding.write_text(
            binding.read_text().replace("chain: matic", 'chain: matic\ngrt_24h: "471.970"', 1)
        )
        self.assertNotEqual(self.verify().returncode, 0)

    def test_semantic_manifest_drift_is_rejected_even_if_relocked(self) -> None:
        manifest = self.root / "uniswap-v3-matic/reference/deployment.yaml"
        manifest.write_text(manifest.read_text().replace("network: matic", "network: mainnet", 1))
        self.relock_artifact("deployment")
        self.assertNotEqual(self.verify().returncode, 0)

    def test_retained_qma8_deployed_mutability_drift_is_rejected_even_if_relocked(self) -> None:
        schema = self.root / QMA8_REFERENCE_FILES[0]
        schema.write_text(
            schema.read_text().replace(
                "type Transaction @entity {",
                "type Transaction @entity(immutable: true) {",
                1,
            )
        )
        self.relock_qma8_reference("deployed_schema")
        self.assertNotEqual(self.verify().returncode, 0)

    def test_qma8_upstream_schema_drift_is_rejected_even_if_relocked(self) -> None:
        schema = self.root / "uniswap-v3/source/schema.graphql"
        schema.write_text(schema.read_text().replace("type Position ", "type PositionDrift ", 1))
        self.relock_qma8_reference("imported_schema")
        self.assertNotEqual(self.verify().returncode, 0)

    def test_m3_contract_promotion_is_rejected_even_if_relocked(self) -> None:
        contract_path = self.root / "uniswap-v3/writer-runtime/contract-v1.json"
        contract = json.loads(contract_path.read_text())
        contract["truth_boundary"]["production_ready"] = True
        contract_path.write_text(json.dumps(contract, indent=2) + "\n")
        self.relock_qma8_reference("writer_runtime")
        self.assertNotEqual(self.verify().returncode, 0)

    def test_bidirectional_nullability_gap_drift_is_rejected_after_profile_relock(self) -> None:
        profile = self.load_profile()
        profile["qma8_static_gap"]["field_differences"]["Tick"]["type_differences"][
            "poolAddress"
        ]["qma8_non_null"] = True
        self.write_profile(profile)
        self.relock_profile()
        self.assertNotEqual(self.verify().returncode, 0)

    def test_collect_behavior_drift_is_rejected_after_profile_relock(self) -> None:
        profile = self.load_profile()
        profile["mapping_behavior"]["collect"]["pool_and_token_tvl_delta"] = "none"
        self.write_profile(profile)
        self.relock_profile()
        self.assertNotEqual(self.verify().returncode, 0)

    def test_uncertified_reuse_promotion_is_rejected_after_profile_relock(self) -> None:
        profile = self.load_profile()
        profile["reuse_assessment"]["certified_unchanged"] = ["store_tokens"]
        profile["reuse_assessment"]["reuse_certified"] = True
        self.write_profile(profile)
        self.relock_profile()
        self.assertNotEqual(self.verify().returncode, 0)

    def test_runtime_gate_promotion_is_rejected_after_profile_relock(self) -> None:
        profile = self.load_profile()
        profile["truth_boundary"]["runtime_parity"] = True
        profile["runtime_parity"] = True
        self.write_profile(profile)
        self.relock_profile()
        self.assertNotEqual(self.verify().returncode, 0)

    def test_provenance_gate_promotion_is_rejected(self) -> None:
        lock = self.load_lock()
        lock["truth_boundary"]["physical_profile_complete"] = True
        self.write_lock(lock)
        self.assertNotEqual(self.verify().returncode, 0)

    def test_behavior_source_closure_drift_is_rejected(self) -> None:
        lock = self.load_lock()
        lock["exact_source"]["behavior_source_files"][0]["sha256"] = "0" * 64
        self.write_lock(lock)
        self.assertNotEqual(self.verify().returncode, 0)

    def test_exact_source_status_drift_is_rejected(self) -> None:
        lock = self.load_lock()
        lock["exact_source"]["status"] = "candidate"
        self.write_lock(lock)
        self.assertNotEqual(self.verify().returncode, 0)

    def test_exact_source_output_drift_is_rejected(self) -> None:
        lock = self.load_lock()
        lock["exact_source"]["build"]["factory_wasm_sha256"] = "0" * 64
        self.write_lock(lock)
        self.assertNotEqual(self.verify().returncode, 0)


if __name__ == "__main__":
    unittest.main()
