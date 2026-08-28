#!/usr/bin/env python3
"""Capture one complete protocol-v3 parity stream and seal local provenance."""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import ipaddress
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import NoReturn


KIND = "uniswap-v3-mainnet-parity-invocation-completion"
BLOCK_KIND = "uniswap-v3-mainnet-parity-block"
STREAM_COMPLETION_KIND = "uniswap-v3-mainnet-parity-stream-completion"
START_BLOCK = 12_369_621
END_BLOCK_EXCLUSIVE = 12_370_674
PROCESSED_BLOCK_LIMIT = END_BLOCK_EXCLUSIVE - START_BLOCK
MODULE = "graph_out"
OUTPUT_TYPE = "sf.substreams.entity.v1.EntityChanges"
CLIENT_VERSION = (
    "uniswap-v3-mainnet-parity-client-v1 "
    "(protocol v3; upstream v1.20.3 cc555bd4e325b65ac3f95dfde4655076f88d4a0a)"
)
UPSTREAM_VERSION = "v1.20.3"
UPSTREAM_COMMIT = "cc555bd4e325b65ac3f95dfde4655076f88d4a0a"
UPSTREAM_TREE = "38ea588549e5e41698da00ee149278aa2d855c64"
HEX40_RE = re.compile(r"^[0-9a-f]{40}$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
ENDPOINT_RE = re.compile(r"^[A-Za-z0-9.-]+:[0-9]+$")
DNS_LABEL_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
TRUST_BOUNDARY = {
    "promotion_eligible": False,
    "authoritative_graph_reference": False,
    "physical_or_poi_parity": False,
    "production_pin": False,
    "approved_runtime_contract": None,
}


class CaptureError(RuntimeError):
    pass


def fail(message: str) -> NoReturn:
    raise CaptureError(message)


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def reject_float(value: str) -> NoReturn:
    fail(f"floating-point JSON value is forbidden: {value}")


def reject_constant(value: str) -> NoReturn:
    fail(f"non-finite JSON value is forbidden: {value}")


def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            fail(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def strict_json_line(raw: bytes, field: str) -> dict[str, object]:
    require(raw and b"\r" not in raw and b"\n" not in raw, f"{field} is not one LF-free record")
    try:
        text = raw.decode("utf-8", errors="strict")
        value = json.loads(
            text,
            object_pairs_hook=reject_duplicate_keys,
            parse_float=reject_float,
            parse_constant=reject_constant,
        )
    except UnicodeDecodeError as error:
        raise CaptureError(f"{field} is not valid UTF-8") from error
    except json.JSONDecodeError as error:
        raise CaptureError(f"{field} is not strict JSON: {error.msg}") from error
    require(isinstance(value, dict), f"{field} must be an object")
    canonical = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    require(raw == canonical, f"{field} is not the exact compact client serialization")
    return value


def exact_keys(value: object, keys: set[str], field: str) -> dict[str, object]:
    require(isinstance(value, dict), f"{field} must be an object")
    require(set(value) == keys, f"{field} keys differ from the capture contract")
    return value


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def regular_bytes(path: Path, field: str) -> bytes:
    require(path.is_file() and not path.is_symlink(), f"{field} is not a regular file: {path}")
    return path.read_bytes()


def publish_exclusive(source: Path, destination: Path) -> None:
    require(source.is_file() and not source.is_symlink(), f"staged output is not regular: {source}")
    require(destination.parent.is_dir(), f"output parent does not exist: {destination.parent}")
    require(not os.path.lexists(destination), f"refusing to overwrite output: {destination}")
    try:
        os.link(source, destination, follow_symlinks=False)
    except FileExistsError as error:
        raise CaptureError(f"refusing to overwrite output: {destination}") from error
    os.chmod(destination, 0o600, follow_symlinks=False)
    directory = os.open(destination.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def client_identity(binary: Path) -> dict[str, object]:
    binary = binary.resolve()
    raw = regular_bytes(binary, "parity capture client")
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in {"SUBSTREAMS_API_TOKEN", "SUBSTREAMS_API_KEY", "ETHEREUM_RPC_URL"}
    }
    try:
        result = subprocess.run(
            [str(binary), "--version"],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
        )
    except OSError as error:
        raise CaptureError("could not execute capture-client identity check") from error
    require(result.returncode == 0 and not result.stderr, "capture-client identity check failed")
    try:
        version = result.stdout.decode("utf-8", errors="strict").strip()
    except UnicodeDecodeError as error:
        raise CaptureError("capture-client identity is not UTF-8") from error
    require(version == CLIENT_VERSION, "capture-client version identity drift")
    return {"version": version, "binary_sha256": sha256_bytes(raw), "binary_bytes": len(raw)}


def request_contract(package_identity: dict[str, object]) -> dict[str, object]:
    return {
        "protocol_version": 3,
        "network": "mainnet",
        "module": MODULE,
        "output_type": OUTPUT_TYPE,
        "start_block": START_BLOCK,
        "start_cursor": "",
        "end_block_exclusive": END_BLOCK_EXCLUSIVE,
        "processed_block_limit": PROCESSED_BLOCK_LIMIT,
        "final_blocks_only": True,
        "production_mode": False,
        "noop_mode": False,
        "partial_blocks": False,
        "max_retries": 0,
        "params": {},
        "debug_initial_store_snapshot_for_modules": [],
        "dev_output_modules": [MODULE],
        "package": package_identity,
    }


def compact_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")


def expected_argv(
    role: str,
    endpoint: str,
    session_id: str,
    invocation_id: str,
    source_revision: str,
    started_at_unix_nanos: int,
) -> list[str]:
    return [
        "uniswap-v3-mainnet-parity-client",
        "--endpoint",
        endpoint,
        "--package",
        f"<package:{role}>",
        "--session-id",
        session_id,
        "--invocation-id",
        invocation_id,
        "--role",
        role,
        "--source-revision",
        source_revision,
        "--started-at-unix-nanos",
        str(started_at_unix_nanos),
    ]


def validate_stdout(
    raw: bytes,
    *,
    role: str,
    endpoint: str,
    session_id: str,
    invocation_id: str,
    source_revision: str,
    started_at_unix_nanos: int,
    package_identity: dict[str, object],
    capture_client_identity: dict[str, object],
    auth_kind: str,
) -> dict[str, object]:
    require(raw.endswith(b"\n") and b"\r" not in raw, "capture stdout must end in one LF and contain no CR")
    lines = raw[:-1].split(b"\n")
    require(len(lines) == PROCESSED_BLOCK_LIMIT + 1, "capture stdout does not contain 1,053 blocks plus completion")
    block_lines = lines[:-1]
    block_hashes: dict[str, str] = {}
    map_hashes: list[str] = []
    cursor_hashes: list[str] = []
    for index, line in enumerate(block_lines):
        field = f"capture stdout block line {index + 1}"
        value = exact_keys(
            strict_json_line(line, field),
            {
                "format_version",
                "kind",
                "block",
                "block_id",
                "timestamp_seconds",
                "timestamp_nanos",
                "module",
                "output_type",
                "map_output_base64",
                "map_output_bytes",
                "map_output_sha256",
                "cursor_sha256",
            },
            field,
        )
        expected_block = START_BLOCK + index
        require(type(value["format_version"]) is int and value["format_version"] == 1, f"{field} version drift")
        require(value["kind"] == BLOCK_KIND, f"{field} kind drift")
        require(type(value["block"]) is int and value["block"] == expected_block, f"{field} sequence drift")
        block_id = value["block_id"]
        require(isinstance(block_id, str) and HEX64_RE.fullmatch(block_id) is not None, f"{field} hash malformed")
        timestamp_seconds = value["timestamp_seconds"]
        timestamp_nanos = value["timestamp_nanos"]
        require(
            type(timestamp_seconds) is int and -62_135_596_800 <= timestamp_seconds <= 253_402_300_799,
            f"{field} timestamp seconds malformed",
        )
        require(type(timestamp_nanos) is int and 0 <= timestamp_nanos < 1_000_000_000, f"{field} timestamp nanos malformed")
        timestamp = (timestamp_seconds, timestamp_nanos)
        if index:
            require(timestamp > last_timestamp, f"{field} timestamp is not strictly increasing")
        last_timestamp = timestamp
        require(value["module"] == MODULE and value["output_type"] == OUTPUT_TYPE, f"{field} output contract drift")
        encoded = value["map_output_base64"]
        require(isinstance(encoded, str) and encoded.isascii(), f"{field} base64 is malformed")
        try:
            decoded = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as error:
            raise CaptureError(f"{field} base64 is malformed") from error
        require(base64.b64encode(decoded).decode("ascii") == encoded, f"{field} base64 is noncanonical")
        require(type(value["map_output_bytes"]) is int and value["map_output_bytes"] == len(decoded), f"{field} byte length drift")
        map_digest = value["map_output_sha256"]
        cursor_digest = value["cursor_sha256"]
        require(isinstance(map_digest, str) and HEX64_RE.fullmatch(map_digest) is not None, f"{field} map digest malformed")
        require(map_digest == sha256_bytes(decoded), f"{field} map digest drift")
        require(isinstance(cursor_digest, str) and HEX64_RE.fullmatch(cursor_digest) is not None, f"{field} cursor digest malformed")
        block_hashes[str(expected_block)] = "0x" + block_id
        map_hashes.append(map_digest)
        cursor_hashes.append(cursor_digest)

    completion_field = "capture stdout completion line"
    completion = exact_keys(
        strict_json_line(lines[-1], completion_field),
        {
            "format_version",
            "kind",
            "client_version",
            "protocol_version",
            "upstream_version",
            "upstream_commit",
            "upstream_tree",
            "session_id",
            "invocation_id",
            "role",
            "source_revision",
            "endpoint",
            "auth_kind",
            "package",
            "capture_client",
            "request",
            "request_sha256",
            "sanitized_argv",
            "started_at_unix_nanos",
            "completed_at_unix_nanos",
            "first_block",
            "last_block",
            "block_count",
            "records_sha256",
            "completed",
        },
        completion_field,
    )
    request = request_contract(package_identity)
    expected_without_completion_clock = {
        "format_version": 1,
        "kind": STREAM_COMPLETION_KIND,
        "client_version": "uniswap-v3-mainnet-parity-client-v1",
        "protocol_version": 3,
        "upstream_version": UPSTREAM_VERSION,
        "upstream_commit": UPSTREAM_COMMIT,
        "upstream_tree": UPSTREAM_TREE,
        "session_id": session_id,
        "invocation_id": invocation_id,
        "role": role,
        "source_revision": source_revision,
        "endpoint": endpoint,
        "auth_kind": auth_kind,
        "package": package_identity,
        "capture_client": capture_client_identity,
        "request": request,
        "request_sha256": sha256_bytes(compact_json(request)),
        "sanitized_argv": expected_argv(
            role,
            endpoint,
            session_id,
            invocation_id,
            source_revision,
            started_at_unix_nanos,
        ),
        "started_at_unix_nanos": started_at_unix_nanos,
        "first_block": START_BLOCK,
        "last_block": END_BLOCK_EXCLUSIVE - 1,
        "block_count": PROCESSED_BLOCK_LIMIT,
        "records_sha256": sha256_bytes(b"".join(line + b"\n" for line in block_lines)),
        "completed": True,
    }
    completed_at = completion["completed_at_unix_nanos"]
    require(
        type(completed_at) is int and started_at_unix_nanos <= completed_at <= time.time_ns() + 60_000_000_000,
        "capture stdout completion clock is outside the invocation bounds",
    )
    comparable = dict(completion)
    del comparable["completed_at_unix_nanos"]
    require(comparable == expected_without_completion_clock, "capture stdout completion contract drift")
    return {
        "first_block": START_BLOCK,
        "last_block": END_BLOCK_EXCLUSIVE - 1,
        "block_count": PROCESSED_BLOCK_LIMIT,
        "started_at_unix_nanos": started_at_unix_nanos,
        "completed_at_unix_nanos": completed_at,
        "first_timestamp": {
            "seconds": strict_json_line(block_lines[0], "first block timestamp")["timestamp_seconds"],
            "nanos": strict_json_line(block_lines[0], "first block timestamp")["timestamp_nanos"],
        },
        "last_timestamp": {"seconds": last_timestamp[0], "nanos": last_timestamp[1]},
        "records_sha256": completion["records_sha256"],
        "block_hashes_sha256": sha256_bytes(
            json.dumps(block_hashes, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ),
        "map_output_hashes_sha256": sha256_bytes(json.dumps(map_hashes, separators=(",", ":")).encode("utf-8")),
        "cursor_hashes_sha256": sha256_bytes(json.dumps(cursor_hashes, separators=(",", ":")).encode("utf-8")),
    }


def capture(args: argparse.Namespace) -> dict[str, object]:
    require(HEX64_RE.fullmatch(args.session_id) is not None, "session ID must be 64 lowercase hex characters")
    require(HEX40_RE.fullmatch(args.source_revision) is not None, "source revision must be 40 lowercase hex characters")
    require(ENDPOINT_RE.fullmatch(args.endpoint) is not None, "endpoint must be a credential-free host:port")
    endpoint_host, endpoint_port = args.endpoint.rsplit(":", 1)
    require(bool(endpoint_host) and 1 <= int(endpoint_port) <= 65_535, "endpoint port is invalid")
    try:
        ipaddress.ip_address(endpoint_host)
    except ValueError:
        pass
    else:
        fail("endpoint must be a DNS target, not an IP literal")
    require(
        len(endpoint_host) <= 253 and all(DNS_LABEL_RE.fullmatch(label) for label in endpoint_host.split(".")),
        "endpoint DNS target is malformed",
    )
    require(args.role in {"baseline", "candidate"}, "role is invalid")
    api_token = os.environ.get("SUBSTREAMS_API_TOKEN", "")
    api_key = os.environ.get("SUBSTREAMS_API_KEY", "")
    require(bool(api_token) != bool(api_key), "set exactly one Substreams credential")

    package = args.package.resolve()
    package_raw = regular_bytes(package, "Substreams package")
    package_identity = {"sha256": sha256_bytes(package_raw), "bytes": len(package_raw)}
    binary = args.capture_client.resolve()
    identity = client_identity(binary)
    client_artifact_identity = {
        "sha256": identity["binary_sha256"],
        "bytes": identity["binary_bytes"],
    }
    outputs = [args.stdout.resolve(strict=False), args.stderr.resolve(strict=False), args.completion.resolve(strict=False)]
    require(len(outputs) == len(set(outputs)), "stdout, stderr, and completion paths must be distinct")
    for output in outputs:
        require(output.parent.is_dir(), f"output parent does not exist: {output.parent}")
        require(not os.path.lexists(output), f"refusing to overwrite output: {output}")

    invocation_id = secrets.token_hex(32)
    started_at_unix_nanos = time.time_ns()
    command = [
        str(binary),
        "--endpoint",
        args.endpoint,
        "--package",
        str(package),
        "--session-id",
        args.session_id,
        "--invocation-id",
        invocation_id,
        "--role",
        args.role,
        "--source-revision",
        args.source_revision,
        "--started-at-unix-nanos",
        str(started_at_unix_nanos),
    ]
    published: list[Path] = []
    staged: list[Path] = []
    try:
        stdout_handle = tempfile.NamedTemporaryFile(prefix=".parity-stdout.", dir=outputs[0].parent, delete=False)
        stderr_handle = tempfile.NamedTemporaryFile(prefix=".parity-stderr.", dir=outputs[1].parent, delete=False)
        staged.extend((Path(stdout_handle.name), Path(stderr_handle.name)))
        os.chmod(stdout_handle.name, 0o600)
        os.chmod(stderr_handle.name, 0o600)
        environment = {
            key: value
            for key, value in os.environ.items()
            if key not in {"ETHEREUM_RPC_URL", "ETHEREUM_RPC_LABEL", "SUBSTREAMS_API_TOKEN", "SUBSTREAMS_API_KEY"}
        }
        if api_key:
            environment["SUBSTREAMS_API_KEY"] = api_key
        else:
            environment["SUBSTREAMS_API_TOKEN"] = api_token
        with stdout_handle, stderr_handle:
            try:
                result = subprocess.run(
                    command,
                    check=False,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_handle,
                    stderr=stderr_handle,
                    env=environment,
                )
            except OSError as error:
                raise CaptureError("parity client could not be executed") from error
            stdout_handle.flush()
            stderr_handle.flush()
            os.fsync(stdout_handle.fileno())
            os.fsync(stderr_handle.fileno())
        require(result.returncode == 0, "parity client failed; raw partial outputs were removed")

        stdout_raw = regular_bytes(staged[0], "captured stdout")
        stderr_raw = regular_bytes(staged[1], "captured stderr")
        secrets_raw = [value.encode("utf-8") for value in (api_key, api_token) if value]
        require(stderr_raw == b"", "successful parity client wrote to stderr")
        auth_kind = "x-api-key" if api_key else "bearer-token"
        stream_summary = validate_stdout(
            stdout_raw,
            role=args.role,
            endpoint=args.endpoint,
            session_id=args.session_id,
            invocation_id=invocation_id,
            source_revision=args.source_revision,
            started_at_unix_nanos=started_at_unix_nanos,
            package_identity=package_identity,
            capture_client_identity=client_artifact_identity,
            auth_kind=auth_kind,
        )
        wrapper_completed_at_unix_nanos = time.time_ns()
        require(
            stream_summary["completed_at_unix_nanos"] <= wrapper_completed_at_unix_nanos,
            "client completion clock exceeds wrapper completion clock",
        )
        request = request_contract(package_identity)
        completion = {
            "format_version": 1,
            "kind": KIND,
            "session_id": args.session_id,
            "invocation_id": invocation_id,
            "role": args.role,
            "source_revision": args.source_revision,
            "package": {
                "artifact": "baseline" if args.role == "baseline" else "configured_mainnet",
                **package_identity,
            },
            "endpoint": args.endpoint,
            "auth_kind": auth_kind,
            "capture_client": identity,
            "request": request,
            "request_sha256": sha256_bytes(compact_json(request)),
            "sanitized_argv": expected_argv(
                args.role,
                args.endpoint,
                args.session_id,
                invocation_id,
                args.source_revision,
                started_at_unix_nanos,
            ),
            "clock": {
                "wrapper_started_at_unix_nanos": started_at_unix_nanos,
                "client_completed_at_unix_nanos": stream_summary["completed_at_unix_nanos"],
                "wrapper_completed_at_unix_nanos": wrapper_completed_at_unix_nanos,
                "ordered": True,
            },
            "stream": stream_summary,
            "raw": {
                "stdout": {"name": outputs[0].name, "sha256": sha256_bytes(stdout_raw), "bytes": len(stdout_raw)},
                "stderr": {"name": outputs[1].name, "sha256": sha256_bytes(stderr_raw), "bytes": len(stderr_raw)},
            },
            "exit_code": 0,
            "completed": True,
            "trust_boundary": dict(TRUST_BOUNDARY),
        }
        payload = (json.dumps(completion, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        completion_handle = tempfile.NamedTemporaryFile(
            prefix=".parity-completion.", dir=outputs[2].parent, delete=False
        )
        staged.append(Path(completion_handle.name))
        os.chmod(completion_handle.name, 0o600)
        with completion_handle:
            completion_handle.write(payload)
            completion_handle.flush()
            os.fsync(completion_handle.fileno())
        for field, staged_payload in (
            ("capture stdout", stdout_raw),
            ("capture stderr", stderr_raw),
            ("capture completion", payload),
        ):
            for secret in secrets_raw:
                require(secret not in staged_payload, f"{field} contains a supplied credential")
        for source, destination in zip(staged, outputs, strict=True):
            publish_exclusive(source, destination)
            published.append(destination)
        return completion
    except BaseException:
        for output in reversed(published):
            try:
                output.unlink()
            except FileNotFoundError:
                pass
        raise
    finally:
        for temporary in staged:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


def parse_args(arguments: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--role", required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--capture-client", type=Path, required=True)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--stdout", type=Path, required=True)
    parser.add_argument("--stderr", type=Path, required=True)
    parser.add_argument("--completion", type=Path, required=True)
    return parser.parse_args(arguments)


def main(arguments: list[str] | None = None) -> int:
    try:
        completion = capture(parse_args(arguments))
    except (CaptureError, OSError, ValueError) as error:
        print(f"Uniswap V3 parity capture failed: {error}", file=sys.stderr)
        return 1
    print(f"captured {completion['role']} invocation as {completion['invocation_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
