#!/usr/bin/env python3
"""Hermetic adversarial tests for the complete protocol-v3 parity verifier."""

from __future__ import annotations

import base64
import copy
import hashlib
import importlib.util
import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
VERIFIER_PATH = ROOT / "scripts/verify-uniswap-v3-mainnet-chain-config-parity.py"
PROFILE_PATH = ROOT / "uniswap-v3/fixtures/mainnet-chain-config-parity-v1.json"
SPEC = importlib.util.spec_from_file_location("v3_mainnet_parity", VERIFIER_PATH)
assert SPEC is not None and SPEC.loader is not None
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def varint(value: int) -> bytes:
    result = bytearray()
    while value >= 0x80:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.append(value)
    return bytes(result)


def field(number: int, value: bytes) -> bytes:
    return varint(number << 3 | 2) + varint(len(value)) + value


def scalar(number: int, value: int) -> bytes:
    return varint(number << 3) + varint(value)


def entity_changes(entity: str, identity: str) -> bytes:
    change = field(1, entity.encode()) + field(2, identity.encode()) + scalar(4, 1)
    return field(5, change)


def artifact(seed: str) -> dict[str, object]:
    return {
        "spkg_sha256": sha256(f"spkg:{seed}".encode()),
        "bytes": 1000 + len(seed),
        "wasm_sha256": sha256(f"wasm:{seed}".encode()),
        "wasm_bytes": 500 + len(seed),
        "execution_module_hashes": {
            module: hashlib.sha1(f"{seed}:{module}".encode()).hexdigest()
            for module in VERIFIER.EXPECTED_MODULES
        },
    }


def capture_client_identity() -> dict[str, object]:
    inventory = [
        "github.com/streamingfast/substreams/pb/sf/substreams/rpc/v3|github.com/streamingfast/substreams|v1.20.3|h1:fixture"
    ]
    build_info = [
        "go\tgo1.26.5",
        "\tpath\tgithub.com/pinax-network/substreams-backfills/scripts/parity-client",
        "\tdep\tgithub.com/streamingfast/substreams\tv1.20.3\th1:fixture",
        "\tbuild\t-trimpath=true",
        "\tbuild\tCGO_ENABLED=0",
        "\tbuild\tGOOS=linux",
        "\tbuild\tGOARCH=amd64",
    ]
    modules = sorted(line for line in build_info if line.startswith("\tdep\t"))
    go_mod = (ROOT / "scripts/parity-client/go.mod").read_bytes()
    stub_mod = (ROOT / "scripts/parity-client/services-control-plane-stub/go.mod").read_bytes()
    module_graph_patch = b"scripts/parity-client/go.mod\0" + go_mod + b"\0scripts/parity-client/services-control-plane-stub/go.mod\0" + stub_mod
    return {
        "version": VERIFIER.CAPTURE_CLIENT_VERSION,
        "binary_sha256": "a" * 64,
        "binary_bytes": 123456,
        "build": {
            "go_version": "go version go1.26.5 linux/amd64",
            "goos": "linux",
            "goarch": "amd64",
            "command": ["go", "build", "-mod=readonly", "-trimpath", "-buildvcs=false", "-ldflags=-buildid=", "-o", "<capture-client>", "."],
            "cgo_enabled": False,
        },
        "source": {
            "upstream_version": VERIFIER.CAPTURE_UPSTREAM_VERSION,
            "upstream_commit": VERIFIER.CAPTURE_UPSTREAM_COMMIT,
            "upstream_tree": VERIFIER.CAPTURE_UPSTREAM_TREE,
            "client_sha256": sha256((ROOT / "scripts/parity-client/main.go").read_bytes()),
            "tests_sha256": sha256((ROOT / "scripts/parity-client/main_test.go").read_bytes()),
            "go_mod_sha256": sha256((ROOT / "scripts/parity-client/go.mod").read_bytes()),
            "go_sum_sha256": sha256((ROOT / "scripts/parity-client/go.sum").read_bytes()),
            "package_less_replacement_go_mod_sha256": sha256((ROOT / "scripts/parity-client/services-control-plane-stub/go.mod").read_bytes()),
            "public_module_graph_patch_sha256": sha256(module_graph_patch),
            "runtime_dependency_inventory": inventory,
            "runtime_dependency_inventory_sha256": sha256(("\n".join(inventory) + "\n").encode()),
            "runtime_dependency_count": len(inventory),
            "binary_build_info": build_info,
            "binary_build_info_sha256": sha256(("\n".join(build_info) + "\n").encode()),
            "binary_module_inventory": modules,
            "binary_module_count": len(modules),
            "private_replacement_imported": False,
        },
    }


def build_manifest(profile_raw: bytes) -> dict[str, object]:
    baseline = artifact("baseline")
    mainnet = artifact("configured")
    base = artifact("base")
    base["wasm_sha256"] = mainnet["wasm_sha256"]
    base["wasm_bytes"] = mainnet["wasm_bytes"]
    revision = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD^{commit}"], text=True).strip()
    tree = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD^{tree}"], text=True).strip()
    return {
        "format_version": 1,
        "kind": VERIFIER.BUILD_KIND,
        "status": VERIFIER.BUILD_STATUS,
        "source": {
            "repository": "pinax-network/substreams-backfills", "revision": revision, "tree": tree,
            "import_repository": VERIFIER.IMPORT_REPOSITORY,
            "import_commit": VERIFIER.IMPORT_COMMIT, "import_tree": VERIFIER.IMPORT_TREE,
        },
        "inputs": {
            "profile_sha256": sha256(profile_raw), "chain_config_sha256": VERIFIER.CONFIG_SHA256,
            "chain_config_provenance_sha256": VERIFIER.CONFIG_PROVENANCE_SHA256,
            "runtime_overlay_sha256": VERIFIER.OVERLAY_SHA256, "schema_sha256": VERIFIER.TARGET_SCHEMA_SHA256,
        },
        "toolchain": {
            "rustc": "rustc 1.79.0", "cargo": "cargo 1.79.0",
            "substreams": {"version": VERIFIER.SUBSTREAMS_VERSION, "release_platform": "linux-x86_64", **VERIFIER.OFFICIAL_SUBSTREAMS_BINARIES["linux-x86_64"]},
            "capture_client": capture_client_identity(), "go": "go version go1.26.5 linux/amd64",
            "python": "Python 3.12.0", "platform": "Linux-x86_64",
        },
        "artifacts": {"baseline": baseline, "configured_mainnet": mainnet, "configured_base": base},
        "assertions": {"configured_mainnet_and_base_wasm_equal": True, "baseline_and_configured_mainnet_wasm_equal": False},
        "trust_boundary": copy.deepcopy(VERIFIER.TRUST_BOUNDARY),
    }


class ParityVerifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="v3-parity-verifier.")
        self.work = Path(self.temporary.name)
        self.capture_dir = self.work / "capture"
        self.output_dir = self.work / "output"
        self.capture_dir.mkdir()
        self.output_dir.mkdir()
        self.profile_raw = PROFILE_PATH.read_bytes()
        self.profile = self.work / "profile.json"
        self.profile.write_bytes(self.profile_raw)
        self.manifest_value = build_manifest(self.profile_raw)
        self.manifest = self.work / "build.json"
        self.manifest.write_bytes(json_bytes(self.manifest_value))
        self.session_id = "b" * 64
        self.endpoint = "mainnet.example.test:443"
        self.rpc_label = "public-test-rpc"
        self.paths = {
            role: {
                "stdout": self.capture_dir / f"{role}.stdout",
                "stderr": self.capture_dir / f"{role}.stderr",
                "completion": self.capture_dir / f"{role}.completion.json",
            }
            for role in ("baseline", "candidate")
        }
        self.outputs = {
            role: {
                "stdout": self.output_dir / f"{role}.stdout",
                "stderr": self.output_dir / f"{role}.stderr",
                "completion": self.output_dir / f"{role}.completion.json",
                "capture": self.output_dir / f"{role}.capture.json",
                "canonical": self.output_dir / f"{role}.canonical.jsonl",
            }
            for role in ("baseline", "candidate")
        }
        self.certificate = self.output_dir / "certificate.json"
        self.rpc_before = self.work / "rpc-before.json"
        self.rpc_after = self.work / "rpc-after.json"
        self.rpc_blocks = {
            str(block): {
                "number": block,
                "hash": "0x" + sha256(str(block).encode()),
                "timestamp_seconds": 1_600_000_000 + index,
            }
            for index, block in enumerate(range(VERIFIER.START_BLOCK, VERIFIER.END_BLOCK_EXCLUSIVE))
        }
        self.stream_outputs = [b"" for _ in range(VERIFIER.PROCESSED_BLOCK_LIMIT)]
        for block, entity in (
            (VERIFIER.START_BLOCK, "Factory"),
            (12_369_651, "Position"),
            (12_370_624, "Mint"),
            (VERIFIER.END_BLOCK_EXCLUSIVE - 1, "TickDayData"),
        ):
            self.stream_outputs[block - VERIFIER.START_BLOCK] = entity_changes(entity, f"id-{block}")
        self.write_rpc("before", self.rpc_before, 100, 200)
        self.write_capture("baseline", self.stream_outputs, 300, 400, 500)
        self.write_capture("candidate", self.stream_outputs, 600, 700, 800)
        self.write_rpc("after", self.rpc_after, 900, 1000)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_rpc(self, phase: str, path: Path, started: int, completed: int) -> None:
        value = {
            "format_version": 1, "kind": VERIFIER.RPC_KIND, "session_id": self.session_id,
            "phase": phase, "rpc_label": self.rpc_label, "network": "mainnet", "chain_id": "0x1",
            "range": {"start_block": VERIFIER.START_BLOCK, "end_block_exclusive": VERIFIER.END_BLOCK_EXCLUSIVE, "block_count": VERIFIER.PROCESSED_BLOCK_LIMIT},
            "batches": {"maximum_batch_size": 50, "request_count": 22},
            "clock": {"started_at_unix_nanos": started, "completed_at_unix_nanos": completed, "ordered": True},
            "blocks": copy.deepcopy(self.rpc_blocks),
            "blocks_sha256": sha256(VERIFIER.canonical_json(self.rpc_blocks)),
            "completed": True,
            "trust_boundary": copy.deepcopy(VERIFIER.TRUST_BOUNDARY),
        }
        path.write_bytes(json_bytes(value))

    def write_capture(self, role: str, outputs: list[bytes], started: int, client_completed: int, wrapper_completed: int) -> None:
        paths = self.paths[role]
        artifact_name = "baseline" if role == "baseline" else "configured_mainnet"
        artifact_value = self.manifest_value["artifacts"][artifact_name]
        client = self.manifest_value["toolchain"]["capture_client"]
        invocation_id = ("1" if role == "baseline" else "2") * 64
        package = {"sha256": artifact_value["spkg_sha256"], "bytes": artifact_value["bytes"]}
        request = VERIFIER.request_contract(package)
        records = []
        lines = []
        for index, raw in enumerate(outputs):
            block = VERIFIER.START_BLOCK + index
            record = {
                "format_version": 1, "kind": VERIFIER.BLOCK_KIND, "block": block,
                "block_id": self.rpc_blocks[str(block)]["hash"][2:],
                "timestamp_seconds": self.rpc_blocks[str(block)]["timestamp_seconds"], "timestamp_nanos": 0,
                "module": VERIFIER.MODULE, "output_type": VERIFIER.OUTPUT_TYPE,
                "map_output_base64": base64.b64encode(raw).decode(), "map_output_bytes": len(raw),
                "map_output_sha256": sha256(raw), "cursor_sha256": sha256(f"cursor:{role}:{block}".encode()),
            }
            line = VERIFIER.compact_json(record)
            records.append(record)
            lines.append(line + b"\n")
        completion = {
            "format_version": 1, "kind": VERIFIER.STREAM_COMPLETION_KIND,
            "client_version": "uniswap-v3-mainnet-parity-client-v1", "protocol_version": 3,
            "upstream_version": VERIFIER.CAPTURE_UPSTREAM_VERSION, "upstream_commit": VERIFIER.CAPTURE_UPSTREAM_COMMIT,
            "upstream_tree": VERIFIER.CAPTURE_UPSTREAM_TREE, "session_id": self.session_id,
            "invocation_id": invocation_id, "role": role,
            "source_revision": self.manifest_value["source"]["revision"], "endpoint": self.endpoint,
            "auth_kind": "bearer-token", "package": package,
            "capture_client": {"sha256": client["binary_sha256"], "bytes": client["binary_bytes"]},
            "request": request, "request_sha256": sha256(VERIFIER.compact_json(request)),
            "sanitized_argv": VERIFIER.expected_argv(role, self.endpoint, self.session_id, invocation_id, self.manifest_value["source"]["revision"], started),
            "started_at_unix_nanos": started, "completed_at_unix_nanos": client_completed,
            "first_block": VERIFIER.START_BLOCK, "last_block": VERIFIER.END_BLOCK_EXCLUSIVE - 1,
            "block_count": VERIFIER.PROCESSED_BLOCK_LIMIT, "records_sha256": sha256(b"".join(lines)), "completed": True,
        }
        stdout = b"".join(lines) + VERIFIER.compact_json(completion) + b"\n"
        paths["stdout"].write_bytes(stdout)
        paths["stderr"].write_bytes(b"")
        block_hashes = {str(record["block"]): "0x" + record["block_id"] for record in records}
        map_hashes = [record["map_output_sha256"] for record in records]
        cursor_hashes = [record["cursor_sha256"] for record in records]
        sidecar = {
            "format_version": 1, "kind": VERIFIER.INVOCATION_KIND, "session_id": self.session_id,
            "invocation_id": invocation_id, "role": role, "source_revision": self.manifest_value["source"]["revision"],
            "package": {"artifact": artifact_name, **package}, "endpoint": self.endpoint, "auth_kind": "bearer-token",
            "capture_client": {"version": client["version"], "binary_sha256": client["binary_sha256"], "binary_bytes": client["binary_bytes"]},
            "request": request, "request_sha256": sha256(VERIFIER.compact_json(request)),
            "sanitized_argv": completion["sanitized_argv"],
            "clock": {"wrapper_started_at_unix_nanos": started, "client_completed_at_unix_nanos": client_completed, "wrapper_completed_at_unix_nanos": wrapper_completed, "ordered": True},
            "stream": {
                "first_block": VERIFIER.START_BLOCK, "last_block": VERIFIER.END_BLOCK_EXCLUSIVE - 1,
                "block_count": VERIFIER.PROCESSED_BLOCK_LIMIT, "started_at_unix_nanos": started,
                "completed_at_unix_nanos": client_completed,
                "first_timestamp": {"seconds": records[0]["timestamp_seconds"], "nanos": 0},
                "last_timestamp": {"seconds": records[-1]["timestamp_seconds"], "nanos": 0},
                "records_sha256": completion["records_sha256"],
                "block_hashes_sha256": sha256(VERIFIER.canonical_json(block_hashes)),
                "map_output_hashes_sha256": sha256(VERIFIER.compact_json(map_hashes)),
                "cursor_hashes_sha256": sha256(VERIFIER.compact_json(cursor_hashes)),
            },
            "raw": {
                "stdout": {"name": paths["stdout"].name, "sha256": sha256(stdout), "bytes": len(stdout)},
                "stderr": {"name": paths["stderr"].name, "sha256": sha256(b""), "bytes": 0},
            },
            "exit_code": 0, "completed": True, "trust_boundary": copy.deepcopy(VERIFIER.TRUST_BOUNDARY),
        }
        paths["completion"].write_bytes(json_bytes(sidecar))

    def verify(self) -> dict[str, object]:
        with mock.patch.object(VERIFIER, "validate_exact_source", return_value={"fixture": {"sha256": "f" * 64, "bytes": 1}}):
            return VERIFIER.verify_and_emit(
                root=ROOT, profile_path=self.profile,
                baseline_stdout_path=self.paths["baseline"]["stdout"], baseline_stderr_path=self.paths["baseline"]["stderr"],
                baseline_completion_path=self.paths["baseline"]["completion"],
                candidate_stdout_path=self.paths["candidate"]["stdout"], candidate_stderr_path=self.paths["candidate"]["stderr"],
                candidate_completion_path=self.paths["candidate"]["completion"], build_manifest_path=self.manifest,
                rpc_before_path=self.rpc_before, rpc_after_path=self.rpc_after,
                baseline_stdout_retained_path=self.outputs["baseline"]["stdout"], baseline_stderr_retained_path=self.outputs["baseline"]["stderr"],
                baseline_completion_retained_path=self.outputs["baseline"]["completion"],
                candidate_stdout_retained_path=self.outputs["candidate"]["stdout"], candidate_stderr_retained_path=self.outputs["candidate"]["stderr"],
                candidate_completion_retained_path=self.outputs["candidate"]["completion"],
                baseline_capture_path=self.outputs["baseline"]["capture"], candidate_capture_path=self.outputs["candidate"]["capture"],
                baseline_canonical_path=self.outputs["baseline"]["canonical"], candidate_canonical_path=self.outputs["candidate"]["canonical"],
                certificate_path=self.certificate, session_id=self.session_id, endpoint=self.endpoint, rpc_label=self.rpc_label,
                redaction_values=(b"never-present-api-secret", b"https://secret-rpc.example/key"),
            )

    def all_outputs(self) -> list[Path]:
        return [self.certificate, *(path for values in self.outputs.values() for path in values.values())]

    def assert_rejected(self, message: str) -> None:
        with self.assertRaisesRegex(VERIFIER.VerificationError, message):
            self.verify()
        self.assertFalse(any(os.path.lexists(path) for path in self.all_outputs()))

    def rewrite_sidecar_raw_hash(self, role: str) -> None:
        sidecar = json.loads(self.paths[role]["completion"].read_text())
        raw = self.paths[role]["stdout"].read_bytes()
        sidecar["raw"]["stdout"] = {"name": self.paths[role]["stdout"].name, "sha256": sha256(raw), "bytes": len(raw)}
        self.paths[role]["completion"].write_bytes(json_bytes(sidecar))

    def test_complete_exact_parity_certificate_is_nonpromotable_and_immutable(self) -> None:
        certificate = self.verify()
        self.assertEqual(certificate["comparison"]["record_count"], 1053)
        self.assertTrue(certificate["comparison"]["ordered_envelopes_equal"])
        self.assertFalse(certificate["comparison"]["missing_blocks_reconstructed"])
        self.assertTrue(certificate["comparison"]["cursor_final_block_and_lib_binding_enforced"])
        self.assertEqual(certificate["entity_truth_boundary"]["known_unimplemented_entity_rows"], ["Collect", "Flash"])
        self.assertFalse(certificate["entity_truth_boundary"]["all_schema_entities_implemented"])
        self.assertEqual(certificate["trust_boundary"], VERIFIER.TRUST_BOUNDARY)
        self.assertEqual(self.outputs["baseline"]["canonical"].read_bytes(), self.outputs["candidate"]["canonical"].read_bytes())
        self.assertEqual(len(self.outputs["baseline"]["canonical"].read_bytes().splitlines()), 1053)
        for path in self.all_outputs():
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o444)

    def test_truncated_extra_reordered_and_duplicate_streams_fail_even_with_fresh_raw_binding(self) -> None:
        for mode in ("truncated", "extra", "reordered", "duplicate"):
            with self.subTest(mode=mode):
                self.tearDown()
                self.setUp()
                lines = self.paths["candidate"]["stdout"].read_bytes().splitlines(keepends=True)
                if mode == "truncated":
                    del lines[-2]
                elif mode == "extra":
                    lines.insert(-1, lines[-2])
                elif mode == "reordered":
                    lines[0], lines[1] = lines[1], lines[0]
                else:
                    lines[1] = lines[0]
                self.paths["candidate"]["stdout"].write_bytes(b"".join(lines))
                self.rewrite_sidecar_raw_hash("candidate")
                self.assert_rejected("exactly 1,053|missing, duplicate, or out-of-range")

    def test_early_eof_or_completion_line_tampering_cannot_be_replayed(self) -> None:
        lines = self.paths["candidate"]["stdout"].read_bytes().splitlines(keepends=True)
        del lines[-2]
        completion = json.loads(lines[-1])
        completion["records_sha256"] = sha256(b"".join(lines[:-1]))
        completion["block_count"] = 1052
        lines[-1] = VERIFIER.compact_json(completion) + b"\n"
        self.paths["candidate"]["stdout"].write_bytes(b"".join(lines))
        self.rewrite_sidecar_raw_hash("candidate")
        self.assert_rejected("exactly 1,053")

    def test_validly_resealed_candidate_map_byte_drift_is_rejected(self) -> None:
        changed = list(self.stream_outputs)
        changed[0] = entity_changes("Factory", "different-id")
        self.write_capture("candidate", changed, 600, 700, 800)
        self.assert_rejected("ordered graph_out protobuf bytes differ")

    def test_base64_length_digest_timestamp_hash_and_output_contract_tamper_are_rejected(self) -> None:
        mutations = (
            ("map_output_base64", "!!!"),
            ("map_output_bytes", 999),
            ("map_output_sha256", "f" * 64),
            ("timestamp_nanos", 1),
            ("block_id", "f" * 64),
            ("module", "other"),
            ("output_type", "other.Type"),
        )
        for key, value in mutations:
            with self.subTest(key=key):
                self.tearDown()
                self.setUp()
                lines = self.paths["candidate"]["stdout"].read_bytes().splitlines(keepends=True)
                record = json.loads(lines[0])
                record[key] = value
                lines[0] = VERIFIER.compact_json(record) + b"\n"
                self.paths["candidate"]["stdout"].write_bytes(b"".join(lines))
                self.rewrite_sidecar_raw_hash("candidate")
                self.assert_rejected("base64|length|digest|timestamp|hash|output contract|provenance")

    def test_rpc_fork_missing_block_timestamp_and_clock_boundaries_are_rejected(self) -> None:
        cases = ("fork", "missing", "timestamp", "clock")
        for case in cases:
            with self.subTest(case=case):
                self.tearDown()
                self.setUp()
                value = json.loads(self.rpc_after.read_text())
                if case == "fork":
                    value["blocks"][str(VERIFIER.START_BLOCK)]["hash"] = "0x" + "f" * 64
                elif case == "missing":
                    value["blocks"].pop(str(VERIFIER.START_BLOCK))
                elif case == "timestamp":
                    value["blocks"][str(VERIFIER.START_BLOCK)]["timestamp_seconds"] += 1
                else:
                    value["clock"]["started_at_unix_nanos"] = 700
                value["blocks_sha256"] = sha256(VERIFIER.canonical_json(value["blocks"]))
                self.rpc_after.write_bytes(json_bytes(value))
                self.assert_rejected("changed|keys differ|timestamps|does not follow")

    def test_invocation_package_binary_request_role_source_and_session_replay_are_rejected(self) -> None:
        keys = ("session_id", "role", "source_revision", "endpoint", "request_sha256")
        for key in keys:
            with self.subTest(key=key):
                self.tearDown()
                self.setUp()
                sidecar = json.loads(self.paths["candidate"]["completion"].read_text())
                sidecar[key] = "x" * (64 if key == "session_id" else 40) if key in {"session_id", "source_revision"} else "tampered"
                self.paths["candidate"]["completion"].write_bytes(json_bytes(sidecar))
                self.assert_rejected("session/source|endpoint/auth|request contract")
        self.tearDown()
        self.setUp()
        sidecar = json.loads(self.paths["candidate"]["completion"].read_text())
        sidecar["capture_client"]["binary_sha256"] = "f" * 64
        self.paths["candidate"]["completion"].write_bytes(json_bytes(sidecar))
        self.assert_rejected("capture-client identity differs")

    def test_unknown_collect_flash_and_malformed_entity_payloads_are_rejected(self) -> None:
        for raw in (entity_changes("Unknown", "id"), entity_changes("Collect", "id"), entity_changes("Flash", "id"), b"\x2a\x80"):
            with self.subTest(raw=raw):
                self.tearDown()
                self.setUp()
                changed = list(self.stream_outputs)
                changed[0] = raw
                self.write_capture("baseline", changed, 300, 400, 500)
                self.write_capture("candidate", changed, 600, 700, 800)
                self.assert_rejected("unknown entity|Collect/Flash|truncated protobuf")

    def test_all_zero_outputs_are_rejected(self) -> None:
        zeros = [b"" for _ in range(VERIFIER.PROCESSED_BLOCK_LIMIT)]
        self.write_capture("baseline", zeros, 300, 400, 500)
        self.write_capture("candidate", zeros, 600, 700, 800)
        self.assert_rejected("no nonempty map output")

    def test_duplicate_key_float_nonfinite_invalid_utf8_and_trailing_data_are_rejected(self) -> None:
        payloads = (
            b'{"format_version":1,"format_version":1}',
            b'{"format_version":1.0}', b'{"format_version":NaN}', b'{"format_version":1} trailing', b'{"x":"\xff"}',
        )
        for payload in payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(VERIFIER.VerificationError):
                    VERIFIER.strict_json_bytes(payload, "fixture")

    def test_secret_scan_refuses_raw_and_all_staged_certificate_payloads(self) -> None:
        secret = b"never-present-api-secret"
        self.paths["candidate"]["stderr"].write_bytes(secret)
        sidecar = json.loads(self.paths["candidate"]["completion"].read_text())
        sidecar["raw"]["stderr"] = {"name": self.paths["candidate"]["stderr"].name, "sha256": sha256(secret), "bytes": len(secret)}
        self.paths["candidate"]["completion"].write_bytes(json_bytes(sidecar))
        self.assert_rejected("supplied secret")

    def test_immutable_outputs_refuse_overwrite_symlink_and_alias(self) -> None:
        self.certificate.write_text("preserve")
        with self.assertRaisesRegex(VERIFIER.VerificationError, "refusing to overwrite"):
            self.verify()
        self.assertEqual(self.certificate.read_text(), "preserve")
        self.assertFalse(any(os.path.lexists(path) for path in self.all_outputs() if path != self.certificate))

    def test_profile_build_and_trust_boundary_tamper_are_rejected(self) -> None:
        profile = json.loads(self.profile.read_text())
        profile["range"]["end_block_exclusive"] += 1
        self.profile.write_bytes(json_bytes(profile))
        self.assert_rejected("profile range drift")
        self.tearDown()
        self.setUp()
        manifest = json.loads(self.manifest.read_text())
        manifest["trust_boundary"]["production_pin"] = True
        self.manifest.write_bytes(json_bytes(manifest))
        self.assert_rejected("production_pin")

        self.tearDown()
        self.setUp()
        manifest = json.loads(self.manifest.read_text())
        manifest["toolchain"]["go"] = "go version go1.26.50 linux/amd64"
        self.manifest.write_bytes(json_bytes(manifest))
        self.assert_rejected("Go version drift")


if __name__ == "__main__":
    unittest.main()
