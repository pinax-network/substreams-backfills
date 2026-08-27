#!/usr/bin/env python3
"""Build or verify the complete SHA-256 inventory for the pinned V3 source tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

SOURCE_COMMIT = "42c7b15345e6df80561b694e52a0eb622b374b96"
SOURCE_TREE = "a00e882e92d07b46550b74dea279c114d57631ac"


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args])


def build_inventory() -> dict[str, object]:
    actual_tree = git("rev-parse", f"{SOURCE_COMMIT}^{{tree}}").decode().strip()
    if actual_tree != SOURCE_TREE:
        raise RuntimeError(f"source tree is {actual_tree}")
    records = git("ls-tree", "-r", "-z", "--long", SOURCE_COMMIT).split(b"\0")
    files: list[dict[str, object]] = []

    for record in records:
        if not record:
            continue
        metadata, raw_path = record.split(b"\t", 1)
        mode, object_type, object_id, raw_size = metadata.decode().split()
        if object_type != "blob":
            raise RuntimeError(f"unexpected Git object type {object_type}")

        payload = git("cat-file", "blob", object_id)
        size = int(raw_size)
        if len(payload) != size:
            raise RuntimeError(f"Git size mismatch for {raw_path!r}")

        files.append(
            {
                "path": raw_path.decode(),
                "mode": mode,
                "size": size,
                "git_blob": object_id,
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )

    return {
        "format_version": 1,
        "source_commit": SOURCE_COMMIT,
        "source_tree": SOURCE_TREE,
        "file_count": len(files),
        "executable_count": sum(item["mode"] == "100755" for item in files),
        "files": files,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", type=Path, help="verify an existing inventory")
    parser.add_argument(
        "--provenance",
        type=Path,
        help="with --check, verify the inventory binding in a provenance lock",
    )
    parser.add_argument("--output", type=Path, help="write the generated inventory")
    args = parser.parse_args()
    if args.check and args.output:
        parser.error("--check and --output are mutually exclusive")
    if args.provenance and not args.check:
        parser.error("--provenance requires --check")
    actual = build_inventory()

    if args.check:
        expected = json.loads(args.check.read_text())
        if actual != expected:
            print(f"inventory drift: regenerate {args.check}", file=sys.stderr)
            return 1
        if args.provenance:
            provenance = json.loads(args.provenance.read_text())
            source = provenance.get("source", {})
            inventory = provenance.get("file_inventory", {})
            expected_binding = {
                "path": args.check.as_posix(),
                "sha256": hashlib.sha256(args.check.read_bytes()).hexdigest(),
                "format_version": actual["format_version"],
                "records": actual["file_count"],
            }
            if source.get("commit") != SOURCE_COMMIT:
                print("provenance source commit drift", file=sys.stderr)
                return 1
            if source.get("tree") != SOURCE_TREE:
                print("provenance source tree drift", file=sys.stderr)
                return 1
            if inventory != expected_binding:
                print("provenance file inventory binding drift", file=sys.stderr)
                return 1
        print(
            f"verified {actual['file_count']} V3 files and "
            f"{actual['executable_count']} executable modes"
        )
        return 0

    if args.output:
        args.output.write_text(json.dumps(actual, indent=2) + "\n")
        print(f"wrote {actual['file_count']} V3 file records to {args.output}")
        return 0

    json.dump(actual, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
