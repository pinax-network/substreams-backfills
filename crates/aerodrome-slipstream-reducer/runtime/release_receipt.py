#!/usr/bin/env python3
"""Bind verified non-final OCI, runtime archive, smoke and registry evidence."""
import argparse
import json
import pathlib
import re

from verify_oci import file_pin, regular, require, small

ASSETS = {
    "producer-linux-amd64.oci.tar": "producer-linux-amd64.oci.tar",
    "producer-runtime.tar": "archive/producer-runtime.tar",
    "discovery.json": "archive/discovery.json",
    "oci-identity.json": "oci-identity.json",
    "registry-roundtrip.json": "registry-roundtrip.json",
    "smoke.json": "smoke/smoke.json",
}


def receipt(root, source, run_url):
    require(re.fullmatch(r"[0-9a-f]{40}", source), "invalid source commit")
    require(re.fullmatch(r"https://github.com/pinax-network/substreams-backfills/actions/runs/[0-9]+", run_url), "unexpected workflow URL")
    identity, _ = small(root / "oci-identity.json")
    roundtrip, _ = small(root / "registry-roundtrip.json")
    discovery, _ = small(root / "archive/discovery.json")
    smoke, _ = small(root / "smoke/smoke.json")
    require(identity["format"] == "pinax.backfill.producer-oci-identity/v1"
            and roundtrip["format"] == identity["format"]
            and discovery["format"] == "pinax.backfill.producer-discovery/v1"
            and smoke["format"] == "pinax.backfill.producer-smoke/v1", "unexpected evidence format")
    for item in (identity, roundtrip, discovery, smoke):
        require(item["production_selectable"] is False and item["source_commit"] == source,
                "evidence source/qualification mismatch")
        require(item["runtime_sha256"] == identity["runtime_sha256"], "evidence runtime mismatch")
    require({k: v for k, v in identity.items() if k != "archive"}
            == {k: v for k, v in roundtrip.items() if k != "archive"}, "registry image identity mismatch")
    pins = {name: file_pin(root / path) for name, path in ASSETS.items()}
    require(identity["archive"] == pins["producer-linux-amd64.oci.tar"]
            and discovery["archive"] == pins["producer-runtime.tar"]
            and discovery["smoke"] == pins["smoke.json"], "release bytes mismatch")
    with regular(root / "immutable-image.txt") as stream:
        raw_ref = stream.read(4097)
    require(len(raw_ref) <= 4096, "oversize image reference")
    immutable = raw_ref.decode().strip()
    require(immutable == "ghcr.io/pinax-network/substreams-backfills/aerodrome-producer@" + identity["oci_manifest"],
            "immutable image reference mismatch")
    return {"format": "pinax.backfill.producer-publication/v1", "production_selectable": False,
            "source_commit": source, "workflow_url": run_url, "platform": "linux/amd64",
            "image": immutable, "runtime_sha256": identity["runtime_sha256"], "assets": pins}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=pathlib.Path, required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--run-url", required=True)
    args = parser.parse_args()
    result = receipt(args.root, args.source, args.run_url)
    with (args.root / "publication.json").open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    with (args.root / "release-notes.md").open("x") as stream:
        stream.write(f"Development producer candidate from exact canonical source `{args.source}`.\n\n")
        stream.write(f"[Actual native Linux build, smoke and registry roundtrip]({args.run_url}).\n\n")
        stream.write(f"Immutable OCI image: `{result['image']}`. Runtime SHA-256: `{result['runtime_sha256']}`.\n\n")
        stream.write("The OCI archive binds the actual inspected image configuration and every compressed/uncompressed layer. The published registry image was independently retrieved by digest, reverified, and executed without network for exact version identity. The extracted Linux bundle passed version/stage/empty-seed checks; stream and live database qualification are separate.\n\n")
        stream.write("All artifacts remain `production_selectable: false`. This release does not authorize a live database load or claim full-range Aerodrome qualification. `publication.json` binds every other release asset.\n")


if __name__ == "__main__":
    main()
