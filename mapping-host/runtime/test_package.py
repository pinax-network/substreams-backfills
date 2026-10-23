import importlib.util
import copy
import json
from pathlib import Path
import shutil
import struct
import tarfile
import subprocess
import tempfile
import sys
import unittest
from unittest.mock import patch

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

    def test_all_nine_bundles_and_binary_verify(self):
        # Eight Uniswap V3 deployments plus the Aerodrome Slipstream Base oracle.
        root = self.payload()
        document = pkg.verify(root, COMMIT)
        self.assertFalse(document["production_selectable"])
        self.assertEqual(9, len(list((root / "opt/mapping-host/segments").iterdir())))

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
        with self.assertRaisesRegex(ValueError, "allowlist"):
            pkg.seal(root)
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
        disk_sources = ("mapping-host/src/disk_oracle.rs", "mapping-host/src/disk_store.rs",
                        "mapping-host/src/disk_store/tests.rs", "mapping-host/src/runner/disk_seed.rs")
        for name in disk_sources:
            path = repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("committed disk source")
        (repo / "secret.env").write_text("not a build input")
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                        "commit", "-qm", "fixture"], check=True)
        (repo / "Cargo.toml").write_text("dirty")
        (repo / "mapping-host/local.env").write_text("untracked")
        dest = self.root / "context"
        pkg.context(repo, dest, "HEAD")
        self.assertEqual("committed", (dest / "Cargo.toml").read_text())
        for name in disk_sources:
            self.assertEqual("committed disk source", (dest / name).read_text())
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

    def test_in_band_descriptor_requires_complete_matching_pair(self):
        root = self.payload()
        segment = root / "opt/mapping-host/segments" / pkg.ROOT_SEGMENT
        descriptor = segment / "block-changes-in-band-descriptor.json"
        sidecar = descriptor.with_suffix(".json.sha256")
        descriptor.write_bytes(pkg.canonical({"descriptor_version": 2, "message_type": "proto:pinax.graph.backfill.v2.BlockChanges"}))
        with self.assertRaisesRegex(ValueError, "requires its sidecar"):
            pkg.seal(root)
        sidecar.write_text("0" * 64)
        with self.assertRaisesRegex(ValueError, "sidecar mismatch"):
            pkg.seal(root)
        sidecar.write_text(pkg.digest(descriptor))
        source = pkg.read_json(root / pkg.SOURCE)
        source["files"] = {"mapping-host/segments/" + path: value for path, value in pkg.inventory(root / "opt/mapping-host/segments").items()}
        source["input_set_sha256"] = pkg.sha(pkg.canonical(source["files"]))
        (root / pkg.SOURCE).write_bytes(pkg.canonical(source))
        pkg.seal(root)
        pkg.verify(root, COMMIT)
        descriptor.write_bytes(pkg.canonical({"descriptor_version": 1}))
        sidecar.write_text(pkg.digest(descriptor))
        with self.assertRaisesRegex(ValueError, "version/message type"):
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

    def test_image_execution_identity_is_checked(self):
        image = {"Os": "linux", "Architecture": "amd64", "Config": {
            "User": "10001:10001", "Entrypoint": ["/" + pkg.BINARY], "WorkingDir": "/opt/mapping-host",
            "Cmd": ["--help"], "Env": pkg.RUNTIME_ENV,
            "Labels": {"org.opencontainers.image.revision": COMMIT, "network.pinax.production-selectable": "false",
                       "org.opencontainers.image.source": "https://github.com/pinax-network/substreams-backfills",
                       "org.opencontainers.image.title": "Uniswap V3 mapping-host execution runtime"}}}
        pkg.verify_image_config(image, COMMIT)
        for field, value in (("User", "0:0"), ("Cmd", ["run"]), ("Env", ["LD_PRELOAD=/malicious.so"]),
                             ("Healthcheck", {"Test": ["CMD", "curl"]}), ("Volumes", {"/opt": {}}),
                             ("OnBuild", ["COPY . /"])):
            changed = copy.deepcopy(image)
            changed["Config"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                pkg.verify_image_config(changed, COMMIT)

    def test_extract_pins_inspected_config_id_not_mutable_tag(self):
        image_id = "sha256:" + "b" * 64
        with patch.object(pkg, "inspect_image", return_value={"Id": image_id}), \
                patch.object(pkg, "run", return_value=b"container\n") as calls, \
                patch.object(pkg, "verify", return_value={}):
            pkg.extract("mutable:tag", self.root / "extracted", COMMIT)
        self.assertEqual(calls.call_args_list[0].args, ("docker", "create", "--platform", "linux/amd64", image_id))
        self.assertFalse(any("mutable:tag" in call.args for call in calls.call_args_list))

    def test_publication_must_match_exact_smoked_image_and_manifest(self):
        image_id, runtime_sha = "sha256:" + "b" * 64, "c" * 64
        document = {"source_commit": COMMIT, "binary_sha256": "d" * 64}
        receipt = {"schema": "pinax.mapping-host.runtime-smoke/v1", "source_commit": COMMIT,
                   "image_config_sha256": image_id, "runtime_json_sha256": runtime_sha,
                   "runtime_binary_sha256": document["binary_sha256"], "network": "none",
                   "blocks": list(pkg.BLOCKS), "production_selectable": False}
        receipt["disk_oracle"] = {"fixture_only": True, "partitions": 2, "network": "none", "from": 13899664,
                                  "to_exclusive": 13899666, "request_sha256": "1"*64, "completion_sha256": "2"*64}
        pkg.verify_smoke_binding(receipt, image_id, runtime_sha, document)
        without_disk = copy.deepcopy(receipt)
        del without_disk["disk_oracle"]
        with self.assertRaisesRegex(ValueError, "exact tested"):
            pkg.verify_smoke_binding(without_disk, image_id, runtime_sha, document)
        for key in ("source_commit", "image_config_sha256", "runtime_json_sha256", "runtime_binary_sha256"):
            changed = dict(receipt, **{key: "wrong"})
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "exact tested"):
                pkg.verify_smoke_binding(changed, image_id, runtime_sha, document)

    def test_smoke_refuses_edited_committed_goldens(self):
        repo = self.root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        paths = ["uniswap-v3/fixtures/blocks.lock.json", f"mapping-host/fixtures/cassettes/{pkg.ROOT_SEGMENT}.json",
                 f"mapping-host/fixtures/reports/{pkg.ROOT_SEGMENT}.json"]
        paths += [f"mapping-host/fixtures/block-changes/{pkg.ROOT_SEGMENT}/{number}.pb" for number in pkg.BLOCKS]
        paths += [pkg.DISK_FIXTURE + "/" + name for name in pkg.DISK_FILES]
        for name in paths:
            path = repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"committed evidence")
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                        "commit", "-qm", "fixture"], check=True)
        commit = pkg.run("git", "-C", str(repo), "rev-parse", "HEAD").decode().strip()
        pkg.verify_fixture_inputs(repo, commit)
        (repo / paths[-1]).write_bytes(b"edited golden")
        with self.assertRaisesRegex(ValueError, "evidence input differs"):
            pkg.verify_fixture_inputs(repo, commit)

    def test_disk_smoke_requires_actual_binary_complete_seed_and_both_frames(self):
        fixtures = self.root / "fixtures"
        output = self.root / "output"
        fixtures.mkdir()
        output.mkdir()
        (fixtures / "request.json").write_bytes(pkg.canonical({"seed_binding":{"boundary":{"block_number":13899663}},"to_exclusive":13899666}))
        for i in range(2):
            (fixtures / f"expected-{i}.bcf1").write_bytes(f"frame-{i}".encode())
            (output / f"partition-{i:03}").mkdir()
            shutil.copyfile(fixtures / f"expected-{i}.bcf1", output / f"partition-{i:03}/frames.bcf1")
        (fixtures / "expected-checkpoint.jsonl").write_bytes(b"complete cold seed\n")
        shutil.copyfile(fixtures / "expected-checkpoint.jsonl", output / "seed.checkpoint.jsonl")
        document = {"format":"pinax.mapping-host.disk-oracle-complete/v1", "fixture_only":True,
                    "production_selectable":False, "request_sha256":pkg.digest(fixtures / "request.json"),
                    "executable":{"sha256":"a"*64}, "from":13899664, "to_exclusive":13899666,
                    "partitions":[{},{}]}
        def seal():
            (output / "complete.json").write_bytes(pkg.canonical(document))
        seal()
        self.assertEqual(2, pkg.verify_disk_smoke(output, fixtures, "a"*64)["partitions"])
        for key, bad in (("fixture_only", False), ("production_selectable", True), ("partitions", [{}]),
                         ("request_sha256", "b"*64), ("executable", {"sha256":"b"*64})):
            original = document[key]
            document[key] = bad
            seal()
            with self.subTest(key=key), self.assertRaises(ValueError):
                pkg.verify_disk_smoke(output, fixtures, "a"*64)
            document[key] = original
        seal()
        for actual in (output / "partition-001/frames.bcf1", output / "seed.checkpoint.jsonl"):
            original = actual.read_bytes()
            actual.write_bytes(original[:-1])
            with self.assertRaises(ValueError):
                pkg.verify_disk_smoke(output, fixtures, "a"*64)
            actual.write_bytes(original)
        (output / ".complete.json.partial").write_bytes(b"partial")
        with self.assertRaisesRegex(ValueError, "partial completion"):
            pkg.verify_disk_smoke(output, fixtures, "a"*64)

    def test_candidate_retains_usable_executable_and_complete_source_archives(self):
        runtime = self.payload()
        (runtime / pkg.BINARY).chmod(0o555)
        context = self.root / "context"
        context.mkdir()
        shutil.copytree(runtime / "opt/mapping-host/segments", context / "mapping-host/segments")
        for name in pkg.EXACT:
            path = context / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"exact source input")
        files = pkg.inventory(context)
        source = {"schema":"pinax.mapping-host.build-inputs/v1", "source_commit":COMMIT,
                  "files":files, "input_set_sha256":pkg.sha(pkg.canonical(files))}
        (context / "source.json").write_bytes(pkg.canonical(source))
        shutil.copyfile(context / "source.json", runtime / pkg.SOURCE)
        pkg.seal(runtime)
        document = pkg.verify(runtime, COMMIT)
        receipt = {"schema":"pinax.mapping-host.runtime-smoke/v1", "source_commit":COMMIT,
                   "image_config_sha256":"sha256:" + "b"*64, "runtime_json_sha256":pkg.digest(runtime/pkg.RUNTIME),
                   "runtime_binary_sha256":document["binary_sha256"], "network":"none", "blocks":list(pkg.BLOCKS),
                   "production_selectable":False,
                   "disk_oracle":{"fixture_only":True, "partitions":2, "network":"none", "from":13899664,
                                  "to_exclusive":13899666, "request_sha256":"1"*64, "completion_sha256":"2"*64}}
        smoke = self.root / "smoke.json"
        smoke.write_bytes(pkg.canonical(receipt))
        output = self.root / "candidate"
        result = pkg.candidate(runtime, context, smoke, COMMIT, output)
        self.assertFalse(result["registry_published"])
        self.assertFalse(result["production_selectable"])
        for key, expected in (("archive", pkg.inventory(runtime)), ("source_archive", pkg.inventory(context))):
            path = output / result[key]["file"]
            self.assertEqual(result[key]["sha256"], pkg.digest(path))
            with tarfile.open(path) as archive:
                self.assertEqual(set(expected), set(archive.getnames()))
                for member in archive:
                    self.assertTrue(member.isfile())
                    self.assertEqual((member.uid, member.gid, member.mtime), (0, 0, 0))
                    self.assertEqual(pkg.sha(archive.extractfile(member).read()), expected[member.name]["sha256"])
                    if member.name == pkg.BINARY:
                        self.assertEqual(member.mode, 0o555)
        self.assertTrue((output / "candidate.json").is_file())
        self.assertFalse((output / ".candidate.json.partial").exists())
        with self.assertRaises(FileExistsError):
            pkg.candidate(runtime, context, smoke, COMMIT, output)
        (context / "Cargo.toml").write_bytes(b"changed source")
        with self.assertRaisesRegex(ValueError, "build inputs differ"):
            pkg.candidate(runtime, context, smoke, COMMIT, self.root / "bad-candidate")
        self.assertFalse((self.root / "bad-candidate/candidate.json").exists())

    def test_streamed_archive_refuses_wrong_bytes_and_nonregular_inputs(self):
        root = self.root / "input"
        root.mkdir()
        (root / "row").write_bytes(b"data")
        with patch.object(pkg, "inventory", return_value={"row":{"sha256":"0"*64,"bytes":4}}):
            with self.assertRaisesRegex(ValueError, "archive bytes changed"):
                pkg.archive_exact(root, self.root / "bad.tar.gz")
        (root / "link").symlink_to(root / "row")
        with self.assertRaisesRegex(ValueError, "non-regular"):
            pkg.archive_exact(root, self.root / "symlink.tar.gz")

    def test_bcf_smoke_requires_exact_four_payloads_and_order(self):
        goldens = REPO / f"fixtures/block-changes/{pkg.ROOT_SEGMENT}"
        report = pkg.read_json(REPO / f"fixtures/reports/{pkg.ROOT_SEGMENT}.json")
        hashes = {block["number"]: bytes.fromhex(block["hash"].removeprefix("0x")) for block in report["blocks"]}
        frames = []
        for number in pkg.BLOCKS:
            payload = (goldens / f"{number}.pb").read_bytes()
            frames.append(b"BCF1\x01\0\0\0" + struct.pack(">Q", number) + hashes[number] + struct.pack(">I", len(payload)) + payload)
        pkg.compare_bcf(b"".join(frames), goldens)
        for bad in (b"".join(frames[:-1]), b"".join(reversed(frames)), b"".join(frames)[:-1],
                    b"".join(frames) + frames[-1],
                    frames[0][:16] + bytes(32) + frames[0][48:] + b"".join(frames[1:])):
            with self.subTest(length=len(bad)), self.assertRaises(ValueError):
                pkg.compare_bcf(bad, goldens)


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.discovery = root / "discovery.json"
        self.manifest = root / "attachment-manifest.json"
        self.image = "ghcr.io/pinax-network/substreams-backfills@sha256:" + "b" * 64
        self.document = {
            "schemaVersion": 2, "mediaType": pkg.OCI_MANIFEST, "artifactType": pkg.ARTIFACT_TYPE,
            "subject": {"digest": self.image.split("@")[1]},
            "annotations": {"org.opencontainers.image.revision": COMMIT},
        }
        self.reseal()

    def reseal(self):
        self.manifest.write_bytes(pkg.canonical(self.document))
        self.attachment = "sha256:" + pkg.digest(self.manifest)
        # Exact ORAS v1.2.3 model: only manifests at the root; reference per descriptor.
        self.listing = {"manifests": [{
            "mediaType": pkg.OCI_MANIFEST, "digest": self.attachment,
            "size": self.manifest.stat().st_size, "artifactType": pkg.ARTIFACT_TYPE,
            "annotations": {"org.opencontainers.image.revision": COMMIT},
            "reference": self.image.split("@")[0] + "@" + self.attachment,
        }]}

    def verify(self, listing=None):
        self.discovery.write_bytes(pkg.canonical(self.listing if listing is None else listing))
        pkg.verify_discovery(self.discovery, self.manifest, self.image, self.attachment, COMMIT)

    def test_pinned_oras_123_discovery_and_unrelated_referrer_pass(self):
        self.verify()
        other = copy.deepcopy(self.listing["manifests"][0])
        other.update(digest="sha256:" + "c" * 64, artifactType="application/another-type",
                     reference=self.image.split("@")[0] + "@sha256:" + "c" * 64)
        self.listing["manifests"].append(other)
        self.verify()

    def test_missing_legacy_empty_and_non_array_discovery_refused(self):
        for listing in ({}, {"referrers": self.listing["manifests"]}, {"manifests": []},
                        {"manifests": None}, {"manifests": {}}, {"manifests": "bad"}, [],
                        {"manifests": self.listing["manifests"], "referrers": []}):
            with self.subTest(listing=listing), self.assertRaises(ValueError):
                self.verify(listing)

    def test_null_and_malformed_json_and_duplicate_keys_refused(self):
        for raw in (b"null", b"{", b'{"manifests":[],"manifests":[]}',
                    pkg.canonical(self.listing) + pkg.canonical(self.listing)):
            self.discovery.write_bytes(raw)
            with self.subTest(raw=raw[:30]), self.assertRaises(ValueError):
                pkg.verify_discovery(self.discovery, self.manifest, self.image, self.attachment, COMMIT)

    def test_malformed_and_duplicate_descriptor_records_refused(self):
        descriptor = self.listing["manifests"][0]
        for entries in ([None], ["bad"], [{}], [descriptor, descriptor], [descriptor, None]):
            with self.subTest(entries=entries), self.assertRaises(ValueError):
                self.verify({"manifests": entries})

    def test_selected_descriptor_fields_and_size_must_match(self):
        changes = [("digest", "sha256:" + "c" * 64), ("digest", None), ("digest", "bad"),
                   ("reference", "ghcr.io/another/repo@" + self.attachment),
                   ("reference", self.image), ("artifactType", "application/other"),
                   ("mediaType", "application/other"), ("annotations", {}),
                   ("annotations", {"org.opencontainers.image.revision": "c" * 40})]
        changes += [("size", value) for value in (0, -1, True, 1.5, "10", None,
                                                  self.manifest.stat().st_size + 1)]
        for key, value in changes:
            listing = copy.deepcopy(self.listing)
            listing["manifests"][0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.verify(listing)
        for key in self.listing["manifests"][0]:
            listing = copy.deepcopy(self.listing)
            del listing["manifests"][0][key]
            with self.subTest(missing=key), self.assertRaises(ValueError):
                self.verify(listing)

    def test_manifest_bytes_are_bound_to_attachment_digest(self):
        self.manifest.write_bytes(self.manifest.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            self.verify()

    def test_fetched_manifest_subject_revision_and_type_are_bound(self):
        original = copy.deepcopy(self.document)
        for key, value in (("subject", {"digest": "sha256:" + "c" * 64}), ("subject", None),
                           ("annotations", {"org.opencontainers.image.revision": "c" * 40}),
                           ("annotations", None), ("mediaType", "wrong"),
                           ("artifactType", "wrong"), ("schemaVersion", 1),
                           ("schemaVersion", 2.0), ("schemaVersion", True)):
            self.document = dict(original, **{key: value})
            self.reseal()
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "identity mismatch"):
                self.verify()

    def test_mutable_or_wrong_repository_and_bad_identity_arguments_refused(self):
        self.discovery.write_bytes(pkg.canonical(self.listing))
        for image in (self.image.split("@")[0] + ":latest", self.image.replace("pinax-network", "another")):
            with self.subTest(image=image), self.assertRaises(ValueError):
                pkg.verify_discovery(self.discovery, self.manifest, image, self.attachment, COMMIT)
        for attachment, commit in (("bad", COMMIT), (self.attachment, "main")):
            with self.assertRaises(ValueError):
                pkg.verify_discovery(self.discovery, self.manifest, self.image, attachment, commit)

    def test_discovery_cli_success_and_refusal(self):
        self.verify()
        command = [sys.executable, str(Path(pkg.__file__)), "verify-discovery",
                   "--discovery", str(self.discovery), "--manifest", str(self.manifest),
                   "--image", self.image, "--attachment", self.attachment, "--commit", COMMIT]
        self.assertEqual(0, subprocess.run(command, capture_output=True).returncode)
        self.discovery.write_text(json.dumps({"referrers": self.listing["manifests"]}))
        self.assertNotEqual(0, subprocess.run(command, capture_output=True).returncode)


if __name__ == "__main__":
    unittest.main()
