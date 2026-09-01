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
VERIFIER = REPOSITORY / "scripts/verify-uniswap-v2-base-target.py"
DEPLOYMENT = "QmQmz5kh1f83Re1Zaj9UYrzKmcWqpKf1tNs9K6M9WrvPC8"
LOCK_PATH = Path("docs/provenance/uniswap-v2-base-target.json")
PROFILE_PATH = Path("uniswap-v2-base/layout-profile-v1.json")
BINDING_PATH = Path(f"uniswap-v2-base/{DEPLOYMENT}.yaml")
README_PATH = Path("README.md")
FALSE_GATE_NAMES = (
    "eligibility_complete",
    "source_revision_pinned",
    "source_reproducible",
    "implementation_complete",
    "runtime_complete",
    "runtime_parity",
    "logical_parity",
    "history_complete",
    "physical_profile_complete",
    "physical_parity",
    "poi_parity",
    "backfill_ready",
    "production_ready",
    "readiness",
    "issue_87_complete",
    "issue_89_complete",
    "issue_93_complete",
)


class UniswapV2BaseTargetTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        shutil.copytree(REPOSITORY / "uniswap-v2-base", self.root / "uniswap-v2-base")
        (self.root / LOCK_PATH.parent).mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPOSITORY / LOCK_PATH, self.root / LOCK_PATH)
        shutil.copy2(REPOSITORY / README_PATH, self.root / README_PATH)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def setUp_surface_reset(self) -> None:
        shutil.rmtree(self.root / "uniswap-v2-base")
        shutil.copytree(REPOSITORY / "uniswap-v2-base", self.root / "uniswap-v2-base")
        shutil.copy2(REPOSITORY / LOCK_PATH, self.root / LOCK_PATH)
        shutil.copy2(REPOSITORY / README_PATH, self.root / README_PATH)

    def verify(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(VERIFIER), "--root", str(self.root)],
            check=False,
            capture_output=True,
            text=True,
        )

    def load_lock(self) -> dict:
        return json.loads((self.root / LOCK_PATH).read_text(encoding="utf-8"))

    def write_lock(self, lock: dict) -> None:
        (self.root / LOCK_PATH).write_text(
            json.dumps(lock, indent=2) + "\n", encoding="utf-8"
        )

    def load_profile(self) -> dict:
        return json.loads((self.root / PROFILE_PATH).read_text(encoding="utf-8"))

    def write_profile(self, profile: dict) -> None:
        (self.root / PROFILE_PATH).write_text(
            json.dumps(profile, indent=2) + "\n", encoding="utf-8"
        )

    def relock_vendored(self, role: str) -> None:
        lock = self.load_lock()
        record = next(item for item in lock["artifact_lock"] if item["role"] == role)
        payload = (self.root / record["vendored_path"]).read_bytes()
        record["vendored_bytes"] = len(payload)
        record["vendored_sha256"] = hashlib.sha256(payload).hexdigest()
        if record["normalization"] == "remove_one_trailing_lf":
            payload = payload[:-1]
        record["source_bytes"] = len(payload)
        record["source_sha256"] = hashlib.sha256(payload).hexdigest()
        self.write_lock(lock)

    def relock_profile(self) -> None:
        lock = self.load_lock()
        payload = (self.root / PROFILE_PATH).read_bytes()
        lock["layout_profile"]["bytes"] = len(payload)
        lock["layout_profile"]["sha256"] = hashlib.sha256(payload).hexdigest()
        self.write_lock(lock)

    def binding_text(self) -> str:
        return (self.root / BINDING_PATH).read_text(encoding="utf-8")

    def write_binding_text(self, value: str) -> None:
        (self.root / BINDING_PATH).write_text(value, encoding="utf-8")

    def test_exact_baseline_passes(self) -> None:
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_manifest_byte_drift_is_rejected(self) -> None:
        manifest = self.root / "uniswap-v2-base/reference/deployment.yaml"
        manifest.write_text(
            manifest.read_text(encoding="utf-8") + "\n", encoding="utf-8"
        )
        self.assertNotEqual(self.verify().returncode, 0)

    def test_factory_address_drift_is_rejected_even_if_relocked(self) -> None:
        manifest = self.root / "uniswap-v2-base/reference/deployment.yaml"
        manifest.write_text(
            manifest.read_text(encoding="utf-8").replace(
                "0x8909Dc15e40173Ff4699343b6eB8132c65e18eC6",
                "0x0000000000000000000000000000000000000001",
            ),
            encoding="utf-8",
        )
        self.relock_vendored("deployment")
        self.assertNotEqual(self.verify().returncode, 0)

    def test_pair_handler_reordering_is_rejected_even_if_relocked(self) -> None:
        manifest = self.root / "uniswap-v2-base/reference/deployment.yaml"
        text = manifest.read_text(encoding="utf-8")
        mint = "        - event: Mint(indexed address,uint256,uint256)\n          handler: handleMint\n"
        burn = (
            "        - event: Burn(indexed address,uint256,uint256,indexed address)\n"
            "          handler: handleBurn\n"
        )
        manifest.write_text(text.replace(mint + burn, burn + mint), encoding="utf-8")
        self.relock_vendored("deployment")
        self.assertNotEqual(self.verify().returncode, 0)

    def test_transfer_handler_removal_is_rejected_even_if_relocked(self) -> None:
        manifest = self.root / "uniswap-v2-base/reference/deployment.yaml"
        transfer = (
            "        - event: Transfer(indexed address,indexed address,uint256)\n"
            "          handler: handleTransfer\n"
        )
        manifest.write_text(
            manifest.read_text(encoding="utf-8").replace(transfer, ""), encoding="utf-8"
        )
        self.relock_vendored("deployment")
        self.assertNotEqual(self.verify().returncode, 0)

    def test_schema_mutability_drift_is_rejected_even_if_relocked(self) -> None:
        schema = self.root / "uniswap-v2-base/reference/schema.graphql"
        schema.write_text(
            schema.read_text(encoding="utf-8").replace(
                "type Swap @entity(immutable: false)",
                "type Swap @entity(immutable: true)",
            ),
            encoding="utf-8",
        )
        self.relock_vendored("schema")
        self.assertNotEqual(self.verify().returncode, 0)

    def test_derived_field_drift_is_rejected_even_if_relocked(self) -> None:
        schema = self.root / "uniswap-v2-base/reference/schema.graphql"
        schema.write_text(
            schema.read_text(encoding="utf-8").replace(
                'mints: [Mint!]! @derivedFrom(field: "pair")',
                "mints: [Mint!]!",
            ),
            encoding="utf-8",
        )
        self.relock_vendored("schema")
        self.assertNotEqual(self.verify().returncode, 0)

    def test_generic_transfer_promotion_is_rejected_after_profile_relock(self) -> None:
        profile = self.load_profile()
        profile["generic_event_extractor"]["pair_transfer_supported"] = True
        self.write_profile(profile)
        self.relock_profile()
        self.assertNotEqual(self.verify().returncode, 0)

    def test_generic_factory_filter_promotion_is_rejected_after_profile_relock(
        self,
    ) -> None:
        profile = self.load_profile()
        profile["generic_event_extractor"]["target_factory_filter_supported"] = True
        self.write_profile(profile)
        self.relock_profile()
        self.assertNotEqual(self.verify().returncode, 0)

    def test_generic_dynamic_pair_filter_promotion_is_rejected_after_profile_relock(
        self,
    ) -> None:
        profile = self.load_profile()
        profile["generic_event_extractor"][
            "dynamic_pair_membership_filter_supported"
        ] = True
        self.write_profile(profile)
        self.relock_profile()
        self.assertNotEqual(self.verify().returncode, 0)

    def test_runtime_gate_promotion_is_rejected_after_profile_relock(self) -> None:
        profile = self.load_profile()
        profile["truth_gates"]["runtime_parity"] = True
        self.write_profile(profile)
        self.relock_profile()
        self.assertNotEqual(self.verify().returncode, 0)

    def test_exact_source_reproduction_promotion_is_rejected(self) -> None:
        lock = self.load_lock()
        lock["source_evidence"]["exact_output_reproduction"] = True
        lock["truth_gates"]["source_reproducible"] = True
        self.write_lock(lock)
        self.assertNotEqual(self.verify().returncode, 0)

    def test_mapping_digest_lock_drift_is_rejected(self) -> None:
        lock = self.load_lock()
        record = next(
            item
            for item in lock["artifact_lock"]
            if item["role"] == "factory_mapping_wasm"
        )
        record["source_sha256"] = "0" * 64
        self.write_lock(lock)
        self.assertNotEqual(self.verify().returncode, 0)

    def test_vendored_mapping_byte_drift_is_rejected(self) -> None:
        path = self.root / "uniswap-v2-base/reference/mappings/Factory.wasm"
        payload = bytearray(path.read_bytes())
        payload[-1] ^= 1
        path.write_bytes(payload)
        self.assertNotEqual(self.verify().returncode, 0)

    def test_vendored_mapping_handler_export_drift_is_rejected_even_if_relocked(
        self,
    ) -> None:
        path = self.root / "uniswap-v2-base/reference/mappings/Pair.wasm"
        payload = path.read_bytes().replace(b"handleTransfer", b"xandleTransfer", 1)
        self.assertNotEqual(payload, path.read_bytes())
        path.write_bytes(payload)
        self.relock_vendored("pair_mapping_wasm")
        self.assertNotEqual(self.verify().returncode, 0)

    def test_binding_required_field_omission_is_rejected(self) -> None:
        self.write_binding_text(
            self.binding_text().replace("display_name: Uniswap V2 Base\n", "")
        )
        self.assertNotEqual(self.verify().returncode, 0)

    def test_binding_unknown_top_level_field_is_rejected(self) -> None:
        self.write_binding_text(self.binding_text() + "runtime_ready: true\n")
        self.assertNotEqual(self.verify().returncode, 0)

    def test_binding_identity_schema_and_m8_drift_are_rejected(self) -> None:
        original = self.binding_text()
        replacements = (
            ("display_name: Uniswap V2 Base", "display_name: Invented V2"),
            (
                "schema: QmeyYQ8ZJnzuQsoXnizGXLyFSt7mcuRNkmNQxMv3pXiMnW",
                "schema: Qm11111111111111111111111111111111111111111111",
            ),
            ("milestone: M8", "milestone: M0"),
            (
                "status: immutable_target_pinned_source_revision_unresolved",
                "status: immutable_target_and_source_pinned",
            ),
        )
        for old, new in replacements:
            with self.subTest(new=new):
                self.write_binding_text(original.replace(old, new))
                self.assertNotEqual(self.verify().returncode, 0)

    def test_market_snapshot_omission_is_rejected(self) -> None:
        block = (
            "market_snapshot:\n"
            '  measured_at: "2026-08-31T17:20:00Z"\n'
            "  queries_24h: 780953\n"
            '  query_fees_grt_24h: "954.416540"\n'
            "  authority: https://github.com/pinax-network/substreams-backfills/issues/83\n"
        )
        self.write_binding_text(self.binding_text().replace(block, ""))
        self.assertNotEqual(self.verify().returncode, 0)

    def test_market_snapshot_non_object_is_rejected(self) -> None:
        text = self.binding_text()
        start = text.index("market_snapshot:\n")
        end = text.index("target_reference:\n")
        self.write_binding_text(
            text[:start] + "market_snapshot: omitted\n" + text[end:]
        )
        self.assertNotEqual(self.verify().returncode, 0)

    def test_market_snapshot_query_count_type_drift_is_rejected(self) -> None:
        original = self.binding_text()
        for replacement in ('  queries_24h: "780953"', "  queries_24h: true"):
            with self.subTest(replacement=replacement):
                self.write_binding_text(
                    original.replace("  queries_24h: 780953", replacement)
                )
                self.assertNotEqual(self.verify().returncode, 0)

    def test_market_snapshot_numeric_fee_is_rejected(self) -> None:
        self.write_binding_text(
            self.binding_text().replace(
                '  query_fees_grt_24h: "954.416540"', "  query_fees_grt_24h: 954.416540"
            )
        )
        self.assertNotEqual(self.verify().returncode, 0)

    def test_market_snapshot_precision_drift_is_rejected(self) -> None:
        original = self.binding_text()
        for value in ("954.41654", "954.4165400"):
            with self.subTest(value=value):
                self.write_binding_text(
                    original.replace(
                        '  query_fees_grt_24h: "954.416540"',
                        f'  query_fees_grt_24h: "{value}"',
                    )
                )
                self.assertNotEqual(self.verify().returncode, 0)

    def test_market_snapshot_authority_drift_is_rejected(self) -> None:
        self.write_binding_text(
            self.binding_text().replace(
                "authority: https://github.com/pinax-network/substreams-backfills/issues/83",
                "authority: https://github.com/pinax-network/substreams-backfills/issues/87",
            )
        )
        self.assertNotEqual(self.verify().returncode, 0)

    def test_market_snapshot_timestamp_or_query_value_drift_is_rejected(self) -> None:
        original = self.binding_text()
        replacements = (
            ("2026-08-31T17:20:00Z", "2026-08-31T17:20:01Z"),
            ("  queries_24h: 780953", "  queries_24h: 780954"),
        )
        for old, new in replacements:
            with self.subTest(new=new):
                self.write_binding_text(original.replace(old, new))
                self.assertNotEqual(self.verify().returncode, 0)

    def test_market_snapshot_wrong_placement_is_rejected(self) -> None:
        self.write_binding_text(
            self.binding_text().replace("market_snapshot:", "target_market_snapshot:")
        )
        self.assertNotEqual(self.verify().returncode, 0)

    def test_legacy_or_flat_market_fields_are_rejected(self) -> None:
        original = self.binding_text()
        for field in (
            "market_qpd",
            "qos_snapshot_at",
            "signal_grt",
            "grt_24h",
            "generic_grt",
            "queries_24h",
            "query_fees_grt_24h",
        ):
            with self.subTest(field=field):
                self.write_binding_text(original + f"{field}: 1\n")
                self.assertNotEqual(self.verify().returncode, 0)

    def test_truth_gate_omission_is_rejected_on_every_surface(self) -> None:
        lock = self.load_lock()
        del lock["truth_gates"]["poi_parity"]
        self.write_lock(lock)
        self.assertNotEqual(self.verify().returncode, 0)

        self.setUp_surface_reset()
        profile = self.load_profile()
        del profile["truth_gates"]["poi_parity"]
        self.write_profile(profile)
        self.relock_profile()
        self.assertNotEqual(self.verify().returncode, 0)

        self.setUp_surface_reset()
        self.write_binding_text(
            self.binding_text().replace("  poi_parity: false\n", "")
        )
        self.assertNotEqual(self.verify().returncode, 0)

    def test_truth_gate_extra_is_rejected_on_every_surface(self) -> None:
        lock = self.load_lock()
        lock["truth_gates"]["invented_ready"] = False
        self.write_lock(lock)
        self.assertNotEqual(self.verify().returncode, 0)

        self.setUp_surface_reset()
        profile = self.load_profile()
        profile["truth_gates"]["invented_ready"] = False
        self.write_profile(profile)
        self.relock_profile()
        self.assertNotEqual(self.verify().returncode, 0)

        self.setUp_surface_reset()
        self.write_binding_text(
            self.binding_text().replace(
                "  eligibility_complete: false\n",
                "  eligibility_complete: false\n  invented_ready: false\n",
            )
        )
        self.assertNotEqual(self.verify().returncode, 0)

    def test_legacy_truth_gate_name_is_rejected_on_every_surface(self) -> None:
        lock = self.load_lock()
        lock["truth_gates"]["implementation_started"] = lock["truth_gates"].pop(
            "implementation_complete"
        )
        self.write_lock(lock)
        self.assertNotEqual(self.verify().returncode, 0)

        self.setUp_surface_reset()
        profile = self.load_profile()
        profile["truth_gates"]["implementation_started"] = profile["truth_gates"].pop(
            "implementation_complete"
        )
        self.write_profile(profile)
        self.relock_profile()
        self.assertNotEqual(self.verify().returncode, 0)

        self.setUp_surface_reset()
        self.write_binding_text(
            self.binding_text().replace(
                "  implementation_complete: false", "  implementation_started: false"
            )
        )
        self.assertNotEqual(self.verify().returncode, 0)

    def test_every_false_gate_promotion_is_rejected_on_every_surface(self) -> None:
        for surface in ("provenance", "profile", "binding"):
            for gate in FALSE_GATE_NAMES:
                with self.subTest(surface=surface, gate=gate):
                    self.setUp_surface_reset()
                    if surface == "provenance":
                        lock = self.load_lock()
                        lock["truth_gates"][gate] = True
                        self.write_lock(lock)
                    elif surface == "profile":
                        profile = self.load_profile()
                        profile["truth_gates"][gate] = True
                        self.write_profile(profile)
                        self.relock_profile()
                    else:
                        self.write_binding_text(
                            self.binding_text().replace(
                                f"  {gate}: false", f"  {gate}: true"
                            )
                        )
                    self.assertNotEqual(self.verify().returncode, 0)

    def test_profile_eligibility_contract_drift_is_rejected(self) -> None:
        mutations = (
            ("required_clusters", ["riv-subgraphs-a"]),
            ("copy_selection", "first_copy"),
            ("required_windows", ["24h"]),
            ("eligible_when", "any_window_exceeds_28_days"),
            ("stop_when", "never"),
            ("no_viable_copy", "missing_attachment_is_eligible"),
        )
        for field, value in mutations:
            with self.subTest(field=field):
                self.setUp_surface_reset()
                profile = self.load_profile()
                profile["eligibility_contract"][field] = value
                self.write_profile(profile)
                self.relock_profile()
                self.assertNotEqual(self.verify().returncode, 0)

    def test_binding_eligibility_policy_or_cluster_drift_is_rejected(self) -> None:
        original = self.binding_text()
        replacements = (
            ("policy: graph-node-net-catchup-v1", "policy: invented-policy"),
            (
                "required_clusters: [riv-subgraphs-a, kan-subgraphs-a]",
                "required_clusters: [riv-subgraphs-a]",
            ),
        )
        for old, new in replacements:
            with self.subTest(new=new):
                self.write_binding_text(original.replace(old, new))
                self.assertNotEqual(self.verify().returncode, 0)

    def test_m8_roadmap_is_bounded_and_link_drift_is_rejected(self) -> None:
        path = self.root / README_PATH
        original = path.read_text(encoding="utf-8")
        marker = "8. **M8 — Uniswap V2 Base**"

        later_milestone_change = original.replace(
            "`#85 + #94 -> #90 -> #92 -> #95`",
            "`independently verified future DAG`",
            1,
        ).replace(
            "\n\nMorpho Blue Base remains outside implementation",
            "\n10. **M10 — Future family**: independently verified roadmap entry."
            "\n\nMorpho Blue Base remains outside implementation",
            1,
        )
        self.assertNotEqual(later_milestone_change, original)
        self.assertIn("10. **M10 — Future family**", later_milestone_change)
        path.write_text(later_milestone_change, encoding="utf-8")
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stderr)

        prefix, section = original.split(marker, 1)
        reordered = section.replace("issues/89", "issues/TEMP", 1)
        reordered = reordered.replace("issues/93", "issues/89", 1)
        reordered = reordered.replace("issues/TEMP", "issues/93", 1)
        mutations = {
            "omission": original.replace(
                "[#89](https://github.com/pinax-network/substreams-backfills/issues/89), then differential\n",
                "differential\n",
                1,
            ),
            "extra": original.replace(
                "[#93](https://github.com/pinax-network/substreams-backfills/issues/93). M8 orders work\n",
                "[#93](https://github.com/pinax-network/substreams-backfills/issues/93), then\n"
                "   [#999](https://github.com/pinax-network/substreams-backfills/issues/999). M8 orders work\n",
                1,
            ),
            "reorder": prefix + marker + reordered,
        }
        for name, mutated in mutations.items():
            with self.subTest(name=name):
                path.write_text(mutated, encoding="utf-8")
                self.assertNotEqual(self.verify().returncode, 0)

    def test_eligibility_promotion_without_evidence_is_rejected(self) -> None:
        binding = self.root / BINDING_PATH
        binding.write_text(
            binding.read_text(encoding="utf-8").replace(
                "decision: indeterminate", "decision: eligible"
            ),
            encoding="utf-8",
        )
        self.assertNotEqual(self.verify().returncode, 0)

    def test_duplicate_manifest_key_is_rejected(self) -> None:
        manifest = self.root / "uniswap-v2-base/reference/deployment.yaml"
        manifest.write_text(
            manifest.read_text(encoding="utf-8") + "specVersion: 0.0.8\n",
            encoding="utf-8",
        )
        self.relock_vendored("deployment")
        self.assertNotEqual(self.verify().returncode, 0)

    def test_duplicate_provenance_key_is_rejected(self) -> None:
        path = self.root / LOCK_PATH
        text = path.read_text(encoding="utf-8")
        path.write_text(
            text.replace(
                '{\n  "format_version": 1,',
                '{\n  "format_version": 1,\n  "format_version": 1,',
            ),
            encoding="utf-8",
        )
        self.assertNotEqual(self.verify().returncode, 0)

    def test_untracked_target_artifact_is_rejected(self) -> None:
        (self.root / "uniswap-v2-base/reference/unlocked.wasm").write_bytes(
            b"not locked"
        )
        self.assertNotEqual(self.verify().returncode, 0)


if __name__ == "__main__":
    unittest.main()
