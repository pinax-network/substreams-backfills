from __future__ import annotations

import copy
import hashlib
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY / "scripts"))

from eligibility import (  # noqa: E402
    EligibilityError,
    build_evidence,
    canonical_json,
    check_fresh_gate,
    load_policy,
    validate_binding,
    validate_binding_evidence,
    validate_evidence,
)


MEASURED_AT = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)


def timestamp(value: datetime) -> str:
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def binding() -> dict:
    return {
        "deployment": "QmY67iZDTsTdpWXSCotpVPYankwnyHXNT7N95YEn8ccUsn",
        "family": "exchange-v3-bsc",
        "chain": "bsc",
        "eligibility": {
            "policy": "graph-node-net-catchup-v1",
            "required_clusters": ["riv-subgraphs-a", "kan-subgraphs-a"],
            "latest": {
                "decision": "indeterminate",
                "reason": "no_fresh_evidence",
                "measured_at": None,
                "evidence": None,
                "sha256": None,
            },
        },
    }


def point(when: datetime, deployment_head: int, chain_head: int, *, observed_offset: int = 0) -> dict:
    observed = when + timedelta(seconds=observed_offset)
    return {
        "requested_at": timestamp(when),
        "deployment_observed_at": timestamp(observed),
        "deployment_head": deployment_head,
        "chain_observed_at": timestamp(observed),
        "chain_head": chain_head,
    }


def window(name: str, *, lag: int = 3_000, net_per_day: int = 100, stale: bool = False) -> dict:
    days = 1 if name == "24h" else 3
    chain_end = 100_000
    deployment_end = chain_end - lag
    chain_delta = 100 * days
    net_delta = net_per_day * days
    deployment_delta = chain_delta + net_delta
    start = MEASURED_AT - timedelta(days=days)
    offset = -601 if stale else 0
    return {
        "start": point(
            start,
            deployment_end - deployment_delta,
            chain_end - chain_delta,
            observed_offset=offset,
        ),
        "end": point(MEASURED_AT, deployment_end, chain_end),
    }


def healthy_copy(
    copy_id: str,
    *,
    lag: int = 3_000,
    net_24h: int = 100,
    net_72h: int = 100,
    synced: bool = False,
    failed: bool = False,
    stale_window: bool = False,
) -> dict:
    return {
        "copy_id": copy_id,
        "selector": {"pod": copy_id.replace("/", "-")},
        "current": {
            "observed_at": timestamp(MEASURED_AT),
            "active": True,
            "attached": True,
            "health": "failed" if failed else "healthy",
            "status": "failed" if failed else "indexing",
            "failed": failed,
            "synced": synced,
            "deployment_head": 100_000 - lag,
            "chain_head": 100_000,
        },
        "windows": {}
        if synced or failed
        else {
            "24h": window("24h", lag=lag, net_per_day=net_24h, stale=stale_window),
            "72h": window("72h", lag=lag, net_per_day=net_72h),
        },
    }


def blocker(kind: str = "missing_attached_version") -> dict:
    return {
        "type": kind,
        "observed_at": timestamp(MEASURED_AT),
        "source": "read-only status and deployment inventory",
        "details": "No viable attached version exists in this cluster.",
    }


def cluster(name: str, copies: list[dict] | None = None, blockers: list[dict] | None = None) -> dict:
    return {
        "cluster": name,
        "accounted": True,
        "copies": copies or [],
        "structural_blockers": blockers or [],
    }


def measurements(clusters: list[dict]) -> dict:
    return {
        "measured_at": timestamp(MEASURED_AT),
        "collector": {"version": 1, "repository_commit": "a" * 40},
        "sources": {
            "status_api": ["read-only snapshot"],
            "victoriametrics": {"queries": ["deployment_head", "ethereum_chain_head_number"]},
            "postgres_inventory": ["read-only deployment and graft inventory"],
        },
        "clusters": clusters,
    }


class EligibilityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policy = load_policy(REPOSITORY / "eligibility/policy-v1.yaml")

    def build(self, clusters: list[dict]) -> dict:
        return build_evidence(measurements(clusters), binding(), self.policy)

    def test_empty_binding_is_fail_closed(self) -> None:
        validate_binding(binding(), self.policy)

    def test_exact_market_snapshot_is_valid(self) -> None:
        candidate = binding()
        candidate["market_snapshot"] = {
            "measured_at": "2026-08-31T17:20:00Z",
            "queries_24h": 73997,
            "query_fees_grt_24h": "171.957",
            "authority": "https://github.com/pinax-network/substreams-backfills/issues/83",
        }
        validate_binding(candidate, self.policy)

    def test_ambiguous_legacy_market_fields_are_rejected(self) -> None:
        for field, value in (
            ("market_qpd", 1900000),
            ("qos_snapshot_at", "2026-08-31T17:20:00Z"),
            ("signal_grt", 14324),
            ("grt_24h", "171.957"),
            ("generic_grt", "171.957"),
            ("queries_24h", 73997),
            ("query_fees_grt_24h", "171.957"),
        ):
            with self.subTest(field=field):
                candidate = binding()
                candidate[field] = value
                with self.assertRaises(EligibilityError):
                    validate_binding(candidate, self.policy)

    def test_market_snapshot_shape_and_types_are_fail_closed(self) -> None:
        baseline = {
            "measured_at": "2026-08-31T17:20:00Z",
            "queries_24h": 73997,
            "query_fees_grt_24h": "171.957",
            "authority": "https://github.com/pinax-network/substreams-backfills/issues/83",
        }
        mutations = {
            "numeric fees": {"query_fees_grt_24h": 171.957},
            "generic fee label": {"query_fees_grt_24h": None, "grt_24h": "171.957"},
            "noncanonical timestamp": {"measured_at": "2026-08-31T17:20:00.000Z"},
            "external authority": {"authority": "https://example.invalid/issues/83"},
            "boolean queries": {"queries_24h": True},
        }
        for name, mutation in mutations.items():
            with self.subTest(name=name):
                snapshot = copy.deepcopy(baseline)
                if mutation.get("query_fees_grt_24h", "unchanged") is None:
                    del snapshot["query_fees_grt_24h"]
                snapshot.update(
                    {key: value for key, value in mutation.items() if value is not None}
                )
                candidate = binding()
                candidate["market_snapshot"] = snapshot
                with self.assertRaises(EligibilityError):
                    validate_binding(candidate, self.policy)

    def test_both_windows_above_threshold_are_eligible(self) -> None:
        evidence = self.build(
            [
                cluster("riv-subgraphs-a", [healthy_copy("riv/copy")]),
                cluster("kan-subgraphs-a", blockers=[blocker()]),
            ]
        )
        self.assertEqual(evidence["summary"]["decision"], "eligible")
        self.assertEqual(evidence["summary"]["reason"], "both_windows_exceed_threshold")
        validate_evidence(evidence, binding(), self.policy)

    def test_exactly_28_days_does_not_qualify(self) -> None:
        evidence = self.build(
            [
                cluster("riv-subgraphs-a", [healthy_copy("riv/copy", lag=2_800)]),
                cluster("kan-subgraphs-a", blockers=[blocker()]),
            ]
        )
        self.assertEqual(evidence["summary"]["decision"], "monitor")

    def test_either_fast_window_keeps_native_sync(self) -> None:
        evidence = self.build(
            [
                cluster("riv-subgraphs-a", [healthy_copy("riv/copy", net_24h=150, net_72h=90)]),
                cluster("kan-subgraphs-a", blockers=[blocker()]),
            ]
        )
        self.assertEqual(evidence["summary"]["decision"], "monitor")

    def test_non_positive_rates_are_eligible(self) -> None:
        evidence = self.build(
            [
                cluster("riv-subgraphs-a", [healthy_copy("riv/copy", net_24h=0, net_72h=-10)]),
                cluster("kan-subgraphs-a", blockers=[blocker()]),
            ]
        )
        self.assertEqual(evidence["summary"], {
            "decision": "eligible",
            "reason": "non_positive_net_rate",
            "threshold_days": 28,
            "fastest_24h": {"copy_id": "riv/copy", "eta_days": None, "eta_kind": "infinite"},
            "fastest_72h": {"copy_id": "riv/copy", "eta_days": None, "eta_kind": "infinite"},
        })

    def test_fastest_copy_across_clusters_wins(self) -> None:
        evidence = self.build(
            [
                cluster("riv-subgraphs-a", [healthy_copy("riv/slow", net_24h=50, net_72h=50)]),
                cluster("kan-subgraphs-a", [healthy_copy("kan/fast", net_24h=200, net_72h=200)]),
            ]
        )
        self.assertEqual(evidence["summary"]["decision"], "monitor")
        self.assertEqual(evidence["summary"]["fastest_24h"]["copy_id"], "kan/fast")

    def test_synced_healthy_copy_is_complete(self) -> None:
        evidence = self.build(
            [
                cluster("riv-subgraphs-a", [healthy_copy("riv/synced", synced=True)]),
                cluster("kan-subgraphs-a", blockers=[blocker()]),
            ]
        )
        self.assertEqual(evidence["summary"]["decision"], "complete")

    def test_failed_duplicate_does_not_poison_healthy_copy(self) -> None:
        failed = healthy_copy("riv/failed", failed=True)
        failed["current"]["observed_at"] = timestamp(MEASURED_AT - timedelta(days=30))
        evidence = self.build(
            [
                cluster("riv-subgraphs-a", [failed, healthy_copy("riv/healthy")]),
                cluster("kan-subgraphs-a", blockers=[blocker()]),
            ]
        )
        self.assertEqual(evidence["summary"]["decision"], "eligible")

    def test_failed_copy_in_other_cluster_does_not_poison_healthy_copy(self) -> None:
        evidence = self.build(
            [
                cluster(
                    "riv-subgraphs-a",
                    [healthy_copy("riv/failed", failed=True)],
                ),
                cluster("kan-subgraphs-a", [healthy_copy("kan/healthy")]),
            ]
        )
        self.assertEqual(evidence["summary"]["decision"], "eligible")
        self.assertEqual(evidence["summary"]["fastest_24h"]["copy_id"], "kan/healthy")

    def test_stopped_copy_in_other_cluster_does_not_poison_healthy_copy(self) -> None:
        stopped = healthy_copy("riv/stopped")
        stopped["current"].update({"active": False, "status": "stopped"})
        stopped["windows"] = {}
        evidence = self.build(
            [
                cluster("riv-subgraphs-a", [stopped]),
                cluster("kan-subgraphs-a", [healthy_copy("kan/healthy")]),
            ]
        )
        self.assertEqual(evidence["summary"]["decision"], "eligible")
        self.assertEqual(evidence["summary"]["fastest_72h"]["copy_id"], "kan/healthy")

    def test_failed_only_copy_does_not_qualify(self) -> None:
        evidence = self.build(
            [
                cluster("riv-subgraphs-a", [healthy_copy("riv/failed", failed=True)]),
                cluster("kan-subgraphs-a", blockers=[blocker()]),
            ]
        )
        self.assertEqual(evidence["summary"]["decision"], "indeterminate")
        self.assertEqual(evidence["summary"]["reason"], "no_healthy_copy")

    def test_proven_structural_blockers_are_eligible(self) -> None:
        evidence = self.build(
            [
                cluster("riv-subgraphs-a", blockers=[blocker("missing_graft_base")]),
                cluster("kan-subgraphs-a", blockers=[blocker("missing_graft_base")]),
            ]
        )
        self.assertEqual(evidence["summary"]["decision"], "eligible")
        self.assertEqual(evidence["summary"]["reason"], "missing_graft_base")

    def test_stale_structural_proof_is_indeterminate(self) -> None:
        stale_blocker = blocker()
        stale_blocker["observed_at"] = timestamp(MEASURED_AT - timedelta(seconds=601))
        evidence = self.build(
            [
                cluster("riv-subgraphs-a", blockers=[stale_blocker]),
                cluster("kan-subgraphs-a", blockers=[blocker()]),
            ]
        )
        self.assertEqual(evidence["summary"]["decision"], "indeterminate")
        self.assertEqual(evidence["summary"]["reason"], "stale_or_incomplete_samples")

    def test_healthy_copy_conflicting_with_structural_absence_is_indeterminate(self) -> None:
        evidence = self.build(
            [
                cluster("riv-subgraphs-a", [healthy_copy("riv/copy")], blockers=[blocker()]),
                cluster("kan-subgraphs-a", blockers=[blocker()]),
            ]
        )
        self.assertEqual(evidence["summary"]["decision"], "indeterminate")
        self.assertEqual(evidence["summary"]["reason"], "conflicting_identity")

    def test_failed_attached_copy_conflicts_with_missing_version_claim(self) -> None:
        evidence = self.build(
            [
                cluster(
                    "riv-subgraphs-a",
                    [healthy_copy("riv/failed", failed=True)],
                    blockers=[blocker("missing_attached_version")],
                ),
                cluster("kan-subgraphs-a", blockers=[blocker()]),
            ]
        )
        self.assertEqual(evidence["summary"]["decision"], "indeterminate")
        self.assertEqual(evidence["summary"]["reason"], "conflicting_identity")

    def test_missing_cluster_is_indeterminate(self) -> None:
        evidence = self.build([cluster("riv-subgraphs-a", [healthy_copy("riv/copy")])])
        self.assertEqual(evidence["summary"]["decision"], "indeterminate")
        self.assertEqual(evidence["summary"]["reason"], "missing_required_cluster")

    def test_stale_window_is_indeterminate(self) -> None:
        evidence = self.build(
            [
                cluster("riv-subgraphs-a", [healthy_copy("riv/copy", stale_window=True)]),
                cluster("kan-subgraphs-a", blockers=[blocker()]),
            ]
        )
        self.assertEqual(evidence["summary"]["reason"], "stale_or_incomplete_samples")

    def test_head_regression_is_indeterminate(self) -> None:
        item = healthy_copy("riv/copy")
        item["windows"]["24h"]["start"]["deployment_head"] = 99_000
        item["windows"]["24h"]["end"]["deployment_head"] = 98_000
        evidence = self.build(
            [cluster("riv-subgraphs-a", [item]), cluster("kan-subgraphs-a", blockers=[blocker()])]
        )
        self.assertEqual(evidence["summary"]["reason"], "head_regression")

    def test_calculation_tampering_is_rejected(self) -> None:
        evidence = self.build(
            [
                cluster("riv-subgraphs-a", [healthy_copy("riv/copy")]),
                cluster("kan-subgraphs-a", blockers=[blocker()]),
            ]
        )
        tampered = copy.deepcopy(evidence)
        tampered["clusters"][0]["copies"][0]["windows"]["24h"]["eta_days"] = "1.000000"
        with self.assertRaisesRegex(EligibilityError, "calculated fields"):
            validate_evidence(tampered, binding(), self.policy)

    def test_binding_digest_pins_exact_evidence_bytes(self) -> None:
        evidence = self.build(
            [
                cluster("riv-subgraphs-a", [healthy_copy("riv/copy")]),
                cluster("kan-subgraphs-a", blockers=[blocker()]),
            ]
        )
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)
            relative = Path("evidence/eligibility") / binding()["deployment"] / "20260827T120000Z.json"
            evidence_path = repository / relative
            evidence_path.parent.mkdir(parents=True)
            contents = canonical_json(evidence)
            evidence_path.write_bytes(contents)
            target = binding()
            target["eligibility"]["latest"] = {
                "decision": evidence["summary"]["decision"],
                "reason": evidence["summary"]["reason"],
                "measured_at": evidence["measured_at"],
                "evidence": relative.as_posix(),
                "sha256": hashlib.sha256(contents).hexdigest(),
            }
            validate_binding(target, self.policy)
            self.assertEqual(validate_binding_evidence(target, self.policy, repository), evidence)
            evidence_path.write_bytes(contents + b" ")
            with self.assertRaisesRegex(EligibilityError, "digest mismatch"):
                validate_binding_evidence(target, self.policy, repository)

    def test_binding_evidence_filename_must_match_timestamp(self) -> None:
        target = binding()
        target["eligibility"]["latest"] = {
            "decision": "eligible",
            "reason": "both_windows_exceed_threshold",
            "measured_at": timestamp(MEASURED_AT),
            "evidence": (
                f"evidence/eligibility/{target['deployment']}/20260827T120001Z.json"
            ),
            "sha256": "a" * 64,
        }
        with self.assertRaisesRegex(EligibilityError, "filename must match"):
            validate_binding(target, self.policy)

    def test_source_provenance_is_required(self) -> None:
        raw = measurements(
            [
                cluster("riv-subgraphs-a", [healthy_copy("riv/copy")]),
                cluster("kan-subgraphs-a", blockers=[blocker()]),
            ]
        )
        raw["sources"]["victoriametrics"]["queries"] = []
        with self.assertRaisesRegex(EligibilityError, "VictoriaMetrics queries"):
            build_evidence(raw, binding(), self.policy)

    def test_action_gate_expires_without_mutating_history(self) -> None:
        evidence = self.build(
            [
                cluster("riv-subgraphs-a", [healthy_copy("riv/copy")]),
                cluster("kan-subgraphs-a", blockers=[blocker()]),
            ]
        )
        target = binding()
        target["eligibility"]["latest"]["decision"] = "eligible"
        target["eligibility"]["latest"]["reason"] = "both_windows_exceed_threshold"
        allowed, _ = check_fresh_gate(
            target, evidence, self.policy, "implementation-start", MEASURED_AT + timedelta(hours=23)
        )
        self.assertTrue(allowed)
        allowed, message = check_fresh_gate(
            target, evidence, self.policy, "implementation-start", MEASURED_AT + timedelta(hours=25)
        )
        self.assertFalse(allowed)
        self.assertIn("exceeds", message)


if __name__ == "__main__":
    unittest.main()
