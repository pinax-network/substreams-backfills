from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[2]
VERIFIER = REPOSITORY / "scripts/verify-uniswap-v3-logical-oracle.py"

SPEC = importlib.util.spec_from_file_location("verify_uniswap_v3_logical_oracle", VERIFIER)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class UniswapV3LogicalOracleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        destination = self.root / MODULE.ORACLE_DIRECTORY
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(REPOSITORY / MODULE.ORACLE_DIRECTORY, destination)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @property
    def oracle(self) -> Path:
        return self.root / MODULE.ORACLE_DIRECTORY

    @property
    def contract_path(self) -> Path:
        return self.root / MODULE.CONTRACT_PATH

    def read_contract(self) -> dict:
        return json.loads(self.contract_path.read_text(encoding="utf-8"))

    def write_contract(self, contract: dict) -> None:
        self.contract_path.write_text(
            json.dumps(contract, indent=2) + "\n",
            encoding="utf-8",
        )

    @contextlib.contextmanager
    def accept_modified_retained_bytes(self, relative: str):
        """Move the byte lock so a negative test reaches semantic validation."""

        path = self.oracle / relative
        payload = path.read_bytes()
        modified_lock = (len(payload), hashlib.sha256(payload).hexdigest())
        original_lock = MODULE.EXPECTED_FILE_LOCKS[relative]
        MODULE.EXPECTED_FILE_LOCKS[relative] = modified_lock

        contract = self.read_contract()
        record = next(item for item in contract["files"] if item["path"] == relative)
        record["bytes"], record["sha256"] = modified_lock
        self.write_contract(contract)
        try:
            yield
        finally:
            MODULE.EXPECTED_FILE_LOCKS[relative] = original_lock

    def test_exact_snapshot_passes(self) -> None:
        MODULE.verify(self.root)

    def test_tampered_response_bytes_are_rejected(self) -> None:
        path = self.oracle / "discovery/mainnet-query-response.json"
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaisesRegex(MODULE.VerificationError, "(?:byte length|SHA-256) drift"):
            MODULE.verify(self.root)

    def test_unlisted_oracle_artifact_is_rejected(self) -> None:
        path = self.oracle / "discovery/authoritative-promotion.json"
        path.write_text(
            '{"final_parity_package":true,"production_backfill_allowed":true}\n',
            encoding="utf-8",
        )
        with self.assertRaisesRegex(MODULE.VerificationError, "file inventory drift"):
            MODULE.verify(self.root)

    def test_source_identity_drift_is_rejected(self) -> None:
        contract = self.read_contract()
        contract["source_identity"]["revision"] = "0" * 40
        self.write_contract(contract)
        with self.assertRaisesRegex(MODULE.VerificationError, "source identity drift"):
            MODULE.verify(self.root)

    def test_query_shape_drift_is_rejected_even_with_a_moved_byte_lock(self) -> None:
        relative = "queries/current-and-required-absence.graphql"
        path = self.oracle / relative
        query = path.read_text(encoding="utf-8")
        self.assertIn("query CurrentAndRequiredAbsence", query)
        path.write_text(
            query.replace("query CurrentAndRequiredAbsence", "query Weakened", 1),
            encoding="utf-8",
        )
        with self.accept_modified_retained_bytes(relative):
            with self.assertRaisesRegex(MODULE.VerificationError, "current query contract"):
                MODULE.verify(self.root)

    def test_any_promotion_gate_is_rejected(self) -> None:
        contract = self.read_contract()
        contract["promotion_gates"]["final_parity_package"] = True
        self.write_contract(contract)
        with self.assertRaisesRegex(MODULE.VerificationError, "promotion gate"):
            MODULE.verify(self.root)

    def test_base_refusal_removal_is_rejected_even_with_a_moved_byte_lock(self) -> None:
        relative = "discovery/base-boundary-error.json"
        (self.oracle / relative).write_text('{"data": {}}\n', encoding="utf-8")
        with self.accept_modified_retained_bytes(relative):
            with self.assertRaisesRegex(MODULE.VerificationError, "Base boundary refusal"):
                MODULE.verify(self.root)

    def test_mainnet_deployment_mismatch_is_rejected_with_a_moved_byte_lock(self) -> None:
        relative = "discovery/mainnet-query-response.json"
        path = self.oracle / relative
        response = json.loads(path.read_text(encoding="utf-8"))
        response["data"]["_meta"]["deployment"] = MODULE.BASE_DEPLOYMENT
        path.write_text(json.dumps(response, indent=2) + "\n", encoding="utf-8")
        with self.accept_modified_retained_bytes(relative):
            with self.assertRaisesRegex(MODULE.VerificationError, "deployment echo mismatch"):
                MODULE.verify(self.root)

    def test_json_booleans_are_not_valid_block_metadata(self) -> None:
        relative = "discovery/mainnet-query-response.json"
        path = self.oracle / relative
        response = json.loads(path.read_text(encoding="utf-8"))
        response["data"]["_meta"]["block"]["number"] = True
        response["data"]["_meta"]["block"]["timestamp"] = True
        path.write_text(json.dumps(response, indent=2) + "\n", encoding="utf-8")
        with self.accept_modified_retained_bytes(relative):
            with self.assertRaisesRegex(MODULE.VerificationError, "block number is invalid"):
                MODULE.verify(self.root)

    def test_indexer_identity_drift_is_rejected_with_a_moved_byte_lock(self) -> None:
        relative = "discovery/base-status-response.json"
        path = self.oracle / relative
        response = json.loads(path.read_text(encoding="utf-8"))
        response["data"]["indexers"][0]["indexerId"] = "0x" + "0" * 40
        path.write_text(json.dumps(response, indent=2) + "\n", encoding="utf-8")
        with self.accept_modified_retained_bytes(relative):
            with self.assertRaisesRegex(MODULE.VerificationError, "indexer identities drift"):
                MODULE.verify(self.root)


if __name__ == "__main__":
    unittest.main()
