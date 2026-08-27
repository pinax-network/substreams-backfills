from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[2]
SOURCE = REPOSITORY / "uniswap-v3/source"
VERIFIER = REPOSITORY / "scripts/verify-uniswap-v3-logical-contract.py"
REQUIRED_FILES = (
    "schema.graphql",
    "substreams.yaml",
    "src/db.rs",
    "src/lib.rs",
    "src/price.rs",
    "src/utils.rs",
)


class UniswapV3LogicalContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.source = Path(self.temporary.name) / "source"
        for relative_path in REQUIRED_FILES:
            destination = self.source / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(SOURCE / relative_path, destination)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def verify(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["python3", str(VERIFIER), "--source-root", str(self.source)],
            check=False,
            capture_output=True,
            text=True,
        )

    def replace(self, relative_path: str, old: str, new: str) -> None:
        path = self.source / relative_path
        contents = path.read_text()
        self.assertIn(old, contents)
        path.write_text(contents.replace(old, new, 1))

    def replace_last(self, relative_path: str, old: str, new: str) -> None:
        path = self.source / relative_path
        contents = path.read_text()
        position = contents.rfind(old)
        self.assertNotEqual(position, -1)
        path.write_text(contents[:position] + new + contents[position + len(old) :])

    def test_exact_import_passes(self) -> None:
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_schema_field_drift_is_rejected(self) -> None:
        self.replace("schema.graphql", "tvlUSD: BigDecimal!", "tvlUSDX: BigDecimal!")
        self.assertNotEqual(self.verify().returncode, 0)

    def test_tick_window_wiring_drift_is_rejected(self) -> None:
        self.replace_last(
            "src/lib.rs",
            "db::tick_windows_create(&mut tables, &ticks_liquidities_deltas);",
            "// removed by negative fixture",
        )
        self.assertNotEqual(self.verify().returncode, 0)

    def test_pool_window_store_key_rename_is_rejected(self) -> None:
        self.replace_last(
            "src/db.rs",
            '.key_last_segment_eq("totalValueLockedUSD")',
            '.key_last_segment_eq("tvlUSD")',
        )
        self.assertNotEqual(self.verify().returncode, 0)

    def test_token_window_store_key_rename_is_rejected(self) -> None:
        self.replace_last(
            "src/db.rs",
            '"untrackedUSD" => "untrackedVolumeUSD"',
            '"untrackedVolumeUSD" => "untrackedVolumeUSD"',
        )
        self.assertNotEqual(self.verify().returncode, 0)

    def test_target_absent_pool_field_is_rejected(self) -> None:
        self.replace(
            "src/db.rs",
            '.set("liquidityProviderCount", &bigint0);',
            '.set("totalValueLockedETHUntracked", &bigdecimal0)\n'
            '        .set("liquidityProviderCount", &bigint0);',
        )
        self.assertNotEqual(self.verify().returncode, 0)

    def test_mainnet_marker_drift_requires_a_versioned_contract(self) -> None:
        self.replace(
            "src/utils.rs",
            "1f98431c8ad98523631ae4a59f267346ea31f984",
            "0000000000000000000000000000000000000000",
        )
        self.assertNotEqual(self.verify().returncode, 0)


if __name__ == "__main__":
    unittest.main()
