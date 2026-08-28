#!/usr/bin/env python3
"""Resolve a materialization destination and reject repository containment."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def same_file(left: Path, right: Path) -> bool:
    try:
        return os.path.samefile(left, right)
    except (FileNotFoundError, OSError):
        return False


def resolve_destination(repository: Path, destination: Path) -> Path:
    repository = repository.resolve(strict=True)
    destination = destination.resolve(strict=False)

    # Comparing strings is insufficient on case-insensitive filesystems. Walk
    # every existing destination ancestor and compare device/inode identity so
    # case aliases and symlink aliases into the repository fail closed.
    if any(
        ancestor.exists() and same_file(ancestor, repository)
        for ancestor in (destination, *destination.parents)
    ):
        raise ValueError("destination must be outside the repository and frozen source")

    # Also refuse an existing ancestor of the repository as a destination. It
    # cannot be a valid empty target and would make a broad extraction unsafe.
    if destination.exists() and any(
        same_file(destination, protected)
        for protected in (repository, *repository.parents)
    ):
        raise ValueError("destination must not contain the repository")

    return destination


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    try:
        print(resolve_destination(args.repository, args.destination))
        return 0
    except (OSError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
