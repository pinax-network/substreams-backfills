import importlib.util
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("package", Path(__file__).with_name("package.py"))
pkg = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pkg)
REPO = Path(__file__).resolve().parents[1]
COMMIT = "a" * 40


class PackagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def payload(self):
        root = self.root / "payload"
        (root / pkg.BINARY).parent.mkdir(parents=True)
        (root / pkg.BINARY).write_bytes(b"test executable")
        shutil.copytree(REPO / "segments", root / "opt/mapping-host/segments")
        files = {"mapping-host/segments/" + path: value for path, value in pkg.inventory(REPO / "segments").items()}
        source = {"schema": "pinax.mapping-host.build-inputs/v1", "source_commit": COMMIT,
                  "files": files, "input_set_sha256": pkg.sha(pkg.canonical(files))}
        (root / pkg.SOURCE).write_bytes(pkg.canonical(source))
        pkg.seal(root)
        return root

    def test_all_eight_bundles_and_binary_verify(self):
        root = self.payload()
        document = pkg.verify(root, COMMIT)
        self.assertFalse(document["production_selectable"])
        self.assertEqual(8, len(list((root / "opt/mapping-host/segments").iterdir())))

    def test_binary_mutation_refused(self):
        root = self.payload()
        (root / pkg.BINARY).write_bytes(b"replacement")
        with self.assertRaisesRegex(ValueError, "inventory"):
            pkg.verify(root, COMMIT)

    def test_bundle_mutation_refused_even_after_resealing_runtime_manifest(self):
        root = self.payload()
        next((root / "opt/mapping-host/segments").rglob("*.wasm")).write_bytes(b"replacement")
        with self.assertRaisesRegex(ValueError, "bundle lock"):
            pkg.seal(root)

    def test_source_revision_mismatch_refused(self):
        with self.assertRaisesRegex(ValueError, "source identity"):
            pkg.verify(self.payload(), "b" * 40)

    def test_unknown_file_and_symlink_refused(self):
        root = self.payload()
        extra = root / "unexpected.env"
        extra.write_text("unexpected")
        with self.assertRaisesRegex(ValueError, "inventory"):
            pkg.verify(root, COMMIT)
        extra.unlink()
        extra.symlink_to(root / pkg.BINARY)
        with self.assertRaisesRegex(ValueError, "non-regular"):
            pkg.verify(root, COMMIT)

    def test_duplicate_json_and_unsafe_paths_refused(self):
        path = self.root / "duplicate.json"
        path.write_text('{"source_commit":"a","source_commit":"b"}')
        with self.assertRaisesRegex(ValueError, "duplicate"):
            pkg.read_json(path)
        for value in ("../x", "/x", "a/../b", "a//b", "./x", ""):
            with self.subTest(value=value), self.assertRaises(ValueError):
                pkg.safe_path(value)

    def test_context_uses_exact_git_objects_excluding_dirty_and_untracked_files(self):
        repo = self.root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        for name in pkg.EXACT:
            path = repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("committed")
        (repo / "secret.env").write_text("not a build input")
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                        "commit", "-qm", "fixture"], check=True)
        (repo / "Cargo.toml").write_text("dirty")
        (repo / "mapping-host/local.env").write_text("untracked")
        dest = self.root / "context"
        pkg.context(repo, dest, "HEAD")
        self.assertEqual("committed", (dest / "Cargo.toml").read_text())
        self.assertFalse((dest / "secret.env").exists())
        self.assertFalse((dest / "mapping-host/local.env").exists())
        (dest / "Cargo.toml").write_text("modified after export")
        with self.assertRaisesRegex(ValueError, "build inputs differ"):
            pkg.verify_source(dest)

    def test_descriptor_sidecar_mismatch_refused(self):
        root = self.payload()
        next((root / "opt/mapping-host/segments").rglob("*.sha256")).write_text("0" * 64)
        with self.assertRaisesRegex(ValueError, "sidecar"):
            pkg.seal(root)

    def test_source_input_hash_cannot_be_replaced_independently(self):
        root = self.payload()
        value = pkg.read_json(root / pkg.RUNTIME)
        value["build_input_set_sha256"] = "0" * 64
        (root / pkg.RUNTIME).write_bytes(pkg.canonical(value))
        with self.assertRaisesRegex(ValueError, "input set"):
            pkg.verify(root, COMMIT)

    def test_publication_refuses_mutable_tags_before_extract(self):
        for image in ("ghcr.io/pinax-network/substreams-backfills:latest", "local:sha"):
            with self.assertRaisesRegex(ValueError, "immutable"):
                pkg.archive(image, self.root / "archive", COMMIT)

    def test_bcf_smoke_requires_exact_four_payloads_and_order(self):
        goldens = REPO / f"fixtures/block-changes/{pkg.ROOT_SEGMENT}"
        frames = []
        for number in pkg.BLOCKS:
            payload = (goldens / f"{number}.pb").read_bytes()
            frames.append(b"BCF1\x01\0\0\0" + struct.pack(">Q", number) + bytes(32) + struct.pack(">I", len(payload)) + payload)
        pkg.compare_bcf(b"".join(frames), goldens)
        for bad in (b"".join(frames[:-1]), b"".join(reversed(frames)), b"".join(frames)[:-1],
                    b"".join(frames) + frames[-1]):
            with self.subTest(length=len(bad)), self.assertRaises(ValueError):
                pkg.compare_bcf(bad, goldens)


if __name__ == "__main__":
    unittest.main()
