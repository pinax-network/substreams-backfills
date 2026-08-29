#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


DEFAULT_MANIFEST = Path("docs/provenance/uniswap-v4-release-assets-v1.json")
MIRROR_ROOT = Path("artifacts/releases/uniswap-v4")

EXPECTED_ASSETS: tuple[dict[str, Any], ...] = (
    {
        "release_tag": "v0.1.0",
        "release_url": "https://github.com/pinax-network/substreams-v4-subgraph/releases/tag/v0.1.0",
        "asset_api_id": 499820971,
        "asset_name": "uniswap-v4-base-backfill-v0.1.0.spkg",
        "asset_url": "https://github.com/pinax-network/substreams-v4-subgraph/releases/download/v0.1.0/uniswap-v4-base-backfill-v0.1.0.spkg",
        "content_type": "application/octet-stream",
        "created_at": "2026-08-03T08:36:32Z",
        "size": 442378,
        "sha256": "75b810d18ec1dc78ca5535b2cc56828334c873b93d39500f93ca036499048453",
        "path": "artifacts/releases/uniswap-v4/v0.1.0/uniswap-v4-base-backfill-v0.1.0.spkg",
    },
    {
        "release_tag": "v0.4.1",
        "release_url": "https://github.com/pinax-network/substreams-v4-subgraph/releases/tag/v0.4.1",
        "asset_api_id": 523102666,
        "asset_name": "uniswap-v4-base-nul-metadata-audit-v0.1.0.spkg",
        "asset_url": "https://github.com/pinax-network/substreams-v4-subgraph/releases/download/v0.4.1/uniswap-v4-base-nul-metadata-audit-v0.1.0.spkg",
        "content_type": "application/octet-stream",
        "created_at": "2026-08-21T02:29:01Z",
        "size": 1534793,
        "sha256": "c2470ab845cebc929aa20489a21114cb9db891aef9ad99559c97757b1938e81a",
        "path": "artifacts/releases/uniswap-v4/v0.4.1/uniswap-v4-base-nul-metadata-audit-v0.1.0.spkg",
    },
)

EXPECTED_BOUNDARY = {
    "mirrored_bytes_are_immutable": True,
    "historical_source_releases_must_remain_available": True,
    "active_workflows_may_still_use_source_repository": True,
    "new_release_from_this_repository_verified": False,
    "source_repository_archive_authorized": False,
}


class VerificationError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def reject_symlink_components(root: Path, relative_path: Path) -> None:
    current = root
    for component in relative_path.parts:
        current /= component
        if current.is_symlink():
            raise VerificationError(
                f"mirrored asset uses a symlinked path component: {relative_path}"
            )


def expected_manifest() -> dict[str, Any]:
    return {
        "format_version": 1,
        "family": "uniswap-v4-base",
        "source_repository": "pinax-network/substreams-v4-subgraph",
        "mirror_root": MIRROR_ROOT.as_posix(),
        "future_release_authority_transferred": False,
        "assets": [dict(asset) for asset in EXPECTED_ASSETS],
        "boundary": dict(EXPECTED_BOUNDARY),
    }


def verify(root: Path, manifest_path: Path = DEFAULT_MANIFEST) -> None:
    root = root.resolve()
    resolved_manifest = manifest_path if manifest_path.is_absolute() else root / manifest_path
    try:
        manifest = json.loads(resolved_manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VerificationError(f"cannot read release-asset manifest: {exc}") from exc

    if manifest != expected_manifest():
        raise VerificationError("release-asset manifest differs from the pinned contract")

    expected_paths: set[str] = set()
    for asset in EXPECTED_ASSETS:
        relative_path = Path(asset["path"])
        expected_paths.add(relative_path.as_posix())
        candidate = root / relative_path
        reject_symlink_components(root, relative_path)
        try:
            resolved_candidate = candidate.resolve(strict=True)
            resolved_candidate.relative_to(root)
        except (OSError, ValueError) as exc:
            raise VerificationError(f"unsafe or missing mirrored asset: {relative_path}") from exc
        if not resolved_candidate.is_file():
            raise VerificationError(f"mirrored asset is not a regular file: {relative_path}")
        actual_size = resolved_candidate.stat().st_size
        if actual_size != asset["size"]:
            raise VerificationError(
                f"{relative_path} has size {actual_size}, expected {asset['size']}"
            )
        actual_sha256 = sha256_file(resolved_candidate)
        if actual_sha256 != asset["sha256"]:
            raise VerificationError(
                f"{relative_path} has SHA-256 {actual_sha256}, expected {asset['sha256']}"
            )

    mirror = root / MIRROR_ROOT
    actual_paths = {
        package.relative_to(root).as_posix()
        for package in mirror.rglob("*.spkg")
        if package.is_file() or package.is_symlink()
    }
    if actual_paths != expected_paths:
        missing = sorted(expected_paths - actual_paths)
        unexpected = sorted(actual_paths - expected_paths)
        raise VerificationError(
            f"release mirror inventory differs: missing={missing}, unexpected={unexpected}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify immutable Uniswap V4 historical release assets."
    )
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()
    try:
        verify(args.root, args.manifest)
    except VerificationError as exc:
        parser.error(str(exc))
    print("verified 2 immutable Uniswap V4 historical release assets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
