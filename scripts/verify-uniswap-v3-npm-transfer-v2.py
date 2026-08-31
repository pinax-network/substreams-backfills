#!/usr/bin/env python3
"""Build or verify the complete retained-WAT NPM Transfer v2 certificate."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import itertools
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[1]
CONTRACT_PATH = Path("uniswap-v3/npm-transfer/v2/contract.json")
CONTRACT_VERSION = "uniswap-v3-npm-transfer/v2"
HANDLER_ID = "NonfungiblePositionManager.handleTransfer"
HANDLER_EXPORT = "handleTransfer"

IMPLEMENTATION_BASE_COMMIT = "8ac009d06ef05d077430aadac5782c6391a0ca0c"
IMPLEMENTATION_BASE_TREE = "2ddc9d94172eb8f61306280320d63a9029efcce3"

FIELD_VERIFIER_PATH = REPOSITORY / "scripts/verify-uniswap-v3-segment-field-semantics-v2.py"
FIELD_VERIFIER_SHA256 = "e14a7ad95f9124861c36f72b60927f02200cfc02ad06eddf31eb36d7cc54e5ec"
WRITER_VERIFIER_PATH = REPOSITORY / "scripts/verify-uniswap-v3-writer-semantics.py"
WRITER_VERIFIER_SHA256 = "8cc6e779c8757cc4f59be49665922383ede95c5d654c65ffd043ea781555514b"

SOURCE_SPECS = {
    "ancestry_v2": (
        Path("uniswap-v3/graft-ancestry/v2/contract.json"),
        "uniswap-v3-graft-ancestry/v2",
        "ae8c3e0099fedf2879b3071c2bcf545050fa4d448d0154fa6b895618bb8e203e",
        "81f38fb34c1a5397386c77d7bd324d0350483587de627f171341f538b93edd37",
    ),
    "writer_compatibility_v3": (
        Path("uniswap-v3/graft-ancestry/v2/writer-compatibility.json"),
        "uniswap-v3-writer-compatibility/v3",
        "259481724561d5aa725c17f90b5a19ea93ad6f7cd6074cf2cb8a8661c39f81c4",
        "96f1bc00e1a0eda7eb2a516e91bf9065aba5e2b668856e1d41905ba6e297bd71",
    ),
    "segment_writer_matrix_v1": (
        Path("uniswap-v3/segment-writer-matrix/v1/contract.json"),
        "uniswap-v3-segment-writer-matrix/v1",
        "7f6d1a34a8c885fe5ddcd81895818ba7ae8a0d736d541b881c1cc7cd54275161",
        "356274207567cbcecb452a198758e8bdfc4440ba34d6ea3e66be2850d1a90280",
    ),
    "segment_field_semantics_v2": (
        Path("uniswap-v3/segment-field-semantics/v2/contract.json"),
        "uniswap-v3-segment-field-semantics/v2",
        "0ca8708bd2ed60d4799559d52b3f7e0602abfd7c3edbd35f579476f00baba6ef",
        "28b9ed0d665cccb47ef6288ba7ae6247368036753bcbbfe0527e184b3c04eed3",
    ),
    "segment_field_semantics_v1": (
        Path("uniswap-v3/segment-field-semantics/v1/contract.json"),
        "uniswap-v3-segment-field-semantics/v1",
        "4daa777ce2d14edd8a665a6a1239db8fb78957aa091174fd31f81b2c25136d4e",
        "34e421f2b276c91cc5596906d3731d16dc3af9ae17c890092e4ddb990a3ecf86",
    ),
}

SCHEMA_ARTIFACTS = {
    "QmSGd2GREu8QzGgqXA626cyYbF65TGXj3gmk96CDBNQ9zG": (
        18_381,
        "35d07db24c66668ffd15f4d415cacdeaf0432c8c6149937cbc9644ae81e47964",
    ),
    "QmU2VngSqWUtEo8XpPiPmXBfwLHZGrKnXqmifcj7GDH1b4": (
        18_381,
        "a623302914a925519745508fbb268100f58eaa65c4b01e84f9db5cf91ab0abcc",
    ),
    "Qma8a81T9XoX5Pbkrk8J3kxMhWdXJzFSYZge1wGi3QZBru": (
        19_034,
        "ae03d0c6d3c6c03f87ae8e699b1e71804266c1d4adb7acbf4f4de5d48727c39c",
    ),
}

MAPPING_EXPECTATIONS = {
    "QmYWR79pUmVbQ42JkvB24D6AKCGtdo4UG78ZSewmFxwQdR": {
        "generation": "legacy-generated-setters",
        "bytes": 20_794,
        "raw_sha256": "3ad2abc957362fa5fa62ef8bb762ab3b38676d1139d1ca85ee0db2b25ade9fca",
        "wat_sha256": "93cf89c0ac5f8af930c4a4a1b273a6831dced3247104db4585b6d6284da789a2",
        "function_count": 89,
        "direct_call_count": 326,
        "direct_target_count": 95,
        "memory_write_count": 172,
        "generic_setter_site_count": 22,
        "named_setter_invocation_count": 29,
        "store_get_site_count": 2,
        "store_set_site_count": 3,
        "call_indirect_count": 0,
        "handler_body_sha256": "9cd6f621c7451519d78081048fd74693bab51c3d0599ab07a0ba951db37c41d2",
        "handler_normalized_body_sha256": "9cd6f621c7451519d78081048fd74693bab51c3d0599ab07a0ba951db37c41d2",
        "handler_call_sequence_sha256": "5ed24128ffff5790f5658b41ec98d7a6426426ae9ead6b0c3613ae0ba6a1cf57",
        "handler_normalized_call_sequence_sha256": "5ed24128ffff5790f5658b41ec98d7a6426426ae9ead6b0c3613ae0ba6a1cf57",
        "handler_function_index": 125,
        "handler_start_line": 4261,
    },
    "Qmebr2EyxV7v1wLt9DSFKA7g8EhcVr9k1x7pwZr5eWEHT6": {
        "same_as": "QmYWR79pUmVbQ42JkvB24D6AKCGtdo4UG78ZSewmFxwQdR",
        "raw_sha256": "bdb35f971e9a03b4bdc92b140d42285e27fdff6efb4edf14fe0f3eaad0c80537",
        "wat_sha256": "19d7511d0a1ba05caeb115d4d820c89c61210c373b9253682915bc40d0d38d5d",
    },
    "QmYwxHm2GNNcukX9oe4owucCLNoAk2rYrbMFuMFtWfKLn2": {
        "same_as": "QmYWR79pUmVbQ42JkvB24D6AKCGtdo4UG78ZSewmFxwQdR",
        "bytes": 20_604,
        "raw_sha256": "b09ba105e25bbca52949325f57c2006fa2e441139617380d5f81e3945dfbbe02",
        "wat_sha256": "c68a6ea285b643a301f7931ec8bebc3acd88c047a7c84b5773ffd2aa8570f9c3",
        "function_count": 87,
        "direct_call_count": 324,
        "direct_target_count": 93,
        "handler_function_index": 123,
        "handler_start_line": 4221,
    },
    "QmWxG1yzdQmp4pRDiqKvTZyRrrrZPRUTza6xznjR1wu1sD": {
        "generation": "current-generic-setters",
        "bytes": 48_593,
        "raw_sha256": "34487685c81672436f34b79f3749f41e6b3c724b52dd8cb24b933e3cb5006124",
        "wat_sha256": "6febde6b56e441b694f1708821a5e507f766ddfac3056a8efbce026826a9dced",
        "function_count": 50,
        "direct_call_count": 352,
        "direct_target_count": 56,
        "memory_write_count": 291,
        "generic_setter_site_count": 39,
        "named_setter_invocation_count": 0,
        "store_get_site_count": 2,
        "store_set_site_count": 3,
        "call_indirect_count": 1,
        "handler_body_sha256": "16cb4f150516682731b387e7b88276e24f74de763ce415f2b754053333323b91",
        "handler_normalized_body_sha256": "f107bb4841917f98a99ae4221979eac1e0bf6f9a269ae8966fca3ed152f848de",
        "handler_call_sequence_sha256": "9f52077fbe0796d32c7247ef0e631182e71b9b5fa31c82ae2ae26b85e6ccc15f",
        "handler_normalized_call_sequence_sha256": "9f52077fbe0796d32c7247ef0e631182e71b9b5fa31c82ae2ae26b85e6ccc15f",
        "handler_function_index": 81,
        "handler_start_line": 6078,
    },
    "QmUk7jc3c8joQBrrcTz2ZEVDKcg1P12G2nFtuNqiikDQLJ": {
        "same_as": "QmYWR79pUmVbQ42JkvB24D6AKCGtdo4UG78ZSewmFxwQdR",
        "bytes": 20_876,
        "raw_sha256": "e25dad1c3b6f1892eee2a8f51da62bb57268286deb9a135d6a689bdca1ad0034",
        "wat_sha256": "4370c99e82c40e311a7a3d9c23ff0a61ed0dfd04feb9d737727308400ce03d12",
        "handler_function_index": 126,
        "handler_start_line": 4272,
    },
    "QmPjhEuGqknJJ2LfJCi6XTLFLtiymYfZAtjTLfkmJJGMEj": {
        "same_as": "QmWxG1yzdQmp4pRDiqKvTZyRrrrZPRUTza6xznjR1wu1sD",
        "bytes": 48_657,
        "raw_sha256": "6338f6b3b2071d0599b8381c948070ca138827bd61b6e5e05eb0d112177b0c91",
        "wat_sha256": "2ca2b971161bb406b60ddf8d0d486ee02c3599dedb72c3c9c9dad9f6e63dd8ca",
        "handler_body_sha256": "3ee2d455074bb628cbda804ac49add1627de503a54a056b10d896c913dc6fca2",
        "handler_call_sequence_sha256": "c3a813e7f018d619f1ee425b45b5f98e34f02772f77459417d0eb4bf7cb1fbce",
    },
}

PROFILE_BY_CID = {
    "QmYWR79pUmVbQ42JkvB24D6AKCGtdo4UG78ZSewmFxwQdR": "mainnet-root-correct-collect",
    "Qmebr2EyxV7v1wLt9DSFKA7g8EhcVr9k1x7pwZr5eWEHT6": "mainnet-second-fee0-overwrite",
    "QmYwxHm2GNNcukX9oe4owucCLNoAk2rYrbMFuMFtWfKLn2": "mainnet-no-collect-amounts",
    "QmWxG1yzdQmp4pRDiqKvTZyRrrrZPRUTza6xznjR1wu1sD": "current-amount0-to-both",
    "QmUk7jc3c8joQBrrcTz2ZEVDKcg1P12G2nFtuNqiikDQLJ": "base-root-amount0-to-both",
    "QmPjhEuGqknJJ2LfJCi6XTLFLtiymYfZAtjTLfkmJJGMEj": "current-amount0-to-both",
}

POSITION_FIELDS = (
    "id", "owner", "pool", "token0", "token1", "tickLower", "tickUpper",
    "liquidity", "depositedToken0", "depositedToken1", "withdrawnToken0",
    "withdrawnToken1", "collectedFeesToken0", "collectedFeesToken1",
    "transaction", "feeGrowthInside0LastX128", "feeGrowthInside1LastX128",
)
SNAPSHOT_FIELDS = (
    "id", "owner", "pool", "position", "blockNumber", "timestamp", "liquidity",
    "depositedToken0", "depositedToken1", "withdrawnToken0", "withdrawnToken1",
    "collectedFeesToken0", "collectedFeesToken1", "transaction",
    "feeGrowthInside0LastX128", "feeGrowthInside1LastX128",
)
TRANSACTION_FIELDS = ("id", "blockNumber", "timestamp", "gasUsed", "gasPrice")
CLASSIFIED_FIELDS = {
    *(('Position', field) for field in POSITION_FIELDS),
    *(('PositionSnapshot', field) for field in SNAPSHOT_FIELDS),
    *(('Transaction', field) for field in TRANSACTION_FIELDS),
}
RELATION_FIELDS = {
    ("Position", "pool"), ("Position", "token0"), ("Position", "token1"),
    ("Position", "tickLower"), ("Position", "tickUpper"),
    ("PositionSnapshot", "pool"),
}
REQUIRED_ABSENT_ENTITIES = {"Collect", "Flash", "TickHourData"}

CATEGORY_CLASSIFIED = "classified_stored_target_with_path_qualified_schema_setter_authority"
CATEGORY_SAVED_NO_SETTER = "saved_target_stored_field_without_reachable_setter"
CATEGORY_DERIVED = "derived_query_field_without_direct_store_transition"
CATEGORY_OUTSIDE = "stored_field_outside_npm_transfer_store_target_closure"

TRUE_FLAGS = (
    "exact_direct_roots_digest_bound_and_recomputed",
    "exact_six_retained_npm_wasms_regenerated_with_wabt_1_0_35",
    "all_eight_segment_bindings_resolved",
    "all_reachable_direct_calls_and_function_bodies_bound",
    "all_reachable_memory_writes_bound",
    "all_generic_named_constructor_unset_and_store_sites_accounted",
    "closed_call_indirect_table_target_proven",
    "all_three_store_targets_and_two_store_read_sites_bound",
    "accepted_existing_new_revert_and_fatal_path_order_bound",
    "all_thirty_eight_distinct_stored_targets_classified",
    "all_six_relation_field_receiver_key_source_paths_bound",
    "all_eight_segments_have_299_outcomes",
    "all_264_required_absent_outcomes_present",
    "all_twenty_eight_recursive_segment_diffs_present",
    "path_qualified_complete_static_npm_transfer_contract",
)
FALSE_FLAGS = (
    "imported_value_semantics_complete",
    "imported_numeric_semantics_complete",
    "imported_string_formatting_semantics_complete",
    "imported_address_conversion_semantics_complete",
    "host_contract_call_return_values_complete",
    "host_contract_call_temporal_semantics_complete",
    "host_contract_call_error_classes_complete",
    "graph_store_read_contents_complete",
    "graph_store_read_ordinal_semantics_complete",
    "graph_store_alias_semantics_complete",
    "graph_store_persistence_complete",
    "graph_store_persistence_proven",
    "graph_handler_rollback_proven",
    "post_fatal_execution_modeled",
    "vid_semantics_complete",
    "poi_semantics_complete",
    "field_value_unchanged_or_preserved_proven",
    "complete_position_history",
    "complete_position_snapshot_history",
    "complete_transaction_history",
    "shared_transaction_last_writer_complete",
    "required_nonempty_certified",
    "runtime_population_complete",
    "target_runtime_identity_bound",
    "graph_oracle_complete",
    "boundary_continuity_complete",
    "logical_parity_complete",
    "physical_parity_complete",
    "poi_parity_complete",
    "source_package_identity_proven",
    "scheduler_implemented",
    "output_implemented",
    "writer_package_consumes_projection",
    "checkpoint_authority",
    "backfill_ready",
    "deployment_ready",
    "production_ready",
    "readiness_complete",
    "issue_37_acceptance_criterion_complete",
    "issue_38_acceptance_criterion_complete",
    "issue_checkbox_completed",
)


class VerificationError(RuntimeError):
    """Raised when retained evidence cannot reproduce the exact certificate."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def raw_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def render(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(), object_pairs_hook=reject_duplicate_keys)
    except (OSError, json.JSONDecodeError) as error:
        raise VerificationError(f"cannot load {path}: {error}") from error


def load_module(name: str, path: Path, digest: str) -> Any:
    require(path.is_file(), f"required verifier missing: {path}")
    require(raw_sha256(path) == digest, f"verifier digest drift: {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"cannot import verifier: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


FIELD = load_module(
    "uniswap_v3_segment_field_semantics_v2_for_npm_transfer_v2",
    FIELD_VERIFIER_PATH,
    FIELD_VERIFIER_SHA256,
)
require(raw_sha256(WRITER_VERIFIER_PATH) == WRITER_VERIFIER_SHA256, "writer verifier digest drift")
WRITER = FIELD.WRITER


def expanded_expectation(cid: str) -> dict[str, Any]:
    raw = dict(MAPPING_EXPECTATIONS[cid])
    parent = raw.pop("same_as", None)
    if parent is None:
        return raw
    return {**expanded_expectation(parent), **raw}


def json_diff_paths(left: Any, right: Any, path: str = "$") -> list[str]:
    if type(left) is not type(right):
        return [path]
    if isinstance(left, dict):
        paths: list[str] = []
        for key in sorted(set(left) | set(right)):
            child = f"{path}.{key}"
            if key not in left or key not in right:
                paths.append(child)
            else:
                paths.extend(json_diff_paths(left[key], right[key], child))
        return paths
    if isinstance(left, list):
        paths = []
        for index in range(max(len(left), len(right))):
            child = f"{path}[{index}]"
            if index >= len(left) or index >= len(right):
                paths.append(child)
            else:
                paths.extend(json_diff_paths(left[index], right[index], child))
        return paths
    return [] if left == right else [path]


def _bind(root: Path, spec: tuple[Path, str, str, str]) -> Any:
    relative, version, raw_digest, canonical_digest = spec
    path = root / relative
    require(path.is_file(), f"required source missing: {relative}")
    require(raw_sha256(path) == raw_digest, f"raw source digest drift: {relative}")
    value = load_json(path)
    require(value.get("contract_version") == version, f"source version drift: {relative}")
    require(canonical_sha256(value) == canonical_digest, f"canonical source digest drift: {relative}")
    return value


def _schema_catalog(field_contract: dict[str, Any]) -> dict[str, Any]:
    catalog = field_contract["field_catalog"]
    require(len(catalog) == 299, "schema field count drift")
    pairs = [(item["entity"], item["field"]) for item in catalog]
    require(len(set(pairs)) == 299, "schema entity/field uniqueness drift")
    storage = Counter(item["storage"] for item in catalog)
    require(storage == Counter({"stored": 286, "derived": 13}), "schema storage split drift")
    require(sum((item["entity"], item["field"]) in CLASSIFIED_FIELDS for item in catalog) == 38, "classified target denominator drift")
    require(sum(item["entity"] in REQUIRED_ABSENT_ENTITIES for item in catalog) == 33, "required absence denominator drift")
    return {
        "field_count": 299,
        "stored_field_count": 286,
        "derived_field_count": 13,
        "entity_count": len({item["entity"] for item in catalog}),
        "entity_field_pairs_sha256": canonical_sha256(pairs),
        "field_catalog_sha256": canonical_sha256(catalog),
    }


def _normalized_call_target(target: str) -> str:
    return target.replace("generated/schema/", "src/types/schema/")


def _site(function: Any, index: int, target: str | None = None) -> dict[str, Any]:
    result = {
        "function": function.name,
        "function_line_index": index,
        "wat_line": function.start_line + index,
    }
    if target is not None:
        result["target"] = target
    return result


def _memory_write_sites(functions: dict[str, Any], closure: set[str]) -> list[dict[str, Any]]:
    pattern = re.compile(r"\b(?:i32|i64|f32|f64|v128)\.store")
    result = []
    for name in sorted(closure):
        function = functions[name]
        for index, line in enumerate(function.lines):
            if pattern.search(line):
                result.append({**_site(function, index), "instruction": line.strip()})
    return result


def _direct_call_sites(functions: dict[str, Any], closure: set[str]) -> list[dict[str, Any]]:
    result = []
    for name in sorted(closure):
        function = functions[name]
        result.extend(_site(function, index, target) for index, target in WRITER.function_call_sites(function))
    return result


def _function_bodies(functions: dict[str, Any], closure: set[str], memory: bytearray) -> list[dict[str, Any]]:
    result = []
    for name in sorted(closure):
        function = functions[name]
        calls = WRITER.function_calls(function)
        result.append(
            {
                "function": name,
                "wat_function_index": function.function_index,
                "wat_start_line": function.start_line,
                "body_sha256": hashlib.sha256(function.payload).hexdigest(),
                "normalized_body_sha256": hashlib.sha256(
                    WRITER.normalized_function_payload(function, memory)
                ).hexdigest(),
                "direct_call_count": len(calls),
                "direct_call_sequence_sha256": hashlib.sha256(
                    ("\n".join(calls) + "\n").encode()
                ).hexdigest(),
            }
        )
    return result


def _semantic_functions(
    functions: dict[str, Any],
    closure: set[str],
    memory: bytearray,
    generation: str,
) -> dict[str, Any]:
    names = {
        "handler": "src/mappings/position-manager/handleTransfer",
        "get_position": "src/mappings/position-manager/getPosition",
        "save_snapshot": "src/mappings/position-manager/savePositionSnapshot",
        "load_transaction": "src/utils/index/loadTransaction",
    }
    result: dict[str, Any] = {}
    for key, name in names.items():
        require(name in functions, f"semantic function missing: {name}")
        function = functions[name]
        result[key] = {
            "function": name,
            "body_sha256": hashlib.sha256(function.payload).hexdigest(),
            "wat_start_line": function.start_line,
            "direct_calls": WRITER.function_calls(function),
            "static_strings": WRITER.function_static_strings(function, memory),
        }
    expected_fields = set(POSITION_FIELDS) | set(SNAPSHOT_FIELDS) | set(TRANSACTION_FIELDS)
    observed_strings = {
        value
        for name in closure
        for value in WRITER.function_static_strings(functions[name], memory)
    }
    require(expected_fields <= observed_strings, "semantic field string closure drift")
    generic = "legacy" if generation.startswith("legacy") else "current"
    constructor_symbols = (
        ["src/types/schema/Position#constructor"] * 3
        if generic == "legacy"
        else ["~lib/@graphprotocol/graph-ts/common/collections/Entity#constructor"] * 3
    )
    return {
        "functions": result,
        "lexical_semantic_field_invocation_count": 39,
        "distinct_semantic_field_count": 38,
        "maximum_expanded_new_position_field_invocation_count": 44,
        "accepted_existing_position_field_invocation_count": 22,
        "semantic_constructor_invocations": [
            {"entity_authority": entity, "function": names[key], "physical_symbol": symbol, "id_effect_class": "constructor_carried" if generic == "legacy" else "explicit_generic_id_set"}
            for entity, key, symbol in zip(
                ("Position", "Transaction", "PositionSnapshot"),
                ("get_position", "load_transaction", "save_snapshot"),
                constructor_symbols,
            )
        ],
        "schema_unset_invocation_count": 0,
    }


def _path_contract(generation: str, api_version: str) -> dict[str, Any]:
    legacy = generation.startswith("legacy")
    gas_used_source = (
        "event.transaction.gasLimit getter result passed to the gasUsed field setter"
        if api_version == "0.0.4"
        else "result of BigInt.fromI32 with literal zero passed to the gasUsed field setter"
    )
    return {
        "accepted_existing_position": {
            "guard": "Position store.get returns a non-null entity pointer",
            "contract_call_count": 0,
            "lexical_field_invocation_count": 22,
            "expanded_store_get_count": 2,
            "expanded_store_set_count": 3,
            "store_set_order": ["Position", "Transaction", "PositionSnapshot"],
            "field_effect_order": [
                "Position.owner setter from Transfer event.to conversion",
                "Position save",
                "PositionSnapshot sixteen-field constructor/setter ledger",
                "Transaction five-field loadTransaction ledger and save",
                "PositionSnapshot save",
            ],
            "position_fields_without_a_setter_before_position_save": [
                field for field in POSITION_FIELDS if field != "owner"
            ],
            "position_fields_without_setter_are_preserved_or_unchanged": False,
        },
        "accepted_new_position": {
            "guard": "Position store.get is null, try_positions is not reverted, and non-try Factory getPool returns",
            "contract_call_count": 2,
            "lexical_field_invocation_count": 39,
            "maximum_expanded_field_invocation_count": 44,
            "expanded_store_get_count": 3,
            "expanded_store_set_count": 4,
            "store_set_order": ["Transaction", "Position", "Transaction", "PositionSnapshot"],
            "field_effect_order": [
                "Position seventeen-field getPosition construction ledger including provisional owner",
                "first Transaction five-field loadTransaction ledger and save",
                "Position.owner overwrite from Transfer event.to conversion",
                "Position save",
                "PositionSnapshot sixteen-field constructor/setter ledger",
                "second Transaction five-field loadTransaction ledger and save",
                "PositionSnapshot save",
            ],
        },
        "try_positions_revert": {
            "guard": "Position store.get is null and generated try_positions reports reverted",
            "normal_return": True,
            "schema_field_invocation_count": 0,
            "store_set_count": 0,
        },
        "factory_get_pool_fatal": {
            "guard": "Position store.get is null, try_positions succeeds, and non-try Factory getPool has no returned value",
            "fatal_before_any_schema_constructor_setter_or_store_set": True,
            "schema_field_invocation_count_before_fatal": 0,
            "store_set_count_before_fatal": 0,
            "post_fatal_execution_modeled": False,
        },
        "contract_calls": {
            "try_positions": "generated try call",
            "factory_get_pool": "legacy Factory wrapper non-try call" if legacy else "current inlined non-try call",
            "host_return_values_complete": False,
            "host_temporal_semantics_complete": False,
        },
        "transaction_gas_used": {
            "api_version": api_version,
            "structural_source": gas_used_source,
            "numeric_meaning_complete": False,
        },
        "no_transfer_exclusion_or_historical_block_branch_in_bound_handler_path": True,
        "global_absence_of_exclusion_literals_claimed": False,
        "persistence_or_rollback_claimed": False,
    }


def _relation_authority() -> list[dict[str, Any]]:
    return [
        {
            "entity": "Position",
            "field": "pool",
            "path": "new-position only",
            "source_chain": "try_positions token0, token1, and fee outputs to non-try Factory getPool, then returned address conversion to the Position.pool setter",
            "receiver_and_key_authority_bound": True,
            "imported_value_semantics_complete": False,
        },
        {
            "entity": "Position",
            "field": "token0",
            "path": "new-position only",
            "source_chain": "try_positions token0 output through address conversion to the Position.token0 generic or generated setter",
            "receiver_and_key_authority_bound": True,
            "imported_value_semantics_complete": False,
        },
        {
            "entity": "Position",
            "field": "token1",
            "path": "new-position only",
            "source_chain": "try_positions token1 output through address conversion to the Position.token1 generic or generated setter",
            "receiver_and_key_authority_bound": True,
            "imported_value_semantics_complete": False,
        },
        {
            "entity": "Position",
            "field": "tickLower",
            "path": "new-position only",
            "source_chain": "the just-set Position.pool getter result, a number-sign literal, and the try_positions tickLower output reach the Position.tickLower setter path",
            "receiver_and_key_authority_bound": True,
            "string_and_numeric_formatting_semantics_complete": False,
        },
        {
            "entity": "Position",
            "field": "tickUpper",
            "path": "new-position only",
            "source_chain": "the just-set Position.pool getter result, a number-sign literal, and the try_positions tickUpper output reach the Position.tickUpper setter path",
            "receiver_and_key_authority_bound": True,
            "string_and_numeric_formatting_semantics_complete": False,
        },
        {
            "entity": "PositionSnapshot",
            "field": "pool",
            "path": "both accepted paths",
            "source_chain": "Position.pool getter result reaches the PositionSnapshot.pool setter path",
            "receiver_and_key_authority_bound": True,
            "store_read_or_alias_value_semantics_complete": False,
        },
    ]


def prove_mapping(
    root: Path,
    executable: Path,
    inventory: dict[str, Any],
    artifact: dict[str, Any],
) -> dict[str, Any]:
    cid = str(inventory["cid"])
    expected = expanded_expectation(cid)
    analysis, functions, memory = WRITER.analyze_mapping(root, executable, inventory, artifact)
    handler = WRITER.resolve_handler(functions, analysis["registered_handler_export_targets"], HANDLER_EXPORT)
    closure = WRITER.reachable_functions(functions, handler, analysis["call_indirect_table_targets"])
    direct_calls = _direct_call_sites(functions, closure)
    writes = _memory_write_sites(functions, closure)
    bodies = _function_bodies(functions, closure, memory)
    normalized_calls = [_normalized_call_target(item["target"]) for item in direct_calls]

    generic_sites = [
        item for item in direct_calls
        if "TypedMap<" in item["target"] and item["target"].endswith("#set")
    ]
    named_sites = [
        item for item in direct_calls
        if re.match(r"^(?:src/types/schema|generated/schema)/[^#]+#set:[^#]+$", item["target"])
    ]
    unset_sites = [item for item in direct_calls if "#unset:" in item["target"]]
    store_get_sites = [item for item in direct_calls if item["target"].endswith("/store.get")]
    store_set_sites = [item for item in direct_calls if item["target"].endswith("/store.set")]
    store_remove_sites = [item for item in direct_calls if item["target"].endswith("/store.remove")]
    ethereum_call_sites = [item for item in direct_calls if item["target"].endswith("/ethereum.call")]
    indirect_sites = []
    for name in sorted(closure):
        function = functions[name]
        for index, line in enumerate(function.lines):
            if "call_indirect" in line:
                indirect_sites.append({**_site(function, index), "instruction": line.strip()})

    handler_record = WRITER.handler_record(handler, memory)
    require(artifact["bytes"] == expected["bytes"], f"{cid} byte count drift")
    require(artifact["sha256"] == expected["raw_sha256"], f"{cid} artifact digest drift")
    require(analysis["wat_sha256"] == expected["wat_sha256"], f"{cid} WAT digest drift")
    observed = {
        "function_count": len(closure),
        "direct_call_count": len(direct_calls),
        "direct_target_count": len(set(normalized_calls)),
        "memory_write_count": len(writes),
        "generic_setter_site_count": len(generic_sites),
        "named_setter_invocation_count": len(named_sites),
        "store_get_site_count": len(store_get_sites),
        "store_set_site_count": len(store_set_sites),
        "call_indirect_count": len(indirect_sites),
    }
    for field, value in observed.items():
        require(value == expected[field], f"{cid} {field} drift: {value} != {expected[field]}")
    require(len(store_remove_sites) == 0 and len(unset_sites) == 0, f"{cid} remove/unset closure drift")
    require(len(ethereum_call_sites) == 2, f"{cid} ethereum.call site count drift")
    require(
        {item["target"] for item in WRITER.extract_store_set_callsites(functions, memory) if item["function"] in closure}
        == {"Position", "PositionSnapshot", "Transaction"},
        f"{cid} store target closure drift",
    )
    require(
        analysis["call_indirect_imported_table_count"] == 0
        and analysis["call_indirect_exported_table_count"] == (0 if indirect_sites else 1)
        and analysis["call_indirect_table_mutation_instruction_count"] == 0
        and analysis["unsupported_call_ref_instruction_count"] == 0,
        f"{cid} indirect table closure drift",
    )
    executable_indirect_targets = (
        analysis["call_indirect_table_targets"] if indirect_sites else []
    )
    require(
        executable_indirect_targets
        == ([] if not indirect_sites else ["~lib/@graphprotocol/graph-ts/common/value/Value#displayData~anonymous|0"]),
        f"{cid} executable indirect target drift",
    )
    handler_expected = {
        "body_sha256": expected["handler_body_sha256"],
        "normalized_body_sha256": expected["handler_normalized_body_sha256"],
        "call_sequence_sha256": expected["handler_call_sequence_sha256"],
        "normalized_call_sequence_sha256": expected["handler_normalized_call_sequence_sha256"],
        "wat_function_index": expected["handler_function_index"],
        "wat_start_line": expected["handler_start_line"],
    }
    for field, value in handler_expected.items():
        require(handler_record[field] == value, f"{cid} handler {field} drift")

    generation = expected["generation"]
    api_version = "0.0.4" if generation.startswith("legacy") else "0.0.7"
    semantic = _semantic_functions(functions, closure, memory, generation)
    constructor_symbols = [item["physical_symbol"] for item in semantic["semantic_constructor_invocations"]]
    for symbol in constructor_symbols:
        require(normalized_calls.count(symbol) >= 1, f"{cid} semantic constructor missing: {symbol}")

    store_targets = [
        {
            "function": item["function"],
            "target": item["target"],
            "site_id": item["site_id"],
            "wat_line": item["wat_line"],
        }
        for item in WRITER.extract_store_set_callsites(functions, memory)
        if item["function"] in closure
    ]
    return {
        "mapping_cid": cid,
        "profile_id": PROFILE_BY_CID[cid],
        "generation": generation,
        "api_version": api_version,
        "retained_wasm": {
            "path": artifact["path"],
            "bytes": artifact["bytes"],
            "raw_sha256": artifact["sha256"],
            "wat_sha256": analysis["wat_sha256"],
        },
        "handler_binding": handler_record,
        "reachable_closure_summary": {
            **observed,
            "store_remove_site_count": 0,
            "schema_unset_site_count": 0,
            "ethereum_call_site_count": 2,
            "physical_store_set_target_count": 3,
            "executable_call_indirect_target_count": len(executable_indirect_targets),
        },
        "reachable_function_bodies": bodies,
        "reachable_function_bodies_sha256": canonical_sha256(bodies),
        "direct_call_sites": direct_calls,
        "direct_call_sites_sha256": canonical_sha256(direct_calls),
        "memory_write_sites": writes,
        "memory_write_sites_sha256": canonical_sha256(writes),
        "schema_api_sites": {
            "generic_typed_map_setters": generic_sites,
            "named_generated_setter_invocations": named_sites,
            "schema_unsets": unset_sites,
            "store_gets": store_get_sites,
            "store_sets": store_set_sites,
            "store_removes": store_remove_sites,
            "ethereum_calls": ethereum_call_sites,
            "store_set_targets": store_targets,
            "call_indirect_sites": indirect_sites,
            "declared_table_initializers": analysis["call_indirect_table_targets"],
            "executable_call_indirect_targets": executable_indirect_targets,
        },
        "semantic_invocation_contract": semantic,
        "path_contract": _path_contract(generation, api_version),
        "relation_field_authority": _relation_authority(),
        "complete_static_schema_api_effect_contract": True,
        "field_value_semantics_complete": False,
        "graph_store_persistence_proven": False,
        "complete_entity_history": False,
    }


def _ancestry_segments(ancestry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for network, network_record in ancestry["networks"].items():
        for segment in network_record["segments"]:
            npm = next(
                item for item in segment["manifest"]["components"]
                if item["name"] == "NonfungiblePositionManager"
            )
            segment_id = f"{network}:{segment['deployment']}"
            result[segment_id] = {
                "network": network,
                "deployment": segment["deployment"],
                "start_block_inclusive": segment["start_block_inclusive"],
                "end_block_inclusive": segment["end_block_inclusive"],
                "schema_cid": segment["manifest"]["schema_cid"],
                "mapping_cid": npm["mapping"]["wasm_cid"],
                "api_version": npm["mapping"]["api_version"],
                "graft": segment["manifest"]["graft"],
            }
    require(len(result) == 8, "ancestry segment population drift")
    return result


def _field_outcome(record: dict[str, Any], proof: dict[str, Any]) -> dict[str, Any]:
    identity = (record["entity"], record["field"])
    classified = identity in CLASSIFIED_FIELDS
    derived = record["storage"] == "derived"
    outside = record["storage"] == "stored" and not classified
    saved_no_setter = False
    require(sum((classified, saved_no_setter, derived, outside)) == 1, f"field category drift: {identity}")
    category = (
        CATEGORY_CLASSIFIED if classified else
        CATEGORY_SAVED_NO_SETTER if saved_no_setter else
        CATEGORY_DERIVED if derived else CATEGORY_OUTSIDE
    )
    required_absent = record["entity"] in REQUIRED_ABSENT_ENTITIES
    if required_absent:
        require(record["population_classification"] == "required_absent", f"required absence drift: {identity}")
    paths: list[str] = []
    if classified:
        if record["entity"] == "Position":
            paths.append("accepted_new_position")
            if record["field"] == "owner":
                paths.append("accepted_existing_position")
        elif record["entity"] in {"PositionSnapshot", "Transaction"}:
            paths.extend(("accepted_existing_position", "accepted_new_position"))
    require(bool(paths) == classified, f"setter-path/classified-field drift: {identity}")
    require(not (derived or outside) or not paths, f"non-stored-target setter path drift: {identity}")
    require(not paths or record["storage"] == "stored", f"setter path reaches non-stored field: {identity}")
    return {
        "entity": record["entity"],
        "field": record["field"],
        "type": record["type"],
        "directives": record["directives"],
        "storage": record["storage"],
        "schema_catalog_record_sha256": canonical_sha256(record),
        "path_qualified_category": category,
        "classified_stored_target": classified,
        "saved_target_stored_no_setter": saved_no_setter,
        "derived_query_field": derived,
        "outside_npm_transfer_store_target_closure": outside,
        "setter_before_matching_save_paths": paths,
        "required_absent_overlay": required_absent,
        "relation_field_authority_bound": identity in RELATION_FIELDS,
        "field_value_semantics_complete": False,
        "field_value_unchanged_or_preserved_proven": False,
        "graph_store_persistence_proven": False,
        "complete_entity_history": False,
        "mapping_proof_sha256": canonical_sha256(proof),
    }


def build_segments(
    field_contract: dict[str, Any],
    ancestry: dict[str, Any],
    proofs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    proof_by_cid = {item["mapping_cid"]: item for item in proofs}
    bindings = _ancestry_segments(ancestry)
    results = []
    for parent in field_contract["segments"]:
        segment_id = parent["segment_id"]
        require(segment_id in bindings, f"segment missing from ancestry: {segment_id}")
        binding = bindings[segment_id]
        proof = proof_by_cid[binding["mapping_cid"]]
        npm_profile = parent["provenance_surface"]["profiles"]["nonfungible_position_manager"]
        require(npm_profile["mapping_cid"] == binding["mapping_cid"], f"{segment_id} mapping binding drift")
        require(npm_profile["profile_id"] == proof["profile_id"], f"{segment_id} profile binding drift")
        require(binding["api_version"] == proof["api_version"], f"{segment_id} API generation drift")
        outcomes = [_field_outcome(record, proof) for record in field_contract["field_catalog"]]
        counts = Counter(item["path_qualified_category"] for item in outcomes)
        require(
            counts == Counter({CATEGORY_CLASSIFIED: 38, CATEGORY_SAVED_NO_SETTER: 0, CATEGORY_DERIVED: 13, CATEGORY_OUTSIDE: 248}),
            f"{segment_id} 299-outcome partition drift",
        )
        require(
            all(bool(item["setter_before_matching_save_paths"]) == item["classified_stored_target"] for item in outcomes),
            f"{segment_id} classified setter-path coverage drift",
        )
        require(
            all(not item["setter_before_matching_save_paths"] for item in outcomes if item["derived_query_field"] or item["outside_npm_transfer_store_target_closure"]),
            f"{segment_id} non-classified setter-path drift",
        )
        require(
            {
                item["field"]
                for item in outcomes
                if item["entity"] == "Transaction" and item["setter_before_matching_save_paths"]
            }
            == set(TRANSACTION_FIELDS),
            f"{segment_id} Transaction setter-path field drift",
        )
        require(sum(item["required_absent_overlay"] for item in outcomes) == 33, f"{segment_id} required absence drift")
        boundary = {
            "segment_id": segment_id,
            "network": binding["network"],
            "deployment": binding["deployment"],
            "start_block_inclusive": binding["start_block_inclusive"],
            "end_block_inclusive": binding["end_block_inclusive"],
            "graft": binding["graft"],
        }
        semantic = {
            "handler_id": HANDLER_ID,
            "segment_boundary": boundary,
            "mapping_cid": proof["mapping_cid"],
            "profile_id": proof["profile_id"],
            "generation": proof["generation"],
            "api_version": proof["api_version"],
            "path_contract": proof["path_contract"],
            "relation_field_authority": proof["relation_field_authority"],
            "field_outcome_summary": {
                "field_outcome_count": 299,
                "classified_stored_target_count": counts[CATEGORY_CLASSIFIED],
                "saved_target_stored_no_setter_count": counts[CATEGORY_SAVED_NO_SETTER],
                "derived_query_field_count": counts[CATEGORY_DERIVED],
                "outside_store_target_closure_count": counts[CATEGORY_OUTSIDE],
                "required_absent_overlay_count": sum(item["required_absent_overlay"] for item in outcomes),
            },
            "field_outcomes": outcomes,
            "complete_path_qualified_static_transfer_contract": True,
            "complete_entity_histories": False,
            "graph_store_persistence_proven": False,
        }
        provenance = {
            "segment_boundary": boundary,
            "mapping_cid": proof["mapping_cid"],
            "profile_id": proof["profile_id"],
            "schema_cid": binding["schema_cid"],
            "api_version": binding["api_version"],
            "retained_wasm": proof["retained_wasm"],
            "handler_binding": proof["handler_binding"],
            "mapping_proof_sha256": canonical_sha256(proof),
            "parent_field_semantic_sha256": parent["semantic_surface_sha256"],
            "parent_field_provenance_sha256": parent["provenance_surface_sha256"],
        }
        results.append({
            **boundary,
            "semantic_surface": semantic,
            "semantic_surface_sha256": canonical_sha256(semantic),
            "provenance_surface": provenance,
            "provenance_surface_sha256": canonical_sha256(provenance),
            "execution_model": "undecided",
            "backfill_allowed": False,
        })
    require(len(results) == 8, "segment result count drift")
    require(sum(len(item["semantic_surface"]["field_outcomes"]) for item in results) == 2392, "aggregate field outcome drift")
    return results


def build_segment_diffs(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
    for left, right in itertools.combinations(segments, 2):
        semantic_paths = json_diff_paths(left["semantic_surface"], right["semantic_surface"])
        provenance_paths = json_diff_paths(left["provenance_surface"], right["provenance_surface"])
        require(semantic_paths and provenance_paths, "empty recursive segment diff")
        results.append({
            "left_segment_id": left["segment_id"],
            "right_segment_id": right["segment_id"],
            "recursive_semantic_diff_paths": semantic_paths,
            "recursive_provenance_diff_paths": provenance_paths,
            "left_semantic_surface_sha256": left["semantic_surface_sha256"],
            "right_semantic_surface_sha256": right["semantic_surface_sha256"],
            "left_provenance_surface_sha256": left["provenance_surface_sha256"],
            "right_provenance_surface_sha256": right["provenance_surface_sha256"],
            "complete_entity_histories_compared": False,
            "boundary_state_compared": False,
            "graph_oracle_compared": False,
        })
    require(len(results) == 28, "pairwise diff count drift")
    return results


def truth_boundary() -> dict[str, bool]:
    require(len(TRUE_FLAGS) == len(set(TRUE_FLAGS)), "duplicate true gate")
    require(len(FALSE_FLAGS) == len(set(FALSE_FLAGS)), "duplicate false gate")
    require(set(TRUE_FLAGS).isdisjoint(FALSE_FLAGS), "truth gate overlap")
    return {**{key: True for key in TRUE_FLAGS}, **{key: False for key in FALSE_FLAGS}}


def load_sources(
    root: Path,
    *,
    recompute_wat: bool = True,
    wasm2wat: Path | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    require(raw_sha256(FIELD_VERIFIER_PATH) == FIELD_VERIFIER_SHA256, "field verifier digest drift")
    require(raw_sha256(WRITER_VERIFIER_PATH) == WRITER_VERIFIER_SHA256, "writer verifier digest drift")
    direct = {name: _bind(root, spec) for name, spec in SOURCE_SPECS.items()}

    field_sources = FIELD.load_sources(
        root,
        recompute_wat=recompute_wat,
        wasm2wat=wasm2wat,
    )
    recomputed_field = FIELD.verify_contract(
        root,
        sources=field_sources,
        recompute_wat=False,
    )
    require(
        canonical_bytes(recomputed_field) == canonical_bytes(direct["segment_field_semantics_v2"]),
        "direct field-semantics v2 contract differs from recomputation",
    )
    require(field_sources["ancestry"] == direct["ancestry_v2"], "field authority ancestry root drift")
    require(field_sources["writer_compatibility"] == direct["writer_compatibility_v3"], "field authority writer root drift")
    require(field_sources["segment_writer_matrix"] == direct["segment_writer_matrix_v1"], "field authority matrix root drift")
    require(field_sources["segment_field_semantics_v1"] == direct["segment_field_semantics_v1"], "field authority v1 root drift")

    catalog_summary = _schema_catalog(recomputed_field)
    ancestry = direct["ancestry_v2"]
    artifacts = {item["cid"]: item for item in ancestry["artifacts"]}
    schema_inventories = {item["cid"]: item for item in ancestry["schema_inventories"]}
    schema_bindings = []
    catalog_projection = [
        {
            "entity": item["entity"],
            "field": item["field"],
            "type": item["type"],
            "directives": item["directives"],
            "storage": item["storage"],
        }
        for item in recomputed_field["field_catalog"]
    ]
    catalog_projection.sort(key=lambda item: (item["entity"], item["field"]))
    for cid, (byte_count, digest) in sorted(SCHEMA_ARTIFACTS.items()):
        require(cid in artifacts and cid in schema_inventories, f"schema authority missing: {cid}")
        artifact = artifacts[cid]
        path = root / artifact["path"]
        require(path.is_file(), f"schema artifact missing: {cid}")
        require(path.stat().st_size == byte_count == artifact["bytes"], f"schema byte count drift: {cid}")
        require(raw_sha256(path) == digest == artifact["sha256"], f"schema digest drift: {cid}")
        direct_projection = [
            {
                "entity": entity["name"],
                "field": field["name"],
                "type": field["type"],
                "directives": field["directives"],
                "storage": field["storage"],
            }
            for entity in schema_inventories[cid]["entities"]
            for field in entity["fields"]
        ]
        direct_projection.sort(key=lambda item: (item["entity"], item["field"]))
        require(direct_projection == catalog_projection, f"direct schema catalog drift: {cid}")
        schema_bindings.append({
            "cid": cid,
            "path": artifact["path"],
            "bytes": byte_count,
            "raw_sha256": digest,
            "field_count": len(direct_projection),
            "field_catalog_sha256": canonical_sha256(direct_projection),
        })

    mapping_artifacts = {item["cid"]: item for item in ancestry["artifacts"]}
    mapping_inventories = {item["cid"]: item for item in ancestry["mapping_writer_inventories"]}
    require(set(MAPPING_EXPECTATIONS) <= set(mapping_artifacts), "mapping artifact population drift")
    require(set(MAPPING_EXPECTATIONS) <= set(mapping_inventories), "mapping inventory population drift")
    require(recompute_wat, "NPM Transfer v2 requires direct retained-WAT recomputation")
    executable = WRITER.resolve_wasm2wat(wasm2wat)
    proofs = [
        prove_mapping(root, executable, mapping_inventories[cid], mapping_artifacts[cid])
        for cid in sorted(MAPPING_EXPECTATIONS)
    ]
    require(len(proofs) == 6, "unique NPM mapping proof count drift")
    return {
        "direct": direct,
        "field_sources": field_sources,
        "field_contract": recomputed_field,
        "catalog_summary": catalog_summary,
        "schema_bindings": schema_bindings,
        "mapping_proofs": proofs,
        "wasm2wat": executable,
    }


def _aggregate_counts(
    proofs: list[dict[str, Any]],
    segments: list[dict[str, Any]],
) -> dict[str, Any]:
    fields = (
        "function_count",
        "direct_call_count",
        "direct_target_count",
        "memory_write_count",
        "generic_setter_site_count",
        "named_setter_invocation_count",
        "store_get_site_count",
        "store_set_site_count",
        "call_indirect_count",
    )
    unique = {
        field: sum(item["reachable_closure_summary"][field] for item in proofs)
        for field in fields
    }
    proof_by_cid = {item["mapping_cid"]: item for item in proofs}
    weighted_proofs = [proof_by_cid[item["semantic_surface"]["mapping_cid"]] for item in segments]
    weighted = {
        field: sum(item["reachable_closure_summary"][field] for item in weighted_proofs)
        for field in fields
    }
    require(
        unique == {
            "function_count": 454,
            "direct_call_count": 2006,
            "direct_target_count": 490,
            "memory_write_count": 1270,
            "generic_setter_site_count": 166,
            "named_setter_invocation_count": 116,
            "store_get_site_count": 12,
            "store_set_site_count": 18,
            "call_indirect_count": 2,
        },
        "unique-six aggregate closure drift",
    )
    require(
        weighted == {
            "function_count": 628,
            "direct_call_count": 2654,
            "direct_target_count": 676,
            "memory_write_count": 1614,
            "generic_setter_site_count": 210,
            "named_setter_invocation_count": 174,
            "store_get_site_count": 16,
            "store_set_site_count": 24,
            "call_indirect_count": 2,
        },
        "eight-binding aggregate closure drift",
    )
    return {
        "unique_six_mapping_physical_totals": unique,
        "eight_binding_weighted_physical_totals": weighted,
        "unique_six_lexical_semantic_field_invocation_count": 234,
        "unique_six_maximum_expanded_new_path_field_invocation_count": 264,
        "unique_six_physical_store_set_site_count": 18,
        "unique_six_maximum_expanded_new_path_store_set_count": 24,
        "eight_binding_lexical_semantic_field_invocation_count": 312,
        "eight_binding_maximum_expanded_new_path_field_invocation_count": 352,
        "eight_binding_physical_store_set_site_count": 24,
        "eight_binding_maximum_expanded_new_path_store_set_count": 32,
        "field_outcome_count": 2392,
        "classified_stored_target_outcome_count": 304,
        "saved_target_stored_no_setter_outcome_count": 0,
        "derived_query_field_outcome_count": 104,
        "outside_store_target_closure_outcome_count": 1984,
        "required_absent_overlay_outcome_count": 264,
    }


def expected_contract_from_sources(sources: dict[str, Any]) -> dict[str, Any]:
    proofs = sources["mapping_proofs"]
    field_contract = sources["field_contract"]
    ancestry = sources["direct"]["ancestry_v2"]
    segments = build_segments(field_contract, ancestry, proofs)
    diffs = build_segment_diffs(segments)
    aggregate = _aggregate_counts(proofs, segments)
    source_contracts = {
        name: {
            "path": str(spec[0]),
            "contract_version": spec[1],
            "raw_sha256": spec[2],
            "canonical_sha256": spec[3],
            "recomputed_directly": True,
        }
        for name, spec in SOURCE_SPECS.items()
    }
    return {
        "format_version": 1,
        "contract_version": CONTRACT_VERSION,
        "mode": "complete-path-qualified-static-npm-transfer-schema-api-effect-matrix",
        "scope": {
            "networks": ["mainnet", "base"],
            "segment_binding_count": 8,
            "unique_npm_wasm_count": 6,
            "handler": HANDLER_ID,
            "schema_field_count_per_segment": 299,
            "field_outcome_count": 2392,
            "classified_stored_target_count_per_segment": 38,
            "saved_target_stored_no_setter_count_per_segment": 0,
            "derived_query_field_count_per_segment": 13,
            "outside_store_target_closure_count_per_segment": 248,
            "required_absent_overlay_count_per_segment": 33,
            "pairwise_recursive_diff_count": 28,
            "issue_acceptance_checkbox_completed": False,
            "claim": "complete path-qualified retained-WAT schema-API effect contract for NonfungiblePositionManager.handleTransfer across eight segment bindings and six unique WASMs; it binds receiver, key, setter, constructor, store and branch order without promoting imported values, store persistence, histories, runtime parity, backfill or readiness",
        },
        "authority_contract": {
            "implementation_base_commit": IMPLEMENTATION_BASE_COMMIT,
            "implementation_base_tree": IMPLEMENTATION_BASE_TREE,
            "semantic_authority": "exact retained deployed NonfungiblePositionManager mapping WASM regenerated with WABT 1.0.35",
            "schema_authority": "three exact retained GraphQL schema artifacts independently match the recomputed 299-field v2 catalog",
            "physical_vs_semantic_boundary": "physical symbols and sites are enumerated independently from 39 lexical semantic invocations, 38 distinct field authorities, and path-expanded invocation counts",
            "no_setter_boundary": "the sixteen other Position fields on the accepted existing path have no setter before Position.save; no preserved, unchanged, value-stable, or persistence claim is made",
            "fatal_boundary": "non-try Factory getPool failure is bound only through the pre-fatal prefix; post-fatal execution and rollback are not modeled",
            "composition_boundary": "NPM Transfer-only static provenance does not complete NPM runtime observation work in issue 37 or the full multi-handler writer-provenance acceptance in issue 38",
        },
        "toolchain": {
            "name": "WABT wasm2wat",
            "version": "1.0.35",
            "command": ["wasm2wat", "--generate-names", "<retained-npm-mapping-wasm>"],
            "ci_linux_release_archive_sha256": "cb3d22440273b1e8ee641e622b7a32222d97b519ad46169b1f8fcc6ce9af0b9b",
            "reviewed_macos_arm64_binary_sha256": "df365308ea4fb092fde16ad0786c7c378bfe82863e460074a9574323f28e17da",
            "cross_platform_authority": "the executable version and six exact generated WAT digests are enforced; platform executable bytes are not asserted equal",
        },
        "source_verifiers": {
            "segment_field_semantics_v2": {
                "path": str(FIELD_VERIFIER_PATH.relative_to(REPOSITORY)),
                "raw_sha256": FIELD_VERIFIER_SHA256,
            },
            "writer_semantics": {
                "path": str(WRITER_VERIFIER_PATH.relative_to(REPOSITORY)),
                "raw_sha256": WRITER_VERIFIER_SHA256,
            },
        },
        "source_contracts": source_contracts,
        "source_contracts_sha256": canonical_sha256(source_contracts),
        "schema_catalog": sources["catalog_summary"],
        "direct_schema_bindings": sources["schema_bindings"],
        "mapping_proofs": proofs,
        "aggregate_counts": aggregate,
        "segments": segments,
        "segment_diffs": diffs,
        "residual_blockers": {
            "semantic": [
                "contract-call returned values, block-pointer timing, error classes, numeric meaning, string formatting, address conversion, and arbitrary aliases remain unproved",
                "store.get contents and event-ordinal visibility, persistence, rollback, post-fatal behavior, VID and PoI remain unproved",
                "the sixteen other Position fields saved on the existing path have no setter before save and are deliberately not described as preserved, unchanged, or value-stable",
                "shared Position, PositionSnapshot, and Transaction histories and last-writer behavior remain incomplete",
            ],
            "execution": [
                "runtime population, package identity, scheduler, output and writer-package consumption remain unimplemented or unproved",
                "continuity, oracle, logical/physical/PoI parity, checkpoint authority, backfill, deployment, production and readiness remain false",
                "no issue 37 or issue 38 checkbox is completed",
            ],
        },
        "truth_boundary": truth_boundary(),
    }


def verify_contract(
    root: Path,
    actual: dict[str, Any] | None = None,
    *,
    sources: dict[str, Any] | None = None,
    recompute_wat: bool = True,
    wasm2wat: Path | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    verified = sources or load_sources(root, recompute_wat=recompute_wat, wasm2wat=wasm2wat)
    expected = expected_contract_from_sources(verified)
    if actual is None:
        path = root / CONTRACT_PATH
        require(path.is_file(), f"NPM Transfer v2 contract missing: {CONTRACT_PATH}")
        actual = load_json(path)
        require(path.read_text() == render(actual), "NPM Transfer v2 contract byte rendering drift")
    require(canonical_bytes(actual) == canonical_bytes(expected), "NPM Transfer v2 contract differs from generated proof")
    truth = actual["truth_boundary"]
    require(set(truth) == set(TRUE_FLAGS) | set(FALSE_FLAGS), "truth-boundary key drift")
    for field in TRUE_FLAGS:
        require(truth[field] is True, f"proved gate drift: {field}")
    for field in FALSE_FLAGS:
        require(truth[field] is False, f"unproved gate promoted: {field}")
    return expected


def write_contract(root: Path, wasm2wat: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    sources = load_sources(root, recompute_wat=True, wasm2wat=wasm2wat)
    expected = expected_contract_from_sources(sources)
    path = root / CONTRACT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(expected))
    return expected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPOSITORY)
    parser.add_argument("--wasm2wat", type=Path)
    parser.add_argument("--write-contract", action="store_true")
    args = parser.parse_args()
    try:
        result = (
            write_contract(args.root, args.wasm2wat)
            if args.write_contract
            else verify_contract(args.root, wasm2wat=args.wasm2wat)
        )
    except (OSError, VerificationError, FIELD.VerificationError, WRITER.VerificationError) as error:
        print(f"NPM Transfer v2 verification failed: {error}", file=sys.stderr)
        return 1
    print(
        "verified Uniswap V3 NPM Transfer v2: "
        f"{result['scope']['segment_binding_count']} bindings, "
        f"{result['scope']['unique_npm_wasm_count']} WASMs, "
        f"{result['scope']['field_outcome_count']} outcomes, "
        f"{len(result['segment_diffs'])} diffs; no issue checkbox completed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
