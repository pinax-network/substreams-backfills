from __future__ import annotations

import ast
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


REPOSITORY = Path(__file__).resolve().parents[2]
VERIFIER = REPOSITORY / "scripts/verify-messari-v3-targets.py"
CONTRACT_PATH = Path("docs/provenance/messari-v3-targets-v1.json")
PROFILE_PATH = Path("messari-v3/layout-profile-v1.json")
SOURCE_PATH = Path("docs/provenance/messari-v3-source.md")

SPEC = importlib.util.spec_from_file_location("verify_messari_v3_targets", VERIFIER)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class MessariV3TargetsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        shutil.copytree(REPOSITORY / "messari-v3", self.root / "messari-v3")
        (self.root / CONTRACT_PATH.parent).mkdir(parents=True)
        shutil.copy2(REPOSITORY / CONTRACT_PATH, self.root / CONTRACT_PATH)
        shutil.copy2(REPOSITORY / SOURCE_PATH, self.root / SOURCE_PATH)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def verify(self, *, write_contract: bool = False) -> subprocess.CompletedProcess[str]:
        command = [sys.executable, str(VERIFIER), "--root", str(self.root)]
        if write_contract:
            command.append("--write-contract")
        return subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            env=os.environ.copy(),
        )

    def load_contract(self) -> dict:
        return json.loads((self.root / CONTRACT_PATH).read_text())

    def write_contract(self, value: dict) -> None:
        (self.root / CONTRACT_PATH).write_text(MODULE.render(value))

    def load_profile(self) -> dict:
        return json.loads((self.root / PROFILE_PATH).read_text())

    def write_profile(self, value: dict) -> None:
        (self.root / PROFILE_PATH).write_text(MODULE.render(value))

    def relock_profile_in_contract(self) -> None:
        profile_path = self.root / PROFILE_PATH
        profile = self.load_profile()
        payload = profile_path.read_bytes()
        contract = self.load_contract()
        contract["layout_profile"].update(
            {
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "canonical_sha256": MODULE.canonical_sha256(profile),
            }
        )
        self.write_contract(contract)

    def test_exact_baseline_passes(self) -> None:
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("2 targets, 26 artifacts, 48 entity bindings", result.stdout)

    def test_contract_generation_is_byte_deterministic(self) -> None:
        before = {
            path: (self.root / path).read_bytes()
            for path in (CONTRACT_PATH, PROFILE_PATH)
        }
        result = self.verify(write_contract=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        for path, payload in before.items():
            self.assertEqual((self.root / path).read_bytes(), payload)

    def test_all_26_artifacts_have_exact_cid_bytes_and_sha(self) -> None:
        contract = self.load_contract()
        records = contract["artifact_lock"]
        self.assertEqual(len(records), 26)
        self.assertEqual(
            {target: sum(item["target"] == target for item in records) for target in MODULE.TARGET_ORDER},
            {"pancakeswap-v3-bsc": 13, "uniswap-v3-base": 13},
        )
        for record in records:
            payload = (self.root / record["vendored_path"]).read_bytes()
            self.assertEqual(len(payload), record["bytes"])
            self.assertEqual(hashlib.sha256(payload).hexdigest(), record["sha256"])
            self.assertEqual(MODULE.unixfs_file_cidv0(payload), record["cid"])

    def test_exact_component_sources_abi_order_and_handlers(self) -> None:
        profile = self.load_profile()
        targets = {item["target"]: item for item in profile["targets"]}
        expected_sources = {
            "pancakeswap-v3-bsc": [
                ("Factory", "0x0BFbCF9fa4f9C56B0F40a671Ad40E0805A091865", 26956207),
                ("NonFungiblePositionManager", "0x46A15B0b27311cedF172AB29E4f4766fbE7F4364", 26931961),
                ("Pool", None, None),
                ("PancakeSwapPool", None, None),
            ],
            "uniswap-v3-base": [
                ("Factory", "0x33128a8fc17869897dce68ed026d694621f6fdfd", 1371670),
                ("NonFungiblePositionManager", "0x03a520b32c04bf3beef7beb72e919cf822ed34f1", 1371704),
                ("Pool", None, None),
                ("UniswapPool", None, None),
            ],
        }
        expected_abis = {
            "pancakeswap-v3-bsc": [
                ["Pool", "Factory", "TickLens", "ERC20", "ERC20SymbolBytes", "ERC20NameBytes"],
                ["Pool", "Factory", "NonFungiblePositionManager", "ERC20"],
                ["Pool", "Factory", "ERC20"],
                ["Pool"],
            ],
            "uniswap-v3-base": [
                ["Pool", "Factory", "TickLens", "ERC20", "ERC20SymbolBytes", "ERC20NameBytes"],
                ["pool", "Factory", "NonFungiblePositionManager", "ERC20"],
                ["Pool", "Factory", "ERC20"],
                ["Pool"],
            ],
        }
        expected_handlers = {
            "pancakeswap-v3-bsc": [
                ["handlePoolCreated"],
                ["handleIncreaseLiquidity", "handleDecreaseLiquidity", "handleTransfer"],
                ["handleInitialize", "handleSetFeeProtocol", "handleCollectPool", "handleSwap", "handleMint", "handleBurn"],
                ["handleSetFeeProtocol"],
            ],
            "uniswap-v3-base": [
                ["handlePoolCreated"],
                ["handleIncreaseLiquidity", "handleDecreaseLiquidity", "handleTransfer"],
                ["handleInitialize", "handleCollectPool", "handleSwap", "handleMint", "handleBurn"],
                ["handleSetFeeProtocol"],
            ],
        }
        for target, expected in expected_sources.items():
            deployment = targets[target]["deployment"]
            self.assertEqual(deployment["spec_version"], "0.0.4")
            components = deployment["components"]
            actual_sources = [
                (item["name"], item["source"].get("address"), item["source"].get("startBlock"))
                for item in components
            ]
            self.assertEqual(actual_sources, expected)
            self.assertEqual([[binding["name"] for binding in item["abi_bindings"]] for item in components], expected_abis[target])
            self.assertEqual([[handler["handler"] for handler in item["event_handlers"]] for item in components], expected_handlers[target])
            self.assertTrue(all(item["mapping_api_version"] == "0.0.6" for item in components))
            self.assertTrue(all(item["source_abi_binding"]["exact_case_resolved"] for item in components))
            self.assertTrue(all(item["source_abi_binding"]["all_declared_events_present"] for item in components))

    def test_schema_denominators_and_exact_directive_diff(self) -> None:
        profile = self.load_profile()
        targets = {item["target"]: item for item in profile["targets"]}
        for target in MODULE.TARGET_ORDER:
            self.assertEqual(targets[target]["schema"]["entity_count"], 24)
            self.assertEqual(targets[target]["schema"]["field_count"], 388)
        diff = profile["cross_target_diff"]["schema"]
        self.assertEqual(diff["field_catalog_sha256"], "76ac4b0b03cb16e9cf6112335feff2a94d2a559132f8895842c9f5a5e5678840")
        self.assertEqual(diff["base_only_network_values"], ["BASE"])
        self.assertEqual(
            diff["entity_directive_differences"],
            {
                "PositionSnapshot": {
                    "pancakeswap-v3-bsc": ["@entity(immutable:true)", "@regularPolling"],
                    "uniswap-v3-base": ["@entity(immutable:true)", "@hourlySnapshot"],
                }
            },
        )

    def test_exact_abi_event_differences(self) -> None:
        abis = self.load_profile()["cross_target_diff"]["abis"]
        self.assertEqual(abis["byte_and_semantic_identical_abis"], ["ERC20", "ERC20NameBytes", "ERC20SymbolBytes", "TickLens"])
        self.assertEqual(list(abis["differing_abis"]), ["Factory", "NonFungiblePositionManager", "Pool"])
        self.assertEqual(
            abis["differing_abis"]["Factory"]["events_only_pancakeswap"],
            ["FeeAmountExtraInfoUpdated(uint24,bool,bool)", "SetLmPoolDeployer(address)", "WhiteListAdded(address,bool)"],
        )
        self.assertEqual(
            abis["differing_abis"]["Pool"]["events_only_pancakeswap"],
            ["SetFeeProtocol(uint32,uint32,uint32,uint32)", "SetLmPoolEvent(address)", "Swap(address,address,int256,int256,uint160,uint128,int24,uint128,uint128)"],
        )
        self.assertEqual(
            abis["differing_abis"]["Pool"]["events_only_base"],
            ["SetFeeProtocol(uint8,uint8,uint8,uint8)", "Swap(address,address,int256,int256,uint160,uint128,int24)"],
        )

    def test_full_wasm_export_tables_are_bound(self) -> None:
        profile = self.load_profile()
        for target in profile["targets"]:
            for name, mapping in target["mappings"].items():
                expected = MODULE.EXPECTED_WASM_EXPORTS[(target["target"], f"mapping/{name}")]
                self.assertEqual(mapping["export_count"], expected[0])
                self.assertEqual(mapping["export_count"], len(mapping["export_table"]))
                self.assertEqual(mapping["export_table_sha256"], expected[1])
                self.assertEqual(MODULE.canonical_sha256(mapping["export_table"]), expected[1])
                self.assertEqual(mapping["handler_exports"], expected[2])

    def test_bsc_missing_handler_and_separate_fee_mapping_are_distinct(self) -> None:
        profile = self.load_profile()
        targets = {item["target"]: item for item in profile["targets"]}
        bsc_components = targets["pancakeswap-v3-bsc"]["deployment"]["components"]
        self.assertEqual(bsc_components[2]["missing_declared_handler_exports"], ["handleSetFeeProtocol"])
        self.assertNotIn("handleSetFeeProtocol", bsc_components[2]["handler_exports"])
        self.assertEqual(bsc_components[3]["mapping_cid"], "QmZh9pwyqnVEknPgTWraJweuyy1qbwzhA2rrSq43xmdgHL")
        self.assertEqual(bsc_components[3]["handler_exports"], ["handleSetFeeProtocol"])
        base_components = targets["uniswap-v3-base"]["deployment"]["components"]
        self.assertEqual(base_components[2]["missing_declared_handler_exports"], [])
        self.assertEqual(base_components[3]["handler_exports"], ["handleSetFeeProtocol"])

    def test_mapping_entity_defects_and_multiplicity_are_exact_for_both_targets(self) -> None:
        profile = self.load_profile()
        expected_missing = {
            "Factory": ["_PricesUSD", "_TokenTracker"],
            "NonFungiblePositionManager": [],
            "primary_pool": ["LiqudityPool", "PoolDailySnapshot", "_PricesUSD", "_Account", "_DailyActiveAccount", "_TokenTracker"],
            "fee_only_template": ["LiqudityPool"],
        }
        expected_duplicates = {
            "Factory": {},
            "NonFungiblePositionManager": {},
            "primary_pool": {"Token": 2},
            "fee_only_template": {},
        }
        quirks = profile["cross_target_diff"]["shared_manifest_quirks"]
        self.assertTrue(quirks["metadata_identical_across_targets_by_role"])
        self.assertEqual(quirks["missing_from_schema_type_declarations_by_role"], expected_missing)
        self.assertEqual(quirks["duplicate_multiplicity_by_role"], expected_duplicates)
        for target in profile["targets"]:
            components = target["deployment"]["components"]
            for role, index in (("Factory", 0), ("NonFungiblePositionManager", 1), ("primary_pool", 2), ("fee_only_template", 3)):
                contract = components[index]["entity_metadata_contract"]
                self.assertEqual(contract["missing_from_schema_type_declarations"], expected_missing[role])
                self.assertEqual(contract["duplicate_multiplicity"], expected_duplicates[role])
                self.assertFalse(contract["normalization_allowed"])
            self.assertEqual(components[2]["entities"].count("Token"), 2)
            self.assertNotIn("Protocol", components[0]["entity_metadata_contract"]["missing_from_schema_type_declarations"])

    def test_source_anchors_reproduction_refusal_and_false_gates_are_exact(self) -> None:
        contract = self.load_contract()
        source = contract["source_provenance"]
        payload = (self.root / SOURCE_PATH).read_bytes()
        self.assertEqual(source["bytes"], len(payload))
        self.assertEqual(source["sha256"], hashlib.sha256(payload).hexdigest())
        anchors = contract["source_provenance"]["anchors"]
        self.assertEqual(
            (anchors["pancakeswap-v3-bsc"]["commit"], anchors["pancakeswap-v3-bsc"]["tree"], anchors["pancakeswap-v3-bsc"]["parent"]),
            ("0c4618d6343b5011742a59ec308dd7ce07b9908b", "1a309dcd6e8827db41a00634eaab6d1e1ed70da6", "6af451686c1dc783f823e51b28686ef95d219c16"),
        )
        self.assertEqual(
            (anchors["uniswap-v3-base"]["commit"], anchors["uniswap-v3-base"]["tree"], anchors["uniswap-v3-base"]["parent"]),
            ("2c60bd10b5e1a090f6e3b55f0634f2a15ec91dbe", "3a2ff3eec89f6ab6f1f61d3c10a546c231c3f06b", "b16e506a84247a178a9eae09e799bc75787f4275"),
        )
        reproduction = contract["source_provenance"]["reproduction"]
        self.assertEqual((reproduction["source_template_spec_version"], reproduction["deployed_manifest_spec_version"]), ("0.0.2", "0.0.4"))
        self.assertTrue(reproduction["spec_version_mismatch"])
        self.assertEqual(reproduction["deleted_dependency"]["commit"], "b34b9003d7bf556836da41b57ef36eb21570620a")
        self.assertFalse(reproduction["deleted_dependency"]["available"])
        self.assertFalse(reproduction["deleted_dependency"]["frozen_yarn_install_succeeded"])
        self.assertFalse(reproduction["deleted_dependency"]["frozen_npm_install_succeeded"])
        self.assertEqual(set(contract["truth_boundary"]), set(MODULE.FALSE_GATES))
        self.assertTrue(all(value is False for value in contract["truth_boundary"].values()))

    def test_source_provenance_prose_drift_is_rejected(self) -> None:
        path = self.root / SOURCE_PATH
        path.write_text(path.read_text().replace("do not replace", "do now replace", 1))
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("source provenance SHA-256 drift", result.stderr)

    def test_duplicate_contract_json_key_is_rejected(self) -> None:
        path = self.root / CONTRACT_PATH
        text = path.read_text().replace(
            '  "artifact_count": 26,',
            '  "artifact_count": 26,\n  "artifact_count": 26,',
            1,
        )
        path.write_text(text)
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duplicate JSON key", result.stderr)

    def test_duplicate_manifest_yaml_key_is_rejected(self) -> None:
        path = self.root / "messari-v3/reference/uniswap-v3-base/deployment.yaml"
        path.write_text("specVersion: 0.0.4\n" + path.read_text())
        with self.assertRaisesRegex(MODULE.VerificationError, "duplicate YAML key"):
            MODULE.load_yaml_unique(path)

    def test_duplicate_abi_json_key_is_rejected(self) -> None:
        path = self.root / "messari-v3/reference/uniswap-v3-base/abis/Pool.json"
        path.write_text(path.read_text().replace('    "anonymous": false,', '    "anonymous": false,\n    "anonymous": false,', 1))
        with self.assertRaisesRegex(MODULE.VerificationError, "duplicate JSON key"):
            MODULE.load_json(path)

    def test_artifact_byte_drift_is_rejected(self) -> None:
        path = self.root / "messari-v3/reference/pancakeswap-v3-bsc/schema.graphql"
        payload = bytearray(path.read_bytes())
        payload[-2] ^= 1
        path.write_bytes(payload)
        self.assertNotEqual(self.verify().returncode, 0)

    def test_unexpected_retained_artifact_is_rejected(self) -> None:
        path = self.root / "messari-v3/reference/uniswap-v3-base/abis/Unexpected.json"
        path.write_text("[]\n")
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("artifact path closure drift", result.stderr)

    def test_unexpected_target_binding_is_rejected(self) -> None:
        path = self.root / "messari-v3/QmUnexpected.yaml"
        path.write_text("deployment: QmUnexpected\n")
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("binding path closure drift", result.stderr)

    def test_contract_relock_cannot_hide_artifact_drift(self) -> None:
        path = self.root / "messari-v3/reference/uniswap-v3-base/schema.graphql"
        payload = bytearray(path.read_bytes())
        payload[-2] ^= 1
        path.write_bytes(payload)
        contract = self.load_contract()
        record = next(item for item in contract["artifact_lock"] if item["target"] == "uniswap-v3-base" and item["role"] == "schema")
        record["bytes"] = len(payload)
        record["sha256"] = hashlib.sha256(payload).hexdigest()
        record["cid"] = MODULE.unixfs_file_cidv0(bytes(payload))
        self.write_contract(contract)
        self.assertNotEqual(self.verify().returncode, 0)

    def test_binding_semantic_drift_is_rejected(self) -> None:
        path = self.root / "messari-v3/QmQjVBdmgZdjHpQsXGSC5uryWLmPkkTAunHN2AnDApZBa3.yaml"
        path.write_text(path.read_text().replace("market_qpd: 143319", "market_qpd: 143320", 1))
        self.assertNotEqual(self.verify().returncode, 0)

    def test_qos_economics_are_not_mislabeled_as_signal(self) -> None:
        contract = self.load_contract()
        bindings = {item["target"]: item["value"] for item in contract["binding_lock"]}
        self.assertEqual(bindings["pancakeswap-v3-bsc"]["query_fees_grt_24h"], 170.760)
        self.assertEqual(bindings["uniswap-v3-base"]["query_fees_grt_24h"], 21.000)
        for binding in bindings.values():
            self.assertEqual(binding["qos_snapshot_at"], "2026-08-31T17:20:00Z")
            self.assertNotIn("signal_grt", binding)

    def test_manifest_semantic_drift_is_rejected_beyond_raw_lock(self) -> None:
        _, artifacts = MODULE.verify_artifacts(self.root)
        path = self.root / artifacts["uniswap-v3-base"]["deployment"]["vendored_path"]
        manifest = MODULE.load_yaml_unique(path)
        manifest["dataSources"][0]["network"] = "mainnet"
        with self.assertRaisesRegex(MODULE.VerificationError, "semantic projection drift"):
            MODULE.manifest_profile("uniswap-v3-base", manifest, artifacts["uniswap-v3-base"])

    def test_profile_metadata_normalization_is_rejected_after_contract_relock(self) -> None:
        profile = self.load_profile()
        primary = profile["targets"][0]["deployment"]["components"][2]
        primary["entities"].remove("LiqudityPool")
        primary["entity_metadata_contract"]["declared_order"].remove("LiqudityPool")
        primary["entity_metadata_contract"]["missing_from_schema_type_declarations"].remove("LiqudityPool")
        self.write_profile(profile)
        self.relock_profile_in_contract()
        self.assertNotEqual(self.verify().returncode, 0)

    def test_cross_target_diff_drift_is_rejected_after_contract_relock(self) -> None:
        profile = self.load_profile()
        profile["cross_target_diff"]["runtime_equivalence_claimed"] = True
        self.write_profile(profile)
        self.relock_profile_in_contract()
        self.assertNotEqual(self.verify().returncode, 0)

    def test_source_anchor_drift_is_rejected(self) -> None:
        contract = self.load_contract()
        contract["source_provenance"]["anchors"]["uniswap-v3-base"]["tree"] = "0" * 40
        self.write_contract(contract)
        self.assertNotEqual(self.verify().returncode, 0)

    def test_truth_gate_promotion_is_rejected(self) -> None:
        contract = self.load_contract()
        contract["truth_boundary"]["backfill_ready"] = True
        self.write_contract(contract)
        self.assertNotEqual(self.verify().returncode, 0)

    def test_source_document_metadata_evidence_is_byte_locked(self) -> None:
        path = self.root / SOURCE_PATH
        path.write_text(path.read_text().replace("`Token` exactly twice", "`Token` twice", 1))
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("source provenance byte count drift", result.stderr)

    def test_verifier_has_no_network_or_subprocess_imports(self) -> None:
        tree = ast.parse(VERIFIER.read_text())
        forbidden = {"aiohttp", "http", "httpx", "requests", "socket", "subprocess", "urllib"}
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".", 1)[0])
        self.assertEqual(imported & forbidden, set())


if __name__ == "__main__":
    unittest.main()
