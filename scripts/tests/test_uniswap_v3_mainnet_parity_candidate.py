from __future__ import annotations

import importlib.util
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPOSITORY = Path(__file__).resolve().parents[2]
BUILDER = REPOSITORY / "scripts/build-uniswap-v3-mainnet-parity-candidate.py"
CAPTURE = REPOSITORY / "scripts/capture-uniswap-v3-mainnet-parity-invocation.py"
VERIFIER = REPOSITORY / "scripts/verify-uniswap-v3-mainnet-chain-config-parity.py"
SPEC = importlib.util.spec_from_file_location("uniswap_v3_mainnet_candidate", BUILDER)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def load_module(name: str, path: Path) -> object:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def varint(value: int) -> bytes:
    output = bytearray()
    while value >= 0x80:
        output.append((value & 0x7F) | 0x80)
        value >>= 7
    output.append(value)
    return bytes(output)


def field(number: int, value: bytes) -> bytes:
    return varint((number << 3) | 2) + varint(len(value)) + value


class ControlledBuildCandidateTest(unittest.TestCase):
    def test_go_version_identity_requires_the_exact_official_output_grammar(self) -> None:
        self.assertIsNotNone(MODULE.GO_VERSION_RE.fullmatch("go version go1.26.5 linux/amd64"))
        for value in (
            "go version go1.26.50 linux/amd64",
            "go version go1.26.5-custom linux/amd64",
            "go version go1.26.5 linux/amd64 spoofed",
            "go version go1.26.5 windows/amd64",
        ):
            with self.subTest(value=value):
                self.assertIsNone(MODULE.GO_VERSION_RE.fullmatch(value))

    def test_cli_release_identity_contract_is_identical_across_all_harness_components(self) -> None:
        capture = load_module("v3_capture_identity_contract", CAPTURE)
        verifier = load_module("v3_verifier_identity_contract", VERIFIER)
        self.assertEqual(MODULE.SUBSTREAMS_VERSION, verifier.SUBSTREAMS_VERSION)
        self.assertEqual(MODULE.OFFICIAL_SUBSTREAMS_BINARIES, verifier.OFFICIAL_SUBSTREAMS_BINARIES)
        self.assertEqual(MODULE.CAPTURE_CLIENT_VERSION, capture.CLIENT_VERSION)
        self.assertEqual(MODULE.CAPTURE_UPSTREAM_COMMIT, capture.UPSTREAM_COMMIT)
        self.assertEqual(MODULE.CAPTURE_UPSTREAM_TREE, capture.UPSTREAM_TREE)

    def test_strict_json_rejects_ambiguous_encodings(self) -> None:
        rejected = (
            b'{"value":1,"value":2}',
            b'{"value":1.0}',
            b'{"value":NaN}',
            b'{"value":1} trailing',
            b'{"value":"\xff"}',
        )
        for payload in rejected:
            with self.subTest(payload=payload):
                with self.assertRaises(MODULE.CandidateError):
                    MODULE.strict_json_bytes(payload, "fixture")

    def test_embedded_wasm_parser_requires_one_nonempty_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary) / "candidate.spkg"
            binary = field(1, b"wasm/rust-v1") + field(2, b"\0asm-candidate")
            package.write_bytes(field(6, field(2, binary)))
            self.assertEqual(MODULE.embedded_wasm(package), b"\0asm-candidate")

            package.write_bytes(field(6, field(2, binary) + field(2, binary)))
            with self.assertRaises(MODULE.CandidateError):
                MODULE.embedded_wasm(package)

    def test_module_inventory_is_complete_and_hashes_are_exact(self) -> None:
        modules = [
            {
                "name": name,
                "hash": "a" * 40,
                **(
                    {"kind": "map", "output_type": "proto:sf.substreams.entity.v1.EntityChanges"}
                    if name == "graph_out"
                    else {}
                ),
            }
            for name in sorted(MODULE.EXPECTED_MODULES)
        ]
        self.assertEqual(
            set(MODULE.module_hashes({"modules": modules}, Path("candidate.spkg"))),
            MODULE.EXPECTED_MODULES,
        )
        modules[0]["hash"] = "b" * 64
        with self.assertRaises(MODULE.CandidateError):
            MODULE.module_hashes({"modules": modules}, Path("candidate.spkg"))

    def test_manifest_write_is_immutable_and_private(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "candidate.json"
            MODULE.write_exclusive(output, {"format_version": 1})
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            original = output.read_bytes()
            with self.assertRaises(FileExistsError):
                MODULE.write_exclusive(output, {"format_version": 2})
            self.assertEqual(output.read_bytes(), original)

    def test_substreams_identity_binds_pinned_version_and_binary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            binary = Path(temporary) / "substreams"
            binary.write_text(f"#!/bin/sh\necho '{MODULE.SUBSTREAMS_VERSION}'\n")
            binary.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
            system = MODULE.platform.system().lower()
            machine = MODULE.platform.machine().lower()
            machine = {"amd64": "x86_64", "aarch64": "arm64"}.get(machine, machine)
            release_platform = f"{system}-{machine}"
            expected = {
                "binary_sha256": MODULE.sha256(binary),
                "binary_bytes": binary.stat().st_size,
                "release_archive_sha256": "0" * 64,
            }
            with mock.patch.object(MODULE.shutil, "which", return_value=str(binary)), mock.patch.dict(
                MODULE.OFFICIAL_SUBSTREAMS_BINARIES,
                {release_platform: expected},
                clear=True,
            ):
                identity = MODULE.substreams_identity(REPOSITORY)
            self.assertEqual(identity["version"], MODULE.SUBSTREAMS_VERSION)
            self.assertEqual(identity["binary_sha256"], MODULE.sha256(binary))
            self.assertEqual(identity["binary_bytes"], binary.stat().st_size)

            for version in ("1.20.2", "1.20.30"):
                with self.subTest(version=version):
                    binary.write_text(f"#!/bin/sh\necho 'substreams version {version}'\n")
                    binary.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
                    with mock.patch.object(MODULE.shutil, "which", return_value=str(binary)):
                        with self.assertRaisesRegex(MODULE.CandidateError, "exact official v1.20.3"):
                            MODULE.substreams_identity(REPOSITORY)


if __name__ == "__main__":
    unittest.main()
