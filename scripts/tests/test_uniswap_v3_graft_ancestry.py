from __future__ import annotations

import copy
import importlib.util
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[2]
VERIFIER = REPOSITORY / "scripts/verify-uniswap-v3-graft-ancestry.py"
SPEC = importlib.util.spec_from_file_location("uniswap_v3_graft_ancestry", VERIFIER)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
CONTRACT_PATH = REPOSITORY / MODULE.CONTRACT_PATH


class UniswapV3GraftAncestryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = MODULE.verify(REPOSITORY)

    def mutated_contract(self, mutate) -> tempfile.TemporaryDirectory[str]:
        temporary = tempfile.TemporaryDirectory()
        path = Path(temporary.name) / "contract.json"
        contract = copy.deepcopy(self.contract)
        mutate(contract)
        path.write_text(MODULE.render(contract), encoding="utf-8")
        temporary.contract_path = path  # type: ignore[attr-defined]
        return temporary

    def copied_root(self) -> tempfile.TemporaryDirectory[str]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        source = REPOSITORY / "uniswap-v3/graft-ancestry/v1"
        target = root / "uniswap-v3/graft-ancestry/v1"
        target.parent.mkdir(parents=True)
        shutil.copytree(source, target)
        temporary.root_path = root  # type: ignore[attr-defined]
        return temporary

    def test_exact_contract_is_deterministic_and_passes(self) -> None:
        self.assertEqual(
            CONTRACT_PATH.read_text(encoding="utf-8"),
            MODULE.render(MODULE.build_contract(REPOSITORY)),
        )
        self.assertEqual(len(self.contract["artifacts"]), 38)
        self.assertEqual(len(self.contract["networks"]["mainnet"]["segments"]), 6)
        self.assertEqual(len(self.contract["networks"]["base"]["segments"]), 2)
        mappings = self.contract["mapping_writer_inventories"]
        self.assertEqual(len(mappings), 20)
        for mapping in mappings:
            self.assertEqual(
                mapping["observed_constant_store_set_target_count"],
                len(mapping["observed_constant_store_set_targets"]),
            )
            self.assertEqual(mapping["manual_wat_sha256"], MODULE.WAT_SHA256[mapping["cid"]])

    def test_graft_block_belongs_to_base_and_next_block_to_child(self) -> None:
        for network in ("mainnet", "base"):
            chain = self.contract["networks"][network]
            for boundary in chain["boundary_probes"]:
                self.assertEqual(
                    MODULE.select_segment(self.contract, network, boundary["graft_block"])[
                        "deployment"
                    ],
                    boundary["base_deployment_at_graft_block"],
                )
                self.assertEqual(
                    MODULE.select_segment(
                        self.contract, network, boundary["graft_block"] + 1
                    )["deployment"],
                    boundary["child_deployment_at_next_block"],
                )

    def test_schema_declared_and_compiled_writer_sets_are_distinct(self) -> None:
        expected_absent = {"Collect", "Flash", "TickHourData"}
        expected_written = set(MODULE.ENTITIES) - expected_absent
        for network in ("mainnet", "base"):
            for segment in self.contract["networks"][network]["segments"]:
                matrix = {item["entity"]: item for item in segment["writer_matrix"]}
                actual_written = {
                    name
                    for name, item in matrix.items()
                    if item["observed_constant_store_set_target_present"]
                }
                self.assertEqual(actual_written, expected_written)
                for name in expected_absent:
                    self.assertEqual(
                        matrix[name]["required_absent_status"],
                        "not_certified",
                    )
                    self.assertEqual(matrix[name]["runtime_population_status"], "not_certified")

    def test_historical_writer_quirks_are_bound_to_specific_mappings(self) -> None:
        observations = {
            item["observation_id"]: item
            for item in self.contract["deployment_specific_static_observations"]
        }
        self.assertIn("npm-mainnet-root-qmywr", observations)
        self.assertIn("npm-mainnet-qmrv-qmebr", observations)
        self.assertIn("npm-mainnet-qmywx-epochs", observations)
        self.assertIn("mainnet-dead-current-guard", observations)
        self.assertIn("tick-hour-no-target-observed", observations)
        self.assertEqual(
            observations["npm-mainnet-qmrv-qmebr"]["mapping_cids"],
            ["Qmebr2EyxV7v1wLt9DSFKA7g8EhcVr9k1x7pwZr5eWEHT6"],
        )
        dead_guard = " ".join(observations["mainnet-dead-current-guard"]["observations"])
        self.assertIn("QmZe", dead_guard)
        self.assertIn("incorrectly skip mainnet block 14317993", dead_guard)
        pool_cids = observations["tick-hour-no-target-observed"]["mapping_cids"]
        self.assertEqual(len(pool_cids), 8)
        self.assertEqual(len(set(pool_cids)), 8)

    def test_wrong_artifact_digest_is_rejected(self) -> None:
        def mutate(contract) -> None:
            contract["artifacts"][0]["sha256"] = "0" * 64

        with self.mutated_contract(mutate) as temporary:
            path = Path(temporary) / "contract.json"
            with self.assertRaisesRegex(MODULE.VerificationError, "SHA-256 drift"):
                MODULE.verify(REPOSITORY, path)

    def test_missing_ancestor_is_rejected(self) -> None:
        def mutate(contract) -> None:
            del contract["networks"]["mainnet"]["segments"][2]

        with self.mutated_contract(mutate) as temporary:
            with self.assertRaises(MODULE.VerificationError):
                MODULE.verify(REPOSITORY, Path(temporary) / "contract.json")

    def test_cycle_or_wrong_parent_is_rejected(self) -> None:
        def mutate(contract) -> None:
            segments = contract["networks"]["mainnet"]["segments"]
            segments[1]["graft"]["base"] = segments[-1]["deployment"]

        with self.mutated_contract(mutate) as temporary:
            with self.assertRaisesRegex(MODULE.VerificationError, "graft base"):
                MODULE.verify(REPOSITORY, Path(temporary) / "contract.json")

    def test_gap_is_rejected(self) -> None:
        def mutate(contract) -> None:
            contract["networks"]["mainnet"]["segments"][1][
                "start_block_inclusive"
            ] += 1

        with self.mutated_contract(mutate) as temporary:
            with self.assertRaises(MODULE.VerificationError):
                MODULE.verify(REPOSITORY, Path(temporary) / "contract.json")

    def test_overlap_is_rejected(self) -> None:
        def mutate(contract) -> None:
            contract["networks"]["mainnet"]["segments"][1][
                "start_block_inclusive"
            ] -= 1

        with self.mutated_contract(mutate) as temporary:
            with self.assertRaises(MODULE.VerificationError):
                MODULE.verify(REPOSITORY, Path(temporary) / "contract.json")

    def test_child_writer_at_graft_block_is_rejected(self) -> None:
        def mutate(contract) -> None:
            segment = contract["networks"]["base"]["segments"][1]
            segment["start_block_inclusive"] = segment["graft"]["block"]

        with self.mutated_contract(mutate) as temporary:
            with self.assertRaisesRegex(
                MODULE.VerificationError, r"gap or overlap|graft block \+ 1"
            ):
                MODULE.verify(REPOSITORY, Path(temporary) / "contract.json")

    def test_segment_selector_fails_closed_on_overlap(self) -> None:
        contract = copy.deepcopy(self.contract)
        segments = contract["networks"]["base"]["segments"]
        segments[1]["start_block_inclusive"] = segments[0]["end_block_inclusive"]
        with self.assertRaisesRegex(MODULE.VerificationError, "matched 2 segments"):
            MODULE.select_segment(contract, "base", segments[0]["end_block_inclusive"])

    def test_unproven_graft_free_root_is_rejected(self) -> None:
        def mutate(contract) -> None:
            contract["networks"]["base"]["segments"][0]["graft_free_root"] = False

        with self.mutated_contract(mutate) as temporary:
            with self.assertRaisesRegex(MODULE.VerificationError, "graft-free claim is unproven"):
                MODULE.verify(REPOSITORY, Path(temporary) / "contract.json")

    def test_unclosed_manifest_artifact_reference_is_rejected(self) -> None:
        def mutate(contract) -> None:
            abi_cid = next(
                item["cid"]
                for item in contract["artifacts"]
                if item["media_type"] == "application/json"
            )
            contract["artifacts"] = [
                item for item in contract["artifacts"] if item["cid"] != abi_cid
            ]

        with self.mutated_contract(mutate) as temporary:
            with self.assertRaisesRegex(MODULE.VerificationError, "closure"):
                MODULE.verify(REPOSITORY, Path(temporary) / "contract.json")

    def test_handler_inventory_drift_is_rejected(self) -> None:
        def mutate(contract) -> None:
            contract["networks"]["mainnet"]["segments"][0]["manifest"][
                "components"
            ][0]["mapping"]["handlers"][0]["handler"] = "handleWrong"

        with self.mutated_contract(mutate) as temporary:
            with self.assertRaisesRegex(MODULE.VerificationError, "manifest inventory drift"):
                MODULE.verify(REPOSITORY, Path(temporary) / "contract.json")

    def test_missing_artifact_file_is_rejected(self) -> None:
        with self.copied_root() as temporary:
            root = Path(temporary)
            cid = self.contract["artifacts"][0]["cid"]
            (root / MODULE.ARTIFACT_DIRECTORY / cid).unlink()
            with self.assertRaisesRegex(MODULE.VerificationError, "missing artifact"):
                MODULE.verify(root)

    def test_artifact_byte_and_cid_drift_is_rejected(self) -> None:
        with self.copied_root() as temporary:
            root = Path(temporary)
            cid = next(
                item["cid"]
                for item in self.contract["artifacts"]
                if item["media_type"] == "application/graphql"
            )
            path = root / MODULE.ARTIFACT_DIRECTORY / cid
            path.write_bytes(path.read_bytes() + b"\n")
            with self.assertRaisesRegex(MODULE.VerificationError, "artifact CID drift"):
                MODULE.verify(root)

    def test_symlink_artifact_is_rejected(self) -> None:
        with self.copied_root() as temporary:
            root = Path(temporary)
            cid = next(
                item["cid"]
                for item in self.contract["artifacts"]
                if item["media_type"] == "application/json"
            )
            path = root / MODULE.ARTIFACT_DIRECTORY / cid
            backup = path.with_suffix(".backup")
            path.rename(backup)
            os.symlink(backup.name, path)
            with self.assertRaisesRegex(MODULE.VerificationError, "must not be a symlink"):
                MODULE.verify(root)

    def test_duplicate_json_key_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "contract.json"
            path.write_text('{"format_version":1,"format_version":1}', encoding="utf-8")
            with self.assertRaisesRegex(MODULE.VerificationError, "duplicate JSON key"):
                MODULE.verify(REPOSITORY, path)


if __name__ == "__main__":
    unittest.main()
