"""Synthetic evidence binding tests, not evidence of OCI execution."""
import json
import pathlib
import tempfile
import unittest

import release_receipt as r
from verify_oci import file_pin

SOURCE = "12" * 20
RUN = "https://github.com/pinax-network/substreams-backfills/actions/runs/123"


class ReceiptTests(unittest.TestCase):
    def fixture(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = pathlib.Path(directory.name)
        (root / "archive").mkdir()
        (root / "smoke").mkdir()
        for name in ("producer-linux-amd64.oci.tar", "archive/producer-runtime.tar"):
            (root / name).write_bytes(b"synthetic artifact")
        common = {"production_selectable": False, "source_commit": SOURCE, "runtime_sha256": "ab" * 32}
        smoke = {**common, "format": "pinax.backfill.producer-smoke/v1"}
        self.save(root, "smoke/smoke.json", smoke)
        identity = {**common, "format": "pinax.backfill.producer-oci-identity/v1", "oci_manifest": "sha256:" + "cd" * 32,
                    "archive": file_pin(root / "producer-linux-amd64.oci.tar")}
        self.save(root, "oci-identity.json", identity)
        self.save(root, "registry-roundtrip.json", identity)
        discovery = {**common, "format": "pinax.backfill.producer-discovery/v1",
                     "archive": file_pin(root / "archive/producer-runtime.tar"), "smoke": file_pin(root / "smoke/smoke.json")}
        self.save(root, "archive/discovery.json", discovery)
        (root / "immutable-image.txt").write_text("ghcr.io/pinax-network/substreams-backfills/aerodrome-producer@" + identity["oci_manifest"] + "\n")
        return root

    def save(self, root, path, value):
        (root / path).write_text(json.dumps(value))

    def test_exact_manifest_pins_every_asset(self):
        value = r.receipt(self.fixture(), SOURCE, RUN)
        self.assertEqual(set(value["assets"]), set(r.ASSETS))
        self.assertFalse(value["production_selectable"])

    def test_relabelled_source_runtime_qualification_or_registry_refuses(self):
        for path, field, value in (("oci-identity.json", "source_commit", "34" * 20),
                                   ("smoke/smoke.json", "runtime_sha256", "ef" * 32),
                                   ("archive/discovery.json", "production_selectable", True),
                                   ("registry-roundtrip.json", "oci_manifest", "sha256:" + "ef" * 32)):
            root = self.fixture()
            content = json.loads((root / path).read_text())
            content[field] = value
            self.save(root, path, content)
            with self.assertRaises(ValueError):
                r.receipt(root, SOURCE, RUN)

    def test_altered_artifacts_or_image_location_refuse(self):
        for path in ("producer-linux-amd64.oci.tar", "archive/producer-runtime.tar", "smoke/smoke.json", "immutable-image.txt"):
            root = self.fixture()
            with (root / path).open("ab") as stream:
                stream.write(b" ")
            # Whitespace is still significant for immutable reference file only
            # when it changes its value, not its conventional final newline.
            if path == "immutable-image.txt":
                (root / path).write_text("ghcr.io/another/image@sha256:" + "cd" * 32)
            with self.assertRaises(ValueError):
                r.receipt(root, SOURCE, RUN)


if __name__ == "__main__":
    unittest.main()
