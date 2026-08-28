#!/usr/bin/env python3
"""Build or verify the complete SHA-256 inventory for the pinned V3 source tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
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


def verify_live_source_tree(source_dir: Path, inventory: dict[str, object]) -> None:
    """Verify the filesystem tree that a materializer would otherwise copy.

    Git's index checks do not report ignored files and can miss untracked
    symlinks.  Both are unsafe here: Cargo consumes extra configuration files,
    and an overlay copy can follow a symlink out of the materialization root.
    The build-only top-level ``target`` directory is allowed when it is a real
    directory, but it is never copied or inspected.
    """

    source_dir = source_dir.resolve(strict=True)
    expected_files = {item["path"]: item for item in inventory["files"]}
    expected_directories = {
        parent.as_posix()
        for relative in expected_files
        for parent in Path(relative).parents
        if parent != Path(".")
    }
    actual_files: dict[str, os.DirEntry[str]] = {}
    actual_directories: set[str] = set()

    def walk(directory: Path, relative_directory: Path) -> None:
        with os.scandir(directory) as entries:
            for entry in entries:
                relative = relative_directory / entry.name
                relative_text = relative.as_posix()
                if relative_directory == Path(".") and entry.name == "target":
                    if entry.is_symlink() or not entry.is_dir(follow_symlinks=False):
                        raise RuntimeError("live source target must be a real directory when present")
                    continue
                if entry.is_symlink():
                    raise RuntimeError(f"live source contains symlink {relative_text}")
                if entry.is_dir(follow_symlinks=False):
                    actual_directories.add(relative_text)
                    walk(Path(entry.path), relative)
                    continue
                if not entry.is_file(follow_symlinks=False):
                    raise RuntimeError(f"live source contains non-regular entry {relative_text}")
                actual_files[relative_text] = entry

    walk(source_dir, Path("."))
    if set(actual_files) != set(expected_files):
        missing = sorted(set(expected_files) - set(actual_files))
        extra = sorted(set(actual_files) - set(expected_files))
        raise RuntimeError(f"live source file set drift; missing={missing}, extra={extra}")
    if actual_directories != expected_directories:
        missing = sorted(expected_directories - actual_directories)
        extra = sorted(actual_directories - expected_directories)
        raise RuntimeError(f"live source directory set drift; missing={missing}, extra={extra}")

    for relative, expected in expected_files.items():
        path = Path(actual_files[relative].path)
        metadata = path.stat(follow_symlinks=False)
        if not stat.S_ISREG(metadata.st_mode):
            raise RuntimeError(f"live source entry is not a regular file: {relative}")
        executable = bool(metadata.st_mode & 0o111)
        expected_executable = expected["mode"] == "100755"
        if executable != expected_executable:
            raise RuntimeError(f"live source executable mode drift: {relative}")
        if metadata.st_size != expected["size"]:
            raise RuntimeError(f"live source size drift: {relative}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected["sha256"]:
            raise RuntimeError(f"live source content drift: {relative}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", type=Path, help="verify an existing inventory")
    parser.add_argument(
        "--provenance",
        type=Path,
        help="with --check, verify the inventory binding in a provenance lock",
    )
    parser.add_argument(
        "--verify-source-dir",
        type=Path,
        help="with --check, verify the exact live filesystem tree before materialization",
    )
    parser.add_argument("--output", type=Path, help="write the generated inventory")
    args = parser.parse_args()
    if args.check and args.output:
        parser.error("--check and --output are mutually exclusive")
    if args.provenance and not args.check:
        parser.error("--provenance requires --check")
    if args.verify_source_dir and not args.check:
        parser.error("--verify-source-dir requires --check")
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
        if args.verify_source_dir:
            try:
                verify_live_source_tree(args.verify_source_dir, actual)
            except (OSError, RuntimeError) as error:
                print(f"live source verification failed: {error}", file=sys.stderr)
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
