#!/usr/bin/env python3
"""Fail-closed verification for the Uniswap V4 q8 metadata capsule."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import sys
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any


CONTRACT = "uniswap-v4-engine-v0.5.0-q8-declared-reference/v1"
CAPSULE_DIRECTORY = Path("docs/provenance/uniswap-v4-engine-v0.5.0/q8")
CLOSURE_PATH = CAPSULE_DIRECTORY / "closure.json"
PARENT_CLOSURE_PATH = CAPSULE_DIRECTORY.parent / "closure.json"
CURRENT_COMPATIBILITY_PATH = CAPSULE_DIRECTORY.parent / "compatibility.json"
ARCHIVE_NAME = "release-complete-q8-200k-20260815-r1-evidence-20260815.tar.gz"
DEPLOYMENT = "Qmbsc6XQWbiv4DfLVfaNciScqYLyDWUYjWzrFBbzzmRsMB"

EXPECTED_SOURCE = {
    "repository": "pinax-network/substreams-graph-node-backfill",
    "commit": "395c9fb0d5377cba058d506043b7891c2f2016a8",
    "tree": "c3568b472faf13e07618e14dc9551f9400551fa3",
}

EXPECTED_FILE_LOCKS: dict[str, tuple[str, str, int, str, str]] = {
    "LICENSE.source": (
        "LICENSE", "source-license", 11357,
        "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4",
        "261eeb9e9f8b2b4b0d119366dda99c6fd7d35c64",
    ),
    "uniswap-v4-base-q8-producer-compatibility.json": (
        "fixtures/uniswap-v4-base-q8-producer-compatibility.json",
        "historical-producer-compatibility", 7252,
        "86b7c38e5d98700b9841aadefaad8ada8543e1d49e5e95d3db881f842b980ce6",
        "e0dee4eaeaec71219491c445374be57e61e32715",
    ),
    "uniswap-v4-base-v0.5.0-q8-READY.json": (
        "fixtures/uniswap-v4-base-v0.5.0-q8-READY.json",
        "certified-segment-ready-seal", 215,
        "073081a599d164c929326ea6eb46599884a927bd2fb21ed944bc75d2171f7de2",
        "b5ee568af9989a47f7d311369dd15f61cb090dc9",
    ),
    "uniswap-v4-base-v0.5.0-q8-manifest.json": (
        "fixtures/uniswap-v4-base-v0.5.0-q8-manifest.json",
        "certified-segment-copy-manifest", 12877,
        "44718ce74c0a60cdc9f5c452d1ce7b804257c887ec1ce8f34e930cfdb7c4d91a",
        "8401eb8b7e85b7917fdd653ae5d4b8e6cdae0c87",
    ),
    "uniswap-v4-base-v0.5.0-q8-reference.json": (
        "fixtures/uniswap-v4-base-v0.5.0-q8-reference.json",
        "declared-historical-reference-metadata", 12671,
        "9a9d2ac3423f19199d527993a97d4e125160f4d07c57cbfde44eb67f7006fc82",
        "f8167150383a610f6bbe41411a24a70fbcf6263b",
    ),
    "uniswap-v4-base-v0.5.0-q8-restore-READY.json": (
        "fixtures/uniswap-v4-base-v0.5.0-q8-restore-READY.json",
        "restore-segment-ready-seal", 215,
        "1a8bd8a749aa0c4a74059dcfebf2dcf9cfabfb234ac01729d90dc98b8a2ea233",
        "9a0a2700eb44f68c9c715207458fc4133c8e06c3",
    ),
    "uniswap-v4-base-v0.5.0-q8-restore-manifest.json": (
        "fixtures/uniswap-v4-base-v0.5.0-q8-restore-manifest.json",
        "restore-segment-copy-manifest", 12876,
        "9d398169ac19416ace56d429e186fbabae71f924ce538ea7fa9173556c5abdd2",
        "958525256fb5e23dc85c2944ba20efd9de210225",
    ),
    "uniswap-v4-base-v4-reference-pod-topology.json": (
        "fixtures/uniswap-v4-base-v4-reference-pod-topology.json",
        "declared-clean-run-pod-topology", 9142,
        "3758fac03502479027a76925cd52b872b26f7b8c82a1aae329fbcbb1630d9aec",
        "4a19c81ddd2911e6759eb11e730ca99f751b6b4b",
    ),
    "uniswap-v4-base-v4-reference-source-observations.json": (
        "fixtures/uniswap-v4-base-v4-reference-source-observations.json",
        "declared-source-observation-contract", 23284,
        "7e7d5847ce33ae7e8469825cf2a3a7ff0a58a213e5cd1b68964eb0d0792fced9",
        "b2a80ed376fdd51b3e03c9fc69a73cdf6e54f2ae",
    ),
}

EXPECTED_ARCHIVE = {
    "local_path": ARCHIVE_NAME,
    "declared_name": ARCHIVE_NAME,
    "status": "locally-recovered-compact-metadata-archive",
    "acceptance_role": "none",
    "bytes": 9047,
    "sha256": "3072f55bac5f0a1bcdff799642cf0b4deeb414381fb19e6a9d18322627ff34d1",
    "file_members": 11,
    "checksum_bound_members": 10,
    "recovery_evidence": (
        "https://github.com/pinax-network/substreams-graph-node-backfill/"
        "issues/32#issuecomment-5303965641"
    ),
    "source_reference_availability_is_stale": True,
}

EXPECTED_ARCHIVE_MEMBERS = {
    "compute-events.jsonl": (8949, "bc99a6129e4d5fef6b7fa26f4a0d3ca4fac81defc260da5b84c760f1e8baa586"),
    "compute-evidence.json": (1021, "8ed3fc467f8c4efb951b239ba75a27991f5bc4b89819f36fbf86b27cd65a4428"),
    "compute-output.jsonl": (1038, "aa9f5745718b553c831528c62af5b9425293ac281d26dd3ca6f86e1d1d79e704"),
    "compute-parity.json": (2379, "0f54661fab6f003b67396d87eef2060f2f96261fdcc9cc27c2f243c461859f11"),
    "compute-performance-comparison.json": (1001, "f7f922092fb883df48b92306cab25f8d7becfbce548270b4f3153e0af004d2f8"),
    "compute-progress.jsonl": (460, "35418cc5467392e7209a38e2c86f61b7e2eb0abf5bf8f6ce226cc3c2c59fd816"),
    "run/spools/segment-33374155-33474154.ready/READY.json": (215, "073081a599d164c929326ea6eb46599884a927bd2fb21ed944bc75d2171f7de2"),
    "run/spools/segment-33374155-33474154.ready/manifest.json": (12877, "44718ce74c0a60cdc9f5c452d1ce7b804257c887ec1ce8f34e930cfdb7c4d91a"),
    "run/spools/segment-33474155-33574154.ready/READY.json": (215, "1a8bd8a749aa0c4a74059dcfebf2dcf9cfabfb234ac01729d90dc98b8a2ea233"),
    "run/spools/segment-33474155-33574154.ready/manifest.json": (12876, "9d398169ac19416ace56d429e186fbabae71f924ce538ea7fa9173556c5abdd2"),
    "SHA256SUMS": (1045, "cee449f4f012f527d0342556974245e7bef69a092f7e2343e9c653658e44eb2f"),
}

EXPECTED_ARCHIVE_DIRECTORIES = {
    ".", "run", "run/spools",
    "run/spools/segment-33374155-33474154.ready",
    "run/spools/segment-33474155-33574154.ready",
}

EXPECTED_COPY_TABLES = (
    "arrakis_hook", "bundle", "modify_liquidity", "poi2$", "pool",
    "pool_day_data", "pool_hour_data", "pool_manager", "position",
    "subscribe", "swap", "tick", "token", "token_day_data",
    "token_hour_data", "transaction", "transfer", "uniswap_day_data",
    "unsubscribe",
)

EXPECTED_TOPOLOGY_ROLES = {
    "evidence_runtime": "publication-bound-by-runtime-contract-and-observed-image-id",
    "compute_load_runtime": "dbb88e451dbd44fd3e412f1d6814939cbc2a0b93c539837ebfb1f28d3dd1711e",
    "graph_node": "c14c6d8e2b2b1ed89f6a89babf48d807b18a43e372fda7fb495d3a9050b65b8b",
    "busybox": "b7f3d86d6e84fc17718c48bcde1450807faa2d56704205c697b4bd5df7b9e29f",
    "python_exporter": "f1a962d8ffa50b2006b72b4713a09a89e57def2d28ac28a36900bc070a00db61",
}

EXPECTED_SEGMENTS = {
    "certified_segment": {
        "start_block": 33374155,
        "end_block": 33474154,
        "target_hash": "53ec0561c1a6d3b867e7a188678cd50256e2baca0ad72ea5ed5b7aefe86316e0",
        "input_frames": 99248,
        "input_payload_bytes": 9061879073,
        "manifest_sha256": "44718ce74c0a60cdc9f5c452d1ce7b804257c887ec1ce8f34e930cfdb7c4d91a",
        "ready_sha256": "073081a599d164c929326ea6eb46599884a927bd2fb21ed944bc75d2171f7de2",
        "copy_file_set_sha256": "f7ac5e9b551f835d9c75baf3bc99e55ce5259d91bd02b9231d52201411ec1ca6",
        "copy_payload_bytes": 21065457930,
        "checkpoint_bytes": 13589557635,
        "checkpoint_sha256": "329a3be191125b90f5e56fa9e5f9da79484c15edcc9d6786405cd3033f238626",
    },
    "restore_segment": {
        "start_block": 33474155,
        "end_block": 33574154,
        "target_hash": "fe88afd7188b33c593fa4eb81409106a220a9d83ca874af714b21b08a30c9116",
        "input_frames": 97580,
        "input_payload_bytes": 6948696921,
        "manifest_sha256": "9d398169ac19416ace56d429e186fbabae71f924ce538ea7fa9173556c5abdd2",
        "ready_sha256": "1a8bd8a749aa0c4a74059dcfebf2dcf9cfabfb234ac01729d90dc98b8a2ea233",
        "copy_file_set_sha256": "81ad8bb4da493ea463c8c3fb632f364f6069d7e08896ad6268ffadfd94db4e43",
        "copy_payload_bytes": 18165472516,
        "checkpoint_bytes": 15996029671,
        "checkpoint_sha256": "0232aa8f53e42d45e7cdc57c75f84ef7804f1ec6abec73b84aef472db2e9c9d6",
    },
}

EXPECTED_RETENTION = {
    "manifest_bytes": True,
    "ready_seal_bytes": True,
    "literal_copy_filenames_sizes_and_digests": True,
    "compute_metadata_archive": True,
    "source_observation_contract": True,
    "pod_topology_contract": True,
    "raw_frame_payload_bytes": False,
    "raw_frame_stream_digest": False,
    "copy_row_and_clamp_payload_bytes": False,
    "seed_checkpoint_bytes": False,
    "certified_checkpoint_bytes": False,
    "restore_checkpoint_bytes": False,
}

EXPECTED_FIELD_SEMANTICS = {
    "input_stream_exact": {
        "observed_value": True,
        "meaning": "input-shape-equality-only",
        "compared_fields": ["input_format", "input_frames", "input_payload_bytes"],
        "raw_byte_identity_proven": False,
        "future_requirement": "emit-and-verify-frame-stream-receipt-sha256",
    }
}

EXPECTED_SCOPE = {
    "issue": 26,
    "status": "declared-historical-reference-metadata",
    "supports_acceptance_criteria": [2],
    "fully_satisfied_acceptance_criteria": [],
    "acceptance_role": "none",
}

EXPECTED_GATES = {
    "criterion_2_complete": False,
    "raw_frame_stream_retained": False,
    "raw_frame_stream_digest_retained": False,
    "copy_payload_retained": False,
    "checkpoint_payloads_retained": False,
    "scratch_target_authorized": False,
    "independent_zero_writer_proven": False,
    "k3_runtime_contract_approved": False,
    "workflow_submission_authorized": False,
    "workflow_submitted": False,
    "database_write_authorized": False,
    "database_mutation_performed": False,
    "backfill_ready": False,
    "production_ready": False,
    "promotion_eligible": False,
}

EXPECTED_NON_CLAIMS = [
    "The recovered compact archive is metadata-only and has acceptance role none.",
    (
        "Historical input_stream_exact means input format, frame count, and "
        "payload byte-count equality; it does not prove raw frame-stream byte identity."
    ),
    (
        "No raw frame payload, COPY row or clamp payload, seed checkpoint, or "
        "output checkpoint bytes are retained here."
    ),
    "The historical archive cannot replace a new authorized two-phase replay.",
    (
        "No scratch target, Kubernetes submission, workflow, database write, "
        "backfill, production, or promotion authority is represented."
    ),
]

HEX_64 = re.compile(r"^[0-9a-f]{64}$")
FORBIDDEN_REFERENCE_CLAIM_KEYS = {
    "criterion_2_complete",
    "reproduction_complete",
    "raw_frame_stream_retained",
    "raw_frame_stream_digest_retained",
    "copy_payload_retained",
    "checkpoint_payloads_retained",
    "scratch_target_authorized",
    "independent_zero_writer_proven",
    "k3_runtime_contract_approved",
    "workflow_submission_authorized",
    "workflow_submitted",
    "database_write_authorized",
    "database_mutation_performed",
    "backfill_ready",
    "production_ready",
    "promotion_eligible",
    "readiness",
}


class VerificationError(ValueError):
    """Raised when retained evidence or its claim boundary drifts."""


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise VerificationError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def load_json_bytes(payload: bytes, label: str) -> Any:
    try:
        return json.loads(payload.decode("utf-8"), object_pairs_hook=reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise VerificationError(f"invalid JSON: {label}: {error}") from error


def load_json(path: Path) -> Any:
    try:
        return load_json_bytes(path.read_bytes(), str(path))
    except OSError as error:
        raise VerificationError(f"cannot read {path}: {error}") from error


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def git_blob_sha1(payload: bytes) -> str:
    header = f"blob {len(payload)}\0".encode("ascii")
    return hashlib.sha1(header + payload).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def strict_equal(actual: Any, expected: Any) -> bool:
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return (
            actual.keys() == expected.keys()
            and all(strict_equal(actual[key], value) for key, value in expected.items())
        )
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(
            strict_equal(observed, wanted)
            for observed, wanted in zip(actual, expected, strict=True)
        )
    return bool(actual == expected)


def require_strict(actual: Any, expected: Any, message: str) -> None:
    require(strict_equal(actual, expected), message)


def reject_forbidden_reference_claims(value: Any, path: str = "reference") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            require(
                key not in FORBIDDEN_REFERENCE_CLAIM_KEYS,
                f"forbidden operational claim key: {path}.{key}",
            )
            reject_forbidden_reference_claims(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_forbidden_reference_claims(child, f"{path}[{index}]")


def regular_bytes(path: Path, label: str) -> bytes:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise VerificationError(f"missing {label}: {path}") from error
    require(not stat.S_ISLNK(metadata.st_mode), f"{label} must not be a symlink")
    require(stat.S_ISREG(metadata.st_mode), f"{label} must be a regular file")
    return path.read_bytes()


def verify_lock(path: Path, byte_count: int, digest: str, label: str) -> bytes:
    payload = regular_bytes(path, label)
    require(len(payload) == byte_count, f"{label} byte length drift")
    require(sha256(payload) == digest, f"{label} SHA-256 drift")
    return payload


def expected_closure_files() -> list[dict[str, Any]]:
    records = []
    for name, (source_path, role, byte_count, digest, blob) in EXPECTED_FILE_LOCKS.items():
        records.append({
            "local_path": name,
            "source_path": source_path,
            "role": role,
            "bytes": byte_count,
            "sha256": digest,
            "git_blob": blob,
        })
    return records


def verify_closure(closure: dict[str, Any]) -> None:
    require(set(closure) == {
        "format_version",
        "contract",
        "source",
        "files",
        "recovered_archive",
        "selected_reference",
        "retention",
        "historical_field_semantics",
        "scope",
        "gates",
        "non_claims",
    }, "closure top-level inventory drift")
    require(closure.get("format_version") == 1, "closure format drift")
    require(closure.get("contract") == CONTRACT, "closure contract drift")
    source = closure.get("source")
    require(isinstance(source, dict), "source contract missing")
    require(set(source) == {*EXPECTED_SOURCE, "license"}, "source contract inventory drift")
    require({key: source.get(key) for key in EXPECTED_SOURCE} == EXPECTED_SOURCE, "source identity drift")
    license_file = expected_closure_files()[0]
    license_record = {
        "spdx": "Apache-2.0",
        "local_path": license_file["local_path"],
        "source_path": license_file["source_path"],
        "bytes": license_file["bytes"],
        "sha256": license_file["sha256"],
        "git_blob": license_file["git_blob"],
    }
    require_strict(source.get("license"), license_record, "source license drift")
    require_strict(closure.get("files"), expected_closure_files(), "source file inventory drift")
    require_strict(closure.get("recovered_archive"), EXPECTED_ARCHIVE, "archive closure drift")
    require_strict(closure.get("retention"), EXPECTED_RETENTION, "retention boundary drift")
    require_strict(
        closure.get("historical_field_semantics"),
        EXPECTED_FIELD_SEMANTICS,
        "historical field semantics drift",
    )
    require_strict(closure.get("scope"), EXPECTED_SCOPE, "acceptance scope drift")
    require_strict(closure.get("gates"), EXPECTED_GATES, "operational gate drift")
    selected = closure.get("selected_reference")
    require(isinstance(selected, dict), "selected q8 reference missing")
    require(
        set(selected) == {"network", "deployment", "seed", *EXPECTED_SEGMENTS},
        "selected reference inventory drift",
    )
    require(selected.get("network") == "base", "selected network drift")
    require(selected.get("deployment") == DEPLOYMENT, "selected deployment drift")
    require_strict(selected.get("seed"), {
        "block": 33374154,
        "hash": "5e8c1de6fe2065fcf08b382b10342e01fd8585052ca39ee1c9f80f37904c72a6",
        "checkpoint_bytes": 11093835518,
        "checkpoint_sha256": "be434078b1b71c3e51a36e37c0473f6b4d7864777511d8119426234d398e397d",
    }, "seed closure drift")
    for key, expected in EXPECTED_SEGMENTS.items():
        segment = selected.get(key)
        require(isinstance(segment, dict), f"{key} closure missing")
        for field, value in expected.items():
            require(segment.get(field) == value, f"{key} closure {field} drift")
        require(
            set(segment)
            == {*expected, "blocks", "copy_tables", "seed_preserved_table"},
            f"{key} closure inventory drift",
        )
        require(segment.get("blocks") == 100000, f"{key} block-count drift")
        require(segment.get("copy_tables") == 19, f"{key} COPY table-count drift")
        require(segment.get("seed_preserved_table") == "data_sources$", f"{key} seed table drift")
    require_strict(closure.get("non_claims"), EXPECTED_NON_CLAIMS, "non-claim boundary drift")


def normalize_tar_name(name: str) -> str:
    normalized = name[2:] if name.startswith("./") else name
    return normalized or "."


def verify_archive(path: Path) -> dict[str, bytes]:
    verify_lock(path, EXPECTED_ARCHIVE["bytes"], EXPECTED_ARCHIVE["sha256"], "q8 compact archive")
    files: dict[str, bytes] = {}
    directories: set[str] = set()
    seen: set[str] = set()
    try:
        with tarfile.open(path, "r:gz") as archive:
            for member in archive.getmembers():
                name = normalize_tar_name(member.name)
                pure = PurePosixPath(name)
                require(not pure.is_absolute() and ".." not in pure.parts, f"unsafe archive member: {name}")
                require(name not in seen, f"duplicate archive member: {name}")
                seen.add(name)
                if member.isdir():
                    directories.add(name)
                    continue
                require(member.isfile(), f"non-regular archive member: {name}")
                handle = archive.extractfile(member)
                require(handle is not None, f"unreadable archive member: {name}")
                files[name] = handle.read()
    except (OSError, tarfile.TarError) as error:
        raise VerificationError(f"invalid q8 compact archive: {error}") from error
    require(directories == EXPECTED_ARCHIVE_DIRECTORIES, "archive directory inventory drift")
    require(set(files) == set(EXPECTED_ARCHIVE_MEMBERS), "archive file inventory drift")
    for name, (byte_count, digest) in EXPECTED_ARCHIVE_MEMBERS.items():
        require(len(files[name]) == byte_count, f"archive member byte drift: {name}")
        require(sha256(files[name]) == digest, f"archive member SHA-256 drift: {name}")
    observed_sums: dict[str, str] = {}
    for line in files["SHA256SUMS"].decode("utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  \./(.+)", line)
        require(match is not None, "invalid archive SHA256SUMS line")
        digest, name = match.groups()
        require(name not in observed_sums, f"duplicate SHA256SUMS member: {name}")
        observed_sums[name] = digest
    require(set(observed_sums) == set(files) - {"SHA256SUMS"}, "SHA256SUMS inventory drift")
    for name, digest in observed_sums.items():
        require(sha256(files[name]) == digest, f"SHA256SUMS mismatch: {name}")
    return files


def verify_manifest(
    manifest: dict[str, Any],
    ready: dict[str, Any],
    expected: dict[str, Any],
    expected_head_block: int,
    expected_head_hash: str,
    poi: dict[str, Any],
) -> None:
    require(manifest.get("format") == "pinax.graph-node.copy-spool", "manifest format drift")
    require(type(manifest.get("version")) is int and manifest["version"] == 1, "manifest version drift")
    require(manifest.get("deployment") == DEPLOYMENT, "manifest deployment drift")
    require(manifest.get("expected_head_block") == expected_head_block, "expected head drift")
    require(manifest.get("expected_head_hash") == expected_head_hash, "expected hash drift")
    require(manifest.get("target_head_block") == expected["end_block"], "target head drift")
    require(manifest.get("target_head_hash") == expected["target_hash"], "target hash drift")
    require(manifest.get("input_format") == "store-state-protobuf-framed", "input format drift")
    require(manifest.get("input_frames") == expected["input_frames"], "input frame-count drift")
    require(manifest.get("input_payload_bytes") == expected["input_payload_bytes"], "input byte-count drift")
    require("input_sha256" not in manifest and "frame_stream_sha256" not in manifest, "invented historical frame digest")
    checkpoint = manifest.get("checkpoint")
    require(checkpoint == {
        "file": "checkpoint.pending",
        "bytes": expected["checkpoint_bytes"],
        "sha256": expected["checkpoint_sha256"],
    }, "checkpoint identity drift")
    copy = manifest.get("copy")
    require(isinstance(copy, dict), "COPY contract missing")
    tables = copy.get("tables")
    require(isinstance(tables, list) and len(tables) == 19, "COPY table-count drift")
    require(tuple(table.get("postgres_table") for table in tables) == EXPECTED_COPY_TABLES, "ordered COPY inventory drift")
    require([table.get("ordinal") for table in tables] == list(range(19)), "COPY ordinal drift")
    row_records = clamp_records = copy_bytes = 0
    for table in tables:
        table_name = table["postgres_table"]
        for kind in ("rows", "clamps"):
            artifact = table.get(kind)
            require(isinstance(artifact, dict), f"{table_name} {kind} missing")
            require(artifact.get("file") == f"{table_name}.{kind}.csv", f"{table_name} {kind} filename drift")
            require(type(artifact.get("bytes")) is int and artifact["bytes"] >= 0, f"{table_name} {kind} bytes invalid")
            require(type(artifact.get("records")) is int and artifact["records"] >= 0, f"{table_name} {kind} records invalid")
            require(isinstance(artifact.get("sha256"), str) and HEX_64.fullmatch(artifact["sha256"]), f"{table_name} {kind} digest invalid")
            copy_bytes += artifact["bytes"]
        row_records += table["rows"]["records"]
        clamp_records += table["clamps"]["records"]
    require(row_records == copy.get("inserted_rows"), "inserted-row total drift")
    require(clamp_records == copy.get("clamped_rows"), "clamped-row total drift")
    require(row_records - clamp_records == copy.get("new_entities"), "new-entity total drift")
    require(copy_bytes == expected["copy_payload_bytes"], "COPY payload-byte total drift")
    require(copy.get("file_set_sha256") == expected["copy_file_set_sha256"], "COPY set drift")
    poi_table = next(table for table in tables if table["postgres_table"] == "poi2$")
    for kind in ("rows", "clamps"):
        require(
            {
                field: poi_table[kind][field]
                for field in ("records", "bytes", "sha256")
            }
            == poi[kind],
            f"PoI {kind} identity drift",
        )
    require(ready == {
        "version": 1,
        "manifest_file": "manifest.json",
        "manifest_sha256": expected["manifest_sha256"],
        "file_set_sha256": expected["copy_file_set_sha256"],
    }, "READY seal drift")


def jsonl(payload: bytes, label: str) -> list[Any]:
    values = []
    for number, line in enumerate(payload.decode("utf-8").splitlines(), 1):
        values.append(load_json_bytes(line.encode(), f"{label}:{number}") if line.startswith("{") else line)
    return values


def verify_archive_semantics(files: dict[str, bytes], payloads: dict[str, bytes]) -> None:
    pairs = (
        ("run/spools/segment-33374155-33474154.ready/manifest.json", "uniswap-v4-base-v0.5.0-q8-manifest.json"),
        ("run/spools/segment-33374155-33474154.ready/READY.json", "uniswap-v4-base-v0.5.0-q8-READY.json"),
        ("run/spools/segment-33474155-33574154.ready/manifest.json", "uniswap-v4-base-v0.5.0-q8-restore-manifest.json"),
        ("run/spools/segment-33474155-33574154.ready/READY.json", "uniswap-v4-base-v0.5.0-q8-restore-READY.json"),
    )
    for archive_name, local_name in pairs:
        require(files[archive_name] == payloads[local_name], f"archive/source fixture drift: {archive_name}")
    evidence = load_json_bytes(files["compute-evidence.json"], "compute evidence")
    require(evidence.get("status") == "compute-complete" and evidence.get("mode") == "compute-only", "compute evidence status drift")
    require(evidence.get("blocks") == 200000, "compute evidence block-count drift")
    require(evidence.get("postgres_writes") is False, "historical PostgreSQL-write claim drift")
    require(evidence.get("postgres_credentials_mounted") is False, "historical credential claim drift")
    parity = load_json_bytes(files["compute-parity.json"], "compute parity")
    require(parity.get("scope") == "compute-checkpoint-and-copy-hashes", "compute parity scope drift")
    require(parity.get("promotion_ready") is False, "historical promotion claim drift")
    require(parity.get("missing_gate") == "stopped-clone-sql-physical-poi-graphql-and-lifecycle", "missing-gate drift")
    segments = parity.get("segments")
    require(isinstance(segments, list) and len(segments) == 2, "archive segment inventory drift")
    for observed, key in zip(segments, ("certified_segment", "restore_segment"), strict=True):
        expected = EXPECTED_SEGMENTS[key]
        require(observed.get("target_head_block") == expected["end_block"], "archive target drift")
        require(observed.get("target_head_hash") == expected["target_hash"], "archive target hash drift")
        require(observed.get("copy_file_set_sha256") == expected["copy_file_set_sha256"], "archive COPY-set drift")
        require(observed.get("checkpoint") == {
            "bytes": expected["checkpoint_bytes"],
            "sha256": expected["checkpoint_sha256"],
        }, "archive checkpoint drift")
        require(observed.get("copy_table_count") == 19, "archive COPY table-count drift")
        require(observed.get("seed_preserved_table") == "data_sources$", "archive seed table drift")
        require(observed.get("input_stream_exact") is True, "historical input-shape flag drift")
    require(parity.get("gates", {}).get("input_streams_exact") is True, "historical input-shape gate drift")
    progress = jsonl(files["compute-progress.jsonl"], "progress")
    outputs = jsonl(files["compute-output.jsonl"], "output")
    require(len(progress) == len(outputs) == 2, "archive progress/output inventory drift")
    events = jsonl(files["compute-events.jsonl"], "events")
    require([value for value in events if isinstance(value, str)] == [
        "native protobuf stream complete: frames=99248 payload_bytes=9061879073 last_block=33474154",
        "native protobuf stream complete: frames=97580 payload_bytes=6948696921 last_block=33574154",
    ], "native stream-shape receipt drift")
    performance = load_json_bytes(files["compute-performance-comparison.json"], "performance")
    require(performance.get("status") == "comparison-not-faster", "performance status drift")
    require(performance.get("promotion_ready") is False, "performance promotion drift")


def verify_reference(root: Path, reference: dict[str, Any], payloads: dict[str, bytes]) -> None:
    require(set(reference) == {
        "format_version",
        "reference_id",
        "status",
        "network",
        "deployment",
        "scratch",
        "certification_execution",
        "contracts",
        "runtime",
        "execution",
        "seed",
        "certified_segment",
        "restore_segment",
        "lifecycle",
        "historical_archive_declaration",
    }, "source reference inventory drift")
    reject_forbidden_reference_claims(reference)
    require(reference.get("status") == "declared-historical-reference-metadata", "reference status drift")
    require(
        set(reference.get("seed", {}))
        == {"block", "hash", "checkpoint_bytes", "checkpoint_sha256", "manifest_sha256"},
        "source seed inventory drift",
    )
    for key in ("certified_segment", "restore_segment"):
        require(
            set(reference.get(key, {}))
            == {
                "start_block",
                "end_block",
                "blocks",
                "target_hash",
                "input_frames",
                "input_payload_bytes",
                "manifest_sha256",
                "ready_sha256",
                "copy_file_set_sha256",
                "checkpoint_bytes",
                "checkpoint_sha256",
                "inserted_rows",
                "clamped_rows",
                "new_entities",
                "copy_tables",
                "seed_preserved_table",
                "poi",
            },
            f"{key} source inventory drift",
        )
    require(
        set(reference.get("runtime", {}))
        == {
            "release",
            "release_commit",
            "release_tree",
            "producer_commit",
            "producer_tree",
            "platform",
            "image",
            "binary_sha256",
        },
        "runtime source inventory drift",
    )
    require(
        set(reference.get("contracts", {}))
        == {"producer", "current", "shared_semantics", "producer_runtime_is_historical"},
        "contracts source inventory drift",
    )
    require(
        set(reference.get("execution", {}))
        == {
            "poi_workers",
            "poi_batch_size",
            "protobuf_decode_ahead",
            "asynchronous_spool_writers",
            "asynchronous_spool_queue_buffers",
            "allocator",
            "parallel_workers",
        },
        "execution source inventory drift",
    )
    require(
        set(reference.get("certification_execution", {}))
        == {
            "source_observations",
            "file_backed_observations",
            "api_backed_observations",
            "raw_source_paths",
            "source_workflow_pods",
            "producer_pods",
            "nonproducer_pods",
            "collector_pods",
            "two_phase_total_pods",
            "workflow_generate_name_prefix",
            "experiment_id_max_length",
            "namespace",
            "source_service_account",
            "collector_service_account",
            "source_observation_contract",
            "pod_topology",
            "source_handoff",
            "workload_contract",
            "images",
            "trust",
            "kubernetes_source_provenance",
            "graphman",
        },
        "certification execution inventory drift",
    )
    require_strict(reference.get("scratch"), {
        "namespace": "subgraphs-backfill",
        "database": "graph_backfill",
        "schema": "sgd2",
        "forbidden_schemas": ["sgd1246", "sgd5303"],
        "starting_head": {
            "block": 33574154,
            "hash": EXPECTED_SEGMENTS["restore_segment"]["target_hash"],
        },
    }, "scratch safety boundary drift")
    declaration = reference.get("historical_archive_declaration")
    require_strict(declaration, {
        "availability": "unavailable-in-this-certification-path",
        "acceptance_role": "none",
        "declared_name": ARCHIVE_NAME,
        "declared_bytes": 9047,
        "declared_sha256": EXPECTED_ARCHIVE["sha256"],
        "note": "Historical metadata only; a new live two-phase replay is required to establish a certificate.",
    }, "source archive declaration drift")
    current_compatibility = regular_bytes(root / CURRENT_COMPATIBILITY_PATH, "current compatibility")
    require(reference.get("contracts", {}).get("current", {}).get("sha256") == sha256(current_compatibility), "current compatibility drift")
    require(reference.get("contracts", {}).get("producer", {}).get("sha256") == EXPECTED_FILE_LOCKS["uniswap-v4-base-q8-producer-compatibility.json"][3], "producer compatibility drift")
    require(reference.get("contracts", {}).get("producer_runtime_is_historical") is True, "historical producer boundary drift")
    parent = load_json(root / PARENT_CLOSURE_PATH)
    require(reference.get("runtime", {}).get("release_commit") == parent.get("source", {}).get("commit"), "engine release commit drift")
    require(reference.get("runtime", {}).get("release_tree") == parent.get("source", {}).get("tree"), "engine release tree drift")
    runtime = reference.get("runtime", {})
    engine = parent.get("engine", {})
    require_strict(
        {
            key: runtime.get(key)
            for key in ("release", "platform", "image", "binary_sha256")
        },
        {
            key: engine.get(key)
            for key in ("release", "platform", "image", "binary_sha256")
        },
        "engine runtime identity drift",
    )
    observations = load_json_bytes(payloads["uniswap-v4-base-v4-reference-source-observations.json"], "source observations")
    certification = reference.get("certification_execution")
    require(isinstance(certification, dict), "certification execution contract missing")
    require_strict(
        {
            key: certification.get(key)
            for key in (
                "source_observations",
                "file_backed_observations",
                "api_backed_observations",
                "raw_source_paths",
                "source_workflow_pods",
                "producer_pods",
                "nonproducer_pods",
                "collector_pods",
                "two_phase_total_pods",
            )
        },
        {
            "source_observations": 53,
            "file_backed_observations": 51,
            "api_backed_observations": 2,
            "raw_source_paths": 59,
            "source_workflow_pods": 35,
            "producer_pods": 20,
            "nonproducer_pods": 15,
            "collector_pods": 1,
            "two_phase_total_pods": 36,
        },
        "certification execution counts drift",
    )
    require_strict(
        certification.get("source_observation_contract"),
        {
            "schema": "pinax.v4-reference-replay-source-observations.v1",
            "scope": "successful-source-workflow",
            "path": "fixtures/uniswap-v4-base-v4-reference-source-observations.json",
            "sha256": sha256(
                payloads["uniswap-v4-base-v4-reference-source-observations.json"]
            ),
            "canonical_parameter_sha256": (
                "3be33736079a342318d1674eaa091e260a2b77a05dec91e91f86bb542fa0ef17"
            ),
        },
        "source-observation reference binding drift",
    )
    require_strict(
        certification.get("pod_topology"),
        {
            "schema": "pinax.v4-reference-replay-clean-run-pod-topology.v1",
            "path": "fixtures/uniswap-v4-base-v4-reference-pod-topology.json",
            "sha256": sha256(
                payloads["uniswap-v4-base-v4-reference-pod-topology.json"]
            ),
        },
        "pod-topology reference binding drift",
    )
    require(
        observations.get("schema") == "pinax.v4-reference-replay-source-observations.v1",
        "source-observation schema drift",
    )
    require(
        observations.get("scope") == "successful-source-workflow",
        "source-observation scope drift",
    )
    entries = observations.get("observations")
    require(observations.get("count") == 53 and isinstance(entries, list) and len(entries) == 53, "source-observation inventory drift")
    require(sum(len(entry.get("raw_paths", [])) for entry in entries) == 59, "raw-path count drift")
    require(len({path for entry in entries for path in entry.get("raw_paths", [])}) == 58, "unique raw-path count drift")
    require(sum("api_source" in entry for entry in entries) == 2, "API observation count drift")
    topology = load_json_bytes(payloads["uniswap-v4-base-v4-reference-pod-topology.json"], "pod topology")
    require(
        topology.get("schema") == "pinax.v4-reference-replay-clean-run-pod-topology.v1",
        "pod-topology schema drift",
    )
    require(topology.get("policy") == "exact-clean-run-no-retry-pods", "pod-topology policy drift")
    require_strict(topology.get("roles"), EXPECTED_TOPOLOGY_ROLES, "pod-topology role drift")
    require_strict(topology.get("counts"), {
        "source_workflow_pods": 35,
        "producer_pods": 20,
        "nonproducer_pods": 15,
        "primary_main_containers": 35,
        "user_sidecars": 14,
        "user_init_containers": 24,
    }, "pod-topology counts drift")
    pods = topology.get("pods")
    require(isinstance(pods, list) and len(pods) == 35, "pod-topology inventory drift")
    require(sum(pod.get("producer") is True for pod in pods) == 20, "producer pod count drift")


def verify(root: Path) -> None:
    capsule = root / CAPSULE_DIRECTORY
    try:
        capsule_stat = capsule.lstat()
    except OSError as error:
        raise VerificationError(f"q8 capsule directory is unavailable: {error}") from error
    require(not capsule.is_symlink(), "q8 capsule directory must not be a symlink")
    require(stat.S_ISDIR(capsule_stat.st_mode), "q8 capsule path must be a directory")
    observed: set[str] = set()
    for path in capsule.iterdir():
        require(not path.is_symlink(), f"q8 capsule entry must not be a symlink: {path.name}")
        require(path.is_file(), f"q8 capsule contains an unexpected directory: {path.name}")
        observed.add(path.name)
    expected = {"README.md", "closure.json", ARCHIVE_NAME, *EXPECTED_FILE_LOCKS}
    require(observed == expected, "q8 capsule file inventory drift")
    closure = load_json(root / CLOSURE_PATH)
    require(isinstance(closure, dict), "closure must be an object")
    verify_closure(closure)
    payloads: dict[str, bytes] = {}
    for name, (_, _, byte_count, digest, blob) in EXPECTED_FILE_LOCKS.items():
        payload = verify_lock(capsule / name, byte_count, digest, f"q8 source file {name}")
        require(git_blob_sha1(payload) == blob, f"q8 source file {name} Git blob drift")
        payloads[name] = payload
    archive_files = verify_archive(capsule / ARCHIVE_NAME)
    reference = load_json_bytes(payloads["uniswap-v4-base-v0.5.0-q8-reference.json"], "q8 reference")
    require(reference.get("network") == "base" and reference.get("deployment") == DEPLOYMENT, "reference identity drift")
    require_strict(
        {
            key: reference.get("seed", {}).get(key)
            for key in ("block", "hash", "checkpoint_bytes", "checkpoint_sha256")
        },
        {
            "block": 33374154,
            "hash": "5e8c1de6fe2065fcf08b382b10342e01fd8585052ca39ee1c9f80f37904c72a6",
            "checkpoint_bytes": 11093835518,
            "checkpoint_sha256": "be434078b1b71c3e51a36e37c0473f6b4d7864777511d8119426234d398e397d",
        },
        "reference seed identity drift",
    )
    manifests = (
        ("certified_segment", "uniswap-v4-base-v0.5.0-q8-manifest.json", "uniswap-v4-base-v0.5.0-q8-READY.json", 33374154, reference["seed"]["hash"]),
        ("restore_segment", "uniswap-v4-base-v0.5.0-q8-restore-manifest.json", "uniswap-v4-base-v0.5.0-q8-restore-READY.json", 33474154, EXPECTED_SEGMENTS["certified_segment"]["target_hash"]),
    )
    for key, manifest_name, ready_name, head_block, head_hash in manifests:
        source_segment = reference.get(key)
        expected_segment = EXPECTED_SEGMENTS[key]
        require(isinstance(source_segment, dict), f"{key} reference missing")
        for field, value in expected_segment.items():
            if field != "copy_payload_bytes":
                require(source_segment.get(field) == value, f"{key} reference {field} drift")
        require(source_segment.get("blocks") == 100000, f"{key} reference block-count drift")
        require(source_segment.get("copy_tables") == 19, f"{key} reference COPY count drift")
        require(source_segment.get("seed_preserved_table") == "data_sources$", f"{key} reference seed table drift")
        manifest = load_json_bytes(payloads[manifest_name], manifest_name)
        ready = load_json_bytes(payloads[ready_name], ready_name)
        verify_manifest(manifest, ready, expected_segment, head_block, head_hash, source_segment["poi"])
        require_strict(
            {
                field: source_segment.get(field)
                for field in ("inserted_rows", "clamped_rows", "new_entities")
            },
            {
                field: manifest["copy"][field]
                for field in ("inserted_rows", "clamped_rows", "new_entities")
            },
            f"{key} row-summary cross-reference drift",
        )
    verify_archive_semantics(archive_files, payloads)
    verify_reference(root, reference, payloads)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[1])
    arguments = parser.parse_args()
    try:
        verify(arguments.repository_root.resolve())
    except VerificationError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(json.dumps({
        "contract": CONTRACT,
        "status": "verified-declared-metadata-only",
        "acceptance_role": "none",
        "criterion_2_complete": False,
        "archive_sha256": EXPECTED_ARCHIVE["sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
