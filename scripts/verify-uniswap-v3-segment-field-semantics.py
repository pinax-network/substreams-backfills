#!/usr/bin/env python3
"""Generate and fail-closed verify the scoped Uniswap V3 field-semantics supplement."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import sys
from pathlib import Path
from typing import Any


CONTRACT_PATH = Path("uniswap-v3/segment-field-semantics/v1/contract.json")
CONTRACT_VERSION = "uniswap-v3-segment-field-semantics/v1"

SOURCE_SPECS = {
    "ancestry": (
        "uniswap-v3/graft-ancestry/v2/contract.json",
        "uniswap-v3-graft-ancestry/v2",
        "ae8c3e0099fedf2879b3071c2bcf545050fa4d448d0154fa6b895618bb8e203e",
    ),
    "writer_compatibility": (
        "uniswap-v3/graft-ancestry/v2/writer-compatibility.json",
        "uniswap-v3-writer-compatibility/v3",
        "259481724561d5aa725c17f90b5a19ea93ad6f7cd6074cf2cb8a8661c39f81c4",
    ),
    "segment_writer_matrix": (
        "uniswap-v3/segment-writer-matrix/v1/contract.json",
        "uniswap-v3-segment-writer-matrix/v1",
        "7f6d1a34a8c885fe5ddcd81895818ba7ae8a0d736d541b881c1cc7cd54275161",
    ),
    "execution_order": (
        "uniswap-v3/execution-order/v1/contract.json",
        "uniswap-v3-execution-order/v1",
        "241e970cfcec4d76610b29a10141d3bff2512d80454a6308594f3db23621cde2",
    ),
    "position_runtime": (
        "uniswap-v3/position-reducer/contract-v1.json",
        "uniswap-v3-position-reducer-runtime/v1",
        "3099c3f08208cf46ce68df3433dd5b757436a3a7e315daec3f0d96bf242185c1",
    ),
    "position_semantics": (
        "uniswap-v3/position-reducer/position-reducer-v1.json",
        "uniswap-v3-position-reducer/v1",
        "f449c4612413f381486de25c8045ea9d46899942b5d78ab12e477a77b261dec0",
    ),
    "transaction_runtime": (
        "uniswap-v3/transaction-reducer/contract-v1.json",
        "uniswap-v3-transaction-reducer-runtime/v1",
        "c9f355d141720dfda4347b4ef6cb5350a96803db31cf4770f035b5efca9def7f",
    ),
    "transaction_semantics": (
        "uniswap-v3/transaction-reducer/transaction-reducer-v1.json",
        "uniswap-v3-transaction-reducer/v1",
        "83268d10f0ef3008d6d30fc3b6fd304fd46a067866b4284344fe468397878246",
    ),
    "flash_runtime": (
        "uniswap-v3/flash-reducer/contract-v1.json",
        "uniswap-v3-flash-reducer-runtime/v1",
        "0b24a14dcf460f9eda75addf7ffd6ae4832cd9c611a56b6f2591972767966168",
    ),
    "flash_semantics": (
        "uniswap-v3/flash-reducer/flash-reducer-v1.json",
        "uniswap-v3-flash-reducer/v1",
        "8951469c026898de69d1a76381539eda3ddfdf094051d2b4b7f4295c860dfa43",
    ),
    "npm_runtime": (
        "uniswap-v3/npm-handler-reducer/contract-v1.json",
        "uniswap-v3-npm-handler-reducer-runtime/v1",
        "6f46d5cca49506c3ee0622351324ccb62a459916f0e41f3772fe021e0e185dd6",
    ),
    "npm_semantics": (
        "uniswap-v3/npm-handler-reducer/npm-handler-reducer-v1.json",
        "uniswap-v3-npm-handler-reducer/v1",
        "86cf89d8ffe66ac9f4aeda468988306ccc9dca1dbfd2641f132f12529207b143",
    ),
    "segment_profiles": (
        "uniswap-v3/writer-runtime/segment-profiles-v1.json",
        "uniswap-v3-writer-runtime-segment-profiles/v1",
        "2b6635c061a7a0bfce39430c71c41dacc1567f095fe41134e890a697aa27f823",
    ),
}

NPM_HANDLERS = [
    "NonfungiblePositionManager.handleIncreaseLiquidity",
    "NonfungiblePositionManager.handleDecreaseLiquidity",
    "NonfungiblePositionManager.handleCollect",
    "NonfungiblePositionManager.handleTransfer",
]
FLASH_HANDLER = "Pool.handleFlash"
REQUIRED_ABSENT_ENTITIES = ["Collect", "Flash", "TickHourData"]

CERTIFIED_FIELDS = {
    "Transaction": {
        "id": ("ID!", ["npm.transaction.id"]),
        "blockNumber": ("BigInt!", ["npm.transaction.block_number"]),
        "timestamp": ("BigInt!", ["npm.transaction.timestamp"]),
        "gasUsed": ("BigInt!", ["npm.transaction.gas_used"]),
        "gasPrice": ("BigInt!", ["npm.transaction.gas_price"]),
    },
    "Position": {
        "id": ("ID!", ["npm.position.identity"]),
        "owner": ("Bytes!", ["npm.position.owner"]),
        "liquidity": ("BigInt!", ["npm.position.liquidity"]),
        "depositedToken0": ("BigDecimal!", ["npm.position.deposited_token0"]),
        "depositedToken1": ("BigDecimal!", ["npm.position.deposited_token1"]),
        "withdrawnToken0": ("BigDecimal!", ["npm.position.withdrawn_token0"]),
        "withdrawnToken1": ("BigDecimal!", ["npm.position.withdrawn_token1"]),
        "collectedFeesToken0": ("BigDecimal!", ["npm.position.collected_fees_token0"]),
        "collectedFeesToken1": ("BigDecimal!", ["npm.position.collected_fees_token1"]),
        "transaction": ("Transaction!", ["npm.position.creation_transaction"]),
        "feeGrowthInside0LastX128": ("BigInt!", ["npm.position.fee_growth_inside0"]),
        "feeGrowthInside1LastX128": ("BigInt!", ["npm.position.fee_growth_inside1"]),
    },
    "PositionSnapshot": {
        "id": ("ID!", ["npm.snapshot.identity"]),
        "owner": ("Bytes!", ["npm.snapshot.copy_position"]),
        "position": ("Position!", ["npm.snapshot.position"]),
        "blockNumber": ("BigInt!", ["npm.snapshot.block_number"]),
        "timestamp": ("BigInt!", ["npm.snapshot.timestamp"]),
        "liquidity": ("BigInt!", ["npm.snapshot.copy_position"]),
        "depositedToken0": ("BigDecimal!", ["npm.snapshot.copy_position"]),
        "depositedToken1": ("BigDecimal!", ["npm.snapshot.copy_position"]),
        "withdrawnToken0": ("BigDecimal!", ["npm.snapshot.copy_position"]),
        "withdrawnToken1": ("BigDecimal!", ["npm.snapshot.copy_position"]),
        "collectedFeesToken0": ("BigDecimal!", ["npm.snapshot.copy_position"]),
        "collectedFeesToken1": ("BigDecimal!", ["npm.snapshot.copy_position"]),
        "transaction": ("Transaction!", ["npm.snapshot.current_transaction"]),
        "feeGrowthInside0LastX128": ("BigInt!", ["npm.snapshot.copy_position"]),
        "feeGrowthInside1LastX128": ("BigInt!", ["npm.snapshot.copy_position"]),
    },
    "Pool": {
        "feeGrowthGlobal0X128": ("BigInt!", ["flash.pool.fee_growth_0"]),
        "feeGrowthGlobal1X128": ("BigInt!", ["flash.pool.fee_growth_1"]),
    },
}

RESIDUAL_CERTIFIED_ENTITY_FIELDS = {
    "Position": ["pool", "token0", "token1", "tickLower", "tickUpper"],
    "PositionSnapshot": ["pool"],
}


class VerificationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise VerificationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json_strict(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(), object_pairs_hook=reject_duplicate_keys)
    except (OSError, json.JSONDecodeError) as error:
        raise VerificationError(f"cannot load {path}: {error}") from error
    require(isinstance(value, dict), f"{path} must contain one JSON object")
    return value


def raw_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


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


def source_record(path: str, version: str, digest: str) -> dict[str, Any]:
    return {"path": path, "contract_version": version, "raw_sha256": digest}


def evidence_ref(source_contract: str, json_path: str) -> dict[str, str]:
    return {"source_contract": source_contract, "json_path": json_path}


def load_sources(root: Path) -> dict[str, dict[str, Any]]:
    sources: dict[str, dict[str, Any]] = {}
    for name, (relative, version, digest) in SOURCE_SPECS.items():
        path = root / relative
        require(path.is_file(), f"required source missing: {relative}")
        require(raw_sha256(path) == digest, f"required source raw digest drift: {relative}")
        value = load_json_strict(path)
        actual_version = value.get("contract_version", value.get("profile_contract_version"))
        require(actual_version == version, f"required source contract version drift: {relative}")
        sources[name] = value
    digest_cache: dict[str, str] = {}

    def verify_local_artifacts(value: Any, context: str) -> None:
        if isinstance(value, dict):
            relative = value.get("path")
            digest = value.get("sha256")
            if isinstance(relative, str) and relative.startswith("uniswap-v3/") and isinstance(digest, str):
                path = root / relative
                require(path.is_file(), f"pinned local artifact missing at {context}: {relative}")
                actual = digest_cache.setdefault(relative, raw_sha256(path))
                require(actual == digest, f"pinned local artifact digest drift at {context}: {relative}")
            for key, child in value.items():
                verify_local_artifacts(child, f"{context}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                verify_local_artifacts(child, f"{context}[{index}]")

    for name, value in sources.items():
        verify_local_artifacts(value, name)
    return sources


def field_rule_catalog() -> dict[str, dict[str, Any]]:
    npm_evidence = [
        evidence_ref("npm_semantics", "$.execution_contract"),
        evidence_ref("npm_semantics", "$.npm_profiles"),
        evidence_ref("position_semantics", "$.execution_contract"),
        evidence_ref("position_semantics", "$.npm_profiles"),
        evidence_ref("transaction_semantics", "$.execution_contract"),
    ]
    flash_evidence = [
        evidence_ref("flash_semantics", "$.execution_contract"),
        evidence_ref("flash_semantics", "$.segments"),
        evidence_ref("writer_compatibility", "$.pool_flash_evidence"),
    ]
    return {
        "npm.transaction.id": {
            "handlers": NPM_HANDLERS,
            "rule": "on every reached loadTransaction helper, upsert lowercase 0x plus the exact 32-byte transaction hash",
            "evidence": npm_evidence,
        },
        "npm.transaction.block_number": {
            "handlers": NPM_HANDLERS,
            "rule": "on every reached loadTransaction helper, overwrite with the exact event block number",
            "evidence": npm_evidence,
        },
        "npm.transaction.timestamp": {
            "handlers": NPM_HANDLERS,
            "rule": "on every reached loadTransaction helper, overwrite with the exact event block timestamp",
            "evidence": npm_evidence,
        },
        "npm.transaction.gas_used": {
            "handlers": NPM_HANDLERS,
            "rule": "segment-selected: apiVersion 0.0.4 stores transaction gas_limit; apiVersion 0.0.7 stores zero; receipt gas is never used",
            "evidence": npm_evidence,
        },
        "npm.transaction.gas_price": {
            "handlers": NPM_HANDLERS,
            "rule": "on every reached loadTransaction helper, overwrite with the exact transaction gas price",
            "evidence": npm_evidence,
        },
        "npm.position.identity": {
            "handlers": NPM_HANDLERS,
            "rule": "new identity uses the decimal NPM token id; an existing Position id is preserved",
            "evidence": npm_evidence,
        },
        "npm.position.owner": {
            "handlers": NPM_HANDLERS,
            "rule": "a provisional new Position starts at zero address; Transfer assigns event.to; other handlers preserve owner",
            "evidence": npm_evidence,
        },
        "npm.position.liquidity": {
            "handlers": NPM_HANDLERS,
            "rule": "Increase adds event liquidity, Decrease subtracts event liquidity, Collect and Transfer preserve the prior value",
            "evidence": npm_evidence,
        },
        "npm.position.deposited_token0": {
            "handlers": NPM_HANDLERS,
            "rule": "Increase adds decimal(event.amount0, token0.decimals); other handlers preserve the prior value",
            "evidence": npm_evidence,
        },
        "npm.position.deposited_token1": {
            "handlers": NPM_HANDLERS,
            "rule": "Increase adds decimal(event.amount1, token1.decimals); other handlers preserve the prior value",
            "evidence": npm_evidence,
        },
        "npm.position.withdrawn_token0": {
            "handlers": NPM_HANDLERS,
            "rule": "Decrease adds decimal(event.amount0, token0.decimals); other handlers preserve the prior value",
            "evidence": npm_evidence,
        },
        "npm.position.withdrawn_token1": {
            "handlers": NPM_HANDLERS,
            "rule": "Decrease adds decimal(event.amount1, token1.decimals); other handlers preserve the prior value",
            "evidence": npm_evidence,
        },
        "npm.position.collected_fees_token0": {
            "handlers": NPM_HANDLERS,
            "rule": "Collect uses the exact segment NPM profile final expression; other handlers preserve the prior value",
            "evidence": npm_evidence + [evidence_ref("writer_compatibility", "$.npm_semantic_profiles")],
        },
        "npm.position.collected_fees_token1": {
            "handlers": NPM_HANDLERS,
            "rule": "Collect uses the exact segment NPM profile final expression; other handlers preserve the prior value",
            "evidence": npm_evidence + [evidence_ref("writer_compatibility", "$.npm_semantic_profiles")],
        },
        "npm.position.creation_transaction": {
            "handlers": NPM_HANDLERS,
            "rule": "a new Position stores its first successfully persisted identity-creation transaction; existing Position.transaction is never overwritten",
            "evidence": npm_evidence,
        },
        "npm.position.fee_growth_inside0": {
            "handlers": NPM_HANDLERS,
            "rule": "new identity starts from positions(); Increase, Decrease, and Collect replace it from successful try_positions; revert and Transfer preserve it",
            "evidence": npm_evidence,
        },
        "npm.position.fee_growth_inside1": {
            "handlers": NPM_HANDLERS,
            "rule": "new identity starts from positions(); Increase, Decrease, and Collect replace it from successful try_positions; revert and Transfer preserve it",
            "evidence": npm_evidence,
        },
        "npm.snapshot.identity": {
            "handlers": NPM_HANDLERS,
            "rule": "accepted handler stores token id plus # plus block number; the last accepted same-Position event in a block overwrites it",
            "evidence": npm_evidence,
        },
        "npm.snapshot.position": {
            "handlers": NPM_HANDLERS,
            "rule": "copy the accepted Position decimal token id",
            "evidence": npm_evidence,
        },
        "npm.snapshot.block_number": {
            "handlers": NPM_HANDLERS,
            "rule": "copy the exact current block number",
            "evidence": npm_evidence,
        },
        "npm.snapshot.timestamp": {
            "handlers": NPM_HANDLERS,
            "rule": "copy the exact current block timestamp",
            "evidence": npm_evidence,
        },
        "npm.snapshot.copy_position": {
            "handlers": NPM_HANDLERS,
            "rule": "copy the accepted post-handler value of the same-named certified Position field",
            "evidence": npm_evidence,
        },
        "npm.snapshot.current_transaction": {
            "handlers": NPM_HANDLERS,
            "rule": "store the current accepted handler transaction; last accepted same-Position event in a block overwrites it",
            "evidence": npm_evidence,
        },
        "flash.pool.fee_growth_0": {
            "handlers": [FLASH_HANDLER],
            "rule": "after Pool load, decode exact 32-byte uint256 from feeGrowthGlobal0X128() calldata f3058399; persist only after fee1 also succeeds",
            "evidence": flash_evidence,
        },
        "flash.pool.fee_growth_1": {
            "handlers": [FLASH_HANDLER],
            "rule": "after fee0 succeeds, decode exact 32-byte uint256 from feeGrowthGlobal1X128() calldata 46141319; atomically save both fields once",
            "evidence": flash_evidence,
        },
    }


def schema_catalog(matrix: dict[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    segments = matrix["segments"]
    require(len(segments) == 8, "segment writer matrix must contain exactly eight segments")
    catalogs: list[dict[str, dict[str, dict[str, Any]]]] = []
    for segment in segments:
        entities: dict[str, dict[str, dict[str, Any]]] = {}
        for entity in segment["entity_field_matrix"]:
            fields = {
                field["name"]: {
                    "type": field["type"],
                    "storage": field["storage"],
                    "directives": field["directives"],
                }
                for field in entity["fields"]
            }
            require(len(fields) == len(entity["fields"]), f"duplicate schema field in {entity['entity']}")
            entities[entity["entity"]] = fields
        require(len(entities) == len(segment["entity_field_matrix"]), "duplicate schema entity")
        catalogs.append(entities)
    for catalog in catalogs[1:]:
        require(catalog == catalogs[0], "schema catalog differs across retained segments")
    return catalogs[0]


def population_contract(matrix: dict[str, Any]) -> dict[str, Any]:
    taxonomy = matrix["population_taxonomy"]
    require(taxonomy["allowed_classifications"] == ["required_nonempty", "conditional", "required_absent"], "population taxonomy drift")
    require(taxonomy["required_nonempty_certified_entities"] == [], "required-nonempty certification unexpectedly promoted")
    require(taxonomy["required_absent_entities"] == REQUIRED_ABSENT_ENTITIES, "required-absent entity set drift")
    require(len(taxonomy["conditional_entities"]) == 17, "conditional entity set drift")
    require(taxonomy["runtime_population_certified"] is False, "runtime population unexpectedly promoted")
    return {
        "classification_scope": "all eight retained mainnet/Base mapping segments",
        "required_nonempty": [],
        "conditional": taxonomy["conditional_entities"],
        "required_absent": taxonomy["required_absent_entities"],
        "runtime_population_certified": False,
        "required_nonempty_certified": False,
    }


def build_field_catalog(sources: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    matrix = sources["segment_writer_matrix"]
    writer = sources["writer_compatibility"]
    schema = schema_catalog(matrix)
    rules = field_rule_catalog()
    records: list[dict[str, Any]] = []

    for entity, fields in CERTIFIED_FIELDS.items():
        require(entity in matrix["population_taxonomy"]["conditional_entities"], f"{entity} must remain conditional")
        for field, (expected_type, rule_ids) in fields.items():
            require(field in schema[entity], f"certified schema field missing: {entity}.{field}")
            actual = schema[entity][field]
            require(actual == {"type": expected_type, "storage": "stored", "directives": ""}, f"certified schema field drift: {entity}.{field}")
            for rule_id in rule_ids:
                require(rule_id in rules, f"unknown field rule: {rule_id}")
            records.append(
                {
                    "entity": entity,
                    "field": field,
                    "type": expected_type,
                    "storage": "stored",
                    "population_classification": "conditional",
                    "completion_scope": "selected_handler_host_projection",
                    "complete_in_scope": True,
                    "complete_entity_history": False,
                    "rule_ids": rule_ids,
                    "schema_evidence": evidence_ref(
                        "segment_writer_matrix",
                        f"$.segments[*].entity_field_matrix[entity={entity}].fields[name={field}]",
                    ),
                }
            )

    absence_by_entity = {item["entity"]: item for item in writer["required_absence_certifications"]}
    require(set(absence_by_entity) == set(REQUIRED_ABSENT_ENTITIES), "required-absence certification set drift")
    for entity in REQUIRED_ABSENT_ENTITIES:
        evidence = absence_by_entity[entity]
        require(evidence["static_writer_absence_certified"] is True, f"{entity} static absence is not certified")
        require(evidence["matching_store_set_callsite_count"] == 0, f"{entity} has a store.set callsite")
        require(evidence["dynamic_store_set_target_count"] == 0, f"{entity} has a dynamic store.set target")
        require(evidence["indirect_store_set_reference_count"] == 0, f"{entity} has an indirect store.set reference")
        for field, actual in schema[entity].items():
            require(actual["storage"] == "stored", f"required-absent derived field unsupported: {entity}.{field}")
            records.append(
                {
                    "entity": entity,
                    "field": field,
                    "type": actual["type"],
                    "storage": "stored",
                    "population_classification": "required_absent",
                    "completion_scope": "retained_mapping_static_writer_closure",
                    "complete_in_scope": True,
                    "complete_entity_history": True,
                    "rule_ids": ["required_absence.no_store_set_target"],
                    "schema_evidence": evidence_ref(
                        "segment_writer_matrix",
                        f"$.segments[*].entity_field_matrix[entity={entity}].fields[name={field}]",
                    ),
                    "absence_evidence": {
                        "source_contract": "writer_compatibility",
                        "json_path": f"$.required_absence_certifications[entity={entity}]",
                        "source_record_sha256": canonical_sha256(evidence),
                    },
                }
            )

    require(len(records) == 67, "scoped field catalog must contain exactly 67 stored-field records")
    require(len({(item["entity"], item["field"]) for item in records}) == 67, "scoped field catalog contains duplicates")
    return records


def find_handler(segment: dict[str, Any], handler_id: str) -> dict[str, Any]:
    matches = [handler for handler in segment["handlers"] if handler["handler_id"] == handler_id]
    require(len(matches) == 1, f"expected one handler record for {handler_id} in {segment['segment_id']}")
    return matches[0]


def handler_provenance(handler: dict[str, Any]) -> dict[str, Any]:
    reachability = handler["conservative_entity_writer_reachability"]
    return {
        "handler_id": handler["handler_id"],
        "mapping_cid": handler["mapping_cid"],
        "exact_wat_export_target": handler["exact_wat_export_target"],
        "numeric_export_function_index": handler["numeric_export_function_index"],
        "body_binding": handler["body_binding"],
        "reachable_store_set_targets": reachability["reachable_store_set_targets"],
        "reachable_store_set_site_count": reachability["reachable_store_set_site_count"],
        "source_handler_record_sha256": canonical_sha256(handler),
    }


def build_segments(sources: dict[str, dict[str, Any]], population: dict[str, Any]) -> list[dict[str, Any]]:
    matrix_segments = sources["segment_writer_matrix"]["segments"]
    npm = sources["npm_semantics"]
    flash = sources["flash_semantics"]
    writer = sources["writer_compatibility"]
    npm_by_id = {item["segment_id"]: item for item in npm["segments"]}
    flash_by_id = {item["segment_id"]: item for item in flash["segments"]}
    writer_by_id = {item["segment_id"]: item for item in writer["segment_writer_contracts"]}
    npm_profiles = {item["profile_id"]: item for item in npm["npm_profiles"]}
    writer_profiles = {item["profile_id"]: item for item in writer["npm_semantic_profiles"]}
    require(len(npm_by_id) == len(flash_by_id) == len(writer_by_id) == 8, "upstream segment set must contain eight unique records")

    npm_execution = npm["execution_contract"]
    flash_execution = flash["execution_contract"]
    npm_runtime = sources["npm_runtime"]["reducer_contract"]
    position_runtime = sources["position_runtime"]["reducer_contract"]
    require(position_runtime["decimal_precision"] == 34, "Position decimal precision drift")
    require(position_runtime["uint_width_bits"] == 256, "Position uint width drift")
    require(npm_runtime["event_loop_count"] == 1, "joint NPM event loop count drift")
    results: list[dict[str, Any]] = []
    for matrix_segment in matrix_segments:
        segment_id = matrix_segment["segment_id"]
        require(segment_id in npm_by_id and segment_id in flash_by_id and segment_id in writer_by_id, f"segment alignment missing: {segment_id}")
        npm_segment = npm_by_id[segment_id]
        flash_segment = flash_by_id[segment_id]
        writer_segment = writer_by_id[segment_id]
        identity_keys = ["network", "start_block_inclusive", "end_block_inclusive", "deployment", "segment_id", "semantic_contract_sha256"]
        for key in identity_keys:
            require(npm_segment[key] == flash_segment[key], f"NPM/Flash segment {key} drift: {segment_id}")
        for key in identity_keys[:-1]:
            require(npm_segment[key] == matrix_segment[key], f"matrix/NPM segment {key} drift: {segment_id}")
        require(npm_segment["semantic_contract_sha256"] == matrix_segment["source_writer_semantic_contract_sha256"], f"semantic source hash drift: {segment_id}")

        npm_profile_id = npm_segment["npm_profile_id"]
        require(npm_profile_id in npm_profiles and npm_profile_id in writer_profiles, f"NPM profile missing: {npm_profile_id}")
        require(matrix_segment["profile_bindings"]["nonfungible_position_manager"]["profile_id"] == npm_profile_id, f"matrix NPM profile drift: {segment_id}")
        require(matrix_segment["profile_bindings"]["pool"]["profile_id"] == flash_segment["pool_profile_id"], f"matrix Pool profile drift: {segment_id}")
        require(npm_segment["nonfatal_errors"] == flash_segment["nonfatal_errors"], f"nonfatal policy drift: {segment_id}")

        npm_handlers = [handler_provenance(find_handler(matrix_segment, handler_id)) for handler_id in NPM_HANDLERS]
        for handler in npm_handlers:
            require(handler["reachable_store_set_targets"] == ["Position", "PositionSnapshot", "Transaction"], f"NPM writer closure drift: {handler['handler_id']} in {segment_id}")
        flash_handler = handler_provenance(find_handler(matrix_segment, FLASH_HANDLER))
        require(flash_handler["reachable_store_set_targets"] == ["Pool"], f"Flash writer closure drift: {segment_id}")

        semantic_surface = {
            "population": population,
            "numeric": {
                "decimal_significant_digits": position_runtime["decimal_precision"],
                "contract_uint_width_bits": position_runtime["uint_width_bits"],
            },
            "npm": {
                "profile_id": npm_profile_id,
                "source_profile_definition": writer_profiles[npm_profile_id]["definition"],
                "executable_profile": npm_profiles[npm_profile_id],
                "api_version": npm_segment["api_version"],
                "stored_gas_used_mode": npm_segment["stored_gas_used_mode"],
                "nonfatal_errors": npm_segment["nonfatal_errors"],
                "historical_guard_effective": npm_segment["historical_guard_effective"],
                "historical_guard": {
                    "block": npm_execution["historical_guard_block"],
                    "handlers": npm_execution["historical_guard_handlers"],
                    "order": npm_execution["historical_guard_order"],
                },
                "excluded_pool": npm_execution["excluded_pool"],
                "excluded_pool_handlers": npm_execution["excluded_pool_handlers"],
                "event_order": npm_execution["event_order"],
                "producer_corruption": npm_execution["producer_corruption"],
                "handler_atomicity": npm_execution["event_state"],
                "graph_call_cache": npm_execution["graph_call_cache"],
                "provisional_identity": npm_execution["provisional_identity"],
                "normal_return_orphans": npm_execution["normal_return_orphans"],
                "new_position_transaction_loads": npm_execution["new_position_transaction_loads"],
                "existing_position_transaction_loads": npm_execution["existing_position_transaction_loads"],
                "fee_refresh_handlers": npm_execution["fee_refresh_handlers"],
                "fee_refresh_revert": npm_execution["fee_refresh_revert"],
                "snapshot_handlers": npm_execution["snapshot_handlers"],
                "write_order": {
                    "new_position": npm_runtime["new_position_save_order"],
                    "existing_position": npm_runtime["existing_position_save_order"],
                    "duplicate_transaction_saves_observable": npm_runtime["duplicate_transaction_saves_observable"],
                },
                "fatal_error": npm_execution["fatal_error"],
                "post_fatal_execution": npm_execution["post_fatal_execution"],
                "nonfatal_error": npm_execution["nonfatal_error"],
                "graph_call_scope": npm_execution["graph_call_scope"],
                "token_read_scope": npm_execution["token_read_scope"],
            },
            "flash": {
                "nonfatal_errors": flash_segment["nonfatal_errors"],
                "pool_load": flash_execution["pool_load"],
                "call_scope": flash_execution["call_scope"],
                "call_cache": flash_execution["call_cache"],
                "fee_growth_0_calldata": flash_execution["fee_growth_0_calldata"],
                "fee_growth_1_calldata": flash_execution["fee_growth_1_calldata"],
                "call_order": flash_execution["call_order"],
                "abi_decode": flash_execution["abi_decode"],
                "atomicity": flash_execution["atomicity"],
                "missing_pool": flash_execution["missing_pool"],
                "first_call_failure": flash_execution["first_call_failure"],
                "second_call_failure": flash_execution["second_call_failure"],
                "fatal_error": flash_execution["fatal_error"],
                "post_fatal_execution": flash_execution["post_fatal_execution"],
                "nonfatal_error": flash_execution["nonfatal_error"],
                "inapplicable_guards": flash_execution["inapplicable_guards"],
                "emitted_row_types": flash_execution["emitted_row_types"],
                "synthetic_row_types": flash_execution["synthetic_row_types"],
            },
        }
        provenance_surface = {
            "source_writer_semantic_contract_sha256": npm_segment["semantic_contract_sha256"],
            "source_writer_segment_contract_sha256": matrix_segment["source_writer_segment_contract_sha256"],
            "matrix_sha256": matrix_segment["matrix_sha256"],
            "npm_mapping_cid": matrix_segment["profile_bindings"]["nonfungible_position_manager"]["mapping_cid"],
            "pool_mapping_cid": flash_segment["pool_mapping_cid"],
            "pool_profile_id": flash_segment["pool_profile_id"],
            "npm_handlers": npm_handlers,
            "flash_handler": flash_handler,
            "writer_segment_record_sha256": canonical_sha256(writer_segment),
        }
        results.append(
            {
                "segment_id": segment_id,
                "network": npm_segment["network"],
                "start_block_inclusive": npm_segment["start_block_inclusive"],
                "end_block_inclusive": npm_segment["end_block_inclusive"],
                "deployment": npm_segment["deployment"],
                "semantic_surface": semantic_surface,
                "semantic_surface_sha256": canonical_sha256(semantic_surface),
                "provenance_surface": provenance_surface,
                "provenance_surface_sha256": canonical_sha256(provenance_surface),
                "execution_model": "undecided",
                "backfill_allowed": False,
            }
        )
    require(len(results) == 8 and len({item["segment_id"] for item in results}) == 8, "generated segment inventory drift")
    return results


def build_segment_diffs(sources: dict[str, dict[str, Any]], segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    upstream = sources["segment_writer_matrix"]["segment_diffs"]
    require(len(upstream) == 28, "upstream pairwise segment diff count drift")
    upstream_by_pair = {(item["left_segment_id"], item["right_segment_id"]): item for item in upstream}
    results = []
    for left, right in itertools.combinations(segments, 2):
        pair = (left["segment_id"], right["segment_id"])
        require(pair in upstream_by_pair, f"upstream segment pair missing: {pair}")
        source_diff = upstream_by_pair[pair]
        semantic_paths = json_diff_paths(left["semantic_surface"], right["semantic_surface"])
        provenance_paths = json_diff_paths(left["provenance_surface"], right["provenance_surface"])
        results.append(
            {
                "left_segment_id": left["segment_id"],
                "right_segment_id": right["segment_id"],
                "relation": source_diff["relation"],
                "boundary_block": source_diff["boundary_block"],
                "left_semantic_surface_sha256": left["semantic_surface_sha256"],
                "right_semantic_surface_sha256": right["semantic_surface_sha256"],
                "semantic_equal": not semantic_paths,
                "semantic_diff_paths": semantic_paths,
                "left_provenance_surface_sha256": left["provenance_surface_sha256"],
                "right_provenance_surface_sha256": right["provenance_surface_sha256"],
                "provenance_equal": not provenance_paths,
                "provenance_diff_paths": provenance_paths,
                "boundary_state_compared": False,
                "graph_oracle_compared": False,
            }
        )
    require(len(results) == 28, "generated pairwise segment diff count drift")
    return results


def truth_boundary() -> dict[str, bool]:
    return {
        "all_eight_scoped_segment_contracts_present": True,
        "all_pairwise_scoped_segment_diffs_present": True,
        "conditional_field_handler_effect_rules_complete_for_certified_subset": True,
        "required_absence_field_closure_complete": True,
        "scoped_historical_exclusions_ordering_and_quirks_bound": True,
        "scoped_npm_call_and_failure_host_projection_complete": True,
        "scoped_pool_flash_two_field_host_projection_complete": True,
        "source_artifact_raw_bytes_bound": True,
        "all_manifest_handler_field_semantics_complete": False,
        "all_stored_fields_exact": False,
        "backfill_ready": False,
        "boundary_state_continuity_complete": False,
        "combined_handler_order_implemented": False,
        "contract_call_semantics_complete_for_all_handlers": False,
        "factory_handler_semantics_complete": False,
        "full_entity_histories_complete": False,
        "full_handler_semantics_complete": False,
        "graph_execution_trace_complete": False,
        "graph_oracle_complete": False,
        "logical_parity_complete": False,
        "physical_parity_complete": False,
        "poi_parity_complete": False,
        "pool_non_flash_handler_semantics_complete": False,
        "post_fatal_execution_modeled": False,
        "production_ready": False,
        "required_nonempty_certified": False,
        "runtime_population_complete": False,
        "segment_execution_models_decided": False,
        "target_runtime_identity_bound": False,
        "writer_runtime_consumes_this_contract": False,
    }


def expected_contract(root: Path) -> dict[str, Any]:
    sources = load_sources(root)
    population = population_contract(sources["segment_writer_matrix"])
    fields = build_field_catalog(sources)
    segments = build_segments(sources, population)
    return {
        "format_version": 1,
        "contract_version": CONTRACT_VERSION,
        "mode": "scoped-host-projection-evidence",
        "scope": {
            "networks": ["mainnet", "base"],
            "segment_count": 8,
            "npm_handlers": NPM_HANDLERS,
            "pool_handlers": [FLASH_HANDLER],
            "conditional_certified_field_count": 34,
            "required_absent_field_count": 33,
            "total_field_record_count": 67,
            "certified_entity_history": False,
            "claim": "exact selected-handler host projections and retained-mapping static absence only",
        },
        "source_contracts": {
            name: source_record(relative, version, digest)
            for name, (relative, version, digest) in SOURCE_SPECS.items()
        },
        "population_contract": population,
        "field_rule_catalog": {
            **field_rule_catalog(),
            "required_absence.no_store_set_target": {
                "handlers": [],
                "rule": "no direct, dynamic, or indirect store.set target exists for the entity in any function of all 20 retained mapping artifacts",
                "evidence": [
                    evidence_ref("writer_compatibility", "$.required_absence_certifications"),
                    evidence_ref("segment_writer_matrix", "$.population_taxonomy"),
                ],
            },
        },
        "field_catalog": fields,
        "residual_field_blockers": [
            {
                "entities": RESIDUAL_CERTIFIED_ENTITY_FIELDS,
                "reason": "the executable host reducer retains address/tick values but does not prove exact Graph serialized relation ids for these stored link fields",
            },
            {
                "entities": ["Transaction"],
                "reason": "Pool Mint/Burn/Swap writers remain outside the NPM-only Transaction contribution, so full Transaction history and last-writer semantics are not certified",
            },
            {
                "entities": ["Pool"],
                "reason": "Swap and other Pool handlers also write fee-growth or neighboring Pool fields; only handleFlash's two-field effect is certified here",
            },
        ],
        "segments": segments,
        "segment_diffs": build_segment_diffs(sources, segments),
        "residual_handler_blockers": [
            "Factory.handlePoolCreated field values and control flow",
            "Pool.handleInitialize, Pool.handleSwap, Pool.handleMint, and Pool.handleBurn field values and control flow",
            "cross-component and dynamic-data-source scheduling",
            "post-fatal Graph execution, retryable failures, persisted data sources, VID allocation, PoI, and deterministic error streams",
            "runtime population, boundary continuity, authoritative oracle, logical parity, physical parity, package wiring, and backfill execution-model selection",
        ],
        "truth_boundary": truth_boundary(),
    }


def verify_contract(root: Path, actual: dict[str, Any] | None = None) -> dict[str, Any]:
    expected = expected_contract(root)
    if actual is None:
        path = root / CONTRACT_PATH
        require(path.is_file(), f"field-semantics contract missing: {CONTRACT_PATH}")
        actual = load_json_strict(path)
    require(
        canonical_bytes(actual) == canonical_bytes(expected),
        "field-semantics contract differs from the exact generated contract",
    )
    return expected


def write_contract(root: Path) -> dict[str, Any]:
    expected = expected_contract(root)
    path = root / CONTRACT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(expected, indent=2, ensure_ascii=True) + "\n")
    return expected


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--write-contract", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    try:
        contract = write_contract(root) if args.write_contract else verify_contract(root)
    except VerificationError as error:
        print(f"segment field-semantics verification failed: {error}", file=sys.stderr)
        return 1
    digest = raw_sha256(root / CONTRACT_PATH) if (root / CONTRACT_PATH).is_file() else canonical_sha256(contract)
    print(
        "verified Uniswap V3 scoped segment field semantics: "
        f"{len(contract['segments'])} segments, {len(contract['segment_diffs'])} pairwise diffs, "
        f"{len(contract['field_catalog'])} field records, sha256 {digest}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
