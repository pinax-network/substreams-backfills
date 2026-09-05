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
EXACT = {
    "Cargo.toml", "mapping-host/Cargo.toml", "mapping-host/Cargo.lock",
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
    if source["source_commit"] != commit or sha(canonical(source["files"])) != source["input_set_sha256"]:
        raise ValueError("runtime build input identity mismatch")
    if source["input_set_sha256"] != document["build_input_set_sha256"]:
        raise ValueError("runtime build input set mismatch")
    if document["binary_sha256"] != digest(root / BINARY):
        raise ValueError("binary identity mismatch")
    verify_bundles(root, source)
    return document


def extract(image, dest, commit):
    # Extraction is from the exact image, never from the host build tree.
    dest.mkdir(parents=True, exist_ok=False)
    container = run("docker", "create", "--platform", "linux/amd64", image).decode().strip()
    try:
        (dest / "usr/local/bin").mkdir(parents=True)
        (dest / "opt").mkdir()
        run("docker", "cp", f"{container}:/{BINARY}", str(dest / BINARY))
        run("docker", "cp", f"{container}:/opt/mapping-host", str(dest / "opt"))
    finally:
        run("docker", "rm", container)
    return verify(dest, commit)


def compare_bcf(data, goldens):
    numbers = []
    while data:
        if len(data) < 52 or data[:8] != b"BCF1\x01\x00\x00\x00":
            raise ValueError("bad BCF1 header")
        number, = struct.unpack(">Q", data[8:16])
        length, = struct.unpack(">I", data[48:52])
        if len(data) < 52 + length or number in numbers:
            raise ValueError("truncated or duplicate BCF1 frame")
        if data[52:52 + length] != (goldens / f"{number}.pb").read_bytes():
            raise ValueError(f"BCF1 golden differs at {number}")
        numbers.append(number)
        data = data[52 + length:]
    if tuple(numbers) != BLOCKS:
        raise ValueError("incomplete or reordered sampled fixture run")


def smoke(repo, image, dest, commit):
    dest.mkdir(parents=True, exist_ok=False)
    document = extract(image, dest / "runtime", commit)
    context(repo, dest / "committed-inputs", commit)
    if (dest / "committed-inputs/source.json").read_bytes() != (dest / "runtime" / SOURCE).read_bytes():
        raise ValueError("image source inventory differs from the exact Git commit")
    # Fixture/golden/cassette inputs are read-only and intentionally not in the image.
    lock = read_json(repo / "uniswap-v3/fixtures/blocks.lock.json")
    fixtures = dest / "fixtures"
    fixtures.mkdir()
    for number in BLOCKS:
        item = next(x for x in lock["assets"] if x["path"].endswith(f"/{number}.pb"))
        path = repo / item["path"]
        if digest(path) != item["sha256"] or path.stat().st_size != item["bytes"]:
            raise ValueError("block fixture differs from lock")
        shutil.copyfile(path, fixtures / f"{number}.pb")
    shutil.copyfile(repo / f"mapping-host/fixtures/cassettes/{ROOT_SEGMENT}.json", fixtures / "cassette.json")
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
        run(*security, image, "verify-bundle", "--segment", f"/opt/mapping-host/segments/{segment.name}")
    run(*security, image, "run", "--segment", f"/opt/mapping-host/segments/{ROOT_SEGMENT}",
        "--blocks", *(f"/fixtures/{x}.pb" for x in BLOCKS), "--cassette", "/fixtures/cassette.json",
        "--out", "/output/report.json", "--bcf1-out", "/output/blocks.bcf1", "--store-out", "/output/store.json")
    compare_bcf((output / "blocks.bcf1").read_bytes(), repo / f"mapping-host/fixtures/block-changes/{ROOT_SEGMENT}")
    report = read_json(output / "report.json")
    if report != read_json(repo / f"mapping-host/fixtures/reports/{ROOT_SEGMENT}.json"):
        raise ValueError("packaged sampled replay report differs from golden")
    receipt = {"schema": "pinax.mapping-host.runtime-smoke/v1", "source_commit": commit,
               "runtime_binary_sha256": document["binary_sha256"], "network": "none",
               "blocks": BLOCKS, "contiguous": False, "production_selectable": False,
               "outputs": inventory(output)}
    (dest / "smoke.json").write_bytes(canonical(receipt))


def archive(image, dest, commit):
    if not re.fullmatch(r"ghcr\.io/pinax-network/substreams-backfills@sha256:[0-9a-f]{64}", image):
        raise ValueError("publication requires the immutable mapping-host image digest")
    dest.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory() as work:
        root = Path(work) / "runtime"
        document = extract(image, root, commit)
        archive_file = dest / f"mapping-host-{commit}-linux-amd64.tar.gz"
        with tarfile.open(archive_file, "w:gz") as out:
            for name in sorted(inventory(root)):
                out.add(root / name, arcname=name, recursive=False)
        external = {"schema": "pinax.mapping-host.oci-publication/v1", "source_commit": commit,
                    "image": image, "runtime": document, "runtime_json_sha256": digest(root / RUNTIME),
                    "archive": {"file": archive_file.name, "sha256": digest(archive_file)},
                    "production_selectable": False}
        (dest / "publication.json").write_bytes(canonical(external))


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
    args = vars(parser.parse_args())
    command = args.pop("command").replace("-", "_")
    globals()[command](**args)


if __name__ == "__main__":
    main()
