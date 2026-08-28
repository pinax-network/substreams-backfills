#!/usr/bin/env python3
"""Fail-closed verification for the host-only Uniswap V3 Transaction reducer."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


CONTRACT_PATH = Path("uniswap-v3/transaction-reducer/contract-v1.json")
CONTRACT_SHA256 = "977424fb7db87ebb91e819f51ae55540e7700303b2c649bec28766c65223a809"
OVERLAY = Path("uniswap-v3/transaction-reducer")
WRITER_VERIFIER_PATH = Path("scripts/verify-uniswap-v3-writer-runtime.py")
WRITER_RUNTIME_SHA256 = "765806bf19fca7695ef4d97f557593e4f791759589fe55c20f18c6523a5d07ca"
WRITER_DESCRIPTOR_SHA256 = "22b899f9eeffc8dcfb608eea7ab93884a1756897aba62dc7107507c50a4ac3f0"
WRITER_SOURCE_SHA256 = "259481724561d5aa725c17f90b5a19ea93ad6f7cd6074cf2cb8a8661c39f81c4"
PROFILE_SHA256 = "2b6635c061a7a0bfce39430c71c41dacc1567f095fe41134e890a697aa27f823"
MATRIX_SHA256 = "7f6d1a34a8c885fe5ddcd81895818ba7ae8a0d736d541b881c1cc7cd54275161"
EXECUTION_ORDER_PATH = Path("uniswap-v3/execution-order/v1/contract.json")
EXECUTION_ORDER_VERSION = "uniswap-v3-execution-order/v1"
EXECUTION_ORDER_RAW_SHA256 = "241e970cfcec4d76610b29a10141d3bff2512d80454a6308594f3db23621cde2"
GRAPH_NODE_VERSION = "v0.44.0"
GRAPH_NODE_COMMIT = "77823b5a7adc4eac4abf03202c8dd7cb00dea31d"
GRAPH_NODE_TREE = "1f372b47e4de659ddbf503cdbc31ebe4d54df239"
GRAPH_NODE_TRANSACTION_ABI_SHA256 = "86932f5228b303ea15121767a5cc5d39417208346a351a2e057e4ac430a6d6c9"
GRAPH_NODE_TRIGGER_SHA256 = "6b31d65fa9c0289d76a5bb7d812965e51e26054bb4fad417aa641843c531700f"
GRAPH_NODE_RECEIPT_SHA256 = "4f491ddc90f16f4aff919dde803ba0ba47cdccf979db5904366b4bc4ca82ec36"
SEMANTICS_SHA256 = "59c78d12d25fcd38a55a73fae447eadaa1b56588d57eb681ea599844b1a950aa"
REDUCER_SOURCE_SHA256 = "c21ce020f4c5dcfc73f0c8bdd30cfcb8098088b21c4d11d8f962d42972852f7e"
REDUCER_TEST_HARNESS_SHA256 = "7884aec740177765f50a7f151a90f305b307dcc9d13a373afcf05c0706ab6075"
EXPECTED_RUNTIME_DELTA = {
    "configs/transaction-reducer-v1.json",
    "src/transaction_reducer.rs",
    "tests/transaction_reducer.rs",
}


class VerificationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def exact_keys(value: dict[str, object], expected: set[str], name: str) -> None:
    require(set(value) == expected, f"{name} field set drift: {sorted(value)}")


def load_writer_verifier(root: Path):
    path = root / WRITER_VERIFIER_PATH
    spec = importlib.util.spec_from_file_location("uniswap_v3_writer_runtime_verifier", path)
    require(spec is not None and spec.loader is not None, "writer verifier cannot be imported")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def expected_truth() -> dict[str, bool]:
    return {
        "backfill_ready": False,
        "boundary_state_continuity_complete": False,
        "diagnostic_only": True,
        "full_npm_handler_semantics": False,
        "graph_out_replaced": False,
        "live_calls_added": False,
        "logical_oracle_complete": False,
        "physical_parity_complete": False,
        "poi_parity_complete": False,
        "failed_handler_poi_error_stream_semantics_certified": False,
        "physical_entity_vid_semantics_certified": False,
        "pool_cross_component_execution_order_certified": False,
        "pool_transaction_writers_audited": False,
        "production_ready": False,
        "runtime_population_complete": False,
        "shared_transaction_last_writer_semantics_certified": False,
        "stores_added": False,
        "substreams_handler_added": False,
    }


def expected_graph_node_transaction_gas_source() -> dict[str, object]:
    return {
        "version": GRAPH_NODE_VERSION,
        "commit": GRAPH_NODE_COMMIT,
        "tree": GRAPH_NODE_TREE,
        "legacy_api_version": "0.0.4",
        "legacy_mapping_property": "event.transaction.gasUsed",
        "legacy_wat_field_offset_bytes": 20,
        "asc_transaction_field": "gas_limit",
        "entity_field": "Transaction.gasUsed",
        "receipt_gas_used_used": False,
        "target_runtime_binary_or_source_identity_bound": False,
        "files": [
            {
                "path": "chain/ethereum/src/runtime/abi.rs",
                "sha256": GRAPH_NODE_TRANSACTION_ABI_SHA256,
                "relevant_lines": ["254-269", "520-537"],
                "immutable_url": (
                    "https://github.com/graphprotocol/graph-node/blob/"
                    f"{GRAPH_NODE_COMMIT}/chain/ethereum/src/runtime/abi.rs"
                ),
                "claim": (
                    "the API 0.0.4 AscEthereumTransaction_0_0_2 field at offset 20 is gas_limit and ToAscObj "
                    "populates it from EthereumTransactionData.gas_limit"
                ),
            },
            {
                "path": "chain/ethereum/src/trigger.rs",
                "sha256": GRAPH_NODE_TRIGGER_SHA256,
                "relevant_lines": ["127-184", "552-557"],
                "immutable_url": (
                    "https://github.com/graphprotocol/graph-node/blob/"
                    f"{GRAPH_NODE_COMMIT}/chain/ethereum/src/trigger.rs"
                ),
                "claim": (
                    "API 0.0.4 selects AscEthereumTransaction_0_0_2 and EthereumTransactionData.gas_limit "
                    "delegates to the transaction gas_limit accessor"
                ),
            },
            {
                "path": "graph/src/components/transaction_receipt.rs",
                "sha256": GRAPH_NODE_RECEIPT_SHA256,
                "relevant_lines": ["9-27"],
                "immutable_url": (
                    "https://github.com/graphprotocol/graph-node/blob/"
                    f"{GRAPH_NODE_COMMIT}/graph/src/components/transaction_receipt.rs"
                ),
                "claim": (
                    "receipt gas_used is a distinct transaction-receipt field and is not the legacy transaction offset"
                ),
            },
        ],
    }


def expected_execution_order_source() -> dict[str, str]:
    return {
        "path": EXECUTION_ORDER_PATH.as_posix(),
        "contract_version": EXECUTION_ORDER_VERSION,
        "raw_sha256": EXECUTION_ORDER_RAW_SHA256,
    }


def load_execution_order(root: Path) -> dict[str, object]:
    path = root / EXECUTION_ORDER_PATH
    require(path.is_file(), "execution-order supplement missing")
    require(sha256(path) == EXECUTION_ORDER_RAW_SHA256, "execution-order supplement raw digest drift")
    contract = json.loads(path.read_text())
    exact_keys(
        contract,
        {
            "format_version",
            "contract_version",
            "mode",
            "reference_truth_sha256",
            "source_contracts",
            "graph_node_reference",
            "execution_model",
            "fixtures",
            "truth_boundary",
        },
        "execution-order supplement",
    )
    require(
        (contract["format_version"], contract["contract_version"], contract["mode"])
        == (1, EXECUTION_ORDER_VERSION, "reference-truth-supplement"),
        "unsupported execution-order supplement",
    )
    reference = contract["graph_node_reference"]
    require(
        (reference["version"], reference["commit"], reference["tree"])
        == (GRAPH_NODE_VERSION, GRAPH_NODE_COMMIT, GRAPH_NODE_TREE),
        "execution-order Graph Node reference identity drift",
    )
    execution = contract["execution_model"]
    dynamic = execution["dynamic_data_sources"]
    rollback = execution["handler_rollback"]
    poi = execution["proof_of_indexing"]
    require(
        dynamic["stage_scope"] == "stage_local"
        and dynamic["raw_global_flattening"] is False
        and dynamic["activation_scope"] == "entire_creation_block"
        and dynamic["creation_log_ordinal_gate"] is False,
        "execution-order dynamic-stage boundary drift",
    )
    require(
        rollback["entity_changes_discarded_on_deterministic_error"] is True
        and rollback["vid_sequence_rewinds_on_handler_rollback"] is False
        and rollback["block_shared_vid_sequence"] is True
        and "proof-of-indexing events" in rollback["not_rewound"],
        "execution-order handler rollback boundary drift",
    )
    require(
        poi["failed_handler_set_entity_events_physically_erased"] is False
        and poi["set_entity_written_before_entity_cache_set"] is True,
        "execution-order PoI boundary drift",
    )
    truth = contract["truth_boundary"]
    require(
        truth["target_runtime_identity_bound"] is False
        and truth["combined_handler_order_implemented"] is False
        and truth["runtime_consumes_contract"] is False
        and truth["physical_parity_complete"] is False
        and truth["poi_parity_complete"] is False
        and truth["backfill_allowed"] is False
        and truth["production_ready"] is False,
        "execution-order truth boundary promoted",
    )
    return contract


def load_contract(root: Path) -> dict[str, object]:
    path = root / CONTRACT_PATH
    require(path.is_file(), "transaction-reducer runtime contract missing")
    require(sha256(path) == CONTRACT_SHA256, "transaction-reducer runtime contract raw digest drift")
    contract = json.loads(path.read_text())
    exact_keys(
        contract,
        {
            "format_version",
            "contract_version",
            "mode",
            "ordered_materialization",
            "repository_artifacts",
            "materialized_runtime_artifacts",
            "producer_contract",
            "reducer_contract",
            "package_contract",
            "truth_boundary",
        },
        "transaction-reducer runtime contract",
    )
    require(
        (contract["format_version"], contract["contract_version"], contract["mode"])
        == (1, "uniswap-v3-transaction-reducer-runtime/v1", "host-diagnostic-only"),
        "unsupported transaction-reducer runtime contract",
    )
    require(
        contract["ordered_materialization"]
        == [
            {
                "path": "uniswap-v3/writer-runtime/contract-v1.json",
                "contract_version": "uniswap-v3-writer-runtime/v1",
                "sha256": WRITER_RUNTIME_SHA256,
            },
            {
                "path": "uniswap-v3/transaction-reducer/transaction-reducer-v1.json",
                "contract_version": "uniswap-v3-transaction-reducer/v1",
                "sha256": SEMANTICS_SHA256,
            },
        ],
        "transaction-reducer materialization order drift",
    )
    expected_artifacts = {
        "readme": ("uniswap-v3/transaction-reducer/README.md", None),
        "reducer_contract": (
            "uniswap-v3/transaction-reducer/transaction-reducer-v1.json",
            "uniswap-v3-transaction-reducer/v1",
        ),
        "reducer_source": ("uniswap-v3/transaction-reducer/src/transaction_reducer.rs", None),
        "reducer_test_harness": (
            "uniswap-v3/transaction-reducer/tests/transaction_reducer.rs",
            None,
        ),
        "segment_matrix": (
            "uniswap-v3/segment-writer-matrix/v1/contract.json",
            "uniswap-v3-segment-writer-matrix/v1",
        ),
        "segment_profiles": (
            "uniswap-v3/writer-runtime/segment-profiles-v1.json",
            "uniswap-v3-writer-runtime-segment-profiles/v1",
        ),
        "source_writer_contract": (
            "uniswap-v3/graft-ancestry/v2/writer-compatibility.json",
            "uniswap-v3-writer-compatibility/v3",
        ),
        "execution_order": (
            EXECUTION_ORDER_PATH.as_posix(),
            EXECUTION_ORDER_VERSION,
        ),
    }
    require(set(contract["repository_artifacts"]) == set(expected_artifacts), "repository artifact set drift")
    for name, (relative, version) in expected_artifacts.items():
        artifact = contract["repository_artifacts"][name]
        exact_keys(artifact, {"path", "sha256"} | ({"contract_version"} if version else set()), f"artifact {name}")
        require(artifact["path"] == relative, f"repository artifact path drift: {name}")
        if version:
            require(artifact["contract_version"] == version, f"repository artifact version drift: {name}")
        require(sha256(root / relative) == artifact["sha256"], f"repository artifact digest drift: {name}")
    require(
        contract["repository_artifacts"]["reducer_contract"]["sha256"] == SEMANTICS_SHA256
        and contract["repository_artifacts"]["reducer_source"]["sha256"] == REDUCER_SOURCE_SHA256
        and contract["repository_artifacts"]["segment_matrix"]["sha256"] == MATRIX_SHA256
        and contract["repository_artifacts"]["segment_profiles"]["sha256"] == PROFILE_SHA256
        and contract["repository_artifacts"]["source_writer_contract"]["sha256"] == WRITER_SOURCE_SHA256
        and contract["repository_artifacts"]["execution_order"]["sha256"] == EXECUTION_ORDER_RAW_SHA256,
        "transaction-reducer pinned repository digest drift",
    )
    require(
        contract["producer_contract"]
        == {
            "writer_runtime_sha256": WRITER_RUNTIME_SHA256,
            "writer_descriptor_sha256": WRITER_DESCRIPTOR_SHA256,
            "segment_matrix_sha256": MATRIX_SHA256,
            "segment_profiles_sha256": PROFILE_SHA256,
            "source_writer_contract_sha256": WRITER_SOURCE_SHA256,
            "execution_order_contract_sha256": EXECUTION_ORDER_RAW_SHA256,
            "graph_node_version": GRAPH_NODE_VERSION,
            "graph_node_commit": GRAPH_NODE_COMMIT,
            "graph_node_tree": GRAPH_NODE_TREE,
            "graph_node_transaction_abi_sha256": GRAPH_NODE_TRANSACTION_ABI_SHA256,
            "graph_node_trigger_sha256": GRAPH_NODE_TRIGGER_SHA256,
            "graph_node_receipt_sha256": GRAPH_NODE_RECEIPT_SHA256,
            "segment_count": 8,
            "writer_protobuf_changed": False,
        },
        "transaction-reducer producer contract drift",
    )
    require(
        contract["reducer_contract"]
        == {
            "state_entities": ["Transaction", "Position.transaction", "PositionSnapshot.transaction"],
            "transaction_id_encoding": "lowercase 0x plus 64 hexadecimal digits",
            "load_transaction_upsert": "unconditional overwrite of blockNumber, timestamp, gasUsed, gasPrice",
            "legacy_api_version": "0.0.4",
            "legacy_gas_used_source": "transaction gas_limit exposed as event.transaction.gasUsed",
            "current_api_version": "0.0.7",
            "current_gas_used_source": "hardcoded zero",
            "receipt_gas_used_used": False,
            "diagnostic_transaction_metadata_fields": ["transaction_hash", "gas_limit", "gas_price"],
            "new_position_helper_call_count": 2,
            "existing_position_helper_call_count": 1,
            "normal_return_orphan_cases": 2,
            "npm_writer_event_order": (
                "global ordinal and block_log_index strictly increasing within the NPM WriterEvents envelope"
            ),
            "transaction_metadata_input_only": True,
            "pool_shared_transaction_writers_in_scope": False,
            "pool_cross_component_execution_order_certified": False,
            "entity_state_discard_scope_only": True,
            "physical_vid_and_poi_error_stream_effects_modeled": False,
        },
        "transaction-reducer execution summary drift",
    )
    require(
        contract["package_contract"]
        == {
            "module_count": 23,
            "diagnostic_module": "map_writer_events",
            "diagnostic_consumers": [],
            "transaction_reducer_substreams_module": False,
            "graph_out_output": "proto:sf.substreams.entity.v1.EntityChanges",
            "manifests_changed_from_writer_runtime": False,
            "protobuf_descriptors_changed_from_writer_runtime": False,
            "shared_wasm_binary_count": 1,
            "wasm_identical_to_writer_runtime": True,
            "writer_package_verifier_inherited": True,
        },
        "transaction-reducer package contract drift",
    )
    require(contract["truth_boundary"] == expected_truth(), "transaction-reducer truth boundary promoted")
    require(
        contract["materialized_runtime_artifacts"]
        == {
            "configs/transaction-reducer-v1.json": SEMANTICS_SHA256,
            "src/lib.rs": "91a2330a1a1016ab00fae61e8d25fde244591159ab4efd848ecc08b2623aca63",
            "src/transaction_reducer.rs": REDUCER_SOURCE_SHA256,
            "tests/transaction_reducer.rs": REDUCER_TEST_HARNESS_SHA256,
        },
        "transaction-reducer materialized artifact inventory drift",
    )
    return contract


def load_semantics(root: Path) -> dict[str, object]:
    path = root / OVERLAY / "transaction-reducer-v1.json"
    require(path.is_file(), "transaction-reducer semantics missing")
    require(sha256(path) == SEMANTICS_SHA256, "transaction-reducer semantics digest drift")
    semantics = json.loads(path.read_text())
    exact_keys(
        semantics,
        {
            "format_version",
            "contract_version",
            "mode",
            "source_writer_runtime",
            "source_segment_matrix",
            "source_segment_profiles",
            "source_graph_node_transaction_gas",
            "source_execution_order",
            "execution_contract",
            "segments",
            "truth_boundary",
        },
        "transaction-reducer semantics",
    )
    require(
        (semantics["format_version"], semantics["contract_version"], semantics["mode"])
        == (1, "uniswap-v3-transaction-reducer/v1", "host-diagnostic-only"),
        "unsupported transaction-reducer semantics",
    )
    require(semantics["source_writer_runtime"]["sha256"] == WRITER_RUNTIME_SHA256, "writer binding drift")
    require(
        semantics["source_writer_runtime"]["writer_descriptor_sha256"] == WRITER_DESCRIPTOR_SHA256,
        "writer descriptor binding drift",
    )
    require(semantics["source_segment_matrix"]["sha256"] == MATRIX_SHA256, "matrix binding drift")
    require(semantics["source_segment_profiles"]["sha256"] == PROFILE_SHA256, "profile binding drift")
    require(
        semantics["source_graph_node_transaction_gas"] == expected_graph_node_transaction_gas_source(),
        "Graph Node transaction gas source binding drift",
    )
    require(semantics["source_execution_order"] == expected_execution_order_source(), "execution-order source drift")
    require(
        semantics["execution_contract"]["legacy_stored_gas_used"]
        == "apiVersion 0.0.4 writes the transaction gas_limit exposed to the mapping as event.transaction.gasUsed",
        "legacy stored gasUsed source drift",
    )
    require(
        semantics["execution_contract"]["current_stored_gas_used"]
        == "apiVersion 0.0.7 writes zero while preserving gasPrice",
        "current stored gasUsed source drift",
    )
    require(
        semantics["execution_contract"]["receipt_gas_used"]
        == "not consumed by either deployed NPM loadTransaction generation",
        "receipt gasUsed exclusion drift",
    )
    require(semantics["execution_contract"]["new_position_helper_calls"] == 2, "new helper count drift")
    require(semantics["execution_contract"]["existing_position_helper_calls"] == 1, "existing helper count drift")
    require(len(semantics["execution_contract"]["normal_return_orphans"]) == 2, "orphan case set drift")
    require(
        semantics["execution_contract"]["deterministic_error_entity_state"]
        == "discard all attempted entity-state writes from the failing handler",
        "deterministic-error entity-state scope drift",
    )
    require(
        semantics["execution_contract"]["npm_writer_event_order"]
        == "strictly increasing global ordinal and block_log_index within the NPM WriterEvents envelope",
        "NPM-local event-order scope drift",
    )
    require(
        "dynamic Pool data-source triggers execute after"
        in semantics["execution_contract"]["pool_cross_component_execution_order"],
        "Pool cross-component order caveat drift",
    )
    require(
        "consume entity VIDs" in semantics["execution_contract"]["physical_graph_node_side_effects"]
        and "PoI and error streams" in semantics["execution_contract"]["physical_graph_node_side_effects"],
        "physical Graph Node side-effect caveat drift",
    )
    require(semantics["truth_boundary"] == expected_truth(), "semantic truth boundary promoted")
    require(len(semantics["segments"]) == 8, "transaction-reducer requires exactly eight segments")
    return semantics


def verify_segment_bindings(root: Path, semantics: dict[str, object]) -> None:
    require(sha256(root / "uniswap-v3/segment-writer-matrix/v1/contract.json") == MATRIX_SHA256, "matrix drift")
    require(sha256(root / "uniswap-v3/writer-runtime/segment-profiles-v1.json") == PROFILE_SHA256, "profile drift")
    matrix = json.loads((root / "uniswap-v3/segment-writer-matrix/v1/contract.json").read_text())
    profiles = json.loads((root / "uniswap-v3/writer-runtime/segment-profiles-v1.json").read_text())["profiles"]
    ancestry = json.loads((root / "uniswap-v3/graft-ancestry/v2/contract.json").read_text())
    api_versions: dict[str, str] = {}
    for network in ("mainnet", "base"):
        for segment in ancestry["networks"][network]["segments"]:
            npm = next(item for item in segment["manifest"]["components"] if item["name"] == "NonfungiblePositionManager")
            api_versions[segment["deployment"]] = npm["mapping"]["api_version"]
    for actual, profile, matrix_segment in zip(semantics["segments"], profiles, matrix["segments"], strict=True):
        require(actual["segment_id"] == profile["segment_id"] == matrix_segment["segment_id"], "segment id drift")
        require(actual["network"] == profile["network"] == matrix_segment["network"], "segment network drift")
        require(actual["start_block_inclusive"] == profile["start_block_inclusive"], "segment start drift")
        require(actual["end_block_inclusive"] == profile["end_block_inclusive"], "segment end drift")
        require(actual["semantic_contract_sha256"] == profile["semantic_contract_sha256"], "semantic SHA drift")
        require(actual["npm_profile_id"] == profile["npm_profile_id"], "NPM profile drift")
        require(actual["nonfatal_errors"] == ("nonFatalErrors" in matrix_segment["manifest_features"]), "error policy drift")
        require(actual["api_version"] == api_versions[profile["deployment"]], "NPM apiVersion drift")
        expected_stored_gas = "transaction-gas-limit" if actual["api_version"] == "0.0.4" else "zero"
        require(actual["stored_gas_used_mode"] == expected_stored_gas, "stored gasUsed mode drift")
        require(actual["historical_guard_effective"] == profile["historical_guard"]["effective_in_segment"], "guard drift")


def verify_graph_node_source_binding(root: Path, semantics: dict[str, object]) -> None:
    execution_order = load_execution_order(root)
    require(
        semantics["source_execution_order"] == expected_execution_order_source(),
        "execution-order supplement binding drift",
    )
    require(
        execution_order["graph_node_reference"]["commit"] == GRAPH_NODE_COMMIT,
        "gas and execution-order Graph Node commits diverge",
    )
    writer_compatibility = json.loads(
        (root / "uniswap-v3/graft-ancestry/v2/writer-compatibility.json").read_text()
    )
    source = writer_compatibility["graph_node_source_evidence"]
    require(
        (source["version"], source["commit"], source["tree"])
        == (GRAPH_NODE_VERSION, GRAPH_NODE_COMMIT, GRAPH_NODE_TREE),
        "Graph Node source identity diverges from writer compatibility evidence",
    )
    trigger = next(
        (item for item in source["files"] if item["path"] == "chain/ethereum/src/trigger.rs"),
        None,
    )
    require(
        trigger is not None and trigger["sha256"] == GRAPH_NODE_TRIGGER_SHA256,
        "Graph Node trigger source digest drift",
    )
    require(
        semantics["source_graph_node_transaction_gas"]["target_runtime_binary_or_source_identity_bound"] is False
        and source["target_runtime_binary_or_source_identity_bound"] is False,
        "Graph Node target-runtime identity was promoted",
    )


def verify_overlay_static(root: Path, writer) -> None:
    require(not (root / OVERLAY / "runtime.patch").exists(), "runtime library patch is forbidden")

    source = (root / OVERLAY / "src/transaction_reducer.rs").read_text()
    require(sha256(root / OVERLAY / "src/transaction_reducer.rs") == REDUCER_SOURCE_SHA256, "source digest drift")
    for required in (
        "pub fn reduce_transaction_block",
        "pub struct TransactionMetadata",
        "PositionCreation",
        "PositionSnapshot",
        "StoredGasUsedMode::TransactionGasLimit",
        "StoredGasUsedMode::Zero",
        "GRAPH_NODE_COMMIT",
        "all_eight_segments_execute_committed_event_with_expected_gas_contract",
        "legacy_and_current_stored_gas_used_distinguish_gas_limit_from_receipt_usage",
        "decrease_success_and_missing_token_fatal_nonfatal_policies",
        "base_root_guard_covers_increase_and_decrease_before_identity",
        "orphan_transaction_then_later_same_token_success_creates_relations",
        'let receipt_actual_gas_used = "21000";',
        'let transaction_gas_limit = "750000";',
        "EventKind::Decrease => Event::DecreaseLiquidity",
        "source_execution_order",
        "SOURCE_EXECUTION_ORDER_RAW_SHA256",
        "pool_cross_component_execution_order_certified",
        "physical_entity_vid_semantics_certified",
        "failed_handler_poi_error_stream_semantics_certified",
        "pool_transaction_writers_audited",
        "shared_transaction_last_writer_semantics_certified",
    ):
        require(required in source, f"transaction-reducer source contract missing `{required}`")
    for forbidden in (
        "#[substreams::handlers",
        "rpc::eth_call",
        "pub fn graph_out",
        "StoreSet",
        "StoreAdd",
        "EntityChanges",
        "std::fs",
        "std::net",
        "handleSwap",
        "handleMint",
        "handleBurn",
        "GasUsedMode::Actual",
    ):
        require(forbidden not in source, f"transaction-reducer source contains forbidden capability `{forbidden}`")

    metadata_body = source.split("pub struct TransactionMetadata {", 1)[1].split("}", 1)[0]
    metadata_fields = {
        line.strip().removeprefix("pub ").split(":", 1)[0]
        for line in metadata_body.splitlines()
        if line.strip().startswith("pub ")
    }
    require(
        metadata_fields == {"transaction_hash", "gas_limit", "gas_price"},
        f"diagnostic transaction metadata field drift: {sorted(metadata_fields)}",
    )
    require(
        "StoredGasUsedMode::TransactionGasLimit => metadata.gas_limit.clone()" in source
        and 'StoredGasUsedMode::Zero => "0".to_owned()' in source
        and "metadata.gas_used" not in source,
        "legacy stored gasUsed is not sourced exclusively from transaction gas_limit",
    )

    harness_path = root / OVERLAY / "tests/transaction_reducer.rs"
    require(sha256(harness_path) == REDUCER_TEST_HARNESS_SHA256, "test harness digest drift")
    harness = harness_path.read_text()
    require(
        "pub use substreams_uniswap_v3::pb;" in harness
        and '#[path = "../src/transaction_reducer.rs"]' in harness
        and "mod transaction_reducer;" in harness,
        "host integration-test harness drift",
    )
    for forbidden in ("pub mod transaction_reducer", "#[substreams::handlers", "wasm32"):
        require(forbidden not in harness, f"test harness contains forbidden runtime linkage `{forbidden}`")


def materialize_expected(root: Path, destination: Path, writer=None) -> None:
    writer = writer or load_writer_verifier(root)
    writer.materialize_expected(root, destination)
    (destination / "tests").mkdir()
    shutil.copy2(root / OVERLAY / "src/transaction_reducer.rs", destination / "src/transaction_reducer.rs")
    shutil.copy2(
        root / OVERLAY / "transaction-reducer-v1.json",
        destination / "configs/transaction-reducer-v1.json",
    )
    shutil.copy2(
        root / OVERLAY / "tests/transaction_reducer.rs",
        destination / "tests/transaction_reducer.rs",
    )


def verify_runtime(root: Path, runtime: Path, contract: dict[str, object], writer) -> Path:
    require(runtime.is_dir(), f"transaction-reducer runtime missing: {runtime}")
    with tempfile.TemporaryDirectory(prefix="uniswap-v3-transaction-expected-") as temporary:
        temporary_path = Path(temporary)
        expected_writer = temporary_path / "writer"
        expected_final = temporary_path / "final"
        writer.materialize_expected(root, expected_writer)
        materialize_expected(root, expected_final, writer)
        writer_files = writer.non_build_files(expected_writer)
        final_files = writer.non_build_files(expected_final)
        runtime_files = writer.non_build_files(runtime)
        delta = {
            relative
            for relative in set(writer_files) | set(final_files)
            if relative not in writer_files
            or relative not in final_files
            or writer_files[relative].read_bytes() != final_files[relative].read_bytes()
        }
        require(delta == EXPECTED_RUNTIME_DELTA, f"transaction-reducer runtime delta drift: {sorted(delta)}")
        require(set(runtime_files) == set(final_files), "transaction-reducer runtime file set drift")
        for relative, expected in final_files.items():
            actual = runtime_files[relative]
            require(actual.read_bytes() == expected.read_bytes(), f"transaction-reducer runtime content drift: {relative}")
            require(
                actual.stat().st_mode & 0o111 == expected.stat().st_mode & 0o111,
                f"transaction-reducer runtime mode drift: {relative}",
            )
    writer.verify_toolchain(runtime)
    writer.verify_protobuf(runtime)
    for relative, digest in contract["materialized_runtime_artifacts"].items():
        require(sha256(runtime / relative) == digest, f"materialized transaction-reducer artifact drift: {relative}")
    return runtime / "target/wasm32-unknown-unknown/release/substreams_uniswap_v3.wasm"


def verify_writer_runtime(root: Path, writer) -> None:
    writer_contract = writer.load_runtime_contract(root)
    require(writer.CONTRACT_SHA256 == WRITER_RUNTIME_SHA256, "loaded writer verifier digest drift")
    require(sha256(root / "uniswap-v3/writer-runtime/contract-v1.json") == WRITER_RUNTIME_SHA256, "writer runtime drift")
    profiles = writer.load_profiles(root)
    configs = writer.load_configs(root)
    writer.load_manifests(root, configs)
    writer.verify_fixture(root)
    writer.verify_overlay_static(root)
    require(writer_contract["package_contract"]["module_count"] == 23, "writer module count drift")
    require(len(profiles["profiles"]) == 8, "writer segment count drift")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--writer-runtime", type=Path)
    parser.add_argument("--mainnet-spkg", type=Path)
    parser.add_argument("--base-spkg", type=Path)
    args = parser.parse_args()
    if bool(args.mainnet_spkg) != bool(args.base_spkg):
        parser.error("--mainnet-spkg and --base-spkg must be passed together")
    if args.mainnet_spkg and not args.runtime:
        parser.error("package checks require --runtime")
    if args.writer_runtime and not args.runtime:
        parser.error("writer-runtime comparison requires --runtime")
    try:
        root = args.root.resolve()
        writer = load_writer_verifier(root)
        contract = load_contract(root)
        semantics = load_semantics(root)
        verify_segment_bindings(root, semantics)
        verify_graph_node_source_binding(root, semantics)
        verify_writer_runtime(root, writer)
        verify_overlay_static(root, writer)
        runtime_wasm = None
        if args.runtime:
            runtime_wasm = verify_runtime(root, args.runtime.resolve(), contract, writer)
        if args.writer_runtime:
            writer_wasm = args.writer_runtime.resolve() / "target/wasm32-unknown-unknown/release/substreams_uniswap_v3.wasm"
            require(runtime_wasm.is_file(), "transaction-reducer WASM missing")
            require(writer_wasm.is_file(), "writer-runtime WASM missing")
            require(runtime_wasm.read_bytes() == writer_wasm.read_bytes(), "host-only reducer changed writer WASM")
        if args.mainnet_spkg:
            writer.verify_packages(
                runtime_wasm,
                {"mainnet": args.mainnet_spkg.resolve(), "base": args.base_spkg.resolve()},
            )
        print("verified host-only Uniswap V3 NPM Transaction reducer, exact eight-segment bindings, and conservative gates")
        return 0
    except (
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        OSError,
        VerificationError,
        subprocess.CalledProcessError,
    ) as error:
        print(f"Uniswap V3 transaction-reducer verification failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
