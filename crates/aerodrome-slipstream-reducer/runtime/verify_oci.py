#!/usr/bin/env python3
"""Verify a retained OCI archive against the actually smoked Docker image.

This is identity evidence for a non-final candidate, never qualification. No
network access, extraction, credential handling, or registry mutation occurs.
"""
import argparse
import gzip
import hashlib
import json
import math
import os
import pathlib
import re
import stat
import tarfile

MAX_ARCHIVE = 4 * 1024**3
MAX_JSON = 4 * 1024**2
MAX_LAYER = 2 * 1024**3


def require(ok, why):
    if not ok:
        raise ValueError(why)


def pairs(rows):
    result = {}
    for key, value in rows:
        require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def parse(data):
    require(len(data) <= MAX_JSON, "oversize JSON")
    def finite(value):
        result = float(value)
        require(math.isfinite(result), "nonfinite JSON")
        return result
    return json.loads(data, object_pairs_hook=pairs,
                      parse_float=finite,
                      parse_constant=lambda _: require(False, "nonfinite JSON"))


def sha(data):
    return hashlib.sha256(data).hexdigest()


def regular(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    stream = os.fdopen(descriptor, "rb")
    if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
        stream.close()
        raise ValueError("not a regular file")
    return stream


def file_pin(path, bound=MAX_ARCHIVE):
    digest = hashlib.sha256()
    size = 0
    with regular(path) as stream:
        while chunk := stream.read(1024**2):
            size += len(chunk)
            require(size <= bound, "file exceeds bound")
            digest.update(chunk)
    return {"bytes": size, "sha256": digest.hexdigest()}


def small(path):
    with regular(path) as stream:
        data = stream.read(MAX_JSON + 1)
    return parse(data), data


def verify(archive, bundle, inspection, source, expected_manifest=None):
    require(re.fullmatch(r"[0-9a-f]{40}", source), "invalid source commit")
    inspect, _ = small(inspection)
    require(isinstance(inspect, list) and len(inspect) == 1, "expected one image inspection")
    inspected = inspect[0]
    runtime, raw_runtime = small(bundle / "runtime.json")
    require(runtime["format"] == "pinax.backfill.producer-runtime/v1"
            and runtime["protocol"] == "pinax.backfill.producer/v1"
            and runtime["production_selectable"] is False
            and runtime["source_commit"] == source, "runtime identity mismatch")
    # Rust VerifiedRuntime and the real smoke already validate the closed bundle;
    # independently bind the exact bytes used to make this OCI identity receipt.
    for name, pin in runtime["files"].items():
        require(all(part not in ("", ".", "..") for part in name.split("/"))
                and not name.startswith("/") and "\\" not in name, "unsafe runtime path")
        require(file_pin(bundle / name, 256 * 1024**2) == pin, "runtime file mismatch")
    archive_pin = file_pin(archive)
    with regular(archive) as archive_stream, tarfile.open(fileobj=archive_stream, mode="r:") as tar:
        entries = {}
        for item in tar:
            name = item.name.rstrip("/")
            require(name and not name.startswith("/") and "\\" not in name
                    and all(p not in ("", ".", "..") for p in name.split("/")), "unsafe OCI path")
            require(name not in entries, "duplicate OCI path")
            require(item.isfile() or item.isdir(), "special OCI entry")
            require(item.size <= MAX_ARCHIVE, "oversize OCI entry")
            entries[name] = item

        def contents(name, bound=MAX_JSON):
            require(name in entries and entries[name].isfile(), "missing OCI file")
            require(entries[name].size <= bound, "oversize OCI metadata")
            with tar.extractfile(entries[name]) as stream:
                data = stream.read(bound + 1)
            require(len(data) <= bound, "OCI metadata grew")
            return data

        require(parse(contents("oci-layout")) == {"imageLayoutVersion": "1.0.0"}, "OCI layout mismatch")
        index = parse(contents("index.json"))
        require(index["schemaVersion"] == 2 and len(index["manifests"]) == 1, "expected one OCI manifest")
        used = {"oci-layout", "index.json"}

        def blob(desc, metadata=False):
            digest = desc["digest"]
            require(re.fullmatch(r"sha256:[0-9a-f]{64}", digest), "invalid OCI digest")
            path = "blobs/sha256/" + digest[7:]
            require(path in entries and entries[path].isfile(), "missing OCI blob")
            item = entries[path]
            require(type(desc["size"]) is int and item.size == desc["size"], "OCI blob size mismatch")
            require(not metadata or item.size <= MAX_JSON, "oversize OCI JSON")
            used.add(path)
            actual = hashlib.sha256()
            with tar.extractfile(item) as stream:
                while chunk := stream.read(1024**2):
                    actual.update(chunk)
            require(actual.hexdigest() == digest[7:], "OCI blob digest mismatch")
            return parse(contents(path)) if metadata else item

        descriptor = index["manifests"][0]
        require(descriptor["mediaType"] == "application/vnd.oci.image.manifest.v1+json", "not an OCI image manifest")
        if expected_manifest is not None:
            require(descriptor["digest"] == expected_manifest, "registry changed OCI manifest")
        manifest = blob(descriptor, True)
        require(manifest["schemaVersion"] == 2
                and manifest["config"]["mediaType"] == "application/vnd.oci.image.config.v1+json", "OCI config type mismatch")
        config = blob(manifest["config"], True)
        require(config["architecture"] == "amd64" and config["os"] == "linux", "not Linux/amd64")
        require(manifest["config"]["digest"] == inspected["Id"], "OCI differs from inspected image")
        require(config["config"] == inspected["Config"], "image configuration mismatch")
        require(config["rootfs"]["type"] == "layers"
                and config["rootfs"]["diff_ids"] == inspected["RootFS"]["Layers"], "root filesystem mismatch")
        cfg = config["config"]
        require(cfg["User"] == "10001:10001"
                and cfg["Entrypoint"] == ["/opt/producer/bin/producer"]
                and cfg["WorkingDir"] == "/opt/producer", "producer image execution identity mismatch")
        labels = cfg["Labels"]
        require(labels["org.opencontainers.image.source"] == "https://github.com/pinax-network/substreams-backfills"
                and labels["org.opencontainers.image.revision"] == source
                and labels["network.pinax.production-selectable"] == "false", "image labels mismatch")
        require(len(manifest["layers"]) == len(config["rootfs"]["diff_ids"]), "layer count mismatch")
        for desc, expected in zip(manifest["layers"], config["rootfs"]["diff_ids"]):
            item = blob(desc)
            kind = desc["mediaType"]
            require(kind in ("application/vnd.oci.image.layer.v1.tar", "application/vnd.oci.image.layer.v1.tar+gzip"), "unsupported layer format")
            with tar.extractfile(item) as raw:
                stream = gzip.GzipFile(fileobj=raw) if kind.endswith("+gzip") else raw
                digest = hashlib.sha256()
                size = 0
                while chunk := stream.read(1024**2):
                    size += len(chunk)
                    require(size <= MAX_LAYER, "unpacked layer exceeds bound")
                    digest.update(chunk)
                require("sha256:" + digest.hexdigest() == expected, "unpacked layer digest mismatch")
        require({name for name, item in entries.items() if item.isfile()} == used, "unreferenced OCI payload")
        require(all(name in ("blobs", "blobs/sha256") for name, item in entries.items() if item.isdir()), "unexpected OCI directory")
    require(file_pin(archive) == archive_pin, "archive changed during verification")
    return {"format": "pinax.backfill.producer-oci-identity/v1", "production_selectable": False,
            "source_commit": source, "platform": "linux/amd64", "oci_manifest": descriptor["digest"],
            "config_digest": manifest["config"]["digest"], "archive": archive_pin,
            "runtime_sha256": sha(raw_runtime), "producer": runtime["files"]["bin/producer"],
            "source_closure": runtime["files"]["source.json"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("archive", "bundle", "inspection", "source", "output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--expected-manifest")
    args = parser.parse_args()
    receipt = verify(pathlib.Path(args.archive), pathlib.Path(args.bundle), pathlib.Path(args.inspection), args.source, args.expected_manifest)
    with pathlib.Path(args.output).open("x") as stream:
        json.dump(receipt, stream, indent=2)
        stream.write("\n")


if __name__ == "__main__":
    main()
