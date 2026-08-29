#!/usr/bin/env python3
"""Fail-closed verification for the Uniswap V4 v0.5.0 reference capsule."""

from __future__ import annotations

import argparse
import hashlib
import json
import stat
import sys
from pathlib import Path
from typing import Any


CONTRACT = "uniswap-v4-engine-v0.5.0-reference/v1"
CAPSULE_DIRECTORY = Path("docs/provenance/uniswap-v4-engine-v0.5.0")
CLOSURE_PATH = CAPSULE_DIRECTORY / "closure.json"
PACKAGE_PATH = Path(
    "uniswap-v4/release/v0.4.0/"
    "uniswap-v4-base-store-state-reducer-v0.4.0.spkg"
)
PACKAGE_CONTRACT_PATH = Path("uniswap-v4/packages/base-uniswap-v4-v0.4.0.json")
IMPORT_PROVENANCE_PATH = Path("docs/provenance/uniswap-v4-v0.4.1.json")
IMPORT_INVENTORY_PATH = Path("docs/provenance/uniswap-v4-v0.4.1-files.json")

EXPECTED_REFERENCE_FILE_LOCKS = {
    PACKAGE_CONTRACT_PATH: (
        3718,
        "e6e279232b62104a15d355b48fdead8203c0e1adffee8bc46de35d44644e39d4",
    ),
    IMPORT_PROVENANCE_PATH: (
        3241,
        "bdd4d895ea3c0d913eb834766781b683e4dbd6cbf26f89c5516b2bf81a0a71fc",
    ),
    IMPORT_INVENTORY_PATH: (
        25724,
        "d173b5d8d6ba127df4e1396356474a364fd96e0f95acaf91fbe64712917c3b42",
    ),
}

DEPLOYMENT = "Qmbsc6XQWbiv4DfLVfaNciScqYLyDWUYjWzrFBbzzmRsMB"
IMPORTED_SPKG_SHA256 = (
    "bc8a841dbb74f9bbc7d90826251ab766ad350170a4832fc3e9b084664d22254a"
)
LEGACY_SPKG_SHA256 = (
    "44520f81a7177af201aa89cd0645f3c9fdf8a50200da1a9232e6335bfecf1a0d"
)

EXPECTED_SOURCE = {
    "repository": "pinax-network/substreams-graph-node-backfill",
    "tag": "v0.5.0",
    "commit": "2b5ef82e2db987a5bfe861330aba0a222956122e",
    "tree": "d1f8c5973ee2177a3a4cdae75717efb939e5da95",
}

# Values are mutable only so adversarial unit tests can move a byte lock and
# prove that semantic cross-reference validation still fails closed.
EXPECTED_FILE_LOCKS: dict[str, dict[str, Any]] = {
    "compatibility.json": {
        "source_path": "adapters/uniswap-v4-base/compatibility.json",
        "role": "engine-compatibility-contract",
        "bytes": 7490,
        "sha256": "fafd21c63a23925327a17db315cb8a5cf7a8127c07401ab08e0c37b8920ea65c",
        "git_blob": "c309986c1b70443111541705d97663b1c15d1068",
    },
    "certificate.json": {
        "source_path": "fixtures/kan-base-v4-store-state-100k-certificate.json",
        "role": "retained-100k-certificate",
        "bytes": 1976,
        "sha256": "2ee4bd2986269361a3490c2dd87e1c775d4ac528fa898ab6093c1a1fa356ff33",
        "git_blob": "594a383fca4e18823f28bf96f377bc61af64d274",
    },
    "benchmark.json": {
        "source_path": "fixtures/kan-base-v4-store-state-100k-benchmark.json",
        "role": "retained-frame-checkpoint-benchmark",
        "bytes": 1899,
        "sha256": "a5ab9fbfc75a2d00698d49da648d7d0b9b1b5d3f209ac9eb685a4991f58248ae",
        "git_blob": "a983471b329a11a51be14376ffd4af46733aa19b",
    },
    "parity.json": {
        "source_path": "fixtures/kan-base-v4-store-state-100k-parity.json",
        "role": "retained-20-table-physical-and-poi-parity",
        "bytes": 5623,
        "sha256": "f337a01844fafd45881ad4b24fdfa6220d4a37598afe506ab5c8552813a10388",
        "git_blob": "ce2fe3367846ba2d622d5eb7a46d1a9ebfa3fb58",
    },
    "graphql.json": {
        "source_path": "fixtures/kan-base-v4-store-state-graphql.json",
        "role": "retained-head-and-graphql-parity",
        "bytes": 556,
        "sha256": "3cc7aee86dadf4dbb5abbf454e897a469bc24ca7050f39e64b9c300640497d96",
        "git_blob": "d285d18c04b3fa3d767885042fab289a9c0b05ce",
    },
    "lifecycle.json": {
        "source_path": "fixtures/kan-base-v4-store-state-lifecycle.json",
        "role": "historical-legacy-candidate-lifecycle-support",
        "bytes": 2598,
        "sha256": "45fef8b545251e912c7e4e6dac517b2c2f4e6452d61a09af5eeadb7f206857ea",
        "git_blob": "8710ab18321a057324679f7871ffaa49198ed522",
    },
    "overlap.json": {
        "source_path": "fixtures/kan-base-v4-store-state-sharded-overlap.json",
        "role": "separate-range-sharded-package-overlap-support",
        "bytes": 686,
        "sha256": "8a5f67a511d219be9e361b1661e13320903ae94a13a31788c0cb60bf25e3df61",
        "git_blob": "73a9c55ffed0769ed591c84074f34b4db65e5e4c",
    },
}

EXPECTED_ENGINE = {
    "release": "v0.5.0",
    "platform": "linux/amd64",
    "image": (
        "ghcr.io/pinax-network/substreams-graph-node-backfill@"
        "sha256:dbb88e451dbd44fd3e412f1d6814939cbc2a0b93c539837ebfb1f28d3dd1711e"
    ),
    "binary_sha256": {
        "state-replay": "de05b611bc53e99ff695d8e0426ed619c27244947130b8b12ca4591c6fa68390",
        "parquet-backfill": "82554a1ab6573279ff564937cd50a5b7fb52ae39837c0f88fba6d341517709b9",
        "postgres-spool-load": "34886bb9c868974eb5f4844a323d76960ff9730fd4dd024e778ed6375d2824e5",
        "substreams-native": "4d8bdd9077551b4f7b55105828721d6fca252de96e30c625c4912d5bb2097ddf",
    },
    "graph_node": {
        "version": "v0.44.0",
        "commit": "77823b5a7adc4eac4abf03202c8dd7cb00dea31d",
        "dump_format": 1,
    },
}

EXPECTED_PACKAGE = {
    "path": str(PACKAGE_PATH),
    "bytes": 1458573,
    "sha256": IMPORTED_SPKG_SHA256,
    "git_blob": "c1b32733c3949bb754bffc773d954aa3008c72b6",
    "repository": "pinax-network/substreams-v4-subgraph",
    "source_tag": "v0.4.1",
    "source_commit": "6812a4deaa5a520020e8d727e17f6d0b7113d0a9",
    "source_tree": "2d60d30242443adc2c021a5b609c27edcb75128a",
    "production_release_tag": "v0.4.0",
    "production_release_commit": "7609dc67ce83865a16e441ff2b3b56db6c46ee2a",
    "package_name": "uniswap_v4_base_store_state_reducer",
    "package_version": "v0.4.0",
    "network": "base",
    "module": "map_store_state_inputs",
    "module_hash": "223408b90abae80960c41e11205fad2294accfa9",
    "output_type": "proto:pinax.uniswap.v4.base.store.v1.ReducerInputs",
    "initial_block": 25350988,
}

EXPECTED_RANGE = {
    "seed_block": 32374154,
    "start_block": 32374155,
    "end_block": 32474154,
    "blocks": 100000,
    "seed_hash": "b4b30252f3b6c183c9b5b36341bd5c1ebb50a87811753d1976b69c01c09e05d4",
    "end_hash": "e2c6b741291ec233e265848784944b7ea33469dd7422b013e537967d0ad79bf9",
}

EXPECTED_TABLES = (
    "pool_manager",
    "bundle",
    "token",
    "pool",
    "tick",
    "uniswap_day_data",
    "pool_day_data",
    "pool_hour_data",
    "token_day_data",
    "token_hour_data",
    "position",
    "arrakis_hook",
    "poi2$",
    "transaction",
    "swap",
    "modify_liquidity",
    "subscribe",
    "unsubscribe",
    "transfer",
    "data_sources$",
)

EXPECTED_POI = {
    "table": "poi2$",
    "local_rows": 86343,
    "source_rows": 86343,
    "local_digest": "906139fe973ba753f93bdc6ac41ee42a8d1dfa33857b065c02007bd08feb41cc",
    "source_digest": "906139fe973ba753f93bdc6ac41ee42a8d1dfa33857b065c02007bd08feb41cc",
}

EXPECTED_HISTORICAL_CERTIFICATE_GATES = {
    "stopped_physical_clone": True,
    "graft_parent_preserved": True,
    "tables_matched": 20,
    "tables_mismatched": 0,
    "vid_sequences_valid": 20,
    "graphql_exact": True,
    "poi_exact": True,
    "no_op_resume": True,
    "graph_node_continuation": True,
    "graph_node_restart": True,
    "graph_node_rewind": True,
    "graph_node_replay": True,
    "sharded_overlap_byte_identical": True,
}

EXPECTED_GATES = {
    "reproduction_complete": False,
    "scratch_target_named": False,
    "scratch_target_disposable": False,
    "scratch_target_stopped": False,
    "independent_zero_writer_proven": False,
    "k3_runtime_contract_approved": False,
    "workflow_submission_authorized": False,
    "workflow_submitted": False,
    "database_write_authorized": False,
    "database_mutation_performed": False,
    "source_database_mutation_performed": False,
    "recovery_database_mutation_performed": False,
    "existing_v4_workflow_mutation_performed": False,
    "readiness": False,
    "backfill_ready": False,
    "production_ready": False,
    "promotion_eligible": False,
}

EXPECTED_MISSING_REFERENCE_BYTES = [
    "selected 100k runtime checkpoint manifest bytes and SHA-256",
    "selected 100k literal COPY spool filenames and file digests",
    "selected 100k frame payload bytes",
    "selected 100k checkpoint bytes",
]

EXPECTED_PROTECTED_RESOURCES = {
    "source_database": {
        "schema": "sgd1246",
        "mutation_authorized": False,
        "mutation_performed": False,
    },
    "recovery_database": {
        "schema": "sgd5303",
        "mutation_authorized": False,
        "mutation_performed": False,
    },
    "existing_v4_workflow": {
        "identifier": None,
        "mutation_authorized": False,
        "mutation_performed": False,
    },
}

EXPECTED_NON_CLAIMS = [
    "The retained 100k range has not been reproduced with engine v0.5.0 or the imported sharded package.",
    "The historical sgd2 target is not authorization to reuse it and no new scratch target is named.",
    "No independent zero-writer evidence, K3 approval, workflow authorization, workflow submission, or database write is represented.",
    "The lifecycle fixture is historical support from a 189-block legacy-candidate continuation, not v0.5.0 evidence.",
    "The overlap fixture is a separate-range package-equivalence result, not reproduction of the selected 100k range.",
    "This capsule does not establish backfill, production, release, or promotion readiness.",
]


class VerificationError(ValueError):
    """Raised when retained evidence or its claim boundary drifts."""


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise VerificationError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def load_json(path: Path) -> Any:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_keys,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise VerificationError(f"cannot load JSON {path}: {error}") from error


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def require_exact_keys(value: Any, expected: set[str], context: str) -> None:
    require(isinstance(value, dict), f"{context} must be an object")
    actual = set(value)
    require(
        actual == expected,
        (
            f"{context} keys drift: missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        ),
    )


def require_regular_file(root: Path, relative: Path, context: str) -> Path:
    require(not relative.is_absolute(), f"{context} path must be relative")
    require(".." not in relative.parts, f"{context} path escapes repository")
    path = root / relative
    component = root
    try:
        for part in relative.parts:
            component /= part
            require(
                not stat.S_ISLNK(component.lstat().st_mode),
                f"{context} path contains a symlink: {relative}",
            )
        file_stat = path.lstat()
    except OSError as error:
        raise VerificationError(f"{context} is unavailable: {relative}: {error}") from error
    require(stat.S_ISREG(file_stat.st_mode), f"{context} must be a regular file: {relative}")
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as error:
        raise VerificationError(f"{context} escapes repository: {relative}") from error
    return path


def sha256_file(path: Path) -> tuple[int, str]:
    payload = path.read_bytes()
    return len(payload), hashlib.sha256(payload).hexdigest()


def expected_file_records() -> list[dict[str, Any]]:
    return [
        {
            "local_path": local_path,
            "source_path": lock["source_path"],
            "role": lock["role"],
            "bytes": lock["bytes"],
            "sha256": lock["sha256"],
            "git_blob": lock["git_blob"],
        }
        for local_path, lock in EXPECTED_FILE_LOCKS.items()
    ]


def verify_inventory(root: Path) -> None:
    capsule = root / CAPSULE_DIRECTORY
    try:
        capsule_stat = capsule.lstat()
    except OSError as error:
        raise VerificationError(f"capsule directory is unavailable: {error}") from error
    require(not capsule.is_symlink(), "capsule directory must not be a symlink")
    require(stat.S_ISDIR(capsule_stat.st_mode), "capsule path must be a directory")

    expected = set(EXPECTED_FILE_LOCKS) | {"closure.json", "README.md"}
    actual: set[str] = set()
    for path in capsule.rglob("*"):
        relative = path.relative_to(capsule).as_posix()
        require(not path.is_symlink(), f"capsule entry must not be a symlink: {relative}")
        require(path.is_file(), f"capsule contains an unexpected directory: {relative}")
        actual.add(relative)
    require(
        actual == expected,
        (
            f"capsule file inventory drift: missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        ),
    )


def verify_file_locks(root: Path, closure: dict[str, Any]) -> dict[str, Any]:
    require(closure["files"] == expected_file_records(), "closure source file records drift")
    loaded: dict[str, Any] = {}
    capsule = root / CAPSULE_DIRECTORY
    for local_path, lock in EXPECTED_FILE_LOCKS.items():
        path = require_regular_file(
            root,
            CAPSULE_DIRECTORY / local_path,
            f"retained {local_path}",
        )
        observed_bytes, observed_sha = sha256_file(path)
        require(
            observed_bytes == lock["bytes"],
            f"{local_path} byte length drift: {observed_bytes}",
        )
        require(
            observed_sha == lock["sha256"],
            f"{local_path} SHA-256 drift: {observed_sha}",
        )
        loaded[local_path] = load_json(capsule / local_path)
    return loaded


def verify_closure_shape(closure: Any) -> None:
    require_exact_keys(
        closure,
        {
            "format_version",
            "contract",
            "status",
            "scope",
            "source",
            "files",
            "engine",
            "imported_package",
            "selected_reference",
            "supporting_evidence",
            "protected_resources",
            "missing_reference_bytes",
            "gates",
            "non_claims",
        },
        "closure",
    )
    require(closure["format_version"] == 1, "closure format version drift")
    require(closure["contract"] == CONTRACT, "closure contract drift")
    require(
        closure["status"] == "pre-execution-reference-only",
        "closure status overclaims execution",
    )
    require(
        closure["scope"]
        == {
            "repository": "pinax-network/substreams-backfills",
            "github_issue": 26,
            "supports_acceptance_criteria": [1, 2],
            "fully_satisfied_acceptance_criteria": [1],
            "partially_satisfied_acceptance_criteria": [2],
            "unsupported_acceptance_criteria": [3, 4, 5, 6, 7, 8],
        },
        "issue #26 acceptance-criteria scope drift",
    )
    criteria = (
        closure["scope"]["supports_acceptance_criteria"]
        + closure["scope"]["fully_satisfied_acceptance_criteria"]
        + closure["scope"]["partially_satisfied_acceptance_criteria"]
        + closure["scope"]["unsupported_acceptance_criteria"]
    )
    require(
        all(type(criterion) is int for criterion in criteria),
        "acceptance-criteria identifiers must be integers",
    )
    require(closure["source"] == EXPECTED_SOURCE, "tagged engine source identity drift")
    require(closure["engine"] == EXPECTED_ENGINE, "engine v0.5.0 identity drift")
    require(
        type(closure["engine"]["graph_node"]["dump_format"]) is int,
        "Graph Node dump format must be an integer",
    )
    require(
        closure["imported_package"] == EXPECTED_PACKAGE,
        "imported package closure identity drift",
    )
    require(
        type(closure["imported_package"]["initial_block"]) is int,
        "imported package initial block must be an integer",
    )
    require_exact_keys(
        closure["supporting_evidence"],
        {"lifecycle", "sharded_overlap"},
        "supporting evidence",
    )
    require(
        closure["protected_resources"] == EXPECTED_PROTECTED_RESOURCES,
        "protected-resource boundary drift",
    )
    require(
        all(
            value is False
            for resource in closure["protected_resources"].values()
            for key, value in resource.items()
            if key in {"mutation_authorized", "mutation_performed"}
        ),
        "protected-resource mutation flags must be false booleans",
    )
    require_exact_keys(closure["gates"], set(EXPECTED_GATES), "operational gates")
    require(
        all(closure["gates"][gate] is False for gate in EXPECTED_GATES),
        "operational gate drift",
    )
    require(
        closure["missing_reference_bytes"] == EXPECTED_MISSING_REFERENCE_BYTES,
        "missing-reference disclosure drift",
    )
    require(closure["non_claims"] == EXPECTED_NON_CLAIMS, "non-claim boundary drift")


def verify_imported_package(root: Path, closure: dict[str, Any], compatibility: dict[str, Any]) -> None:
    package = require_regular_file(root, PACKAGE_PATH, "imported Store-state SPKG")
    observed_bytes, observed_sha = sha256_file(package)
    require(observed_bytes == EXPECTED_PACKAGE["bytes"], "imported SPKG byte length drift")
    require(observed_sha == IMPORTED_SPKG_SHA256, "imported SPKG SHA-256 drift")

    locked_reference_paths: dict[Path, Path] = {}
    for relative, expected_lock in EXPECTED_REFERENCE_FILE_LOCKS.items():
        reference = require_regular_file(root, relative, f"locked reference {relative}")
        observed_lock = sha256_file(reference)
        require(
            observed_lock == expected_lock,
            (
                f"{relative} byte/SHA-256 drift: got {observed_lock}, "
                f"expected {expected_lock}"
            ),
        )
        locked_reference_paths[relative] = reference

    package_contract = load_json(locked_reference_paths[PACKAGE_CONTRACT_PATH])
    provenance = load_json(locked_reference_paths[IMPORT_PROVENANCE_PATH])
    inventory = load_json(locked_reference_paths[IMPORT_INVENTORY_PATH])

    require_exact_keys(
        package_contract,
        {
            "format_version",
            "network",
            "deployment",
            "initial_block",
            "repository",
            "release",
            "historical_build_repository",
            "packages",
        },
        "V4 package contract",
    )
    require(
        package_contract["format_version"] == 1
        and package_contract["network"] == EXPECTED_PACKAGE["network"]
        and package_contract["deployment"] == DEPLOYMENT
        and package_contract["initial_block"] == EXPECTED_PACKAGE["initial_block"]
        and package_contract["repository"] == EXPECTED_PACKAGE["repository"]
        and package_contract["release"] == EXPECTED_PACKAGE["production_release_tag"],
        "V4 package contract root identity drift",
    )
    state_contract = package_contract["packages"]["store_state"]
    for key in (
        "asset",
        "sha256",
        "package_name",
        "package_version",
        "module",
        "module_hash",
        "output_type",
    ):
        expected_key = "path" if key == "asset" else key
        expected_value = (
            Path(EXPECTED_PACKAGE["path"]).name
            if key == "asset"
            else EXPECTED_PACKAGE[expected_key]
        )
        require(
            state_contract[key] == expected_value,
            f"V4 package contract {key} drift",
        )

    require_exact_keys(
        provenance,
        {
            "format_version",
            "family",
            "source",
            "production_release",
            "release_assets",
            "module_contracts",
            "ownership",
            "integration_constraints",
            "retirement_gates",
        },
        "V4 import provenance",
    )
    require(
        provenance["source"]
        == {
            "repository": EXPECTED_PACKAGE["repository"],
            "tag": EXPECTED_PACKAGE["source_tag"],
            "commit": EXPECTED_PACKAGE["source_commit"],
            "history_mirror": "refs/heads/upstream/uniswap-v4-v0.4.1",
            "tree": EXPECTED_PACKAGE["source_tree"],
            "tracked_files": 98,
            "executable_files": 13,
        },
        "V4 imported source provenance drift",
    )
    require(
        provenance["production_release"]
        == {
            "tag": EXPECTED_PACKAGE["production_release_tag"],
            "commit": EXPECTED_PACKAGE["production_release_commit"],
        },
        "V4 production release provenance drift",
    )
    retained_asset = [
        item
        for item in provenance["release_assets"]
        if item["name"] == Path(EXPECTED_PACKAGE["path"]).name
    ]
    require(
        retained_asset
        == [
            {
                "release": "v0.4.0",
                "name": Path(EXPECTED_PACKAGE["path"]).name,
                "sha256": IMPORTED_SPKG_SHA256,
                "retained_in_import": True,
            }
        ],
        "V4 retained release asset identity drift",
    )
    require(
        provenance["module_contracts"]["map_store_state_inputs"]
        == EXPECTED_PACKAGE["module_hash"],
        "V4 imported module contract drift",
    )

    require_exact_keys(
        inventory,
        {
            "format_version",
            "source_commit",
            "source_tree",
            "file_count",
            "executable_count",
            "files",
        },
        "V4 import inventory",
    )
    require(
        inventory["format_version"] == 1
        and inventory["source_commit"] == EXPECTED_PACKAGE["source_commit"]
        and inventory["source_tree"] == EXPECTED_PACKAGE["source_tree"]
        and inventory["file_count"] == 98
        and inventory["executable_count"] == 13,
        "V4 import inventory identity drift",
    )
    relative_package = str(PACKAGE_PATH.relative_to("uniswap-v4"))
    inventory_record = [
        item for item in inventory["files"] if item["path"] == relative_package
    ]
    require(
        inventory_record
        == [
            {
                "path": relative_package,
                "mode": "100644",
                "size": EXPECTED_PACKAGE["bytes"],
                "git_blob": EXPECTED_PACKAGE["git_blob"],
                "sha256": IMPORTED_SPKG_SHA256,
            }
        ],
        "V4 imported package inventory record drift",
    )

    store_state = compatibility["store_state_spkg"]
    require(
        {
            "repository": store_state["repository"],
            "release": store_state["release"],
            "asset": store_state["asset"],
            "sha256": store_state["sha256"],
            "package_name": store_state["package_name"],
            "package_version": store_state["package_version"],
            "network": store_state["network"],
            "module": store_state["module"],
            "module_hash": store_state["module_hash"],
            "output_type": store_state["output_type"],
            "initial_block": store_state["initial_block"],
        }
        == {
            "repository": EXPECTED_PACKAGE["repository"],
            "release": EXPECTED_PACKAGE["production_release_tag"],
            "asset": Path(EXPECTED_PACKAGE["path"]).name,
            "sha256": EXPECTED_PACKAGE["sha256"],
            "package_name": EXPECTED_PACKAGE["package_name"],
            "package_version": EXPECTED_PACKAGE["package_version"],
            "network": EXPECTED_PACKAGE["network"],
            "module": EXPECTED_PACKAGE["module"],
            "module_hash": EXPECTED_PACKAGE["module_hash"],
            "output_type": EXPECTED_PACKAGE["output_type"],
            "initial_block": EXPECTED_PACKAGE["initial_block"],
        },
        "compatibility contract and imported package identity differ",
    )
    require(
        store_state["imported_module_hashes"]
        == state_contract["imported_module_hashes"],
        "imported Store module hashes differ between compatibility and package contracts",
    )
    compatibility_shards = store_state["tick_liquidity_shards"]
    package_shards = state_contract["tick_liquidity_shards"]
    require(
        {
            "count": compatibility_shards["count"],
            "partition": compatibility_shards["partition"],
            "module_hashes": compatibility_shards["module_hashes"],
        }
        == package_shards,
        "Tick-liquidity shard identity differs between compatibility and package contracts",
    )
    require(
        compatibility_shards["legacy_key_encoding"] is True
        and compatibility_shards["replaces_module"] == "store_tick_liquidity"
        and compatibility_shards["replaced_module_hash"]
        == "6abfe7cad14187870e808e940ae4f4b3b56a0bfd",
        "Tick-liquidity replacement contract drift",
    )
    require(
        store_state["built_modules"]
        == [
            *compatibility_shards["module_hashes"].keys(),
            "store_pool_sqrt_price",
            "store_token_decimals",
            "store_pool_token_decimals",
            EXPECTED_PACKAGE["module"],
        ],
        "Store-state built-module inventory drift",
    )
    require(
        closure["imported_package"]["sha256"] == observed_sha,
        "closure and imported SPKG bytes differ",
    )


def verify_compatibility(compatibility: dict[str, Any]) -> None:
    require_exact_keys(
        compatibility,
        {
            "format_version",
            "adapter",
            "deployment",
            "graft_base",
            "graft_block",
            "spkg",
            "store_spkg",
            "store_fed_spkg",
            "store_state_spkg",
            "direct_postgres",
            "runtime",
            "graph_node",
        },
        "compatibility contract",
    )
    require(
        compatibility["format_version"] == 1
        and compatibility["adapter"] == "uniswap-v4-base"
        and compatibility["deployment"] == DEPLOYMENT,
        "compatibility root identity drift",
    )


def verify_engine_compatibility(compatibility: dict[str, Any], closure: dict[str, Any]) -> None:
    require(
        compatibility["runtime"]
        == {
            "release": EXPECTED_ENGINE["release"],
            "platform": EXPECTED_ENGINE["platform"],
            "image": EXPECTED_ENGINE["image"],
            "binary_sha256": EXPECTED_ENGINE["binary_sha256"],
        },
        "compatibility runtime does not pin engine v0.5.0",
    )
    require(
        compatibility["graph_node"] == EXPECTED_ENGINE["graph_node"],
        "compatibility Graph Node identity drift",
    )
    require(closure["engine"] == EXPECTED_ENGINE, "closure engine identity drift")


def verify_certificate_artifact_links(
    certificate: dict[str, Any], loaded: dict[str, Any]
) -> None:
    require_exact_keys(
        certificate,
        {
            "format_version",
            "status",
            "network",
            "deployment",
            "range",
            "legacy_runtime",
            "sharded_runtime",
            "artifacts",
            "gates",
        },
        "retained certificate",
    )
    expected_links = {
        "benchmark": ("benchmark.json", "fixtures/kan-base-v4-store-state-100k-benchmark.json"),
        "parity": ("parity.json", "fixtures/kan-base-v4-store-state-100k-parity.json"),
        "graphql": ("graphql.json", "fixtures/kan-base-v4-store-state-graphql.json"),
        "lifecycle": ("lifecycle.json", "fixtures/kan-base-v4-store-state-lifecycle.json"),
        "overlap": ("overlap.json", "fixtures/kan-base-v4-store-state-sharded-overlap.json"),
    }
    require(set(certificate["artifacts"]) == set(expected_links), "certificate artifact set drift")
    for name, (local_path, source_path) in expected_links.items():
        link = certificate["artifacts"][name]
        require(
            link
            == {
                "path": source_path,
                "sha256": EXPECTED_FILE_LOCKS[local_path]["sha256"],
            },
            f"certificate {name} artifact cross-reference drift",
        )
        require(loaded[local_path] is not None, f"retained {name} JSON was not loaded")


def verify_selected_reference(loaded: dict[str, Any], closure: dict[str, Any]) -> None:
    certificate = loaded["certificate.json"]
    benchmark = loaded["benchmark.json"]
    parity = loaded["parity.json"]
    graphql = loaded["graphql.json"]
    lifecycle = loaded["lifecycle.json"]
    overlap = loaded["overlap.json"]
    selected = closure["selected_reference"]

    require_exact_keys(
        selected,
        {
            "classification",
            "deployment",
            "network",
            "range",
            "frame_stream",
            "retained_manifest",
            "runtime_checkpoint_manifest",
            "copy_inventory",
            "checkpoint",
            "physical_rows",
            "poi",
            "graphql",
            "historical_target_evidence",
        },
        "selected reference",
    )
    require(
        selected["classification"]
        == "historical-retained-certificate-not-v0.5.0-reproduction",
        "selected reference classification overclaims reproduction",
    )
    require(
        selected["deployment"] == DEPLOYMENT and selected["network"] == "base",
        "selected reference deployment identity drift",
    )
    require(selected["range"] == EXPECTED_RANGE, "selected range closure drift")

    certificate_range = certificate["range"]
    require(
        certificate["format_version"] == 1
        and certificate["status"] == "complete"
        and certificate["network"] == "base"
        and certificate["deployment"] == DEPLOYMENT,
        "retained certificate root identity drift",
    )
    require(
        certificate_range
        == {
            "seed_block": EXPECTED_RANGE["seed_block"],
            "start_block": EXPECTED_RANGE["start_block"],
            "end_block": EXPECTED_RANGE["end_block"],
            "blocks": EXPECTED_RANGE["blocks"],
            "seed_hash": EXPECTED_RANGE["seed_hash"],
            "end_hash": EXPECTED_RANGE["end_hash"],
        },
        "certificate range/hash cross-reference drift",
    )
    require(
        EXPECTED_RANGE["start_block"] == EXPECTED_RANGE["seed_block"] + 1
        and EXPECTED_RANGE["end_block"] - EXPECTED_RANGE["start_block"] + 1
        == EXPECTED_RANGE["blocks"],
        "selected range arithmetic is invalid",
    )
    require(
        certificate["legacy_runtime"]["spkg_sha256"] == LEGACY_SPKG_SHA256,
        "retained certificate legacy package identity drift",
    )
    require(
        certificate["sharded_runtime"]["spkg_sha256"] == IMPORTED_SPKG_SHA256,
        "retained certificate sharded package identity drift",
    )
    certificate_gates = certificate["gates"]
    require_exact_keys(
        certificate_gates,
        set(EXPECTED_HISTORICAL_CERTIFICATE_GATES),
        "historical certificate gates",
    )
    for gate in ("tables_matched", "tables_mismatched", "vid_sequences_valid"):
        require(
            type(certificate_gates[gate]) is int
            and certificate_gates[gate]
            == EXPECTED_HISTORICAL_CERTIFICATE_GATES[gate],
            f"historical certificate gate drift: {gate}",
        )
    for gate in (
        set(EXPECTED_HISTORICAL_CERTIFICATE_GATES)
        - {"tables_matched", "tables_mismatched", "vid_sequences_valid"}
    ):
        require(
            certificate_gates[gate] is True,
            f"historical certificate gate drift: {gate}",
        )
    verify_certificate_artifact_links(certificate, loaded)

    benchmark_range = benchmark["range"]
    require(
        benchmark["format_version"] == 1
        and benchmark["status"] == "complete"
        and benchmark["network"] == "base"
        and benchmark["deployment"] == DEPLOYMENT,
        "benchmark root identity drift",
    )
    require(
        benchmark_range
        == {
            "seed": EXPECTED_RANGE["seed_block"],
            "start": EXPECTED_RANGE["start_block"],
            "end": EXPECTED_RANGE["end_block"],
            "blocks": EXPECTED_RANGE["blocks"],
            "seed_hash": EXPECTED_RANGE["seed_hash"],
            "end_hash": EXPECTED_RANGE["end_hash"],
        },
        "benchmark range/hash cross-reference drift",
    )
    require(benchmark["spkg_sha256"] == LEGACY_SPKG_SHA256, "benchmark legacy SPKG drift")
    require(
        benchmark["image"] != EXPECTED_ENGINE["image"],
        "historical benchmark must not be relabeled as v0.5.0 execution",
    )
    require(
        selected["frame_stream"]
        == {
            "input": benchmark["input"],
            "event_bearing_frames": benchmark["cold_cache"]["event_bearing_frames"],
            "protobuf_payload_bytes": benchmark["cold_cache"]["protobuf_payload_bytes"],
        }
        == {
            "input": "store-state-protobuf-framed",
            "event_bearing_frames": 86342,
            "protobuf_payload_bytes": 1069268806,
        },
        "frame-stream cross-reference drift",
    )
    require(
        selected["checkpoint"]
        == benchmark["checkpoint"]
        == {
            "bytes": 5942403462,
            "sha256": "69b69f4f44f7344f64bddb798f393fbc7411be044fc98932579a36d1ff66231a",
        },
        "checkpoint cross-reference drift",
    )
    require(
        benchmark["cluster"] == selected["historical_target_evidence"]["cluster"]
        and benchmark["schema"] == selected["historical_target_evidence"]["schema"]
        and benchmark["graft_parent_seed"]["source_schema"]
        == selected["historical_target_evidence"]["source_schema"],
        "historical target-evidence cross-reference drift",
    )
    require(
        selected["historical_target_evidence"]["classification"]
        == "prior-certificate-context-only-not-a-new-authorized-target",
        "historical target evidence was promoted to an authorized target",
    )
    require(
        selected["historical_target_evidence"]
        == {
            "cluster": "kan-subgraphs-a",
            "schema": "sgd2",
            "source_schema": "sgd1246",
            "classification": "prior-certificate-context-only-not-a-new-authorized-target",
        },
        "historical target evidence contains unapproved fields",
    )
    require(
        selected["retained_manifest"]
        == {
            "kind": "certificate-artifact-digest-manifest",
            "path": "certificate.json",
            "sha256": EXPECTED_FILE_LOCKS["certificate.json"]["sha256"],
        },
        "retained certificate-manifest identity drift",
    )
    require(
        selected["runtime_checkpoint_manifest"]
        == {"retained": False, "sha256": None, "bytes": None}
        and selected["runtime_checkpoint_manifest"]["retained"] is False,
        "missing runtime checkpoint manifest was falsely claimed",
    )

    require_exact_keys(
        parity,
        {
            "deployment",
            "local_schema",
            "source_schema",
            "range",
            "vid_policy",
            "row_comparison",
            "future_range_policy",
            "source_policy",
            "seed_policy",
            "matched_tables",
            "mismatched_tables",
            "local_rows",
            "source_rows",
            "tables",
        },
        "20-table parity",
    )
    require(
        parity["deployment"] == DEPLOYMENT
        and parity["range"]
        == {
            "seed": EXPECTED_RANGE["seed_block"],
            "start": EXPECTED_RANGE["start_block"],
            "end": EXPECTED_RANGE["end_block"],
        },
        "parity range cross-reference drift",
    )
    require(
        parity["matched_tables"] == 20
        and parity["mismatched_tables"] == 0
        and len(parity["tables"]) == 20,
        "20-table parity cardinality drift",
    )
    table_names = [table["table"] for table in parity["tables"]]
    require(table_names == list(EXPECTED_TABLES), "COPY table inventory or order drift")
    require(len(set(table_names)) == 20, "COPY table inventory contains duplicates")
    for table in parity["tables"]:
        require(
            table["status"] == "match"
            and type(table["local_rows"]) is int
            and table["local_rows"] >= 0
            and table["local_rows"] == table["source_rows"],
            f"physical row parity drift for {table['table']}",
        )
        if table["table"] == "data_sources$":
            require(
                set(table) == {"table", "status", "local_rows", "source_rows"},
                "data_sources$ parity shape drift",
            )
        else:
            require(
                set(table)
                == {
                    "table",
                    "status",
                    "local_rows",
                    "source_rows",
                    "local_digest",
                    "source_digest",
                }
                and table["local_digest"] == table["source_digest"],
                f"physical digest parity drift for {table['table']}",
            )
    require(
        sum(table["local_rows"] for table in parity["tables"]) == parity["local_rows"]
        and sum(table["source_rows"] for table in parity["tables"]) == parity["source_rows"]
        and parity["local_rows"] == parity["source_rows"] == 12393562,
        "physical-row total cross-reference drift",
    )
    copy_inventory = selected["copy_inventory"]
    require(
        copy_inventory
        == {
            "classification": "table-level-parity-inventory-not-copy-spool-file-set",
            "matched_tables": 20,
            "mismatched_tables": 0,
            "tables": list(EXPECTED_TABLES),
            "copy_spool_file_set_retained": False,
        },
        "COPY inventory claim boundary drift",
    )
    require(
        copy_inventory["copy_spool_file_set_retained"] is False,
        "COPY spool retention flag must be a false boolean",
    )
    require(
        selected["physical_rows"]
        == {"local": parity["local_rows"], "source": parity["source_rows"]},
        "physical-row closure cross-reference drift",
    )
    poi = next(table for table in parity["tables"] if table["table"] == "poi2$")
    require(
        poi == {"status": "match", **EXPECTED_POI},
        "retained PoI table identity drift",
    )
    require(selected["poi"] == EXPECTED_POI, "PoI closure cross-reference drift")

    require(
        graphql
        == {
            "deployment": DEPLOYMENT,
            "block": {
                "number": EXPECTED_RANGE["end_block"],
                "hash": EXPECTED_RANGE["end_hash"],
            },
            "local_subgraph": "prototype/uniswap-v4-base-substreams-kan",
            "source_subgraph": "transplant/sgd1246",
            "response": {
                "pool_managers": 1,
                "bundles": 1,
                "tokens": 25,
                "pools": 25,
                "normalized_sha256": "336c7e85baa68501dfaf5a12d764aa9f9ea9fd3f9668696944a9d008fc6fe982",
            },
            "match": True,
            "local_head_exact": True,
            "status": "complete",
        },
        "GraphQL retained artifact drift",
    )
    require(
        selected["graphql"]
        == {
            "block": graphql["block"]["number"],
            "block_hash": graphql["block"]["hash"],
            "normalized_sha256": graphql["response"]["normalized_sha256"],
        },
        "GraphQL closure cross-reference drift",
    )

    lifecycle_support = closure["supporting_evidence"]["lifecycle"]
    require(
        lifecycle["status"] == "complete"
        and lifecycle["deployment"] == DEPLOYMENT
        and lifecycle["seed"]["block"] == EXPECTED_RANGE["end_block"]
        and lifecycle["seed"]["hash"] == EXPECTED_RANGE["end_hash"]
        and lifecycle["seed"]["graphql_sha256"]
        == graphql["response"]["normalized_sha256"],
        "historical lifecycle seed cross-reference drift",
    )
    require(
        lifecycle["target"]["block"] - lifecycle["seed"]["block"]
        == lifecycle["target"]["blocks"]
        == 189,
        "historical lifecycle range drift",
    )
    require(
        lifecycle["candidate"]["spkg_sha256"] == LEGACY_SPKG_SHA256
        and lifecycle["candidate"]["image"] != EXPECTED_ENGINE["image"],
        "historical lifecycle was relabeled as v0.5.0/imported-package evidence",
    )
    require(
        lifecycle_support
        == {
            "classification": "historical-189-block-legacy-candidate-continuation-only",
            "seed_block": lifecycle["seed"]["block"],
            "seed_hash": lifecycle["seed"]["hash"],
            "target_block": lifecycle["target"]["block"],
            "target_hash": lifecycle["target"]["hash"],
            "legacy_spkg_sha256": lifecycle["candidate"]["spkg_sha256"],
        },
        "historical lifecycle support classification drift",
    )

    overlap_support = closure["supporting_evidence"]["sharded_overlap"]
    require(
        overlap["version"] == 1
        and overlap["spkg_sha256"] == IMPORTED_SPKG_SHA256
        and overlap["range"]["end_block"] - overlap["range"]["start_block"] + 1
        == 100000
        and overlap["byte_identical_to_legacy_checkpoint"] is True
        and overlap["postgres_default_transaction_read_only"] is True
        and overlap["database_head_unchanged"] is True,
        "sharded overlap evidence drift",
    )
    require(
        overlap["range"]["start_block"] != EXPECTED_RANGE["start_block"]
        and overlap["range"]["end_block"] != EXPECTED_RANGE["end_block"],
        "separate-range overlap was conflated with selected reproduction",
    )
    require(
        overlap_support
        == {
            "classification": "separate-range-immutable-package-equivalence-only",
            "start_block": overlap["range"]["start_block"],
            "end_block": overlap["range"]["end_block"],
            "blocks": 100000,
            "spkg_sha256": overlap["spkg_sha256"],
            "checkpoint_sha256": overlap["checkpoint_sha256"],
            "checkpoint_bytes": overlap["checkpoint_bytes"],
            "byte_identical_to_legacy_checkpoint": True,
            "postgres_default_transaction_read_only": True,
            "database_head_unchanged": True,
        },
        "sharded overlap support classification drift",
    )


def verify(root: Path) -> None:
    root = root.resolve()
    verify_inventory(root)
    closure = load_json(require_regular_file(root, CLOSURE_PATH, "closure manifest"))
    verify_closure_shape(closure)
    loaded = verify_file_locks(root, closure)
    compatibility = loaded["compatibility.json"]
    verify_compatibility(compatibility)
    verify_engine_compatibility(compatibility, closure)
    verify_imported_package(root, closure, compatibility)
    verify_selected_reference(loaded, closure)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root (defaults to the verifier's repository)",
    )
    args = parser.parse_args()
    try:
        verify(args.root)
    except VerificationError as error:
        print(f"Uniswap V4 engine reference verification failed: {error}", file=sys.stderr)
        return 1
    print(
        "verified engine v0.5.0 identity, imported V4 package, retained 100k "
        "pre-execution summary, typed historical certificate gates, and "
        "all-false execution/readiness gates"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
