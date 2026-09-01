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
VERIFIER = REPOSITORY / "scripts/verify-uniswap-v4-q8-reference.py"

SPEC = importlib.util.spec_from_file_location(
    "verify_uniswap_v4_q8_reference",
    VERIFIER,
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class UniswapV4Q8ReferenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        source = REPOSITORY / MODULE.CAPSULE_DIRECTORY.parent
        destination = self.root / MODULE.CAPSULE_DIRECTORY.parent
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, destination)
        self.original_file_locks = copy.deepcopy(MODULE.EXPECTED_FILE_LOCKS)

    def tearDown(self) -> None:
        MODULE.EXPECTED_FILE_LOCKS.clear()
        MODULE.EXPECTED_FILE_LOCKS.update(self.original_file_locks)
        self.temporary.cleanup()

    @property
    def capsule(self) -> Path:
        return self.root / MODULE.CAPSULE_DIRECTORY

    @property
    def closure_path(self) -> Path:
        return self.root / MODULE.CLOSURE_PATH

    def read_json(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def write_json(self, path: Path, value: dict) -> None:
        path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")

    def fixture_path(self, name: str) -> Path:
        return self.capsule / name

    def read_fixture(self, name: str) -> dict:
        return self.read_json(self.fixture_path(name))

    def write_fixture(self, name: str, value: dict) -> None:
        self.write_json(self.fixture_path(name), value)

    def bind_reference_contract_sha(self, contract: str, fixture: str) -> None:
        reference = self.read_fixture("uniswap-v4-base-v0.5.0-q8-reference.json")
        reference["certification_execution"][contract]["sha256"] = hashlib.sha256(
            self.fixture_path(fixture).read_bytes()
        ).hexdigest()
        self.write_fixture("uniswap-v4-base-v0.5.0-q8-reference.json", reference)

    @contextlib.contextmanager
    def accept_modified_source_file(self, name: str, *, refresh_blob: bool = True):
        source_path, role, _, _, blob = MODULE.EXPECTED_FILE_LOCKS[name]
        payload = self.fixture_path(name).read_bytes()
        if refresh_blob:
            blob = MODULE.git_blob_sha1(payload)
        updated = (source_path, role, len(payload), hashlib.sha256(payload).hexdigest(), blob)
        MODULE.EXPECTED_FILE_LOCKS[name] = updated
        closure = self.read_json(self.closure_path)
        record = next(item for item in closure["files"] if item["local_path"] == name)
        record["bytes"] = updated[2]
        record["sha256"] = updated[3]
        record["git_blob"] = updated[4]
        self.write_json(self.closure_path, closure)
        try:
            yield
        finally:
            MODULE.EXPECTED_FILE_LOCKS[name] = self.original_file_locks[name]

    def test_exact_q8_capsule_passes(self) -> None:
        MODULE.verify(self.root)

    def test_tampered_source_fixture_bytes_are_rejected(self) -> None:
        path = self.fixture_path("uniswap-v4-base-v0.5.0-q8-reference.json")
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaisesRegex(MODULE.VerificationError, "(?:byte length|SHA-256) drift"):
            MODULE.verify(self.root)

    def test_source_git_blob_claim_cannot_be_stale_after_digest_move(self) -> None:
        name = "uniswap-v4-base-v0.5.0-q8-reference.json"
        path = self.fixture_path(name)
        path.write_bytes(path.read_bytes() + b"\n")
        with self.accept_modified_source_file(name, refresh_blob=False):
            with self.assertRaisesRegex(MODULE.VerificationError, "Git blob drift"):
                MODULE.verify(self.root)

    def test_tampered_compact_archive_is_rejected(self) -> None:
        path = self.fixture_path(MODULE.ARCHIVE_NAME)
        path.write_bytes(path.read_bytes() + b"\x00")
        with self.assertRaisesRegex(MODULE.VerificationError, "(?:byte length|SHA-256) drift"):
            MODULE.verify(self.root)

    def test_unlisted_capsule_file_is_rejected(self) -> None:
        (self.capsule / "execution-complete.json").write_text(
            '{"criterion_2_complete":true}\n',
            encoding="utf-8",
        )
        with self.assertRaisesRegex(MODULE.VerificationError, "file inventory drift"):
            MODULE.verify(self.root)

    def test_unlisted_capsule_directory_is_rejected(self) -> None:
        claims = self.capsule / "claims"
        claims.mkdir()
        (claims / "production.json").write_text(
            '{"production_ready":true}\n',
            encoding="utf-8",
        )
        with self.assertRaisesRegex(MODULE.VerificationError, "unexpected directory"):
            MODULE.verify(self.root)

    def test_symlinked_source_fixture_is_rejected(self) -> None:
        path = self.fixture_path("uniswap-v4-base-v0.5.0-q8-READY.json")
        path.unlink()
        path.symlink_to(self.fixture_path("uniswap-v4-base-v0.5.0-q8-restore-READY.json"))
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

    def test_criterion_2_completion_claim_is_rejected(self) -> None:
        closure = self.read_json(self.closure_path)
        closure["scope"]["fully_satisfied_acceptance_criteria"] = [2]
        closure["gates"]["criterion_2_complete"] = True
        self.write_json(self.closure_path, closure)
        with self.assertRaisesRegex(MODULE.VerificationError, "(?:acceptance scope|operational gate) drift"):
            MODULE.verify(self.root)

    def test_raw_frame_retention_claim_is_rejected(self) -> None:
        closure = self.read_json(self.closure_path)
        closure["retention"]["raw_frame_payload_bytes"] = True
        closure["retention"]["raw_frame_stream_digest"] = True
        self.write_json(self.closure_path, closure)
        with self.assertRaisesRegex(MODULE.VerificationError, "retention boundary drift"):
            MODULE.verify(self.root)

    def test_historical_input_shape_cannot_be_relabelled_byte_exact(self) -> None:
        closure = self.read_json(self.closure_path)
        semantics = closure["historical_field_semantics"]["input_stream_exact"]
        semantics["meaning"] = "raw-byte-identity"
        semantics["raw_byte_identity_proven"] = True
        self.write_json(self.closure_path, closure)
        with self.assertRaisesRegex(MODULE.VerificationError, "historical field semantics drift"):
            MODULE.verify(self.root)

    def test_numeric_zero_is_not_accepted_as_false_gate(self) -> None:
        closure = self.read_json(self.closure_path)
        closure["gates"]["criterion_2_complete"] = 0
        self.write_json(self.closure_path, closure)
        with self.assertRaisesRegex(MODULE.VerificationError, "operational gate drift"):
            MODULE.verify(self.root)

    def test_numeric_retention_and_archive_booleans_are_rejected(self) -> None:
        closure = self.read_json(self.closure_path)
        closure["retention"]["manifest_bytes"] = 1
        closure["recovered_archive"]["source_reference_availability_is_stale"] = 1
        self.write_json(self.closure_path, closure)
        with self.assertRaisesRegex(
            MODULE.VerificationError,
            "(?:retention boundary|archive closure) drift",
        ):
            MODULE.verify(self.root)

    def test_archive_acceptance_role_cannot_be_promoted(self) -> None:
        closure = self.read_json(self.closure_path)
        closure["recovered_archive"]["acceptance_role"] = "criterion-2-oracle"
        self.write_json(self.closure_path, closure)
        with self.assertRaisesRegex(MODULE.VerificationError, "archive closure drift"):
            MODULE.verify(self.root)

    def test_non_claim_cannot_be_removed(self) -> None:
        closure = self.read_json(self.closure_path)
        closure["non_claims"].pop()
        self.write_json(self.closure_path, closure)
        with self.assertRaisesRegex(MODULE.VerificationError, "non-claim boundary drift"):
            MODULE.verify(self.root)

    def test_source_unavailable_declaration_cannot_be_silently_rewritten(self) -> None:
        name = "uniswap-v4-base-v0.5.0-q8-reference.json"
        reference = self.read_fixture(name)
        reference["historical_archive_declaration"]["availability"] = "repository-retained"
        self.write_fixture(name, reference)
        with self.accept_modified_source_file(name):
            with self.assertRaisesRegex(MODULE.VerificationError, "source archive declaration drift"):
                MODULE.verify(self.root)

    def test_scratch_schema_cannot_name_protected_source(self) -> None:
        name = "uniswap-v4-base-v0.5.0-q8-reference.json"
        reference = self.read_fixture(name)
        reference["scratch"]["schema"] = "sgd1246"
        reference["scratch"]["forbidden_schemas"] = []
        self.write_fixture(name, reference)
        with self.accept_modified_source_file(name):
            with self.assertRaisesRegex(MODULE.VerificationError, "scratch safety boundary drift"):
                MODULE.verify(self.root)

    def test_poi_drift_fails_after_reference_hash_move(self) -> None:
        name = "uniswap-v4-base-v0.5.0-q8-reference.json"
        reference = self.read_fixture(name)
        reference["certified_segment"]["poi"]["rows"]["sha256"] = "0" * 64
        self.write_fixture(name, reference)
        with self.accept_modified_source_file(name):
            with self.assertRaisesRegex(MODULE.VerificationError, "PoI rows identity drift"):
                MODULE.verify(self.root)

    def test_source_observation_count_drift_fails_after_hash_move(self) -> None:
        name = "uniswap-v4-base-v4-reference-source-observations.json"
        observations = self.read_fixture(name)
        observations["count"] = 52
        self.write_fixture(name, observations)
        self.bind_reference_contract_sha("source_observation_contract", name)
        with self.accept_modified_source_file(name):
            with self.accept_modified_source_file("uniswap-v4-base-v0.5.0-q8-reference.json"):
                with self.assertRaisesRegex(MODULE.VerificationError, "source-observation inventory drift"):
                    MODULE.verify(self.root)

    def test_source_observation_scope_drift_fails_after_hash_move(self) -> None:
        name = "uniswap-v4-base-v4-reference-source-observations.json"
        observations = self.read_fixture(name)
        observations["scope"] = "failed-or-incomplete-workflow"
        self.write_fixture(name, observations)
        self.bind_reference_contract_sha("source_observation_contract", name)
        with self.accept_modified_source_file(name):
            with self.accept_modified_source_file("uniswap-v4-base-v0.5.0-q8-reference.json"):
                with self.assertRaisesRegex(MODULE.VerificationError, "source-observation scope drift"):
                    MODULE.verify(self.root)

    def test_pod_topology_drift_fails_after_hash_move(self) -> None:
        name = "uniswap-v4-base-v4-reference-pod-topology.json"
        topology = self.read_fixture(name)
        topology["counts"]["producer_pods"] = 19
        self.write_fixture(name, topology)
        self.bind_reference_contract_sha("pod_topology", name)
        with self.accept_modified_source_file(name):
            with self.accept_modified_source_file("uniswap-v4-base-v0.5.0-q8-reference.json"):
                with self.assertRaisesRegex(MODULE.VerificationError, "pod-topology counts drift"):
                    MODULE.verify(self.root)

    def test_pod_topology_policy_drift_fails_after_hash_move(self) -> None:
        name = "uniswap-v4-base-v4-reference-pod-topology.json"
        topology = self.read_fixture(name)
        topology["policy"] = "allow-retry-pods"
        self.write_fixture(name, topology)
        self.bind_reference_contract_sha("pod_topology", name)
        with self.accept_modified_source_file(name):
            with self.accept_modified_source_file("uniswap-v4-base-v0.5.0-q8-reference.json"):
                with self.assertRaisesRegex(MODULE.VerificationError, "pod-topology policy drift"):
                    MODULE.verify(self.root)

    def test_seed_checkpoint_drift_fails_after_reference_hash_move(self) -> None:
        name = "uniswap-v4-base-v0.5.0-q8-reference.json"
        reference = self.read_fixture(name)
        reference["seed"]["checkpoint_bytes"] = 1
        reference["seed"]["checkpoint_sha256"] = "0" * 64
        self.write_fixture(name, reference)
        with self.accept_modified_source_file(name):
            with self.assertRaisesRegex(MODULE.VerificationError, "reference seed identity drift"):
                MODULE.verify(self.root)

    def test_segment_row_summary_drift_fails_after_reference_hash_move(self) -> None:
        name = "uniswap-v4-base-v0.5.0-q8-reference.json"
        reference = self.read_fixture(name)
        for field in ("inserted_rows", "clamped_rows", "new_entities"):
            reference["certified_segment"][field] = 0
        self.write_fixture(name, reference)
        with self.accept_modified_source_file(name):
            with self.assertRaisesRegex(MODULE.VerificationError, "row-summary cross-reference drift"):
                MODULE.verify(self.root)

    def test_nested_operational_claim_is_rejected_after_hash_move(self) -> None:
        name = "uniswap-v4-base-v0.5.0-q8-reference.json"
        reference = self.read_fixture(name)
        reference["certified_segment"]["criterion_2_complete"] = True
        self.write_fixture(name, reference)
        with self.accept_modified_source_file(name):
            with self.assertRaisesRegex(MODULE.VerificationError, "forbidden operational claim key"):
                MODULE.verify(self.root)

    def test_runtime_binary_drift_fails_after_reference_hash_move(self) -> None:
        name = "uniswap-v4-base-v0.5.0-q8-reference.json"
        reference = self.read_fixture(name)
        reference["runtime"]["binary_sha256"]["state-replay"] = "0" * 64
        self.write_fixture(name, reference)
        with self.accept_modified_source_file(name):
            with self.assertRaisesRegex(MODULE.VerificationError, "engine runtime identity drift"):
                MODULE.verify(self.root)

    def test_q8_capsule_root_symlink_is_rejected(self) -> None:
        real_capsule = self.capsule.with_name("q8-real")
        self.capsule.rename(real_capsule)
        self.capsule.symlink_to(real_capsule, target_is_directory=True)
        with self.assertRaisesRegex(MODULE.VerificationError, "directory must not be a symlink"):
            MODULE.verify(self.root)

    def test_current_compatibility_drift_is_rejected(self) -> None:
        path = self.root / MODULE.CURRENT_COMPATIBILITY_PATH
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaisesRegex(MODULE.VerificationError, "current compatibility drift"):
            MODULE.verify(self.root)


if __name__ == "__main__":
    unittest.main()
