from __future__ import annotations

import unittest
from pathlib import Path

import yaml


REPOSITORY = Path(__file__).resolve().parents[2]
AUTHORITY = "https://github.com/pinax-network/substreams-backfills/issues/83"
LEGACY_FIELDS = {"market_qpd", "qos_snapshot_at", "signal_grt"}

EXACT_SNAPSHOTS = {
    Path("uniswap-v2-base/QmQmz5kh1f83Re1Zaj9UYrzKmcWqpKf1tNs9K6M9WrvPC8.yaml"): {
        "measured_at": "2026-08-31T17:20:00Z",
        "queries_24h": 780953,
        "query_fees_grt_24h": "954.416540",
        "authority": AUTHORITY,
    },
    Path("uniswap-v3-matic/QmWqwrVtcTzZzbTLGLgiRSQzbZ7MTH53VwqK4AxXVmf7n3.yaml"): {
        "measured_at": "2026-08-31T17:20:00Z",
        "queries_24h": 386433,
        "query_fees_grt_24h": "471.970",
        "authority": AUTHORITY,
    },
    Path(
        "pancakeswap-infinity-cl-bsc/QmVjXU7yQNyyLphPGqoz8iBzqu5YXphooFJn15JqZ6ZMFz.yaml"
    ): {
        "measured_at": "2026-08-31T17:20:00Z",
        "queries_24h": 25405,
        "query_fees_grt_24h": "30.041",
        "authority": AUTHORITY,
    },
    Path("exchange-v3-bsc/QmY67iZDTsTdpWXSCotpVPYankwnyHXNT7N95YEn8ccUsn.yaml"): {
        "measured_at": "2026-08-31T17:20:00Z",
        "queries_24h": 73997,
        "query_fees_grt_24h": "171.957",
        "authority": AUTHORITY,
    },
}

INTENTIONALLY_UNSNAPSHOTTED = (
    Path("morpho-blue-base/QmWSfh5qnidd1tBd6FY6eDvbSQUPTNhNG7o8CUGenvbaht.yaml"),
    Path("uniswap-v3/QmTZ8ejXJxRo7vDBS4uwqBeGoxLSWbhaA7oXa1RvxunLy7.yaml"),
    Path("uniswap-v3/Qmb4VUcAY9LsVgeCuCCMs7X1XrkbRcaiuAbSK8SqhmsAfP.yaml"),
)


def load_binding(path: Path) -> dict:
    value = yaml.safe_load((REPOSITORY / path).read_text())
    if not isinstance(value, dict):
        raise AssertionError(f"binding is not an object: {path}")
    return value


class TargetMarketSnapshotTest(unittest.TestCase):
    def test_exact_august_31_snapshots_are_locked(self) -> None:
        for path, expected in EXACT_SNAPSHOTS.items():
            with self.subTest(path=path):
                binding = load_binding(path)
                self.assertEqual(binding.get("market_snapshot"), expected)
                self.assertFalse(LEGACY_FIELDS.intersection(binding))

    def test_unattributed_historical_estimates_are_not_promoted(self) -> None:
        for path in INTENTIONALLY_UNSNAPSHOTTED:
            with self.subTest(path=path):
                binding = load_binding(path)
                self.assertNotIn("market_snapshot", binding)
                self.assertFalse(LEGACY_FIELDS.intersection(binding))


if __name__ == "__main__":
    unittest.main()
