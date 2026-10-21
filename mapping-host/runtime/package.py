#!/usr/bin/env python3
"""Committed-input image packaging. No deployment, credentials, or live replay."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import struct
import subprocess
import tarfile
import tempfile

ROOT_SEGMENT = "Qme66ZNMxSdCQKzaDuvS381whCVYCQjf637sGZCqJHAWHB"
BLOCKS = (12369621, 12369739, 12369879, 12370523)
RUNTIME = "opt/mapping-host/runtime.json"
SOURCE = "opt/mapping-host/source.json"
BINARY = "usr/local/bin/graph-mapping-host"
SCHEMA = "pinax.mapping-host.execution-runtime/v1"
ARTIFACT_TYPE = "application/vnd.pinax.mapping-host.runtime.v1"
OCI_MANIFEST = "application/vnd.oci.image.manifest.v1+json"
RUNTIME_ENV = ["PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"]
EXACT = {
    "Cargo.toml", "mapping-host/Cargo.toml", "mapping-host/Cargo.lock", "mapping-host/build.rs",
    "mapping-host/rust-toolchain.toml", "mapping-host/runtime/Dockerfile",
    "mapping-host/runtime/package.py",
}
PREFIXES = ("common/", "mapping-host/src/", "mapping-host/vendor/", "mapping-host/segments/")


def run(*args, **kwargs):
    return subprocess.check_output(args, **kwargs)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def canonical(value):
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def read_json(path):
    def unique(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result
    return json.loads(path.read_bytes(), object_pairs_hook=unique)


def safe_path(value):
    path = PurePosixPath(value)
    if not value or path.is_absolute() or str(path) != value or ".." in path.parts:
        raise ValueError(f"unsafe path: {value!r}")
    return value


def inventory(root, exclude=()):
    result = {}
    for path in sorted(root.rglob("*")):
        name = path.relative_to(root).as_posix()
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode) or not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
            raise ValueError(f"non-regular input: {name}")
        if path.is_file() and name not in exclude:
            result[name] = {"sha256": digest(path), "bytes": path.stat().st_size}
    return result


def allowed(name):
    # Exact git objects, not an archive of a possibly dirty working directory.
    return name in EXACT or name.startswith(PREFIXES)


def context(repo, dest, revision):
    commit = run("git", "-C", str(repo), "rev-parse", "--verify", revision + "^{commit}").decode().strip()
    if not re.fullmatch("[0-9a-f]{40}", commit):
        raise ValueError("expected a full Git commit")
    dest.mkdir(parents=True, exist_ok=False)
    tree = run("git", "-C", str(repo), "ls-tree", "-rz", commit)
    for record in tree.split(b"\0"):
        if not record:
            continue
        meta, raw_name = record.split(b"\t", 1)
        mode, kind, oid = meta.decode().split()
        name = safe_path(raw_name.decode())
        if not allowed(name):
            continue
        if kind != "blob" or mode not in ("100644", "100755"):
            raise ValueError(f"unsupported Git input: {name}")
        path = dest / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(run("git", "-C", str(repo), "cat-file", "blob", oid))
        path.chmod(0o755 if mode == "100755" else 0o644)
    files = inventory(dest)
    if not EXACT <= files.keys():
        raise ValueError("missing mandatory build input")
    document = {"schema": "pinax.mapping-host.build-inputs/v1", "source_commit": commit,
                "files": files, "input_set_sha256": sha(canonical(files))}
    (dest / "source.json").write_bytes(canonical(document))
    verify_source(dest)
    print(commit)


def verify_source(root):
    document = read_json(root / "source.json")
    if document["schema"] != "pinax.mapping-host.build-inputs/v1":
        raise ValueError("unsupported source identity")
    files = inventory(root, ("source.json",))
    if files != document["files"] or any(not allowed(name) for name in files):
        raise ValueError("build inputs differ from sealed committed input set")
    if not EXACT <= files.keys() or sha(canonical(files)) != document["input_set_sha256"]:
        raise ValueError("invalid build input set")
    if not re.fullmatch("[0-9a-f]{40}", document["source_commit"]):
        raise ValueError("invalid source commit")


def verify_bundles(root, source):
    segments = root / "opt/mapping-host/segments"
    for segment in sorted(segments.iterdir()):
        lock = read_json(segment / "bundle.lock.json")
        if lock["deployment"] != segment.name:
            raise ValueError("bundle deployment mismatch")
        expected = {"bundle.lock.json", "block-changes-descriptor.json", "block-changes-descriptor.json.sha256"}
        in_band = segment / "block-changes-in-band-descriptor.json"
        in_band_pin = in_band.with_suffix(".json.sha256")
        if in_band.exists() != in_band_pin.exists():
            raise ValueError("in-band descriptor requires its sidecar")
        if in_band.exists():
            expected.update((in_band.name, in_band_pin.name))
            if in_band_pin.read_text().strip() != digest(in_band):
                raise ValueError("in-band descriptor sidecar mismatch")
            descriptor = read_json(in_band)
            if descriptor.get("descriptor_version") != 2 or descriptor.get("message_type") != "proto:pinax.graph.backfill.v2.BlockChanges":
                raise ValueError("in-band descriptor version/message type mismatch")
        for item in lock["files"]:
            name = safe_path(item["path"])
            if name in expected:
                raise ValueError("duplicate bundle file")
            expected.add(name)
            path = segment / name
            if digest(path) != item["sha256"] or path.stat().st_size != item["bytes"]:
                raise ValueError(f"bundle lock mismatch: {path}")
        if set(inventory(segment)) != expected:
            raise ValueError("bundle has extra or missing files")
        descriptor = segment / "block-changes-descriptor.json"
        if descriptor.with_suffix(".json.sha256").read_text().strip() != digest(descriptor):
            raise ValueError("descriptor sidecar mismatch")
    expected = {name.removeprefix("mapping-host/"): item for name, item in source["files"].items()
                if name.startswith("mapping-host/segments/")}
    actual = {"segments/" + name: item for name, item in inventory(segments).items()}
    if not expected or actual != expected:
        raise ValueError("bundles differ from committed build inputs")


def seal(root):
    source = read_json(root / SOURCE)
    verify_bundles(root, source)
    files = inventory(root, (RUNTIME,))
    document = {"schema": SCHEMA, "source_commit": source["source_commit"],
                "platform": "linux/amd64", "production_selectable": False,
                "scope": "experimental deployed-mapping producer; not a full-ancestry certification",
                "build_input_set_sha256": source["input_set_sha256"], "files": files,
                "binary_sha256": files[BINARY]["sha256"]}
    (root / RUNTIME).write_bytes(canonical(document))
    verify(root, source["source_commit"])


def verify(root, commit):
    document = read_json(root / RUNTIME)
    if document["schema"] != SCHEMA or document["source_commit"] != commit:
        raise ValueError("runtime source identity mismatch")
    if document["production_selectable"] is not False or document["platform"] != "linux/amd64":
        raise ValueError("unsupported runtime capability/platform")
    if inventory(root, (RUNTIME,)) != document["files"]:
        raise ValueError("runtime file inventory mismatch")
    source = read_json(root / SOURCE)
    if (source["schema"] != "pinax.mapping-host.build-inputs/v1" or source["source_commit"] != commit
            or sha(canonical(source["files"])) != source["input_set_sha256"]):
        raise ValueError("runtime build input identity mismatch")
    expected_files = {BINARY, SOURCE} | {
        "opt/" + name for name in source["files"] if name.startswith("mapping-host/segments/")}
    if set(document["files"]) != expected_files:
        raise ValueError("runtime payload differs from the explicit application allowlist")
    if source["input_set_sha256"] != document["build_input_set_sha256"]:
        raise ValueError("runtime build input set mismatch")
    if document["binary_sha256"] != digest(root / BINARY):
        raise ValueError("binary identity mismatch")
    verify_bundles(root, source)
    return document


def extract(image, dest, commit):
    # Extraction is from the exact image, never from the host build tree.
    config = inspect_image(image, commit)
    dest.mkdir(parents=True, exist_ok=False)
    container = run("docker", "create", "--platform", "linux/amd64", config["Id"]).decode().strip()
    try:
        (dest / "usr/local/bin").mkdir(parents=True)
        (dest / "opt").mkdir()
        run("docker", "cp", f"{container}:/{BINARY}", str(dest / BINARY))
        run("docker", "cp", f"{container}:/opt/mapping-host", str(dest / "opt"))
    finally:
        run("docker", "rm", container)
    return verify(dest, commit)


def verify_image_config(image, commit):
    config = image["Config"]
    labels = {"org.opencontainers.image.source": "https://github.com/pinax-network/substreams-backfills",
              "org.opencontainers.image.revision": commit,
              "org.opencontainers.image.title": "Uniswap V3 mapping-host execution runtime",
              "network.pinax.production-selectable": "false"}
    if (image["Os"] != "linux" or image["Architecture"] != "amd64"
            or config["User"] != "10001:10001"
            or config["Entrypoint"] != ["/" + BINARY]
            or config["Cmd"] != ["--help"] or config["Env"] != RUNTIME_ENV
            or config["WorkingDir"] != "/opt/mapping-host"
            or config["Labels"] != labels):
        raise ValueError("unsupported image execution identity")
    checked = {"User", "Entrypoint", "Cmd", "Env", "WorkingDir", "Labels", "ArgsEscaped"}
    if config.get("ArgsEscaped") is not None and type(config["ArgsEscaped"]) is not bool:
        raise ValueError("invalid legacy Windows ArgsEscaped metadata")
    for key in set(config) - checked:
        if config[key] not in (None, False, "", [], {}):
            raise ValueError(f"unexpected image execution field: {key}")


def inspect_image(image, commit):
    info = json.loads(run("docker", "image", "inspect", image))[0]
    verify_image_config(info, commit)
    if not re.fullmatch("sha256:[0-9a-f]{64}", info["Id"]):
        raise ValueError("invalid immutable image config ID")
    return info


def verify_fixture_inputs(repo, commit):
    names = ["uniswap-v3/fixtures/blocks.lock.json",
             f"mapping-host/fixtures/cassettes/{ROOT_SEGMENT}.json",
             f"mapping-host/fixtures/reports/{ROOT_SEGMENT}.json"]
    names += [f"mapping-host/fixtures/block-changes/{ROOT_SEGMENT}/{number}.pb" for number in BLOCKS]
    verified = {}
    for name in names:
        expected = run("git", "-C", str(repo), "cat-file", "blob", commit + ":" + name)
        if (repo / name).read_bytes() != expected:
            raise ValueError("smoke evidence input differs from the exact commit: " + name)
        verified[name] = expected
    return verified


def compare_bcf(data, goldens):
    numbers = []
    report = read_json(goldens.parents[1] / "reports" / f"{goldens.name}.json")
    expected_hashes = {block["number"]: bytes.fromhex(block["hash"].removeprefix("0x")) for block in report["blocks"]}
    while data:
        if len(data) < 52 or data[:8] != b"BCF1\x01\x00\x00\x00":
            raise ValueError("bad BCF1 header")
        number, = struct.unpack(">Q", data[8:16])
        length, = struct.unpack(">I", data[48:52])
        if len(data) < 52 + length or number in numbers:
            raise ValueError("truncated or duplicate BCF1 frame")
        if data[16:48] != expected_hashes.get(number):
            raise ValueError("BCF1 clock hash differs from golden")
        if data[52:52 + length] != (goldens / f"{number}.pb").read_bytes():
            raise ValueError(f"BCF1 golden differs at {number}")
        numbers.append(number)
        data = data[52 + length:]
    if tuple(numbers) != BLOCKS:
        raise ValueError("incomplete or reordered sampled fixture run")


def smoke(repo, image, dest, commit):
    dest.mkdir(parents=True, exist_ok=False)
    image_id = inspect_image(image, commit)["Id"]
    document = extract(image_id, dest / "runtime", commit)
    context(repo, dest / "committed-inputs", commit)
    if (dest / "committed-inputs/source.json").read_bytes() != (dest / "runtime" / SOURCE).read_bytes():
        raise ValueError("image source inventory differs from the exact Git commit")
    # Fixture/golden/cassette inputs are read-only and intentionally not in the image.
    evidence = dest / "committed-evidence"
    for name, raw in verify_fixture_inputs(repo, commit).items():
        path = evidence / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    lock = read_json(evidence / "uniswap-v3/fixtures/blocks.lock.json")
    fixtures = dest / "fixtures"
    fixtures.mkdir()
    for number in BLOCKS:
        item = next(x for x in lock["assets"] if x["path"].endswith(f"/{number}.pb"))
        path = repo / item["path"]
        raw = path.read_bytes()
        if sha(raw) != item["sha256"] or len(raw) != item["bytes"]:
            raise ValueError("block fixture differs from lock")
        (fixtures / f"{number}.pb").write_bytes(raw)
    shutil.copyfile(evidence / f"mapping-host/fixtures/cassettes/{ROOT_SEGMENT}.json", fixtures / "cassette.json")
    output = dest / "output"
    output.mkdir()
    # Runner host owns this directory; the image still executes as UID 10001.
    output.chmod(0o777)
    security = ["docker", "run", "--rm", "--platform", "linux/amd64", "--network", "none",
                "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                "--user", "10001:10001", "--tmpfs", "/tmp:rw,nosuid,nodev,size=1g",
                "--mount", f"type=bind,src={fixtures.resolve()},dst=/fixtures,readonly",
                "--mount", f"type=bind,src={output.resolve()},dst=/output"]
    for segment in (dest / "runtime/opt/mapping-host/segments").iterdir():
        run(*security, image_id, "verify-bundle", "--segment", f"/opt/mapping-host/segments/{segment.name}")
    run(*security, image_id, "run", "--segment", f"/opt/mapping-host/segments/{ROOT_SEGMENT}",
        "--blocks", *(f"/fixtures/{x}.pb" for x in BLOCKS), "--cassette", "/fixtures/cassette.json",
        "--out", "/output/report.json", "--bcf1-out", "/output/blocks.bcf1", "--store-out", "/output/store.json")
    compare_bcf((output / "blocks.bcf1").read_bytes(), evidence / f"mapping-host/fixtures/block-changes/{ROOT_SEGMENT}")
    report = read_json(output / "report.json")
    if report != read_json(evidence / f"mapping-host/fixtures/reports/{ROOT_SEGMENT}.json"):
        raise ValueError("packaged sampled replay report differs from golden")
    receipt = {"schema": "pinax.mapping-host.runtime-smoke/v1", "source_commit": commit,
               "image_config_sha256": image_id, "runtime_json_sha256": digest(dest / "runtime" / RUNTIME),
               "runtime_binary_sha256": document["binary_sha256"], "network": "none",
               "blocks": BLOCKS, "contiguous": False, "production_selectable": False,
               "outputs": inventory(output)}
    (dest / "smoke.json").write_bytes(canonical(receipt))


def verify_smoke_binding(receipt, image_id, runtime_sha, document):
    if (receipt["schema"] != "pinax.mapping-host.runtime-smoke/v1" or receipt["source_commit"] != document["source_commit"]
            or receipt["image_config_sha256"] != image_id or receipt["runtime_json_sha256"] != runtime_sha
            or receipt["runtime_binary_sha256"] != document["binary_sha256"] or receipt["network"] != "none"
            or receipt["blocks"] != list(BLOCKS) or receipt["production_selectable"] is not False):
        raise ValueError("published image differs from the exact tested image receipt")


def archive(image, dest, commit, smoke_receipt=None):
    if not re.fullmatch(r"ghcr\.io/pinax-network/substreams-backfills@sha256:[0-9a-f]{64}", image):
        raise ValueError("publication requires the immutable mapping-host image digest")
    dest.mkdir(parents=True, exist_ok=False)
    image_id = inspect_image(image, commit)["Id"]
    receipt = read_json(smoke_receipt)
    with tempfile.TemporaryDirectory() as work:
        root = Path(work) / "runtime"
        document = extract(image_id, root, commit)
        verify_smoke_binding(receipt, image_id, digest(root / RUNTIME), document)
        archive_file = dest / f"mapping-host-{commit}-linux-amd64.tar.gz"
        with tarfile.open(archive_file, "w:gz") as out:
            for name in sorted(inventory(root)):
                out.add(root / name, arcname=name, recursive=False)
        external = {"schema": "pinax.mapping-host.oci-publication/v1", "source_commit": commit,
                    "image": image, "image_config_sha256": image_id,
                    "runtime": document, "runtime_json_sha256": digest(root / RUNTIME),
                    "smoke_receipt_sha256": digest(smoke_receipt),
                    "archive": {"file": archive_file.name, "sha256": digest(archive_file)},
                    "production_selectable": False}
        (dest / "publication.json").write_bytes(canonical(external))


def verify_discovery(discovery, manifest, image, attachment, commit):
    """Verify the pinned ORAS 1.2.3 discovery shape and exact fetched referrer."""
    if not re.fullmatch(r"ghcr\.io/pinax-network/substreams-backfills@sha256:[0-9a-f]{64}", image):
        raise ValueError("discovery requires the immutable mapping-host image")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", attachment) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("invalid attachment or source revision")
    raw = manifest.read_bytes()
    if "sha256:" + sha(raw) != attachment:
        raise ValueError("fetched attachment digest mismatch")
    document = read_json(manifest)
    if (not isinstance(document, dict) or type(document.get("schemaVersion")) is not int
            or document["schemaVersion"] != 2
            or document.get("mediaType") != OCI_MANIFEST
            or document.get("artifactType") != ARTIFACT_TYPE
            or not isinstance(document.get("subject"), dict)
            or document["subject"].get("digest") != image.split("@", 1)[1]
            or not isinstance(document.get("annotations"), dict)
            or document["annotations"].get("org.opencontainers.image.revision") != commit):
        raise ValueError("fetched attachment identity mismatch")
    listing = read_json(discovery)
    # ORAS 1.2.3 uses manifests, with references on each descriptor, not at the root.
    if not isinstance(listing, dict) or set(listing) != {"manifests"} or not isinstance(listing["manifests"], list):
        raise ValueError("unsupported ORAS 1.2.3 discovery format")
    seen, matches = set(), []
    for item in listing["manifests"]:
        if (not isinstance(item, dict) or not isinstance(item.get("digest"), str)
                or not re.fullmatch(r"sha256:[0-9a-f]{64}", item["digest"])
                or type(item.get("size")) is not int or item["size"] <= 0
                or not isinstance(item.get("mediaType"), str)
                or item.get("reference") != image.split("@", 1)[0] + "@" + item["digest"]):
            raise ValueError("malformed discovery descriptor")
        if item["digest"] in seen:
            raise ValueError("duplicate discovery descriptor")
        seen.add(item["digest"])
        if item["digest"] == attachment:
            matches.append(item)
    if len(matches) != 1:
        raise ValueError("expected exactly one discovered attachment")
    selected = matches[0]
    if (selected["mediaType"] != OCI_MANIFEST or selected.get("artifactType") != ARTIFACT_TYPE
            or selected["size"] != len(raw) or not isinstance(selected.get("annotations"), dict)
            or selected["annotations"].get("org.opencontainers.image.revision") != commit):
        raise ValueError("discovered attachment identity mismatch")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("context", "verify-source", "seal", "verify", "extract", "smoke", "archive"):
        p = commands.add_parser(name)
        if name in ("verify-source", "seal", "verify"):
            p.add_argument("--root", required=True, type=Path)
        else:
            p.add_argument("--dest", required=True, type=Path)
        if name in ("context", "smoke"):
            p.add_argument("--repo", required=True, type=Path)
        if name == "context":
            p.add_argument("--revision", default="HEAD")
        if name in ("extract", "smoke", "archive"):
            p.add_argument("--image", required=True)
        if name in ("verify", "extract", "smoke", "archive"):
            p.add_argument("--commit", required=True)
        if name == "archive":
            p.add_argument("--smoke-receipt", required=True, type=Path)
    p = commands.add_parser("verify-discovery")
    p.add_argument("--discovery", required=True, type=Path)
    p.add_argument("--manifest", required=True, type=Path)
    p.add_argument("--image", required=True)
    p.add_argument("--attachment", required=True)
    p.add_argument("--commit", required=True)
    args = vars(parser.parse_args())
    command = args.pop("command").replace("-", "_")
    globals()[command](**args)


if __name__ == "__main__":
    main()
