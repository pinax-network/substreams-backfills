"""Synthetic codec tests only; these do not build or execute a producer image."""
import copy
import gzip
import io
import json
import os
import pathlib
import tarfile
import tempfile
import unittest

import verify_oci as v

SOURCE = "12" * 20


def raw(value):
    return json.dumps(value, separators=(",", ":")).encode()


class Fixture:
    def __init__(self, root):
        self.root = root
        self.bundle = root / "bundle"
        self.bundle.mkdir()
        (self.bundle / "bin").mkdir()
        producer = b"synthetic executable identity only"
        (self.bundle / "bin/producer").write_bytes(producer)
        (self.bundle / "source.json").write_bytes(b"synthetic source closure")
        self.runtime = {"format": "pinax.backfill.producer-runtime/v1", "protocol": "pinax.backfill.producer/v1",
                        "production_selectable": False, "source_commit": SOURCE,
                        "files": {name: v.file_pin(self.bundle / name) for name in ("bin/producer", "source.json")}}
        (self.bundle / "runtime.json").write_bytes(raw(self.runtime))
        layer = b"synthetic filesystem layer"
        compressed = gzip.compress(layer, mtime=0)
        self.entries = {"oci-layout": raw({"imageLayoutVersion": "1.0.0"})}
        self.config = {"architecture": "amd64", "os": "linux", "rootfs": {"type": "layers", "diff_ids": ["sha256:" + v.sha(layer)]},
                       "config": {"User": "10001:10001", "Entrypoint": ["/opt/producer/bin/producer"], "WorkingDir": "/opt/producer",
                                  "Labels": {"org.opencontainers.image.source": "https://github.com/pinax-network/substreams-backfills",
                                             "org.opencontainers.image.revision": SOURCE, "network.pinax.production-selectable": "false"}}}
        config_desc = self.blob(raw(self.config), "application/vnd.oci.image.config.v1+json")
        self.inspection = [{"Id": config_desc["digest"], "Config": copy.deepcopy(self.config["config"]),
                            "RootFS": {"Layers": copy.deepcopy(self.config["rootfs"]["diff_ids"])}}]
        self.manifest = {"schemaVersion": 2, "config": config_desc,
                         "layers": [self.blob(compressed, "application/vnd.oci.image.layer.v1.tar+gzip")]}
        self.reseal()

    def blob(self, data, kind):
        digest = v.sha(data)
        self.entries["blobs/sha256/" + digest] = data
        return {"mediaType": kind, "digest": "sha256:" + digest, "size": len(data)}

    def reseal(self):
        self.descriptor = self.blob(raw(self.manifest), "application/vnd.oci.image.manifest.v1+json")
        self.entries["index.json"] = raw({"schemaVersion": 2, "manifests": [self.descriptor]})

    def write(self, extra=None):
        path = self.root / "image.oci.tar"
        with tarfile.open(path, "w") as tar:
            for name, data in self.entries.items():
                item = tarfile.TarInfo(name)
                item.size = len(data)
                tar.addfile(item, io.BytesIO(data))
            if extra:
                tar.addfile(extra, io.BytesIO(b"x" * extra.size))
        (self.root / "inspection.json").write_bytes(raw(self.inspection))
        return path

    def verify(self, expected=None):
        return v.verify(self.write(), self.bundle, self.root / "inspection.json", SOURCE, expected)


class IdentityTests(unittest.TestCase):
    def fixture(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return Fixture(pathlib.Path(directory.name))

    def test_exact_identity_and_independent_manifest_pin(self):
        f = self.fixture()
        receipt = f.verify(f.descriptor["digest"])
        self.assertFalse(receipt["production_selectable"])
        self.assertEqual(receipt["config_digest"], f.inspection[0]["Id"])
        self.assertEqual(receipt["runtime_sha256"], v.sha((f.bundle / "runtime.json").read_bytes()))
        with self.assertRaisesRegex(ValueError, "registry changed"):
            f.verify("sha256:" + "00" * 32)

    def test_containerd_id_requires_exact_retained_manifest_and_unchanged_config(self):
        f = self.fixture()
        f.inspection[0]["Id"] = f.descriptor["digest"]
        f.inspection[0]["Descriptor"] = copy.deepcopy(f.descriptor)
        receipt = f.verify()
        self.assertEqual(receipt["image_id"], f.descriptor["digest"])
        self.assertEqual(receipt["config_digest"], f.manifest["config"]["digest"])
        for mutation in range(9):
            changed = copy.deepcopy(f.inspection)
            if mutation == 0:
                del changed[0]["Descriptor"]
            elif mutation == 1:
                changed[0]["Descriptor"]["digest"] = "sha256:" + "00" * 32
            elif mutation == 2:
                changed[0]["Descriptor"]["size"] += 1
            elif mutation == 3:
                changed[0]["Descriptor"]["mediaType"] = "application/vnd.oci.image.index.v1+json"
            elif mutation == 4:
                changed[0]["Id"] = "sha256:" + "00" * 32
            elif mutation == 5:
                changed[0]["Config"]["User"] = "0"
            elif mutation == 6:
                changed[0]["RootFS"]["Layers"] = []
            elif mutation == 7:
                changed[0]["Descriptor"]["size"] = True
            else:
                changed[0]["Id"] = f.manifest["config"]["digest"]
                changed[0]["Descriptor"]["digest"] = "sha256:" + "00" * 32
            original = f.inspection
            f.inspection = changed
            with self.assertRaises(ValueError, msg=str(mutation)):
                f.verify()
            f.inspection = original
        name = "blobs/sha256/" + f.manifest["config"]["digest"][7:]
        f.entries[name] = f.entries[name].replace(b'10001:10001', b'00000:00000')
        with self.assertRaisesRegex(ValueError, "blob digest mismatch"):
            f.verify()

    def test_layer_change_fails_even_when_tar_is_well_formed(self):
        f = self.fixture()
        name = "blobs/sha256/" + f.manifest["layers"][0]["digest"][7:]
        f.entries[name] = f.entries[name][:-1] + bytes([f.entries[name][-1] ^ 1])
        with self.assertRaisesRegex(ValueError, "blob digest"):
            f.verify()

    def test_rehashed_layer_must_match_smoked_rootfs(self):
        f = self.fixture()
        old = f.manifest["layers"][0]
        del f.entries["blobs/sha256/" + old["digest"][7:]]
        del f.entries["blobs/sha256/" + f.descriptor["digest"][7:]]
        f.manifest["layers"][0] = f.blob(gzip.compress(b"altered", mtime=0), old["mediaType"])
        f.reseal()
        with self.assertRaisesRegex(ValueError, "unpacked layer digest"):
            f.verify()

    def test_inspection_and_runtime_mutations_refuse(self):
        for mutate in (lambda f: f.inspection[0].update(Id="sha256:" + "00" * 32),
                       lambda f: f.inspection[0]["Config"].update(User="0"),
                       lambda f: f.inspection[0]["RootFS"].update(Layers=[])):
            f = self.fixture()
            mutate(f)
            with self.assertRaises(ValueError):
                f.verify()
        f = self.fixture()
        (f.bundle / "bin/producer").write_bytes(b"different")
        with self.assertRaisesRegex(ValueError, "runtime file"):
            f.verify()
        f = self.fixture()
        f.runtime["production_selectable"] = True
        (f.bundle / "runtime.json").write_bytes(raw(f.runtime))
        with self.assertRaisesRegex(ValueError, "runtime identity"):
            f.verify()

    def test_unreferenced_duplicate_special_traversal_entries_refuse(self):
        for name, kind in (("surprise", tarfile.REGTYPE), ("index.json", tarfile.REGTYPE),
                           ("../outside", tarfile.REGTYPE), ("alias", tarfile.SYMTYPE)):
            f = self.fixture()
            item = tarfile.TarInfo(name)
            item.type = kind
            item.linkname = "index.json" if kind == tarfile.SYMTYPE else ""
            with self.assertRaises(ValueError):
                v.verify(f.write(item), f.bundle, f.root / "inspection.json", SOURCE)

    def test_json_duplicate_and_archive_symlink_refuse(self):
        with self.assertRaisesRegex(ValueError, "duplicate JSON"):
            v.parse(b'{"a":1,"a":2}')
        for data in (b'{"a":1e999}', b'{"a":NaN}'):
            with self.assertRaisesRegex(ValueError, "nonfinite JSON"):
                v.parse(data)
        f = self.fixture()
        f.write()
        link = f.root / "link.tar"
        link.symlink_to("image.oci.tar")
        with self.assertRaises(OSError):
            v.verify(link, f.bundle, f.root / "inspection.json", SOURCE)

    def test_fifo_artifacts_refuse_without_waiting_for_a_writer(self):
        f = self.fixture()
        pipe = f.root / "pipe"
        os.mkfifo(pipe)
        with self.assertRaisesRegex(ValueError, "regular file"):
            v.file_pin(pipe)
        with self.assertRaisesRegex(ValueError, "regular file"):
            v.small(pipe)


if __name__ == "__main__":
    unittest.main()
