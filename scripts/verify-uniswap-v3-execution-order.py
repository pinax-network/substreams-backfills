#!/usr/bin/env python3
"""Verify the Graph Node v0.44 Uniswap V3 execution-order supplement."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]
CONTRACT_PATH = Path("uniswap-v3/execution-order/v1/contract.json")
CONTRACT_VERSION = "uniswap-v3-execution-order/v1"
WRITER_PATH = Path("uniswap-v3/graft-ancestry/v2/writer-compatibility.json")
WRITER_VERSION = "uniswap-v3-writer-compatibility/v3"
WRITER_RAW_SHA256 = (
    "259481724561d5aa725c17f90b5a19ea93ad6f7cd6074cf2cb8a8661c39f81c4"
)
MATRIX_PATH = Path("uniswap-v3/segment-writer-matrix/v1/contract.json")
MATRIX_VERSION = "uniswap-v3-segment-writer-matrix/v1"
MATRIX_RAW_SHA256 = (
    "7f6d1a34a8c885fe5ddcd81895818ba7ae8a0d736d541b881c1cc7cd54275161"
)
GRAPH_NODE_VERSION = "v0.44.0"
GRAPH_NODE_COMMIT = "77823b5a7adc4eac4abf03202c8dd7cb00dea31d"
GRAPH_NODE_TREE = "1f372b47e4de659ddbf503cdbc31ebe4d54df239"


class VerificationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_path(path: Path) -> str:
    require(path.is_file(), f"required file missing: {path}")
    return sha256_bytes(path.read_bytes())


def canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return sha256_bytes(payload)


def render(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> dict[str, object]:
    require(path.is_file(), f"JSON contract missing: {path}")
    value = json.loads(path.read_text(), object_pairs_hook=reject_duplicate_keys)
    require(isinstance(value, dict), f"JSON root must be an object: {path}")
    return value


def exact_keys(value: dict[str, object], expected: set[str], name: str) -> None:
    require(set(value) == expected, f"{name} field set drift: {sorted(value)}")


def graph_node_file(
    path: str,
    sha256: str,
    relevant_lines: list[str],
    claims: list[str],
) -> dict[str, object]:
    return {
        "path": path,
        "sha256": sha256,
        "immutable_url": (
            "https://github.com/graphprotocol/graph-node/blob/"
            f"{GRAPH_NODE_COMMIT}/{path}"
        ),
        "relevant_lines": relevant_lines,
        "claims": claims,
    }


GRAPH_NODE_FILES = [
    graph_node_file(
        "chain/ethereum/src/trigger.rs",
        "6b31d65fa9c0289d76a5bb7d812965e51e26054bb4fad417aa641843c531700f",
        ["364-403"],
        ["ethereum-trigger-comparator"],
    ),
    graph_node_file(
        "graph/src/blockchain/block_stream.rs",
        "8e4004884534c18054cb7ccd30b9eb675cbc956a3f651041e546ccca31fb0933",
        ["248-260", "293-295"],
        ["stage-trigger-sort-and-dedup", "extended-stage-resort"],
    ),
    graph_node_file(
        "core/src/subgraph/runner/mod.rs",
        "bb5623ed45b51ad99c783069ea4344c08a69e826016951a8b6282f3685e4b026",
        [
            "636-805",
            "807-825",
            "854-923",
            "947-1027",
            "1060-1180",
            "1222-1292",
            "1295-1405",
            "1698-1768",
        ],
        [
            "initial-stage-before-dynamic-stages",
            "breadth-first-dynamic-datasource-stages",
            "whole-block-refetch-per-dynamic-stage",
            "new-host-creation-order",
            "fatal-and-nonfatal-deterministic-error-policy",
            "block-shared-vid-generator",
            "poi-entity-consumes-shared-vid",
        ],
    ),
    graph_node_file(
        "core/src/subgraph/inputs.rs",
        "22a2ee4a8ef0b7ef4cca52115b505c41ff5ee917621645fa48e0971e712ff278",
        ["79-85"],
        ["nonfatal-errors-feature-selects-error-policy"],
    ),
    graph_node_file(
        "core/src/subgraph/runner/trigger_runner.rs",
        "02813d2165820c59b9391fef0c70e565f7175b5f8f40c062b71b7975645d8e93",
        ["44-78"],
        ["runnable-triggers-execute-in-stage-order"],
    ),
    graph_node_file(
        "core/src/subgraph/trigger_processor.rs",
        "5cdce1e42627e45d8520d5e8d938a1eb13f142c245d72d5bfb098d94e7cb2905",
        ["24-80"],
        [
            "matching-hosts-execute-in-host-order",
            "poi-boundary-is-runnable-trigger-scoped",
            "deterministic-error-poi-event-appended",
        ],
    ),
    graph_node_file(
        "core/src/subgraph/context/instance/hosts.rs",
        "059be297f3f0696d4b1c8900a3287e19a5fc761510f212da94b2642085dc0bc2",
        ["59-75", "96-120"],
        ["onchain-host-insertion-order-retained"],
    ),
    graph_node_file(
        "core/src/subgraph/context/instance/mod.rs",
        "4646efa652cd60763c8f3d6555640c2065804c654c73ff08e79b04b79849dd8e",
        ["133-187"],
        ["duplicate-runtime-hosts-are-not-added"],
    ),
    graph_node_file(
        "core/src/subgraph/instance_manager.rs",
        "8921629009c13cf1fa7464fddf6dea62440e432f5681172a8ce4be2ee60abfed",
        ["350-357", "529-545"],
        ["manifest-hosts-before-stored-dynamic-hosts"],
    ),
    graph_node_file(
        "core/src/subgraph/loader.rs",
        "1bd089f3e888da61df66c4782f59dbd325de0b16e0e304300e951ce89f69c46d",
        ["8-38"],
        ["stored-dynamic-datasources-loaded-in-store-order"],
    ),
    graph_node_file(
        "store/postgres/src/dynds/shared.rs",
        "d055be63954a967d395145cf16b6c58f276a0c54f99640f3f1ca11ac9f86c087",
        ["40-102"],
        ["legacy-stored-datasource-order-is-creation-block-then-database-vid"],
    ),
    graph_node_file(
        "store/postgres/src/dynds/private.rs",
        "f3959c0729536d633222c2ffc2c221399c424fd232d6f79a707471baec353f61",
        ["105-149"],
        ["private-stored-datasource-order-is-creation-block-then-database-vid"],
    ),
    graph_node_file(
        "chain/ethereum/src/data_source.rs",
        "d636a77029f1bd56101a1d9524a80f4b63a4157433a31b8964239c82a1e22921",
        ["90-138", "675-703"],
        [
            "dynamic-datasource-start-block-is-creation-block",
            "matching-gates-by-address-and-block-number-not-log-ordinal",
        ],
    ),
    graph_node_file(
        "runtime/wasm/src/module/instance.rs",
        "5d259076417e59ef217d888b5bb8e711faa31e7431165ac8f5c2bbeac9accc86",
        ["164-247"],
        ["mapping-handler-enter-exit-and-deterministic-discard"],
    ),
    graph_node_file(
        "runtime/wasm/src/module/context.rs",
        "f3bb98699b3c3b20a3627df8c96f2eb633629c5dad8426490850226c2cfea800",
        ["1021-1068"],
        ["datasource-create-receives-block-number-with-no-log-ordinal"],
    ),
    graph_node_file(
        "graph/src/components/subgraph/instance.rs",
        "e55bda1854ea60b10729b56b2e1b524bbc76aaa02a4d3256424b1631968de504",
        ["150-179"],
        ["failed-handler-entities-and-created-datasources-discarded"],
    ),
    graph_node_file(
        "graph/src/components/store/entity_cache.rs",
        "6242beb1480057b553e5300917d310d13194c6c4948c8137b3b6b2eba9a8139b",
        ["21-68", "140-154", "209-233", "350-385"],
        [
            "block-shared-monotonic-vid-sequence",
            "handler-entity-buffer-discard-does-not-rewind-vid",
        ],
    ),
    graph_node_file(
        "store/postgres/src/relational.rs",
        "32081c3a099af03dcbc50d0a76bf876457741eb16d7ac39d234d90332f6a0c55",
        ["1076-1120"],
        ["chain-revert-removes-and-unclamps-entity-versions"],
    ),
    graph_node_file(
        "store/postgres/src/writable.rs",
        "f2d71c26e9aef31f71c65329769e1d964c34d6e4936acd51aa006ea64ebea1ce",
        ["1131-1211", "1445-1495", "1800-1843"],
        [
            "writer-selects-synchronous-transaction-or-async-queue-acceptance",
            "accepted-block-transaction-advances-in-memory-block-pointer",
        ],
    ),
    graph_node_file(
        "runtime/wasm/src/host_exports.rs",
        "7ec1c25389a3d8a173963175afc036b2dbbc442ee41a3ed4295e4991198bec98",
        ["300-340"],
        ["poi-set-entity-written-before-entity-cache-set"],
    ),
    graph_node_file(
        "graph/src/components/subgraph/proof_of_indexing/online.rs",
        "06862d0f0a7150a0e6ad7c42670292c875ad77c78c726225215db230c085fa6a",
        ["154-168", "197-207", "230-247"],
        ["poi-handler-boundary-and-redacted-event-count"],
    ),
    graph_node_file(
        "graph/src/components/subgraph/proof_of_indexing/event.rs",
        "5d46455d5e3103afd724ef09c3708ee413a722ed2eed393e7d9f7276d0b6a7b2",
        ["8-58"],
        ["poi-set-entity-and-deterministic-error-event-semantics"],
    ),
]


GRAPH_NODE_REFERENCE = {
    "version": GRAPH_NODE_VERSION,
    "commit": GRAPH_NODE_COMMIT,
    "tree": GRAPH_NODE_TREE,
    "tag_ref_url": "https://api.github.com/repos/graphprotocol/graph-node/git/ref/tags/v0.44.0",
    "commit_url": (
        "https://github.com/graphprotocol/graph-node/commit/"
        f"{GRAPH_NODE_COMMIT}"
    ),
    "source_files": GRAPH_NODE_FILES,
    "scope": "primary-source reference model; not target runtime identity",
}


EXECUTION_MODEL = {
    "scope": "Ethereum onchain triggers and mapping handlers in Graph Node v0.44.0",
    "stage_one": {
        "input": "sorted and deduplicated BlockWithTriggers for the block",
        "ordering_scope": "stage_local",
        "initial_host_order": (
            "successfully instantiated nonduplicate hosts encountered from manifest "
            "data sources in manifest order, followed by stored dynamic data sources "
            "ordered by creation block then database vid"
        ),
        "handler_order": (
            "for each ordered raw trigger, matching hosts execute in insertion order"
        ),
        "ethereum_comparator": {
            "block_start": "before every non-Start trigger",
            "non_start_block_triggers": (
                "after calls and logs; relative input order is retained when the "
                "block-trigger comparator is equal"
            ),
            "log_vs_log": "ascending global log index",
            "call_vs_call": "ascending transaction index",
            "log_vs_call_same_transaction": "log before call",
            "log_vs_call_different_transaction": "ascending transaction index",
        },
    },
    "dynamic_data_sources": {
        "traversal": "breadth_first",
        "stage_scope": "stage_local",
        "stage_batch": (
            "successfully instantiated nonduplicate hosts produced by the prior "
            "stage, preserving encounter order"
        ),
        "trigger_source": (
            "refetch and rematch the whole creation block for each new-host batch"
        ),
        "host_scope": "only hosts created in the current dynamic stage",
        "host_order": "data-source creation order",
        "activation_scope": "entire_creation_block",
        "creation_log_ordinal_gate": False,
        "raw_global_flattening": False,
    },
    "handler_rollback": {
        "entity_changes_buffered_per_mapping_handler": True,
        "entity_changes_discarded_on_deterministic_error": True,
        "created_data_sources_discarded_on_deterministic_error": True,
        "block_shared_vid_sequence": True,
        "vid_reserved_sequence_start": 100,
        "vid_sequence_rewinds_on_handler_rollback": False,
        "vid_allocation": (
            "each EntityCache::set call that reaches the allocation point receives "
            "a fresh VID; discarding that handler's entity buffer does not reclaim it"
        ),
        "discard_scope": [
            "handler entity updates",
            "handler-created data sources",
        ],
        "not_rewound": [
            "VID sequence",
            "auto-ID sequence",
            "proof-of-indexing events",
            "write-capacity accounting",
            "metrics",
            "cache reads",
        ],
        "chain_reorg_replay": (
            "entity versions created at or after the first reverted block are removed; "
            "prior versions closed there are unclamped; replay constructs a fresh "
            "block-scoped sequence generator"
        ),
        "entity_vid_distinct_from_dynamic_datasource_metadata_vid": True,
    },
    "proof_of_indexing": {
        "set_entity_written_before_entity_cache_set": True,
        "set_entity_precedes_vid_allocation": True,
        "handler_boundary": (
            "once per runnable raw trigger before its ordered hosted mapping handlers"
        ),
        "deterministic_error": (
            "append DeterministicError with redacted_events equal to PoI events "
            "since the runnable-trigger boundary"
        ),
        "failed_handler_set_entity_events_physically_erased": False,
        "redaction_encoding": "retained SetEntity events plus appended counter",
    },
    "failure_modes": {
        "deterministic_nonfatal": (
            "discard the failing mapping handler's entity and created-data-source "
            "changes; retain successful modifications and submit the block/PoI "
            "transaction; continuation is conditional on no fail-fast cancellation"
        ),
        "deterministic_fatal": (
            "discard the failing mapping handler; filter only entity modifications to "
            "the PoI entity, still pass persisted data sources and deterministic errors "
            "to the block transaction, advance the failed block pointer, then stop"
        ),
        "deterministic_nonfatal_fail_fast": (
            "after transaction, an unsynced deployment may still be canceled by maybe_cancel"
        ),
        "pretransaction_mapping_decode_or_dynamic_stage_unknown": (
            "return before block transaction; do not commit that partial block state"
        ),
    },
}


ORDER_FIXTURE = {
    "fixture_id": "stage-local-whole-block-breadth-first",
    "description": (
        "Synthetic log-only counterexample: every dynamic-stage match predates the "
        "log that created its host, so flattening or ordinal gating changes the trace."
    ),
    "initial_hosts": ["factory"],
    "triggers": [
        {
            "id": "grandchild-hit",
            "log_index": 1,
            "matching_hosts": ["pool-a-child", "pool-b-child"],
        },
        {"id": "pool-a-hit", "log_index": 3, "matching_hosts": ["pool-a"]},
        {"id": "pool-b-hit", "log_index": 4, "matching_hosts": ["pool-b"]},
        {"id": "create-a", "log_index": 10, "matching_hosts": ["factory"]},
        {"id": "create-b", "log_index": 20, "matching_hosts": ["factory"]},
    ],
    "creations": [
        {
            "parent_host": "factory",
            "trigger": "create-a",
            "created_host": "pool-a",
        },
        {
            "parent_host": "factory",
            "trigger": "create-b",
            "created_host": "pool-b",
        },
        {
            "parent_host": "pool-a",
            "trigger": "pool-a-hit",
            "created_host": "pool-a-child",
        },
        {
            "parent_host": "pool-b",
            "trigger": "pool-b-hit",
            "created_host": "pool-b-child",
        },
    ],
    "expected_stage_batches": [
        ["factory"],
        ["pool-a", "pool-b"],
        ["pool-a-child", "pool-b-child"],
    ],
    "expected_trace": [
        {"stage": 0, "host": "factory", "trigger": "create-a", "log_index": 10},
        {"stage": 0, "host": "factory", "trigger": "create-b", "log_index": 20},
        {"stage": 1, "host": "pool-a", "trigger": "pool-a-hit", "log_index": 3},
        {"stage": 1, "host": "pool-b", "trigger": "pool-b-hit", "log_index": 4},
        {
            "stage": 2,
            "host": "pool-a-child",
            "trigger": "grandchild-hit",
            "log_index": 1,
        },
        {
            "stage": 2,
            "host": "pool-b-child",
            "trigger": "grandchild-hit",
            "log_index": 1,
        },
    ],
}


ROLLBACK_FIXTURE = {
    "fixture_id": "handler-rollback-vid-gap-and-poi-redaction",
    "scope": "one hosted mapping handler per runnable raw trigger",
    "vid_sequence_start": 100,
    "handlers": [
        {"id": "success-before", "outcome": "success", "set_entities": ["A"]},
        {
            "id": "deterministic-failure",
            "outcome": "deterministic_error",
            "set_entities": ["B", "C"],
        },
        {"id": "success-after", "outcome": "success", "set_entities": ["D"]},
    ],
    "expected_allocations": [
        {"entity": "A", "vid_sequence": 100},
        {"entity": "B", "vid_sequence": 101},
        {"entity": "C", "vid_sequence": 102},
        {"entity": "D", "vid_sequence": 103},
        {"entity": "PoI", "vid_sequence": 104},
    ],
    "expected_persisted_entities_nonfatal": [
        {"entity": "A", "vid_sequence": 100},
        {"entity": "D", "vid_sequence": 103},
        {"entity": "PoI", "vid_sequence": 104},
    ],
    "expected_poi_events": [
        {"type": "SetEntity", "entity": "A"},
        {"type": "SetEntity", "entity": "B"},
        {"type": "SetEntity", "entity": "C"},
        {"type": "DeterministicError", "redacted_events": 2},
        {"type": "SetEntity", "entity": "D"},
    ],
    "fatal_transaction": {
        "entity_modifications": [{"entity": "PoI", "vid_sequence": 104}],
        "persisted_dynamic_data_sources_passed": True,
        "deterministic_errors_passed": True,
        "failed_block_pointer_advanced": True,
        "deployment_stops_after_transaction": True,
    },
    "nonfatal_transaction": {
        "persisted_user_entities": ["A", "D"],
        "poi_entity_modification": {"entity": "PoI", "vid_sequence": 104},
        "block_transaction_accepted_and_pointer_advanced": True,
        "continuation_after_transaction_acceptance": (
            "conditional_on_no_fail_fast_cancellation"
        ),
    },
}


TRUTH_BOUNDARY = {
    "graph_node_reference_source_bound": True,
    "dynamic_datasource_stage_reference_modeled": True,
    "target_runtime_identity_bound": False,
    "combined_handler_order_implemented": False,
    "runtime_consumes_contract": False,
    "same_path_order_machine_proven": False,
    "physical_parity_complete": False,
    "poi_parity_complete": False,
    "backfill_allowed": False,
    "production_ready": False,
}


def bind_source_contracts(root: Path) -> dict[str, object]:
    writer_path = root / WRITER_PATH
    matrix_path = root / MATRIX_PATH
    require(
        sha256_path(writer_path) == WRITER_RAW_SHA256,
        "writer-v3 raw SHA-256 drift",
    )
    require(
        sha256_path(matrix_path) == MATRIX_RAW_SHA256,
        "segment-matrix-v1 raw SHA-256 drift",
    )
    writer = load_json(writer_path)
    matrix = load_json(matrix_path)
    require(writer.get("contract_version") == WRITER_VERSION, "writer version drift")
    require(matrix.get("contract_version") == MATRIX_VERSION, "matrix version drift")
    graph_reference = writer.get("graph_node_source_evidence")
    require(isinstance(graph_reference, dict), "writer Graph Node evidence missing")
    require(
        (
            graph_reference.get("version"),
            graph_reference.get("commit"),
            graph_reference.get("tree"),
        )
        == (GRAPH_NODE_VERSION, GRAPH_NODE_COMMIT, GRAPH_NODE_TREE),
        "writer Graph Node reference drift",
    )
    matrix_sources = matrix.get("source_contracts")
    require(isinstance(matrix_sources, dict), "matrix source contracts missing")
    matrix_writer = matrix_sources.get("writer")
    require(isinstance(matrix_writer, dict), "matrix writer binding missing")
    require(
        matrix_writer.get("raw_sha256") == WRITER_RAW_SHA256,
        "matrix no longer binds the exact writer-v3 raw bytes",
    )
    return {
        "writer_v3": {
            "path": WRITER_PATH.as_posix(),
            "contract_version": WRITER_VERSION,
            "raw_sha256": WRITER_RAW_SHA256,
        },
        "segment_matrix_v1": {
            "path": MATRIX_PATH.as_posix(),
            "contract_version": MATRIX_VERSION,
            "raw_sha256": MATRIX_RAW_SHA256,
        },
    }


def simulate_order_fixture(
    fixture: dict[str, object],
    *,
    raw_global_flattening: bool = False,
    creation_log_ordinal_gate: bool = False,
) -> dict[str, object]:
    triggers = sorted(fixture["triggers"], key=lambda item: item["log_index"])
    creation_lookup: dict[tuple[str, str], list[str]] = {}
    for creation in fixture["creations"]:
        key = (creation["parent_host"], creation["trigger"])
        creation_lookup.setdefault(key, []).append(creation["created_host"])

    current_hosts = list(fixture["initial_hosts"])
    created_at: dict[str, int] = {}
    stage_batches: list[list[str]] = []
    trace: list[dict[str, object]] = []
    stage = 0
    while current_hosts:
        require(stage < 32, "execution-order fixture contains a creation cycle")
        stage_batches.append(list(current_hosts))
        next_hosts: list[str] = []
        for trigger in triggers:
            for host in current_hosts:
                if host not in trigger["matching_hosts"]:
                    continue
                if creation_log_ordinal_gate and host in created_at:
                    if trigger["log_index"] <= created_at[host]:
                        continue
                trace.append(
                    {
                        "stage": stage,
                        "host": host,
                        "trigger": trigger["id"],
                        "log_index": trigger["log_index"],
                    }
                )
                for created_host in creation_lookup.get((host, trigger["id"]), []):
                    next_hosts.append(created_host)
                    created_at[created_host] = trigger["log_index"]
        current_hosts = next_hosts
        stage += 1

    if raw_global_flattening:
        trace = sorted(trace, key=lambda item: (item["log_index"], item["stage"]))
    return {"stage_batches": stage_batches, "trace": trace}


def simulate_rollback_fixture(
    fixture: dict[str, object],
    *,
    rewind_vid_on_error: bool = False,
    erase_failed_poi_events: bool = False,
) -> dict[str, object]:
    next_vid = fixture["vid_sequence_start"]
    allocations: list[dict[str, object]] = []
    persisted: list[dict[str, object]] = []
    poi_events: list[dict[str, object]] = []
    for handler in fixture["handlers"]:
        handler_poi_start = len(poi_events)
        handler_allocations: list[dict[str, object]] = []
        for entity in handler["set_entities"]:
            allocation = {"entity": entity, "vid_sequence": next_vid}
            next_vid += 1
            allocations.append(allocation)
            handler_allocations.append(allocation)
            poi_events.append({"type": "SetEntity", "entity": entity})
        if handler["outcome"] == "success":
            persisted.extend(handler_allocations)
        elif handler["outcome"] == "deterministic_error":
            redacted_events = len(poi_events) - handler_poi_start
            if rewind_vid_on_error:
                next_vid -= len(handler_allocations)
            if erase_failed_poi_events:
                del poi_events[handler_poi_start:]
                redacted_events = 0
            poi_events.append(
                {"type": "DeterministicError", "redacted_events": redacted_events}
            )
        else:
            raise VerificationError(f"unknown rollback-fixture outcome: {handler['outcome']}")
    poi_allocation = {"entity": "PoI", "vid_sequence": next_vid}
    allocations.append(poi_allocation)
    persisted.append(poi_allocation)
    return {
        "allocations": allocations,
        "persisted_entities_nonfatal": persisted,
        "poi_events": poi_events,
    }


def fixture_payload() -> dict[str, object]:
    return {
        "stage_order": copy.deepcopy(ORDER_FIXTURE),
        "rollback": copy.deepcopy(ROLLBACK_FIXTURE),
    }


def reference_truth_payload(
    execution_model: dict[str, object], fixtures: dict[str, object]
) -> dict[str, object]:
    return {"execution_model": execution_model, "fixtures": fixtures}


def build_contract(root: Path) -> dict[str, object]:
    fixtures = fixture_payload()
    return {
        "format_version": 1,
        "contract_version": CONTRACT_VERSION,
        "mode": "reference-truth-supplement",
        "source_contracts": bind_source_contracts(root),
        "graph_node_reference": copy.deepcopy(GRAPH_NODE_REFERENCE),
        "execution_model": copy.deepcopy(EXECUTION_MODEL),
        "fixtures": fixtures,
        "reference_truth_sha256": canonical_sha256(
            reference_truth_payload(EXECUTION_MODEL, fixtures)
        ),
        "truth_boundary": copy.deepcopy(TRUTH_BOUNDARY),
    }


def verify_erratum(root: Path) -> None:
    readme = root / "uniswap-v3/graft-ancestry/README.md"
    text = readme.read_text()
    for required in (
        "## Execution-order erratum",
        "stage-local",
        "breadth-first dynamic-data-source stages",
        "not gated by the creating log's ordinal",
        "../execution-order/README.md",
    ):
        require(required in text, f"graft-ancestry execution-order erratum lost `{required}`")


def validate_internal_contract(contract: dict[str, object], root: Path) -> None:
    exact_keys(
        contract,
        {
            "format_version",
            "contract_version",
            "mode",
            "source_contracts",
            "graph_node_reference",
            "execution_model",
            "fixtures",
            "reference_truth_sha256",
            "truth_boundary",
        },
        "execution-order contract",
    )
    require(
        (
            contract["format_version"],
            contract["contract_version"],
            contract["mode"],
        )
        == (1, CONTRACT_VERSION, "reference-truth-supplement"),
        "execution-order contract identity drift",
    )
    require(
        contract["source_contracts"] == bind_source_contracts(root),
        "execution-order source-contract binding drift",
    )
    require(
        contract["graph_node_reference"] == GRAPH_NODE_REFERENCE,
        "Graph Node source file, line, or SHA-256 drift",
    )
    source_paths = [item["path"] for item in contract["graph_node_reference"]["source_files"]]
    require(len(source_paths) == len(set(source_paths)), "duplicate Graph Node source binding")
    require(len(source_paths) == 22, "Graph Node source binding count drift")

    model = contract["execution_model"]
    dynamic = model["dynamic_data_sources"]
    require(
        dynamic["stage_scope"] == "stage_local"
        and dynamic["raw_global_flattening"] is False,
        "raw-global flattening is forbidden; ordering is stage-local",
    )
    require(
        dynamic["activation_scope"] == "entire_creation_block"
        and dynamic["creation_log_ordinal_gate"] is False,
        "creation-log ordinal gating is forbidden; activation is block-scoped",
    )
    rollback = model["handler_rollback"]
    require(
        rollback["block_shared_vid_sequence"] is True
        and rollback["vid_sequence_rewinds_on_handler_rollback"] is False,
        "VID rollback is forbidden; the block-shared sequence is monotonic",
    )
    poi = model["proof_of_indexing"]
    require(
        poi["failed_handler_set_entity_events_physically_erased"] is False
        and poi["redaction_encoding"]
        == "retained SetEntity events plus appended counter",
        "PoI erasure is forbidden; DeterministicError encodes retained-event redaction",
    )
    require(model == EXECUTION_MODEL, "execution-order reference model drift")

    fixtures = contract["fixtures"]
    require(fixtures == fixture_payload(), "execution-order fixture drift")
    order_result = simulate_order_fixture(fixtures["stage_order"])
    require(
        order_result["stage_batches"]
        == fixtures["stage_order"]["expected_stage_batches"],
        "breadth-first stage batch trace drift",
    )
    require(
        order_result["trace"] == fixtures["stage_order"]["expected_trace"],
        "stage-local execution trace drift",
    )
    require(
        simulate_order_fixture(
            fixtures["stage_order"], raw_global_flattening=True
        )["trace"]
        != order_result["trace"],
        "order fixture no longer distinguishes raw-global flattening",
    )
    require(
        simulate_order_fixture(
            fixtures["stage_order"], creation_log_ordinal_gate=True
        )["trace"]
        != order_result["trace"],
        "order fixture no longer distinguishes creation-ordinal gating",
    )

    rollback_result = simulate_rollback_fixture(fixtures["rollback"])
    require(
        rollback_result["allocations"]
        == fixtures["rollback"]["expected_allocations"],
        "rollback allocation trace drift",
    )
    require(
        rollback_result["persisted_entities_nonfatal"]
        == fixtures["rollback"]["expected_persisted_entities_nonfatal"],
        "nonfatal persisted-entity trace drift",
    )
    require(
        rollback_result["poi_events"] == fixtures["rollback"]["expected_poi_events"],
        "PoI redaction trace drift",
    )
    require(
        simulate_rollback_fixture(
            fixtures["rollback"], rewind_vid_on_error=True
        )["allocations"]
        != rollback_result["allocations"],
        "rollback fixture no longer distinguishes VID rewind",
    )
    require(
        simulate_rollback_fixture(
            fixtures["rollback"], erase_failed_poi_events=True
        )["poi_events"]
        != rollback_result["poi_events"],
        "rollback fixture no longer distinguishes PoI erasure",
    )

    require(
        contract["reference_truth_sha256"]
        == canonical_sha256(reference_truth_payload(model, fixtures)),
        "execution-order reference truth digest drift",
    )
    require(
        contract["truth_boundary"] == TRUTH_BOUNDARY,
        "execution-order truth boundary promoted or drifted",
    )
    verify_erratum(root)


def verify(root: Path, contract_path: Path = CONTRACT_PATH) -> dict[str, object]:
    contract = load_json(root / contract_path)
    validate_internal_contract(contract, root)
    expected = build_contract(root)
    require(contract == expected, "execution-order contract is not deterministic")
    require(
        (root / contract_path).read_text() == render(expected),
        "execution-order contract byte rendering drift",
    )
    return contract


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=REPOSITORY)
    parser.add_argument("--contract", type=Path, default=CONTRACT_PATH)
    parser.add_argument("--write-contract", action="store_true")
    args = parser.parse_args()
    try:
        root = args.root.resolve()
        contract_path = args.contract
        if args.write_contract:
            target = root / contract_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(render(build_contract(root)))
        contract = verify(root, contract_path)
        print(
            "verified Uniswap V3 Graph Node v0.44 stage ordering, "
            "rollback/VID/PoI truth, and conservative gates "
            f"({contract['reference_truth_sha256']})"
        )
        return 0
    except (
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        OSError,
        VerificationError,
    ) as error:
        print(f"Uniswap V3 execution-order verification failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
