#!/usr/bin/env python3
"""Unauthenticated roundtrip of every published GitHub release asset.

The local publication receipt describes intended assets. Only this separate
completion receipt proves that all seven public uploads were fetched unchanged.
Partial downloads remain diagnostic; completion is written last.
"""
import argparse
import hashlib
import json
import os
import pathlib
import re
import urllib.parse
import urllib.request

from release_receipt import ASSETS
from verify_oci import file_pin, require, small


class HttpsRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        require(urllib.parse.urlsplit(newurl).scheme == "https", "non-HTTPS release redirect")
        return super().redirect_request(request, fp, code, message, headers, newurl)


def verify(root, tag, output, opener=None):
    match = re.fullmatch(r"aerodrome-producer-candidate-([0-9a-f]{40})-run-([0-9]+)-attempt-([0-9]+)", tag)
    require(match is not None, "unexpected release tag")
    publication, _ = small(root / "publication.json")
    require(publication["format"] == "pinax.backfill.producer-publication/v1"
            and publication["production_selectable"] is False
            and publication["source_commit"] == match[1]
            and publication["workflow_url"] == "https://github.com/pinax-network/substreams-backfills/actions/runs/" + match[2],
            "release/source/workflow mismatch")
    expected = {name: file_pin(root / path) for name, path in ASSETS.items()}
    require(publication["assets"] == expected, "local publication asset mismatch")
    expected["publication.json"] = file_pin(root / "publication.json")
    output.mkdir()
    opener = opener or urllib.request.build_opener(HttpsRedirect()).open
    base = "https://github.com/pinax-network/substreams-backfills/releases/download/" + tag + "/"
    for name, pin in expected.items():
        request = urllib.request.Request(base + name, headers={"User-Agent": "Pinax-producer-release-verifier/1"})
        temporary = output / (name + ".partial")
        digest, count = hashlib.sha256(), 0
        with opener(request, timeout=120) as response, temporary.open("xb") as stream:
            require(response.status == 200, "release download was not successful")
            while chunk := response.read(1024**2):
                count += len(chunk)
                require(count <= pin["bytes"], "release asset exceeds pinned size")
                digest.update(chunk)
                stream.write(chunk)
            stream.flush()
            os.fsync(stream.fileno())
        require({"bytes": count, "sha256": digest.hexdigest()} == pin, "published release asset differs")
        temporary.rename(output / name)
    result = {"format": "pinax.backfill.producer-release-verification/v1", "production_selectable": False,
              "source_commit": match[1], "release_url": base.replace("/download/", "/tag/").rstrip("/"),
              "unauthenticated_https": True, "assets": expected}
    partial = output / "complete.json.partial"
    with partial.open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(output, os.O_RDONLY)
    try:
        os.fsync(directory)
        partial.rename(output / "complete.json")
        os.fsync(directory)
    finally:
        os.close(directory)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=pathlib.Path)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    args = parser.parse_args()
    verify(args.root, args.tag, args.output)


if __name__ == "__main__":
    main()
