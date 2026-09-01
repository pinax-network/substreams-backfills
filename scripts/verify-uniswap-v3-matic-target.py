#!/usr/bin/env python3
"""Verify the immutable Matic target, static layout, and exact-source behavior profile."""

from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
import re
import sys
from pathlib import Path

import yaml


LOCK_PATH = Path("docs/provenance/uniswap-v3-matic-target.json")
PROFILE_PATH = Path("uniswap-v3-matic/layout-profile-v1.json")
EXPECTED_DEPLOYMENT = "QmWqwrVtcTzZzbTLGLgiRSQzbZ7MTH53VwqK4AxXVmf7n3"
BINDING_PATH = Path(f"uniswap-v3-matic/{EXPECTED_DEPLOYMENT}.yaml")
EXPECTED_SCHEMA = "QmVYKvi799Cpg4WVXjhSWjRXNcNg4p1JQxj1WBdbcfHvoq"
EXPECTED_QMA8_SCHEMA = "Qma8a81T9XoX5Pbkrk8J3kxMhWdXJzFSYZge1wGi3QZBru"
EXPECTED_SOURCE_STATUS = "exact_reproduction"
EXPECTED_SOURCE_COMMIT = "d07374a05719e68a10a339f79cdfbc048807cfdc"
EXPECTED_SOURCE_TREE = "8f5cefd138068952bee909522a0f1d88fdc87b42"
EXPECTED_PROFILE_BYTES = 17057
EXPECTED_PROFILE_SHA256 = "dae4b26bf9ba97f4e8a83facf8494adda7f45e3cd6f330929027e73a71c288a0"

EXPECTED_PROFILE_HANDLERS = {
    "Factory": [
        (
            "handlePoolCreated",
            "PoolCreated(address,address,uint24,int24,address)",
            "0x783cca1c0412dd0d695e784568c96da2e9c22ff989357a2e8b1d9b2b4e6b7118",
        )
    ],
    "Pool": [
        (
            "handleInitialize",
            "Initialize(uint160,int24)",
            "0x98636036cb66a9c19a37435efc1e90142190214e8abeb821bdba3f2990dd4c95",
        ),
        (
            "handleSwap",
            "Swap(address,address,int256,int256,uint160,uint128,int24)",
            "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67",
        ),
        (
            "handleMint",
            "Mint(address,address,int24,int24,uint128,uint256,uint256)",
            "0x7a53080ba414158be7ec69b987b5fb7d07dee101fe85488f0853ae16239d0bde",
        ),
        (
            "handleBurn",
            "Burn(address,int24,int24,uint128,uint256,uint256)",
            "0x0c396cd989a39f4459b5fa1aed6a9a8dcdbc45908acfd67e028cd568da98982c",
        ),
        (
            "handleCollect",
            "Collect(address,address,int24,int24,uint128,uint128)",
            "0x70935338e69775456a85ddef226c395fb668b63fa0115f5f20610b388e6ca9c0",
        ),
    ],
}

EXPECTED_BEHAVIOR_SOURCE_PATHS = [
    "config/matic/chain.ts",
    "src/common/backfill.ts",
    "src/common/constants.ts",
    "src/common/pricing.ts",
    "src/common/staticTokenDefinition.ts",
    "src/common/token.ts",
    "src/common/utils.ts",
    "src/v3/mappings/burn.ts",
    "src/v3/mappings/collect.ts",
    "src/v3/mappings/core.ts",
    "src/v3/mappings/factory.ts",
    "src/v3/mappings/initialize.ts",
    "src/v3/mappings/intervalUpdates.ts",
    "src/v3/mappings/mint.ts",
    "src/v3/mappings/swap.ts",
    "src/v3/mappings/tick.ts",
    "src/v3/mappings/utils.ts",
]
EXPECTED_BEHAVIOR_SOURCE_LOCK_SHA256 = (
    "6444ef3af35d15445a86056f65db9aca24c29d94e468e76c95f018609fcdb0aa"
)
EXPECTED_MARKET_SNAPSHOT = {
    "measured_at": "2026-08-31T17:20:00Z",
    "queries_24h": 386433,
    "query_fees_grt_24h": "471.970",
    "authority": "https://github.com/pinax-network/substreams-backfills/issues/83",
}

EXPECTED_REQUIRED_CHANGES = [
    "matic_chain_config_and_factory_start_block",
    "sixteen_entity_graph_out_with_bytes_ids_and_exact_nullability",
    "six_immutable_entity_physical_and_operation_order_support",
    "pool_collect_decode_transaction_tvl_fee_and_interval_semantics",
    "token_pool_count_zero_compatibility",
    "omit_position_snapshot_tick_windows_fee_growth_and_flash_writers",
    "matic_transaction_repeated_save_and_nonfatal_failure_fixtures",
    "exact_handler_save_order_blockchanges_and_poi_projection",
    "target_specific_package_module_hashes_and_initial_block",
    "matic_graph_node_logical_physical_vid_poi_and_postgresql_parity_certification",
]

EXPECTED_REMAINING_GATES = [
    "M0: fully account for both required clusters by inventorying every current copy or fresh structural absence proof; when viable healthy copies exist, independently select the minimum stable same-pod 24-hour ETA and minimum stable same-pod 72-hour ETA across all viable copies, which may be different copies, and require both minima to exceed 28 days or be non-converging; either minimum at or below 28 days stops implementation, compute, and load; with no viable copy, require fresh structural absence proof from both clusters.",
    "M2_ordered_blockchanges_generic_loader_and_release_contract",
    "M2_matic_physical_profile_and_loader_schema_metadata_proof",
    "M3_certified_qma8_factory_pool_handler_field_and_runtime_contract",
    "Matic_runtime_implementation_and_fixed_range_differential_parity",
    "Matic_physical_vid_poi_failure_and_postgresql_restore_certification",
    "paused_load_validation_and_separate_operational_activation_approval",
]

EXPECTED_TRUTH_BOUNDARY = {
    "static_target_layout_complete": True,
    "qma8_deployed_schema_diff_complete": True,
    "exact_source_transitive_closure_complete": True,
    "static_mapping_behavior_profile_complete": True,
    "reuse_assessment_static_only": True,
    "full_graph_node_runtime_handler_semantics_complete": False,
    "implementation_authorized": False,
    "eligibility_complete": False,
    "runtime_parity": False,
    "logical_parity": False,
    "physical_profile_complete": False,
    "physical_parity": False,
    "poi_parity": False,
    "target_graph_node_runtime_identity_bound": False,
    "backfill_ready": False,
    "production_ready": False,
}


def fail(message: str) -> None:
    raise ValueError(message)


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def load_json(path: Path) -> object:
    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                fail(f"duplicate JSON key in {path}: {key}")
            value[key] = item
        return value

    with path.open() as handle:
        return json.load(handle, object_pairs_hook=reject_duplicate_keys)


def repository_path(root: Path, value: object, label: str) -> Path:
    if not isinstance(value, str) or value.startswith("/") or ".." in Path(value).parts:
        fail(f"invalid repository path for {label}: {value!r}")
    path = (root / value).resolve()
    if root.resolve() not in path.parents:
        fail(f"repository path escapes root for {label}: {value}")
    return path


def cid_from_file(value: object) -> str:
    if not isinstance(value, dict) or set(value) != {"/"}:
        fail(f"unexpected IPFS file value: {value!r}")
    location = value["/"]
    if not isinstance(location, str) or not location.startswith("/ipfs/Qm"):
        fail(f"unexpected IPFS location: {location!r}")
    return location.removeprefix("/ipfs/")


def normalize_source_bytes(payload: bytes, normalization: str) -> bytes:
    if normalization == "identity":
        return payload
    if normalization == "remove_one_trailing_lf":
        if not payload.endswith(b"\n") or payload.endswith(b"\n\n"):
            fail("ABI normalization requires exactly one vendored trailing LF")
        return payload[:-1]
    fail(f"unknown normalization: {normalization}")


def verify_artifact_lock(root: Path, lock: dict[str, object]) -> dict[str, dict[str, object]]:
    records = lock.get("artifact_lock")
    if not isinstance(records, list):
        fail("artifact_lock must be a list")

    by_role: dict[str, dict[str, object]] = {}
    for record in records:
        if not isinstance(record, dict):
            fail("artifact record must be an object")
        role = record.get("role")
        cid = record.get("cid")
        if not isinstance(role, str) or role in by_role:
            fail(f"duplicate or invalid artifact role: {role!r}")
        if not isinstance(cid, str) or not cid.startswith("Qm"):
            fail(f"invalid CID for {role}: {cid!r}")
        by_role[role] = record

        vendored_path = record.get("vendored_path")
        if vendored_path is None:
            for required in ("source_bytes", "source_sha256"):
                if required not in record:
                    fail(f"unvendored {role} is missing {required}")
            continue
        if not isinstance(vendored_path, str):
            fail(f"invalid vendored path for {role}")
        path = repository_path(root, vendored_path, role)
        payload = path.read_bytes()
        if len(payload) != record.get("vendored_bytes"):
            fail(f"vendored byte count drift for {role}")
        if sha256(payload) != record.get("vendored_sha256"):
            fail(f"vendored digest drift for {role}")

        source_payload = normalize_source_bytes(payload, str(record.get("normalization")))
        if len(source_payload) != record.get("source_bytes"):
            fail(f"source byte count drift for {role}")
        if sha256(source_payload) != record.get("source_sha256"):
            fail(f"source digest drift for {role}")
        if role.endswith("_abi"):
            json.loads(source_payload)

    expected_roles = {
        "deployment",
        "schema",
        "factory_abi",
        "erc20_abi",
        "erc20_symbol_bytes_abi",
        "erc20_name_bytes_abi",
        "pool_abi",
        "factory_mapping_wasm",
        "pool_mapping_wasm",
    }
    if set(by_role) != expected_roles:
        fail(f"artifact roles drift: {sorted(set(by_role) ^ expected_roles)}")
    return by_role


def normalize_event(event: str) -> str:
    return re.sub(r"\s+", "", event)


def abi_contract(mapping: dict[str, object]) -> list[tuple[str, str]]:
    entries = mapping.get("abis")
    if not isinstance(entries, list):
        fail("mapping ABI contract must be a list")
    return [(str(entry.get("name")), cid_from_file(entry.get("file"))) for entry in entries]


def verify_manifest(root: Path, lock: dict[str, object], artifacts: dict[str, dict[str, object]]) -> None:
    path = root / str(artifacts["deployment"]["vendored_path"])
    manifest = yaml.safe_load(path.read_text())
    deployment = lock["deployment"]

    if deployment.get("data_sources") != ["Factory"] or deployment.get("templates") != ["Pool"]:
        fail("deployment component inventory drift")
    if deployment.get("features") != ["nonFatalErrors", "grafting"]:
        fail("deployment feature lock drift")
    if deployment.get("position_manager") is not False or deployment.get("flash_handler") is not False:
        fail("deployment absence contract drift")

    if manifest.get("specVersion") != deployment["spec_version"]:
        fail("manifest specVersion drift")
    if manifest.get("repository") != "https://github.com/Uniswap/uniswap-v3-subgraph":
        fail("manifest source repository drift")
    if manifest.get("features") != ["nonFatalErrors", "grafting"]:
        fail("manifest feature contract drift")
    if "graft" in manifest:
        fail("target manifest unexpectedly gained a concrete graft")
    if cid_from_file(manifest["schema"]["file"]) != EXPECTED_SCHEMA:
        fail("manifest schema CID drift")

    data_sources = manifest.get("dataSources")
    templates = manifest.get("templates")
    if not isinstance(data_sources, list) or len(data_sources) != 1:
        fail("expected exactly one Factory data source")
    if not isinstance(templates, list) or len(templates) != 1:
        fail("expected exactly one Pool template")

    factory = data_sources[0]
    factory_mapping = factory["mapping"]
    if (
        factory.get("name") != "Factory"
        or factory.get("network") != "matic"
        or factory.get("kind") != "ethereum/contract"
    ):
        fail("Factory data-source identity drift")
    if factory["source"] != {
        "abi": "Factory",
        "address": deployment["factory"],
        "startBlock": deployment["start_block"],
    }:
        fail("Factory source contract drift")
    if factory_mapping.get("apiVersion") != deployment["mapping_api_version"]:
        fail("Factory mapping apiVersion drift")
    if (
        factory_mapping.get("kind") != "ethereum/events"
        or factory_mapping.get("language") != "wasm/assemblyscript"
        or factory_mapping.get("entities") != ["Pool", "Token"]
    ):
        fail("Factory mapping shape drift")
    if abi_contract(factory_mapping) != [
        ("Factory", artifacts["factory_abi"]["cid"]),
        ("ERC20", artifacts["erc20_abi"]["cid"]),
        ("ERC20SymbolBytes", artifacts["erc20_symbol_bytes_abi"]["cid"]),
        ("ERC20NameBytes", artifacts["erc20_name_bytes_abi"]["cid"]),
        ("Pool", artifacts["pool_abi"]["cid"]),
    ]:
        fail("Factory ABI inventory drift")
    if cid_from_file(factory_mapping["file"]) != artifacts["factory_mapping_wasm"]["cid"]:
        fail("Factory mapping CID drift")
    factory_handlers = factory_mapping.get("eventHandlers")
    if not isinstance(factory_handlers, list) or [entry.get("handler") for entry in factory_handlers] != [
        "handlePoolCreated"
    ]:
        fail("Factory handler contract drift")
    if normalize_event(factory_handlers[0].get("event", "")) != normalize_event(
        "PoolCreated(indexed address,indexed address,indexed uint24,int24,address)"
    ):
        fail("Factory event signature drift")

    pool = templates[0]
    pool_mapping = pool["mapping"]
    if (
        pool.get("name") != "Pool"
        or pool.get("network") != "matic"
        or pool.get("kind") != "ethereum/contract"
    ):
        fail("Pool template identity drift")
    if pool.get("source") != {"abi": "Pool"}:
        fail("Pool source contract drift")
    if pool_mapping.get("apiVersion") != deployment["mapping_api_version"]:
        fail("Pool mapping apiVersion drift")
    if (
        pool_mapping.get("kind") != "ethereum/events"
        or pool_mapping.get("language") != "wasm/assemblyscript"
        or pool_mapping.get("entities") != ["Pool", "Token"]
    ):
        fail("Pool mapping shape drift")
    if abi_contract(pool_mapping) != [
        ("Pool", artifacts["pool_abi"]["cid"]),
        ("Factory", artifacts["factory_abi"]["cid"]),
        ("ERC20", artifacts["erc20_abi"]["cid"]),
    ]:
        fail("Pool ABI inventory drift")
    if cid_from_file(pool_mapping["file"]) != artifacts["pool_mapping_wasm"]["cid"]:
        fail("Pool mapping CID drift")

    expected_handlers = [
        "handleInitialize",
        "handleSwap",
        "handleMint",
        "handleBurn",
        "handleCollect",
    ]
    handlers = pool_mapping.get("eventHandlers")
    if not isinstance(handlers, list) or [entry.get("handler") for entry in handlers] != expected_handlers:
        fail("Pool handler order or set drift")
    if any(entry.get("handler") == "handleFlash" for entry in handlers):
        fail("target manifest unexpectedly gained Flash")

    expected_events = [
        "Initialize(uint160,int24)",
        "Swap(indexed address,indexed address,int256,int256,uint160,uint128,int24)",
        "Mint(address,indexed address,indexed int24,indexed int24,uint128,uint256,uint256)",
        "Burn(indexed address,indexed int24,indexed int24,uint128,uint256,uint256)",
        "Collect(indexed address,address,indexed int24,indexed int24,uint128,uint128)",
    ]
    if [normalize_event(entry["event"]) for entry in handlers] != [
        normalize_event(event) for event in expected_events
    ]:
        fail("Pool event signatures drift")


def parse_schema(path: Path) -> tuple[dict[str, dict[str, str]], set[str], set[str]]:
    entities: dict[str, dict[str, str]] = {}
    immutable: set[str] = set()
    mutable: set[str] = set()
    current: str | None = None

    declaration_pattern = re.compile(
        r"^type\s+([_A-Za-z][_0-9A-Za-z]*)\s+@entity\s*"
        r"(?:\(immutable:\s*(true|false)\))?\s*\{"
    )
    for raw_line in path.read_text().splitlines():
        line = raw_line.split("#", 1)[0].strip()
        declaration = declaration_pattern.match(line)
        if declaration:
            current = declaration.group(1)
            entities[current] = {}
            if declaration.group(2) == "true":
                immutable.add(current)
            else:
                mutable.add(current)
            continue
        if current and line == "}":
            current = None
            continue
        if current:
            field = re.match(r"^([_A-Za-z][_0-9A-Za-z]*)\s*:\s*([\[\]!_A-Za-z0-9]+)", line)
            if field:
                entities[current][field.group(1)] = field.group(2)
    return entities, immutable, mutable


def logical_hash(entities: dict[str, dict[str, str]]) -> str:
    payload = json.dumps(entities, sort_keys=True, separators=(",", ":"))
    return sha256(payload.encode())


def contract_diff(
    matic: dict[str, dict[str, str]], qma8: dict[str, dict[str, str]]
) -> tuple[list[str], list[str], list[str], dict[str, dict[str, object]]]:
    missing = sorted(set(qma8) - set(matic))
    extra = sorted(set(matic) - set(qma8))
    exact = sorted(entity for entity in set(matic) & set(qma8) if matic[entity] == qma8[entity])
    differences: dict[str, dict[str, object]] = {}
    for entity in sorted(set(matic) & set(qma8)):
        matic_fields = matic[entity]
        qma8_fields = qma8[entity]
        missing_fields = sorted(set(qma8_fields) - set(matic_fields))
        extra_fields = sorted(set(matic_fields) - set(qma8_fields))
        type_differences = {
            field: {
                "matic_type": matic_fields[field],
                "qma8_type": qma8_fields[field],
                "matic_non_null": matic_fields[field].endswith("!"),
                "qma8_non_null": qma8_fields[field].endswith("!"),
            }
            for field in sorted(set(matic_fields) & set(qma8_fields))
            if matic_fields[field] != qma8_fields[field]
        }
        if missing_fields or extra_fields or type_differences:
            differences[entity] = {
                "missing_from_matic": missing_fields,
                "extra_in_matic": extra_fields,
                "type_differences": type_differences,
            }
    return missing, extra, exact, differences


def verify_repository_records(
    root: Path,
    records: object,
    expected: list[dict[str, object]],
    label: str,
) -> None:
    if records != expected:
        fail(f"{label} inventory or lock drift")
    for record in expected:
        payload = repository_path(root, record["path"], str(record["role"])).read_bytes()
        if len(payload) != record["bytes"] or sha256(payload) != record["sha256"]:
            fail(f"{label} payload drift: {record['role']}")


def verify_qma8_reference(root: Path, lock: dict[str, object]) -> dict[str, object]:
    reference = lock.get("qma8_reference")
    if not isinstance(reference, dict) or reference.get("family") != "uniswap-v3-mainnet-base":
        fail("Qma8 family reference drift")
    deployed = reference.get("deployed_schema")
    expected_deployed = {
        "cid": EXPECTED_QMA8_SCHEMA,
        "path": (
            "uniswap-v3/graft-ancestry/v1/artifacts/"
            "Qma8a81T9XoX5Pbkrk8J3kxMhWdXJzFSYZge1wGi3QZBru"
        ),
        "bytes": 19034,
        "sha256": "ae03d0c6d3c6c03f87ae8e699b1e71804266c1d4adb7acbf4f4de5d48727c39c",
        "entity_count": 20,
        "logical_sha256": "6c801fc4c141c0ae12dbb937652f0dd49c9be5bd3b1b3c8e38bdb92fe6efec5d",
        "immutable_entities": [],
    }
    if deployed != expected_deployed:
        fail("retained Qma8 deployed-schema identity drift")
    deployed_payload = repository_path(root, deployed["path"], "Qma8 deployed schema").read_bytes()
    if len(deployed_payload) != deployed["bytes"] or sha256(deployed_payload) != deployed["sha256"]:
        fail("retained Qma8 deployed-schema payload drift")

    upstream = reference.get("upstream_source")
    if not isinstance(upstream, dict) or {
        key: upstream.get(key) for key in ("repository", "commit", "tree")
    } != {
        "repository": "pinax-network/substreams-uniswap-v3",
        "commit": "42c7b15345e6df80561b694e52a0eb622b374b96",
        "tree": "a00e882e92d07b46550b74dea279c114d57631ac",
    }:
        fail("Qma8 upstream source identity drift")
    expected_upstream_records = [
        {
            "role": "upstream_provenance",
            "path": "docs/provenance/uniswap-v3-qma8a81t-parity.json",
            "bytes": 3134,
            "sha256": "aafc43562e8867b0e40cfc905065aad14dc72227b7b937d1cf7ccbf6eb8457a8",
        },
        {
            "role": "upstream_file_inventory",
            "path": "docs/provenance/uniswap-v3-qma8a81t-parity-files.json",
            "bytes": 18035,
            "sha256": "177a98f60f230d1b13dfa064f3b98a50163a506d2c7a08432330d47ee2170e60",
        },
        {
            "role": "imported_schema",
            "path": "uniswap-v3/source/schema.graphql",
            "bytes": 18883,
            "sha256": "f234a0e4dc88c923d6ad28a3fcd1ed6093351bd2221d7c18486f0cbde41bb52c",
        },
        {
            "role": "imported_module_graph",
            "path": "uniswap-v3/source/substreams.yaml",
            "bytes": 11178,
            "sha256": "74489e3056ff18760b3cd416fb10558f7fec1481a441b596e2b1e0f526c879a5",
        },
    ]
    verify_repository_records(root, upstream.get("records"), expected_upstream_records, "Qma8 upstream")
    upstream_provenance = load_json(root / "docs/provenance/uniswap-v3-qma8a81t-parity.json")
    if not isinstance(upstream_provenance, dict):
        fail("Qma8 upstream provenance must be an object")
    if upstream_provenance.get("source", {}).get("commit") != upstream["commit"]:
        fail("Qma8 upstream provenance commit drift")
    if upstream_provenance.get("source", {}).get("tree") != upstream["tree"]:
        fail("Qma8 upstream provenance tree drift")
    if upstream_provenance.get("target_schema", {}).get("raw_sha256") != deployed["sha256"]:
        fail("Qma8 upstream provenance target-schema binding drift")

    expected_m3_records = [
        {
            "role": "graft_ancestry",
            "path": "uniswap-v3/graft-ancestry/v2/contract.json",
            "bytes": 541804,
            "sha256": "ae8c3e0099fedf2879b3071c2bcf545050fa4d448d0154fa6b895618bb8e203e",
        },
        {
            "role": "writer_compatibility",
            "path": "uniswap-v3/graft-ancestry/v2/writer-compatibility.json",
            "bytes": 517362,
            "sha256": "259481724561d5aa725c17f90b5a19ea93ad6f7cd6074cf2cb8a8661c39f81c4",
        },
        {
            "role": "segment_writer_matrix",
            "path": "uniswap-v3/segment-writer-matrix/v1/contract.json",
            "bytes": 2785821,
            "sha256": "7f6d1a34a8c885fe5ddcd81895818ba7ae8a0d736d541b881c1cc7cd54275161",
        },
        {
            "role": "execution_order",
            "path": "uniswap-v3/execution-order/v1/contract.json",
            "bytes": 22216,
            "sha256": "241e970cfcec4d76610b29a10141d3bff2512d80454a6308594f3db23621cde2",
        },
        {
            "role": "writer_runtime",
            "path": "uniswap-v3/writer-runtime/contract-v1.json",
            "bytes": 6247,
            "sha256": "765806bf19fca7695ef4d97f557593e4f791759589fe55c20f18c6523a5d07ca",
        },
        {
            "role": "segment_profiles",
            "path": "uniswap-v3/writer-runtime/segment-profiles-v1.json",
            "bytes": 12989,
            "sha256": "2b6635c061a7a0bfce39430c71c41dacc1567f095fe41134e890a697aa27f823",
        },
        {
            "role": "mainnet_chain_config",
            "path": "uniswap-v3/chain-config/configs/mainnet-v1.json",
            "bytes": 3503,
            "sha256": "30f5caf9ee8906a8886dc103e55286b9d5b6dbd8784d1c97d21b9a38b266bb55",
        },
    ]
    verify_repository_records(
        root, reference.get("m3_contract_closure"), expected_m3_records, "Qma8 M3 closure"
    )
    if reference.get("authority") != {
        "deployed_schema_is_layout_authority": True,
        "imported_source_schema_is_mutability_authority": False,
        "contract_closure_hashes_imply_m3_certification": False,
        "target_graph_node_runtime_identity_bound": False,
    }:
        fail("Qma8 reference authority boundary drift")

    false_truth_claims = {
        "graft_ancestry": [
            "boundary_state_continuity_complete",
            "field_writer_audit_complete",
            "logical_oracle_complete",
            "physical_parity_complete",
            "poi_parity_complete",
            "production_ready",
        ],
        "writer_compatibility": [
            "backfill_ready",
            "factory_pool_full_field_writer_semantics_complete",
            "full_handler_semantics_complete",
            "logical_oracle_complete",
            "physical_parity_complete",
            "poi_parity_complete",
            "production_ready",
            "runtime_population_complete",
            "target_graph_node_runtime_identity_bound",
        ],
        "segment_writer_matrix": [
            "backfill_ready",
            "field_writer_semantics_complete",
            "full_handler_semantics_complete",
            "logical_parity_complete",
            "physical_parity_complete",
            "poi_parity_complete",
            "production_ready",
            "runtime_population_complete",
            "target_graph_node_runtime_identity_bound",
        ],
        "execution_order": [
            "backfill_allowed",
            "combined_handler_order_implemented",
            "physical_parity_complete",
            "poi_parity_complete",
            "production_ready",
            "runtime_consumes_contract",
            "target_runtime_identity_bound",
        ],
        "writer_runtime": [
            "backfill_ready",
            "graph_out_replaced",
            "logical_oracle_complete",
            "physical_parity_complete",
            "poi_parity_complete",
            "production_ready",
            "runtime_population_complete",
        ],
    }
    by_role = {str(record["role"]): record for record in expected_m3_records}
    for role, claims in false_truth_claims.items():
        contract = load_json(root / str(by_role[role]["path"]))
        if not isinstance(contract, dict) or not isinstance(contract.get("truth_boundary"), dict):
            fail(f"Qma8 M3 truth boundary missing: {role}")
        if any(contract["truth_boundary"].get(claim) is not False for claim in claims):
            fail(f"Qma8 M3 truth boundary was promoted: {role}")
    return deployed


def verify_schema(
    root: Path,
    lock: dict[str, object],
    artifacts: dict[str, dict[str, object]],
    qma8_reference: dict[str, object],
) -> None:
    contract = lock["logical_contract"]
    matic, immutable, mutable = parse_schema(
        repository_path(root, artifacts["schema"]["vendored_path"], "Matic schema")
    )
    qma8, qma8_immutable, qma8_mutable = parse_schema(
        repository_path(root, qma8_reference["path"], "Qma8 deployed schema")
    )

    if sorted(matic) != contract["entities"] or len(matic) != contract["entity_count"]:
        fail("Matic entity set drift")
    if logical_hash(matic) != contract["logical_sha256"]:
        fail("Matic logical schema digest drift")
    if sorted(immutable) != contract["immutable_entities"]:
        fail("Matic immutable entity contract drift")
    if sorted(mutable) != contract["mutable_entities"]:
        fail("Matic mutable entity contract drift")
    if len(qma8) != contract["qma8_entity_count"] or logical_hash(qma8) != contract["qma8_logical_sha256"]:
        fail("Qma8 logical reference drift")
    if sorted(qma8_immutable) != contract["qma8_immutable_entities"]:
        fail("Qma8 deployed mutability reference drift")
    if len(qma8_mutable) != len(qma8):
        fail("Qma8 deployed schema must remain all mutable")

    missing, extra, exact, differences = contract_diff(matic, qma8)
    if missing != contract["missing_from_matic"]:
        fail("Matic missing-entity gap list drift")
    if extra != contract["extra_in_matic"]:
        fail("Matic extra-entity gap list drift")
    if exact != contract["exact_field_match_entities"]:
        fail("Matic exact-field entity list drift")
    if sorted(immutable - qma8_immutable) != contract["immutable_in_matic_but_mutable_in_qma8"]:
        fail("Matic-to-Qma8 immutable/mutable gap drift")
    if sorted(qma8_immutable - immutable) != contract["mutable_in_matic_but_immutable_in_qma8"]:
        fail("Qma8-to-Matic immutable/mutable gap drift")
    if differences != contract["field_differences"]:
        fail("Matic field/type/nullability gap list drift")
    if contract.get("scope") != (
        "static_deployed_schema_only_pending_runtime_physical_and_poi_comparison"
    ):
        fail("Matic/Qma8 schema comparison scope drift")

    imported, imported_immutable, _ = parse_schema(root / "uniswap-v3/source/schema.graphql")
    if logical_hash(imported) != logical_hash(qma8):
        fail("Qma8 imported source logical schema drift")
    if sorted(imported_immutable) != ["Burn", "Mint", "Swap", "Transaction"]:
        fail("Qma8 imported source mutability boundary drift")


def verify_profile(
    root: Path,
    lock: dict[str, object],
    artifacts: dict[str, dict[str, object]],
    qma8_reference: dict[str, object],
) -> None:
    profile_payload = repository_path(root, str(PROFILE_PATH), "Matic layout profile").read_bytes()
    if len(profile_payload) != EXPECTED_PROFILE_BYTES or sha256(profile_payload) != EXPECTED_PROFILE_SHA256:
        fail("machine-readable Matic layout profile digest drift")
    if lock.get("layout_profile") != {
        "path": str(PROFILE_PATH),
        "bytes": EXPECTED_PROFILE_BYTES,
        "sha256": EXPECTED_PROFILE_SHA256,
    }:
        fail("Matic layout profile provenance lock drift")
    profile = load_json(root / PROFILE_PATH)
    if not isinstance(profile, dict):
        fail("Matic layout profile must be an object")
    if (
        profile.get("format_version") != 1
        or profile.get("profile_id") != "uniswap-v3-matic-QmWqwrVt"
        or profile.get("status") != "static_target_layout_and_exact_source_behavior_profile_only"
        or profile.get("implementation_status") != "not_started"
        or profile.get("runtime_parity") is not False
        or profile.get("eligibility_decision") != "indeterminate_no_fresh_evidence"
        or profile.get("family") != "uniswap-v3-matic"
        or profile.get("chain") != "matic"
    ):
        fail("Matic layout profile identity or static-only status drift")
    if profile.get("deployment") != {
        "cid": EXPECTED_DEPLOYMENT,
        "spec_version": "0.0.4",
        "mapping_api_version": "0.0.7",
        "factory_start_block": 22757547,
        "graft": None,
        "features": ["nonFatalErrors", "grafting"],
    }:
        fail("Matic layout profile deployment contract drift")

    expected_component_contracts = {
        "Factory": {
            "kind": "data_source",
            "address": "0x1f98431c8ad98523631ae4a59f267346ea31f984",
            "start_block": 22757547,
            "mapping_cid": artifacts["factory_mapping_wasm"]["cid"],
        },
        "Pool": {
            "kind": "template",
            "created_by": "Factory.handlePoolCreated",
            "mapping_cid": artifacts["pool_mapping_wasm"]["cid"],
        },
    }
    components = profile.get("components")
    if (
        not isinstance(components, list)
        or not all(isinstance(item, dict) for item in components)
        or [item.get("name") for item in components] != ["Factory", "Pool"]
    ):
        fail("Matic layout profile component inventory or order drift")
    for component in components:
        name = str(component.get("name"))
        handlers = component.get("handlers")
        contract = {key: value for key, value in component.items() if key not in {"name", "handlers"}}
        if contract != expected_component_contracts[name]:
            fail(f"Matic profile component contract drift: {name}")
        if not isinstance(handlers, list) or [
            (handler.get("name"), handler.get("signature"), handler.get("topic0"))
            for handler in handlers
            if isinstance(handler, dict)
        ] != EXPECTED_PROFILE_HANDLERS[name]:
            fail(f"Matic profile handler/topic contract drift: {name}")

    logical = lock["logical_contract"]
    if profile.get("entity_layout") != {
        "entity_count": logical["entity_count"],
        "logical_sha256": logical["logical_sha256"],
        "entities": logical["entities"],
        "immutable_entities": logical["immutable_entities"],
        "mutable_entities": logical["mutable_entities"],
        "bytes_id_entities": ["Pool", "Token"],
        "flash_schema_present": True,
        "flash_handler_present": False,
    }:
        fail("Matic profile entity-layout contract drift")
    if profile.get("qma8_deployed_reference") != {
        "schema_cid": qma8_reference["cid"],
        "schema_path": qma8_reference["path"],
        "schema_bytes": qma8_reference["bytes"],
        "schema_sha256": qma8_reference["sha256"],
        "entity_count": qma8_reference["entity_count"],
        "logical_sha256": qma8_reference["logical_sha256"],
        "immutable_entities": qma8_reference["immutable_entities"],
        "authority": (
            "retained_deployed_schema_for_entity_field_type_nullability_and_mutability"
        ),
        "imported_source_schema_is_mutability_authority": False,
    }:
        fail("Matic profile Qma8 deployed reference drift")
    if profile.get("qma8_static_gap") != {
        "comparison_direction": "bidirectional_matic_and_retained_qma8_deployed_schema",
        "missing_from_matic": logical["missing_from_matic"],
        "extra_in_matic": logical["extra_in_matic"],
        "immutable_in_matic_but_mutable_in_qma8": logical[
            "immutable_in_matic_but_mutable_in_qma8"
        ],
        "mutable_in_matic_but_immutable_in_qma8": logical[
            "mutable_in_matic_but_immutable_in_qma8"
        ],
        "exact_field_match_entities": logical["exact_field_match_entities"],
        "field_differences": logical["field_differences"],
        "scope": "static_deployed_schema_only_pending_runtime_physical_and_poi_comparison",
    }:
        fail("Matic profile bidirectional Qma8 static gap drift")

    expected_mapping_behavior = {
        "evidence": (
            "byte_exact_mapping_reproduction_plus_digest_bound_exact_source_transitive_closure"
        ),
        "factory_pool_created": {
            "pool_id": "pool_address_bytes",
            "token_ids": "token_address_bytes",
            "factory_entity_id": "lowercase_factory_address_hex",
            "bundle_entity_id": "1",
            "factory_pool_count_increment": 1,
            "token_pool_count_on_creation": 0,
            "token_pool_count_incremented": False,
            "dynamic_pool_template_created": True,
            "skip_pools": [],
            "pool_mappings": [],
            "missing_token_decimals_behavior": (
                "return_without_pool_token_or_factory_saves; a newly-created Bundle may "
                "already have been saved"
            ),
            "save_order": ["Pool", "PoolTemplate.create", "Token0", "Token1", "Factory"],
        },
        "initialize": {
            "updates": [
                "Pool.sqrtPrice",
                "Pool.tick",
                "Bundle.ethPriceUSD",
                "PoolDayData",
                "PoolHourData",
                "Token0.derivedETH",
                "Token1.derivedETH",
            ],
            "pool_saved_before_bundle_and_interval_updates": True,
        },
        "mint": {
            "active_liquidity_condition": "tickLower_le_pool_tick_and_tickUpper_gt_pool_tick",
            "pool_and_token_tvl_delta": "add_amounts",
            "tick_liquidity_delta": (
                "lower_gross_and_net_plus; upper_gross_plus_and_net_minus"
            ),
            "emits": ["Transaction", "Mint"],
        },
        "burn": {
            "active_liquidity_condition": "tickLower_le_pool_tick_and_tickUpper_gt_pool_tick",
            "pool_and_token_tvl_delta": "none_until_collect",
            "tick_liquidity_delta": (
                "lower_gross_and_net_minus; upper_gross_minus_and_net_plus"
            ),
            "emits": ["Transaction", "Burn"],
        },
        "swap": {
            "ignored_pool": "0x9663f2ca0454accad3e094448ea6f77443880454",
            "amounts": "signed_pool_tvl_deltas_and_absolute_volume_amounts",
            "tracked_volume_divisor": 2,
            "untracked_volume_divisor": 2,
            "lp_fee_formula": "tracked_volume_times_fee_tier_div_1000000",
            "pool_saved_before_bundle_price_and_derived_token_price_updates": True,
            "emits": ["Transaction", "Swap"],
        },
        "collect": {
            "component": "Pool",
            "pool_and_token_tvl_delta": "subtract_collected_amounts",
            "collected_fee_aggregates": [
                "Pool.collectedFeesToken0",
                "Pool.collectedFeesToken1",
                "Pool.collectedFeesUSD",
            ],
            "transaction_saved_before_token_presence_check": True,
            "missing_token_behavior": "return_after_transaction_save",
            "emits": ["Transaction", "Collect"],
        },
        "transactions": {
            "id": "lowercase_transaction_hash_hex",
            "helper_saves_on_every_mint_burn_swap_or_collect_call": True,
            "gas_used": "0",
            "gas_price": "event.transaction.gasPrice",
            "immutable_target_entity": True,
            "same_transaction_multi_event_runtime_effect_certified": False,
        },
        "intervals": [
            "uniswap_day",
            "pool_day",
            "pool_hour",
            "token_day",
            "token_hour",
        ],
        "operation_order": {
            "helper_functions_save_entities_internally": True,
            "swap_repeats_pool_hour_save": True,
            "ordered_store_operations_required_for_poi": True,
            "coalesced_final_entity_changes_sufficient": False,
        },
        "writer_absence": {
            "position_manager_component_absent": True,
            "position_entities_absent": ["Position", "PositionSnapshot"],
            "tick_window_entities_absent": ["TickDayData", "TickHourData"],
            "flash_handler_absent": True,
            "flash_entity_static_writer_absent": True,
            "runtime_population_certified": False,
        },
    }
    if profile.get("mapping_behavior") != expected_mapping_behavior:
        fail("Matic exact-source mapping behavior contract drift")

    chain = lock["exact_source"]["chain_configuration"]
    if profile.get("chain_configuration") != {
        "reference_token": str(chain["reference_token"]).lower(),
        "stable_token_pool": str(chain["stable_token_pool"]).lower(),
        "minimum_native_locked": chain["minimum_native_locked"],
        "whitelist_tokens": chain["whitelist_tokens"],
        "stable_coins": chain["stable_coins"],
        "skip_pools": [],
        "pool_mappings": [],
        "static_token_definitions": [],
    }:
        fail("Matic profile chain configuration drift")

    expected_reuse = {
        "scope": "static_source_comparison_only",
        "certified_unchanged": [],
        "candidate_reuse_without_internal_algorithm_change": [
            {
                "component": "raw_firehose_block_transport",
                "dependency": "M2 ordered BlockChanges protocol and engine contract",
            },
            {
                "component": (
                    "Factory PoolCreated and Pool Initialize/Swap/Mint/Burn ABI decoders"
                ),
                "dependency": (
                    "Matic address routing, canonical ordinal fixtures, and target package tests"
                ),
            },
            {
                "component": "store_pools_created",
                "dependency": "Matic map_pools_created adapter and ERROR_POOL removal",
            },
            {
                "component": "store_pool_count",
                "dependency": "Matic factory identity and PoolCreated acceptance parity",
            },
            {
                "component": "store_pool_sqrt_price",
                "dependency": "Matic event extraction and Initialize/Swap ordinal parity",
            },
            {
                "component": "decimal conversion and sqrt-price math",
                "dependency": (
                    "Graph Node decimal normalization and fixed-range differential fixtures"
                ),
            },
        ],
        "target_adapter_required": [
            "map_pools_created token RPC failure and metadata fallback behavior",
            "whitelist pool derivation and Matic pricing configuration",
            "pool liquidity and derived TVL routing",
            "day/hour window creation, update, save order, and retention behavior",
            "target initial block and manifest/package configuration",
        ],
        "target_specific_replacement_required": [
            "map_extract_data_types must include Pool Collect and exclude NPM/Flash-only paths",
            "store_tokens must preserve Token.poolCount at zero instead of incrementing per pool",
            "transaction and total tx-count behavior must include Matic Pool Collect ordering",
            "swap volume, fee, TVL, and interval aggregation must reproduce the exact Matic mapping",
            "tick storage must omit TickDayData/TickHourData and the eleven absent Tick fields",
            "graph_out must emit the 16-entity Bytes-ID and six-immutable-entity layout",
        ],
        "components_to_omit": [
            "NonfungiblePositionManager routing",
            "Position and PositionSnapshot reducers",
            "TickDayData and TickHourData writers",
            "Pool fee-growth-global writers",
            "Flash handler and Flash row emission",
        ],
        "reuse_certified": False,
    }
    if profile.get("reuse_assessment") != expected_reuse:
        fail("Matic static reuse assessment drift")

    if profile.get("dependencies") != {
        "m2_generic_runtime": [
            "ordered BlockChanges family-to-engine protocol replacing common/src/lib.rs placeholder",
            "legacy schema profile support for Bytes versus ID, nullability, and immutable tables",
            "Graph Node metadata, VID, block-range, block$, decimal, PoI, and failure semantics",
            "target physical-profile capture and certification harness",
            "fail-closed paused load and resume/checkpoint lifecycle",
        ],
        "m3_qma8_artifacts": [
            "uniswap-v3/graft-ancestry/v2/contract.json",
            "uniswap-v3/graft-ancestry/v2/writer-compatibility.json",
            "uniswap-v3/segment-writer-matrix/v1/contract.json",
            "uniswap-v3/execution-order/v1/contract.json",
            "uniswap-v3/writer-runtime/contract-v1.json",
            "uniswap-v3/writer-runtime/segment-profiles-v1.json",
            "uniswap-v3/chain-config/configs/mainnet-v1.json",
        ],
        "m3_required_truth": [
            "full Factory and Pool handler/field writer semantics",
            "runtime population and required-absence oracle",
            "boundary continuity and fixed-range logical parity",
            "target Graph Node runtime identity, physical history, VID, PoI, and failure behavior",
        ],
    }:
        fail("Matic M2/M3 dependency contract drift")
    if profile.get("required_target_changes") != EXPECTED_REQUIRED_CHANGES:
        fail("Matic required target-change inventory drift")
    if profile.get("truth_boundary") != EXPECTED_TRUTH_BOUNDARY:
        fail("Matic profile truth boundary drift")
    if profile.get("remaining_gates") != EXPECTED_REMAINING_GATES:
        fail("Matic profile remaining-gate contract drift")


def verify_source_pin(lock: dict[str, object], artifacts: dict[str, dict[str, object]]) -> None:
    source = lock.get("exact_source")
    if not isinstance(source, dict):
        fail("exact_source must be an object")
    if source.get("status") != EXPECTED_SOURCE_STATUS:
        fail("Matic source must remain bound to the exact reproduction")
    if source.get("repository") != "https://github.com/Uniswap/v3-subgraph":
        fail("exact source repository drift")
    if source.get("earliest_exact_commit") != EXPECTED_SOURCE_COMMIT:
        fail("earliest exact source commit drift")
    if source.get("tree") != EXPECTED_SOURCE_TREE:
        fail("exact source tree drift")
    for key in ("earliest_exact_commit", "mainline_equivalent_commit", "tree"):
        if not re.fullmatch(r"[0-9a-f]{40}", str(source.get(key, ""))):
            fail(f"invalid exact source {key}")

    build = source.get("build")
    if not isinstance(build, dict) or build.get("result") != "byte_exact_to_deployed_mapping_objects":
        fail("exact source build result drift")
    for prefix, role in (
        ("factory", "factory_mapping_wasm"),
        ("pool", "pool_mapping_wasm"),
    ):
        if build.get(f"{prefix}_wasm_bytes") != artifacts[role]["source_bytes"]:
            fail(f"{prefix} exact source byte count drift")
        if build.get(f"{prefix}_wasm_sha256") != artifacts[role]["source_sha256"]:
            fail(f"{prefix} exact source digest drift")

    toolchain = source.get("toolchain")
    if toolchain != {
        "reference_node": "18.18.0",
        "reference_corepack": "0.19.0",
        "yarn": "1.22.22",
        "graph_cli": "0.64.1",
        "graph_ts": "0.38.1",
        "assemblyscript_root": "0.19.23",
        "assemblyscript_graph_ts_nested": "0.27.31",
    }:
        fail("exact source toolchain drift")

    source_files = source.get("source_files")
    if not isinstance(source_files, list) or len(source_files) != 6:
        fail("exact source file lock drift")
    if {entry.get("path") for entry in source_files if isinstance(entry, dict)} != {
        "package.json",
        "yarn.lock",
        "script/build.ts",
        "config/matic/chain.ts",
        "config/matic/config.json",
        "src/v3/schema.graphql",
    }:
        fail("exact source file inventory drift")
    for entry in source_files:
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("path"), str)
            or not isinstance(entry.get("bytes"), int)
            or not re.fullmatch(r"[0-9a-f]{64}", str(entry.get("sha256", "")))
        ):
            fail("invalid exact source build-input record")

    behavior_files = source.get("behavior_source_files")
    if (
        not isinstance(behavior_files, list)
        or [entry.get("path") for entry in behavior_files if isinstance(entry, dict)]
        != EXPECTED_BEHAVIOR_SOURCE_PATHS
    ):
        fail("exact source behavior closure inventory or order drift")
    behavior_lock_payload = json.dumps(
        behavior_files, sort_keys=True, separators=(",", ":")
    ).encode()
    if sha256(behavior_lock_payload) != EXPECTED_BEHAVIOR_SOURCE_LOCK_SHA256:
        fail("exact source behavior closure lock drift")
    for entry in behavior_files:
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("bytes"), int)
            or not re.fullmatch(r"[0-9a-f]{64}", str(entry.get("sha256", "")))
            or not re.fullmatch(r"[0-9a-f]{40}", str(entry.get("git_blob", "")))
        ):
            fail("invalid exact source behavior file record")
    if source.get("behavior_source_scope") != {
        "entrypoints": ["src/v3/mappings/factory.ts", "src/v3/mappings/core.ts"],
        "transitive_local_import_closure_complete": True,
        "generated_bindings_and_node_modules_excluded": True,
        "behavior_claims_require_exact_source_build_match": True,
    }:
        fail("exact source behavior closure scope drift")

    if lock.get("truth_boundary") != EXPECTED_TRUTH_BOUNDARY:
        fail("Matic provenance truth boundary drift")
    if lock.get("remaining_gates") != [
        (
            "M0: fully account for both required clusters by inventorying every current "
            "copy or fresh structural absence proof; when viable healthy copies exist, "
            "independently select the minimum stable same-pod 24-hour ETA and minimum "
            "stable same-pod 72-hour ETA across all viable copies, which may be different copies, and "
            "require both minima to exceed 28 days or be non-converging; either minimum "
            "at or below 28 days stops implementation, compute, and load; with no viable "
            "copy, require fresh structural absence proof from both clusters."
        ),
        "M2 must ship the ordered BlockChanges generic loader and release contract.",
        "M2 must capture and verify the Matic physical schema and loader metadata profile.",
        (
            "M3 must certify the Qma8 Factory/Pool handler, field-writer, runtime-population, "
            "and required-absence contract."
        ),
        "The Matic runtime must implement this profile and pass fixed-range differential parity.",
        (
            "Matic physical, VID, PoI, failure, PostgreSQL, and paused-restore certification "
            "must pass."
        ),
        "A paused load requires separate operational validation and activation approval.",
    ]:
        fail("remaining Matic gates must stay explicit and fail closed")


def manifest_semantic_shape(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: "<content-addressed-artifact>" if key == "file" else manifest_semantic_shape(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [manifest_semantic_shape(item) for item in value]
    return value


def git_blob_hash(payload: bytes) -> str:
    return hashlib.sha1(f"blob {len(payload)}\0".encode() + payload).hexdigest()


def exact_behavior_source_closure(source_root: Path, entrypoints: list[str]) -> list[str]:
    pending = list(entrypoints)
    closure: set[str] = set()
    import_pattern = re.compile(r"\bfrom\s+['\"]([^'\"]+)['\"]")
    while pending:
        current = pending.pop()
        if current in closure:
            continue
        payload = repository_path(source_root, current, "behavior source closure").read_text()
        closure.add(current)
        for imported in import_pattern.findall(payload):
            if not imported.startswith("."):
                continue
            resolved = posixpath.normpath(str(Path(current).parent / imported))
            if not Path(resolved).suffix:
                resolved += ".ts"
            if "generated" in Path(resolved).parts:
                continue
            if resolved == "src/common/chain.ts":
                resolved = "config/matic/chain.ts"
            if resolved.startswith("../"):
                fail(f"behavior source import escapes exact source root: {current} -> {imported}")
            if resolved not in closure:
                pending.append(resolved)
    return sorted(closure)


def verify_exact_source_build(
    root: Path,
    source_root: Path,
    lock: dict[str, object],
    artifacts: dict[str, dict[str, object]],
) -> None:
    source = lock["exact_source"]
    closure = exact_behavior_source_closure(
        source_root, source["behavior_source_scope"]["entrypoints"]
    )
    if closure != EXPECTED_BEHAVIOR_SOURCE_PATHS:
        fail("computed exact source behavior import closure drift")
    for record in source["source_files"]:
        payload = repository_path(source_root, record["path"], "exact source input").read_bytes()
        if len(payload) != record["bytes"] or sha256(payload) != record["sha256"]:
            fail(f"exact source build-input drift: {record['path']}")
        if "git_blob" in record and git_blob_hash(payload) != record["git_blob"]:
            fail(f"exact source build-input Git blob drift: {record['path']}")
    for record in source["behavior_source_files"]:
        payload = repository_path(source_root, record["path"], "behavior source").read_bytes()
        if (
            len(payload) != record["bytes"]
            or sha256(payload) != record["sha256"]
            or git_blob_hash(payload) != record["git_blob"]
        ):
            fail(f"exact source behavior closure drift: {record['path']}")

    deployed_manifest = yaml.safe_load(
        repository_path(root, artifacts["deployment"]["vendored_path"], "Matic manifest").read_text()
    )
    built_manifest = yaml.safe_load(
        repository_path(source_root, "build/subgraph.yaml", "built Matic manifest").read_text()
    )
    if manifest_semantic_shape(built_manifest) != manifest_semantic_shape(deployed_manifest):
        fail("exact source generated manifest is not semantically identical to the deployment")

    deployed_schema = repository_path(
        root, artifacts["schema"]["vendored_path"], "Matic schema"
    ).read_bytes()
    normalized_schema, replacements = re.subn(
        rb"@entity\(immutable: (?:true|false)\)", b"@entity", deployed_schema
    )
    normalization = source["schema_normalization"]
    if replacements != normalization["remove_explicit_immutable_arguments"]:
        fail("deployed schema immutable-argument normalization drift")
    if len(normalized_schema) != normalization["source_bytes"]:
        fail("normalized exact source schema byte count drift")
    if sha256(normalized_schema) != normalization["source_sha256"]:
        fail("normalized exact source schema digest drift")
    for schema_path in ("src/v3/schema.graphql", "build/schema.graphql"):
        if repository_path(source_root, schema_path, "exact source schema").read_bytes() != normalized_schema:
            fail(f"exact source schema mismatch: {schema_path}")

    built_artifacts = {
        "factory_abi": "build/Factory/abis/factory.json",
        "erc20_abi": "build/Factory/abis/ERC20.json",
        "erc20_symbol_bytes_abi": "build/Factory/abis/ERC20SymbolBytes.json",
        "erc20_name_bytes_abi": "build/Factory/abis/ERC20NameBytes.json",
        "pool_abi": "build/Factory/abis/pool.json",
        "factory_mapping_wasm": "build/Factory/Factory.wasm",
        "pool_mapping_wasm": "build/templates/Pool/Pool.wasm",
    }
    for role, relative_path in built_artifacts.items():
        payload = repository_path(source_root, relative_path, role).read_bytes()
        if len(payload) != artifacts[role]["source_bytes"]:
            fail(f"exact source build byte count drift for {role}")
        if sha256(payload) != artifacts[role]["source_sha256"]:
            fail(f"exact source build digest drift for {role}")

    installed_versions = {
        "graph_cli": load_json(source_root / "node_modules/@graphprotocol/graph-cli/package.json")[
            "version"
        ],
        "graph_ts": load_json(source_root / "node_modules/@graphprotocol/graph-ts/package.json")[
            "version"
        ],
        "assemblyscript_root": load_json(source_root / "node_modules/assemblyscript/package.json")[
            "version"
        ],
        "assemblyscript_graph_ts_nested": load_json(
            source_root / "node_modules/@graphprotocol/graph-ts/node_modules/assemblyscript/package.json"
        )["version"],
    }
    for key, value in installed_versions.items():
        if value != source["toolchain"][key]:
            fail(f"installed exact source toolchain drift: {key}")


def verify_binding(root: Path) -> None:
    binding = yaml.safe_load((root / BINDING_PATH).read_text())
    if (
        not isinstance(binding, dict)
        or binding.get("deployment") != EXPECTED_DEPLOYMENT
        or binding.get("family") != "uniswap-v3-matic"
        or binding.get("chain") != "matic"
        or binding.get("milestone") != "M4"
        or binding.get("market_snapshot") != EXPECTED_MARKET_SNAPSHOT
        or any(
            field != "market_snapshot"
            and (
                field.startswith(("market_", "qos_", "query_fee"))
                or "grt" in field
                or field in {"queries_24h", "query_count_24h", "fees_24h"}
            )
            for field in binding
        )
        or binding.get("eligibility", {}).get("latest", {}).get("decision")
        != "indeterminate"
        or binding.get("eligibility", {}).get("latest", {}).get("reason")
        != "no_fresh_evidence"
    ):
        fail("Matic binding, M4 market snapshot, or fail-closed eligibility drift")


def verify(root: Path, lock_path: Path, exact_source_root: Path | None = None) -> None:
    lock = load_json(root / lock_path)
    if not isinstance(lock, dict) or lock.get("format_version") != 1:
        fail("unsupported Matic target lock")
    deployment = lock.get("deployment")
    if not isinstance(deployment, dict) or deployment.get("cid") != EXPECTED_DEPLOYMENT:
        fail("deployment identity drift")
    artifacts = verify_artifact_lock(root, lock)
    verify_manifest(root, lock, artifacts)
    qma8_reference = verify_qma8_reference(root, lock)
    verify_schema(root, lock, artifacts, qma8_reference)
    verify_profile(root, lock, artifacts, qma8_reference)
    verify_source_pin(lock, artifacts)
    verify_binding(root)
    if exact_source_root is not None:
        verify_exact_source_build(root, exact_source_root.resolve(), lock, artifacts)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--lock", type=Path, default=LOCK_PATH)
    parser.add_argument("--exact-source-root", type=Path)
    args = parser.parse_args()
    try:
        verify(args.root.resolve(), args.lock, args.exact_source_root)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, yaml.YAMLError) as error:
        print(f"Uniswap V3 Matic target verification failed: {error}", file=sys.stderr)
        return 1
    print(
        "verified immutable Matic deployment/schema/ABI artifacts, exact manifest shape, "
        "retained Qma8 closure, bidirectional layout gap, exact-source behavior/reuse "
        "profile, false readiness gates, and the exact source/toolchain reproduction"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
