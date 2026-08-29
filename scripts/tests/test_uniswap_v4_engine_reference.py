from __future__ import annotations

import contextlib
import copy
import hashlib
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[2]
VERIFIER = REPOSITORY / "scripts/verify-uniswap-v4-engine-reference.py"

SPEC = importlib.util.spec_from_file_location(
    "verify_uniswap_v4_engine_reference",
    VERIFIER,
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class UniswapV4EngineReferenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        capsule = self.root / MODULE.CAPSULE_DIRECTORY
        capsule.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(REPOSITORY / MODULE.CAPSULE_DIRECTORY, capsule)
        for relative in (
            MODULE.PACKAGE_PATH,
            MODULE.PACKAGE_CONTRACT_PATH,
            MODULE.IMPORT_PROVENANCE_PATH,
            MODULE.IMPORT_INVENTORY_PATH,
        ):
            destination = self.root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPOSITORY / relative, destination)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @property
    def capsule(self) -> Path:
        return self.root / MODULE.CAPSULE_DIRECTORY

    @property
    def closure_path(self) -> Path:
        return self.root / MODULE.CLOSURE_PATH

    def read_json(self, relative: Path) -> dict:
        return json.loads((self.root / relative).read_text(encoding="utf-8"))

    def write_json(self, relative: Path, value: dict) -> None:
        (self.root / relative).write_text(
            json.dumps(value, indent=2) + "\n",
            encoding="utf-8",
        )

    def read_fixture(self, name: str) -> dict:
        return self.read_json(MODULE.CAPSULE_DIRECTORY / name)

    def write_fixture(self, name: str, value: dict) -> None:
        self.write_json(MODULE.CAPSULE_DIRECTORY / name, value)

    @contextlib.contextmanager
    def accept_modified_retained_bytes(self, *names: str):
        """Move byte locks so a test reaches semantic cross-reference checks."""

        originals = {
            name: copy.deepcopy(MODULE.EXPECTED_FILE_LOCKS[name]) for name in names
        }
        closure = self.read_json(MODULE.CLOSURE_PATH)
        for name in names:
            payload = (self.capsule / name).read_bytes()
            observed_bytes = len(payload)
            observed_sha = hashlib.sha256(payload).hexdigest()
            MODULE.EXPECTED_FILE_LOCKS[name]["bytes"] = observed_bytes
            MODULE.EXPECTED_FILE_LOCKS[name]["sha256"] = observed_sha
            record = next(
                item for item in closure["files"] if item["local_path"] == name
            )
            record["bytes"] = observed_bytes
            record["sha256"] = observed_sha
            if name == "certificate.json":
                closure["selected_reference"]["retained_manifest"]["sha256"] = (
                    observed_sha
                )
        self.write_json(MODULE.CLOSURE_PATH, closure)
        try:
            yield
        finally:
            for name, original in originals.items():
                MODULE.EXPECTED_FILE_LOCKS[name] = original

    def update_certificate_artifact_sha(self, artifact: str, fixture: str) -> None:
        payload = (self.capsule / fixture).read_bytes()
        certificate = self.read_fixture("certificate.json")
        certificate["artifacts"][artifact]["sha256"] = hashlib.sha256(payload).hexdigest()
        self.write_fixture("certificate.json", certificate)

    def test_exact_reference_passes(self) -> None:
        MODULE.verify(self.root)

    def test_tampered_tagged_fixture_bytes_are_rejected(self) -> None:
        path = self.capsule / "benchmark.json"
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaisesRegex(MODULE.VerificationError, "(?:byte length|SHA-256) drift"):
            MODULE.verify(self.root)

    def test_unlisted_capsule_file_is_rejected(self) -> None:
        (self.capsule / "execution-complete.json").write_text(
            '{"reproduction_complete":true}\n',
            encoding="utf-8",
        )
        with self.assertRaisesRegex(MODULE.VerificationError, "file inventory drift"):
            MODULE.verify(self.root)

    def test_symlinked_retained_fixture_is_rejected(self) -> None:
        benchmark = self.capsule / "benchmark.json"
        benchmark.unlink()
        benchmark.symlink_to(self.capsule / "certificate.json")
        with self.assertRaisesRegex(MODULE.VerificationError, "symlink"):
            MODULE.verify(self.root)

    def test_duplicate_closure_key_is_rejected(self) -> None:
        raw = self.closure_path.read_text(encoding="utf-8")
        self.closure_path.write_text(
            raw.replace("{\n", '{\n  "format_version": 1,\n', 1),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(MODULE.VerificationError, "duplicate JSON key"):
            MODULE.verify(self.root)

    def test_engine_digest_drift_is_rejected(self) -> None:
        closure = self.read_json(MODULE.CLOSURE_PATH)
        closure["engine"]["image"] = closure["engine"]["image"].split("@", 1)[0] + (
            "@sha256:" + "0" * 64
        )
        self.write_json(MODULE.CLOSURE_PATH, closure)
        with self.assertRaisesRegex(MODULE.VerificationError, "engine v0.5.0 identity drift"):
            MODULE.verify(self.root)

    def test_any_operational_gate_is_rejected(self) -> None:
        closure = self.read_json(MODULE.CLOSURE_PATH)
        closure["gates"]["workflow_submission_authorized"] = True
        self.write_json(MODULE.CLOSURE_PATH, closure)
        with self.assertRaisesRegex(MODULE.VerificationError, "operational gate drift"):
            MODULE.verify(self.root)

    def test_numeric_zero_is_not_accepted_as_a_false_gate(self) -> None:
        closure = self.read_json(MODULE.CLOSURE_PATH)
        closure["gates"]["workflow_submitted"] = 0
        self.write_json(MODULE.CLOSURE_PATH, closure)
        with self.assertRaisesRegex(MODULE.VerificationError, "operational gate drift"):
            MODULE.verify(self.root)

    def test_protected_resource_mutation_claim_is_rejected(self) -> None:
        closure = self.read_json(MODULE.CLOSURE_PATH)
        closure["protected_resources"]["recovery_database"]["mutation_performed"] = True
        self.write_json(MODULE.CLOSURE_PATH, closure)
        with self.assertRaisesRegex(
            MODULE.VerificationError,
            "protected-resource boundary drift",
        ):
            MODULE.verify(self.root)

    def test_issue_scope_cannot_claim_reproduction(self) -> None:
        closure = self.read_json(MODULE.CLOSURE_PATH)
        closure["scope"]["fully_satisfied_acceptance_criteria"].append(3)
        self.write_json(MODULE.CLOSURE_PATH, closure)
        with self.assertRaisesRegex(
            MODULE.VerificationError,
            "acceptance-criteria scope drift",
        ):
            MODULE.verify(self.root)

    def test_missing_runtime_bytes_cannot_be_claimed_retained(self) -> None:
        closure = self.read_json(MODULE.CLOSURE_PATH)
        closure["selected_reference"]["runtime_checkpoint_manifest"] = {
            "retained": True,
            "sha256": "0" * 64,
            "bytes": 1,
        }
        self.write_json(MODULE.CLOSURE_PATH, closure)
        with self.assertRaisesRegex(
            MODULE.VerificationError,
            "runtime checkpoint manifest was falsely claimed",
        ):
            MODULE.verify(self.root)

    def test_checkpoint_drift_fails_after_self_consistent_hash_move(self) -> None:
        benchmark = self.read_fixture("benchmark.json")
        benchmark["checkpoint"]["sha256"] = "0" * 64
        self.write_fixture("benchmark.json", benchmark)
        self.update_certificate_artifact_sha("benchmark", "benchmark.json")
        with self.accept_modified_retained_bytes("benchmark.json", "certificate.json"):
            with self.assertRaisesRegex(
                MODULE.VerificationError,
                "checkpoint cross-reference drift",
            ):
                MODULE.verify(self.root)

    def test_historical_certificate_gate_drift_fails_after_hash_move(self) -> None:
        certificate = self.read_fixture("certificate.json")
        certificate["gates"]["graph_node_restart"] = False
        self.write_fixture("certificate.json", certificate)
        with self.accept_modified_retained_bytes("certificate.json"):
            with self.assertRaisesRegex(
                MODULE.VerificationError,
                "historical certificate gate drift: graph_node_restart",
            ):
                MODULE.verify(self.root)

    def test_frame_count_drift_fails_after_self_consistent_hash_move(self) -> None:
        benchmark = self.read_fixture("benchmark.json")
        benchmark["cold_cache"]["event_bearing_frames"] += 1
        self.write_fixture("benchmark.json", benchmark)
        self.update_certificate_artifact_sha("benchmark", "benchmark.json")
        with self.accept_modified_retained_bytes("benchmark.json", "certificate.json"):
            with self.assertRaisesRegex(
                MODULE.VerificationError,
                "frame-stream cross-reference drift",
            ):
                MODULE.verify(self.root)

    def test_poi_drift_fails_after_self_consistent_hash_move(self) -> None:
        parity = self.read_fixture("parity.json")
        poi = next(item for item in parity["tables"] if item["table"] == "poi2$")
        poi["local_digest"] = poi["source_digest"] = "0" * 64
        self.write_fixture("parity.json", parity)
        self.update_certificate_artifact_sha("parity", "parity.json")
        with self.accept_modified_retained_bytes("parity.json", "certificate.json"):
            with self.assertRaisesRegex(
                MODULE.VerificationError,
                "retained PoI table identity drift",
            ):
                MODULE.verify(self.root)

    def test_copy_table_inventory_drift_fails_after_hash_move(self) -> None:
        parity = self.read_fixture("parity.json")
        parity["tables"][0]["table"] = "invented_copy_table"
        self.write_fixture("parity.json", parity)
        self.update_certificate_artifact_sha("parity", "parity.json")
        with self.accept_modified_retained_bytes("parity.json", "certificate.json"):
            with self.assertRaisesRegex(
                MODULE.VerificationError,
                "COPY table inventory",
            ):
                MODULE.verify(self.root)

    def test_imported_package_bytes_are_rejected_when_tampered(self) -> None:
        package = self.root / MODULE.PACKAGE_PATH
        package.write_bytes(package.read_bytes() + b"\x00")
        with self.assertRaisesRegex(
            MODULE.VerificationError,
            "imported SPKG (?:byte length|SHA-256) drift",
        ):
            MODULE.verify(self.root)

    def test_package_contract_byte_drift_is_rejected(self) -> None:
        contract = self.read_json(MODULE.PACKAGE_CONTRACT_PATH)
        contract["packages"]["store_state"]["module_hash"] = "0" * 40
        self.write_json(MODULE.PACKAGE_CONTRACT_PATH, contract)
        with self.assertRaisesRegex(
            MODULE.VerificationError,
            "base-uniswap-v4-v0.4.0.json byte/SHA-256 drift",
        ):
            MODULE.verify(self.root)

    def test_import_provenance_tree_drift_is_rejected(self) -> None:
        provenance = self.read_json(MODULE.IMPORT_PROVENANCE_PATH)
        provenance["source"]["tree"] = "0" * 40
        self.write_json(MODULE.IMPORT_PROVENANCE_PATH, provenance)
        with self.assertRaisesRegex(
            MODULE.VerificationError,
            "uniswap-v4-v0.4.1.json byte/SHA-256 drift",
        ):
            MODULE.verify(self.root)


if __name__ == "__main__":
    unittest.main()
