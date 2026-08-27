#!/usr/bin/env python3
"""Build or verify the complete SHA-256 inventory for the pinned V4 source tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

SOURCE_COMMIT = "6812a4deaa5a520020e8d727e17f6d0b7113d0a9"
SOURCE_TREE = "2d60d30242443adc2c021a5b609c27edcb75128a"


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args])


def build_inventory() -> dict[str, object]:
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
    args = parser.parse_args()
    actual = build_inventory()

    if args.check:
        expected = json.loads(args.check.read_text())
        if actual != expected:
            print(f"inventory drift: regenerate {args.check}", file=sys.stderr)
            return 1
        print(
            f"verified {actual['file_count']} V4 files and "
            f"{actual['executable_count']} executable modes"
        )
        return 0

    json.dump(actual, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
