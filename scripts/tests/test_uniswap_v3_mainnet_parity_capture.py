from __future__ import annotations

import importlib.util
import json
import os
import stat
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
CAPTURE_PATH = ROOT / "scripts/capture-uniswap-v3-mainnet-parity-invocation.py"
SPEC = importlib.util.spec_from_file_location("v3_mainnet_parity_capture", CAPTURE_PATH)
assert SPEC is not None and SPEC.loader is not None
CAPTURE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CAPTURE)


FAKE_CLIENT = textwrap.dedent(
    r'''#!/usr/bin/env python3
import base64
import hashlib
import json
import os
import sys
import time
from pathlib import Path

CLIENT_VERSION = "uniswap-v3-mainnet-parity-client-v1 (protocol v3; upstream v1.20.3 cc555bd4e325b65ac3f95dfde4655076f88d4a0a)"
if sys.argv[1:] == ["--version"]:
    print(os.environ.get("FAKE_CLIENT_VERSION", CLIENT_VERSION))
    raise SystemExit(0)
if os.environ.get("FAKE_CLIENT_FAIL") == "1":
    print("fixture failure", file=sys.stderr)
    print("partial")
    raise SystemExit(7)

def argument(name):
    return sys.argv[sys.argv.index(name) + 1]

endpoint = argument("--endpoint")
package_path = Path(argument("--package"))
session_id = argument("--session-id")
invocation_id = argument("--invocation-id")
role = argument("--role")
source_revision = argument("--source-revision")
started = int(argument("--started-at-unix-nanos"))
package_raw = package_path.read_bytes()
binary_raw = Path(sys.argv[0]).resolve().read_bytes()
package = {"sha256": hashlib.sha256(package_raw).hexdigest(), "bytes": len(package_raw)}
client = {"sha256": hashlib.sha256(binary_raw).hexdigest(), "bytes": len(binary_raw)}
request = {
    "protocol_version": 3,
    "network": "mainnet",
    "module": "graph_out",
    "output_type": "sf.substreams.entity.v1.EntityChanges",
    "start_block": 12369621,
    "start_cursor": "",
    "end_block_exclusive": 12370674,
    "processed_block_limit": 1053,
    "final_blocks_only": True,
    "production_mode": False,
    "noop_mode": False,
    "partial_blocks": False,
    "max_retries": 0,
    "params": {},
    "debug_initial_store_snapshot_for_modules": [],
    "dev_output_modules": ["graph_out"],
    "package": package,
}
sanitized = [
    "uniswap-v3-mainnet-parity-client", "--endpoint", endpoint,
    "--package", f"<package:{role}>", "--session-id", session_id,
    "--invocation-id", invocation_id, "--role", role,
    "--source-revision", source_revision, "--started-at-unix-nanos", str(started),
]
lines = []
limit = 1052 if os.environ.get("FAKE_EARLY_EOF") == "1" else 1053
for index in range(limit):
    block = 12369621 + index
    raw = b"" if index % 2 == 0 else bytes([index % 251])
    record = {
        "format_version": 1,
        "kind": "uniswap-v3-mainnet-parity-block",
        "block": block,
        "block_id": f"{block:064x}",
        "timestamp_seconds": 1600000000 + index,
        "timestamp_nanos": index,
        "module": "graph_out",
        "output_type": "sf.substreams.entity.v1.EntityChanges",
        "map_output_base64": base64.b64encode(raw).decode(),
        "map_output_bytes": len(raw),
        "map_output_sha256": hashlib.sha256(raw).hexdigest(),
        "cursor_sha256": hashlib.sha256(f"cursor-{block}".encode()).hexdigest(),
    }
    line = json.dumps(record, separators=(",", ":"))
    lines.append((line + "\n").encode())
    sys.stdout.write(line + "\n")
if limit != 1053:
    raise SystemExit(0)
completion = {
    "format_version": 1,
    "kind": "uniswap-v3-mainnet-parity-stream-completion",
    "client_version": "uniswap-v3-mainnet-parity-client-v1",
    "protocol_version": 3,
    "upstream_version": "v1.20.3",
    "upstream_commit": "cc555bd4e325b65ac3f95dfde4655076f88d4a0a",
    "upstream_tree": "38ea588549e5e41698da00ee149278aa2d855c64",
    "session_id": session_id,
    "invocation_id": invocation_id,
    "role": role,
    "source_revision": source_revision,
    "endpoint": endpoint,
    "auth_kind": "x-api-key" if os.environ.get("SUBSTREAMS_API_KEY") else "bearer-token",
    "package": package,
    "capture_client": client,
    "request": request,
    "request_sha256": hashlib.sha256(json.dumps(request, separators=(",", ":")).encode()).hexdigest(),
    "sanitized_argv": sanitized,
    "started_at_unix_nanos": started,
    "completed_at_unix_nanos": max(started, time.time_ns()),
    "first_block": 12369621,
    "last_block": 12370673,
    "block_count": 1053,
    "records_sha256": hashlib.sha256(b"".join(lines)).hexdigest(),
    "completed": True,
}
if os.environ.get("FAKE_TAMPER_COMPLETION") == "1":
    completion["last_block"] -= 1
if os.environ.get("FAKE_SECRET_OUTPUT") == "1":
    print(os.environ.get("SUBSTREAMS_API_TOKEN") or os.environ.get("SUBSTREAMS_API_KEY"), file=sys.stderr)
sys.stdout.write(json.dumps(completion, separators=(",", ":")) + "\n")
'''
)


class InvocationCaptureTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="v3-capture-test.")
        self.work = Path(self.temporary.name)
        self.client = self.work / "parity-client"
        self.client.write_text(FAKE_CLIENT, encoding="utf-8")
        self.client.chmod(0o755)
        self.package = self.work / "candidate.spkg"
        self.package.write_bytes(b"fixture-package")
        self.stdout = self.work / "stdout"
        self.stderr = self.work / "stderr"
        self.completion = self.work / "completion.json"
        self.environment = {
            "SUBSTREAMS_API_TOKEN": "credential-never-serialized",
            "SUBSTREAMS_API_KEY": "",
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def args(self, **overrides: str) -> object:
        values = {
            "session_id": "a" * 64,
            "source_revision": "b" * 40,
            "role": "candidate",
            "endpoint": "mainnet.example.test:443",
            "capture_client": str(self.client),
            "package": str(self.package),
            "stdout": str(self.stdout),
            "stderr": str(self.stderr),
            "completion": str(self.completion),
            **overrides,
        }
        arguments: list[str] = []
        for key, value in values.items():
            arguments.extend((f"--{key.replace('_', '-')}", value))
        return CAPTURE.parse_args(arguments)

    def test_success_seals_atomic_private_outputs_and_complete_provenance(self) -> None:
        with mock.patch.dict(os.environ, self.environment, clear=False):
            completion = CAPTURE.capture(self.args())
        self.assertTrue(completion["completed"])
        self.assertEqual(completion["stream"]["block_count"], 1053)
        self.assertEqual(completion["auth_kind"], "bearer-token")
        self.assertEqual(json.loads(self.completion.read_text()), completion)
        self.assertNotIn("credential-never-serialized", self.completion.read_text())
        self.assertNotIn(str(self.package), self.completion.read_text())
        self.assertTrue(completion["clock"]["ordered"])
        for path in (self.stdout, self.stderr, self.completion):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertFalse(list(self.work.glob(".parity-*")))

    def test_wrong_client_version_is_rejected_before_outputs_exist(self) -> None:
        environment = {**self.environment, "FAKE_CLIENT_VERSION": "uniswap-v3-mainnet-parity-client-v1.20"}
        with mock.patch.dict(os.environ, environment, clear=False):
            with self.assertRaisesRegex(CAPTURE.CaptureError, "version identity drift"):
                CAPTURE.capture(self.args())
        self.assertFalse(self.stdout.exists())

    def test_failure_early_eof_completion_tamper_and_secret_remove_all_staged_outputs(self) -> None:
        cases = (
            ("FAKE_CLIENT_FAIL", "parity client failed"),
            ("FAKE_EARLY_EOF", "1,053 blocks plus completion"),
            ("FAKE_TAMPER_COMPLETION", "completion contract drift"),
            ("FAKE_SECRET_OUTPUT", "successful parity client wrote to stderr"),
        )
        for name, message in cases:
            with self.subTest(name=name):
                environment = {**self.environment, name: "1"}
                with mock.patch.dict(os.environ, environment, clear=False):
                    with self.assertRaisesRegex(CAPTURE.CaptureError, message):
                        CAPTURE.capture(self.args())
                self.assertFalse(self.stdout.exists())
                self.assertFalse(self.stderr.exists())
                self.assertFalse(self.completion.exists())
                self.assertFalse(list(self.work.glob(".parity-*")))

    def test_existing_output_is_never_reused(self) -> None:
        self.stdout.write_text("preserve", encoding="utf-8")
        with mock.patch.dict(os.environ, self.environment, clear=False):
            with self.assertRaisesRegex(CAPTURE.CaptureError, "refusing to overwrite"):
                CAPTURE.capture(self.args())
        self.assertEqual(self.stdout.read_text(), "preserve")
        self.assertFalse(self.stderr.exists())
        self.assertFalse(self.completion.exists())

    def test_malformed_metadata_endpoint_and_credentials_are_rejected(self) -> None:
        cases = (
            ({"session_id": "short"}, "session ID"),
            ({"endpoint": "https://user:password@example.test:443"}, "credential-free"),
            ({"role": "other"}, "role"),
        )
        for overrides, message in cases:
            with self.subTest(overrides=overrides):
                with mock.patch.dict(os.environ, self.environment, clear=False):
                    with self.assertRaisesRegex(CAPTURE.CaptureError, message):
                        CAPTURE.capture(self.args(**overrides))
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(CAPTURE.CaptureError, "exactly one"):
                CAPTURE.capture(self.args())


if __name__ == "__main__":
    unittest.main()
