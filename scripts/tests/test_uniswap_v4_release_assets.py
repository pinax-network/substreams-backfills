from __future__ import annotations

import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[2]
VERIFIER = REPOSITORY / "scripts/verify-uniswap-v4-release-assets.py"
SPEC = importlib.util.spec_from_file_location("uniswap_v4_release_assets", VERIFIER)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class UniswapV4ReleaseAssetsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.manifest_path = self.root / MODULE.DEFAULT_MANIFEST
        self.manifest_path.parent.mkdir(parents=True)
        self.manifest = MODULE.expected_manifest()
        self.write_manifest()
        for asset in MODULE.EXPECTED_ASSETS:
            source = REPOSITORY / asset["path"]
            destination = self.root / asset["path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def write_manifest(self) -> None:
        self.manifest_path.write_text(
            json.dumps(self.manifest, indent=2) + "\n", encoding="utf-8"
        )

    def test_exact_mirror_passes(self) -> None:
        MODULE.verify(self.root)

    def test_changed_asset_byte_is_rejected(self) -> None:
        asset_path = self.root / MODULE.EXPECTED_ASSETS[0]["path"]
        with asset_path.open("r+b") as package:
            first_byte = package.read(1)[0]
            package.seek(0)
            package.write(bytes([first_byte ^ 0xFF]))
        with self.assertRaisesRegex(MODULE.VerificationError, "SHA-256"):
            MODULE.verify(self.root)

    def test_manifest_metadata_drift_is_rejected(self) -> None:
        self.manifest["assets"][0]["asset_api_id"] += 1
        self.write_manifest()
        with self.assertRaisesRegex(MODULE.VerificationError, "pinned contract"):
            MODULE.verify(self.root)

    def test_authority_claim_is_rejected(self) -> None:
        self.manifest["future_release_authority_transferred"] = True
        self.write_manifest()
        with self.assertRaisesRegex(MODULE.VerificationError, "pinned contract"):
            MODULE.verify(self.root)

    def test_missing_asset_is_rejected(self) -> None:
        (self.root / MODULE.EXPECTED_ASSETS[1]["path"]).unlink()
        with self.assertRaisesRegex(MODULE.VerificationError, "missing mirrored asset"):
            MODULE.verify(self.root)

    def test_unlisted_package_is_rejected(self) -> None:
        unexpected = self.root / MODULE.MIRROR_ROOT / "v9.9.9/unlisted.spkg"
        unexpected.parent.mkdir(parents=True)
        shutil.copyfile(self.root / MODULE.EXPECTED_ASSETS[0]["path"], unexpected)
        with self.assertRaisesRegex(MODULE.VerificationError, "unexpected"):
            MODULE.verify(self.root)

    def test_symlinked_asset_is_rejected(self) -> None:
        target = self.root / MODULE.EXPECTED_ASSETS[0]["path"]
        copy_path = target.with_suffix(".copy")
        shutil.copyfile(target, copy_path)
        target.unlink()
        target.symlink_to(copy_path)
        with self.assertRaisesRegex(MODULE.VerificationError, "symlinked path component"):
            MODULE.verify(self.root)

    def test_symlinked_mirror_root_is_rejected(self) -> None:
        mirror = self.root / MODULE.MIRROR_ROOT
        relocated = self.root / "relocated-mirror"
        mirror.rename(relocated)
        mirror.symlink_to(relocated, target_is_directory=True)
        with self.assertRaisesRegex(MODULE.VerificationError, "symlinked path component"):
            MODULE.verify(self.root)

    def test_symlinked_version_directory_is_rejected(self) -> None:
        version = self.root / MODULE.MIRROR_ROOT / "v0.1.0"
        relocated = self.root / "relocated-v0.1.0"
        version.rename(relocated)
        version.symlink_to(relocated, target_is_directory=True)
        with self.assertRaisesRegex(MODULE.VerificationError, "symlinked path component"):
            MODULE.verify(self.root)


if __name__ == "__main__":
    unittest.main()
