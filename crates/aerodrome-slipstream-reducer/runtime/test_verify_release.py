"""In-memory release-server adversaries; no real upload/download is claimed."""
import io
import unittest

import release_receipt
import verify_release
import test_release_receipt as fixtures

SOURCE, RUN = fixtures.SOURCE, fixtures.RUN


class ReleaseTests(unittest.TestCase):
    fixture = fixtures.ReceiptTests.fixture
    save = fixtures.ReceiptTests.save

    def prepared(self):
        root = self.fixture()
        receipt = release_receipt.receipt(root, SOURCE, RUN)
        self.save(root, "publication.json", receipt)
        assets = {name: (root / path).read_bytes() for name, path in release_receipt.ASSETS.items()}
        assets["publication.json"] = (root / "publication.json").read_bytes()
        return root, assets

    def opener(self, assets):
        def opened(request, timeout):
            self.assertFalse(request.has_header("Authorization"))
            self.assertTrue(request.full_url.startswith("https://github.com/"))
            self.assertEqual(timeout, 120)
            name = request.full_url.rsplit("/", 1)[-1]
            stream = io.BytesIO(assets[name])
            stream.status = 200
            return stream
        return opened

    def test_every_asset_matches_before_completion_and_existing_output_refuses(self):
        root, assets = self.prepared()
        output = root / "downloads"
        tag = "aerodrome-producer-candidate-" + SOURCE + "-run-123-attempt-1"
        value = verify_release.verify(root, tag, output, self.opener(assets))
        self.assertEqual(set(value["assets"]), set(assets))
        self.assertTrue((output / "complete.json").is_file())
        for name, data in assets.items():
            self.assertEqual((output / name).read_bytes(), data)
        with self.assertRaises(FileExistsError):
            verify_release.verify(root, tag, output, self.opener(assets))

    def test_missing_altered_truncated_and_extra_bytes_never_complete(self):
        for mutation in (lambda a: a.pop("publication.json"),
                         lambda a: a.update({"publication.json": a["publication.json"][:-1]}),
                         lambda a: a.update({"smoke.json": a["smoke.json"] + b"x"}),
                         lambda a: a.update({"producer-runtime.tar": b"X" * len(a["producer-runtime.tar"])})):
            root, assets = self.prepared()
            mutation(assets)
            output = root / "downloads"
            with self.assertRaises((ValueError, KeyError)):
                verify_release.verify(root, "aerodrome-producer-candidate-" + SOURCE + "-run-123-attempt-1", output, self.opener(assets))
            self.assertFalse((output / "complete.json").exists())

    def test_relabelled_release_is_refused_before_download(self):
        root, assets = self.prepared()
        for tag in ("arbitrary", "aerodrome-producer-candidate-" + "34" * 20 + "-run-123-attempt-1",
                    "aerodrome-producer-candidate-" + SOURCE + "-run-124-attempt-1"):
            with self.assertRaises(ValueError):
                verify_release.verify(root, tag, root / "downloads", self.opener(assets))
            self.assertFalse((root / "downloads").exists())


if __name__ == "__main__":
    unittest.main()
