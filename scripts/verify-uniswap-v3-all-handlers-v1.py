#!/usr/bin/env python3
"""Build or verify the candidate Uniswap V3 all-handlers v1 certificate.

The certificate is intentionally static and fail closed.  It composes exact
component contracts from pinned Git objects, reconstructs the shared schema
from the three retained GraphQL files, and projects every handler/segment/
field cell into one conservative vocabulary.  Every component root is pinned
to canonical ancestry, but the aggregate candidate is not itself promoted to
canonical publication and no Graph Store or runtime truth is claimed.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import re
import subprocess
import sys
import tarfile
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[1]
CONTRACT_PATH = Path("uniswap-v3/all-handlers/v1/contract.json")
CONTRACT_VERSION = "uniswap-v3-all-handlers/v1"
IMPLEMENTATION_BASE_COMMIT = "09555b21c1a18767107b92ae7bef20dfb2da77c2"
IMPLEMENTATION_BASE_TREE = "4adcdd646b04ca49631fe33f4b8330bff6d7f905"

SEGMENT_FIELD_COMMIT = "86ba5eaf978b4751011cdcbc8d764814105c5d02"
SEGMENT_FIELD_TREE = "69f4d49b02dd65af0bdb8c575fa961f9d09bbd99"
SEGMENT_FIELD_PATH = "uniswap-v3/segment-field-semantics/v2/contract.json"
SEGMENT_FIELD_RAW_SHA256 = "0ca8708bd2ed60d4799559d52b3f7e0602abfd7c3edbd35f579476f00baba6ef"
SEGMENT_FIELD_CANONICAL_SHA256 = "28b9ed0d665cccb47ef6288ba7ae6247368036753bcbbfe0527e184b3c04eed3"
FIELD_CATALOG_SHA256 = "b866d0241355fb378d891dd31193de30bc61771b2fc3b27f3793b0445d391424"

EXECUTION_ORDER_COMMIT = "8c625578bcf2e2131bc8c954f99378509b19c751"
EXECUTION_ORDER_TREE = "733a03f38b0061f62c92b41c7d49c415939fe221"
EXECUTION_ORDER_PATH = "uniswap-v3/execution-order/v1/contract.json"
EXECUTION_ORDER_RAW_SHA256 = "241e970cfcec4d76610b29a10141d3bff2512d80454a6308594f3db23621cde2"
EXECUTION_ORDER_CANONICAL_SHA256 = "3e58943f80e97688e05fffd73e3680de44570195383e78b02d1caab7bdc65d7b"

CATEGORY_SETTER = "stored_component_setter_or_direct_write_authority"
CATEGORY_NO_SETTER = "stored_component_nonsetter_classification"
CATEGORY_OUTSIDE = "stored_outside_certified_handler_effect_scope"
CATEGORY_DERIVED = "derived_schema_field"
CATEGORIES = (CATEGORY_SETTER, CATEGORY_NO_SETTER, CATEGORY_OUTSIDE, CATEGORY_DERIVED)

SWAP_NATIVE_CATEGORY_BY_FLAG = {
    "stored_field_with_exact_setter_and_lexically_later_same_group_store_receiver_origin_overlap": (
        "stored_field_with_exact_setter_and_lexically_later_same_group_store_receiver_origin_overlap",
        CATEGORY_SETTER,
    ),
    "stored_field_on_reachable_store_without_exact_schema_setter": (
        "stored_field_on_reachable_entity_store_without_exact_schema_setter",
        CATEGORY_NO_SETTER,
    ),
    "stored_field_outside_pool_swap_store_closure": (
        "stored_field_outside_pool_swap_graph_store_closure",
        CATEGORY_OUTSIDE,
    ),
    "derived_field_without_direct_graph_store_transition": (
        "derived_field_without_direct_graph_store_transition",
        CATEGORY_DERIVED,
    ),
}

NPM_OUTSIDE_FLAG = {
    "transfer": "outside_npm_transfer_store_target_closure",
    "collect": "outside_npm_collect_store_target_closure",
    "increase": "outside_npm_liquidity_store_target_closure",
    "decrease": "outside_npm_liquidity_store_target_closure",
}

MANIFEST_HANDLER_ORDER = [
    "handlePoolCreated",
    "handleIncreaseLiquidity",
    "handleDecreaseLiquidity",
    "handleCollect",
    "handleTransfer",
    "handleInitialize",
    "handleSwap",
    "handleMint",
    "handleBurn",
    "handleFlash",
]

HANDLERS = {
    "factory": "Factory.handlePoolCreated",
    "initialize": "Pool.handleInitialize",
    "flash": "Pool.handleFlash",
    "burn": "Pool.handleBurn",
    "mint": "Pool.handleMint",
    "swap": "Pool.handleSwap",
    "transfer": "NonfungiblePositionManager.handleTransfer",
    "collect": "NonfungiblePositionManager.handleCollect",
    "increase": "NonfungiblePositionManager.handleIncreaseLiquidity",
    "decrease": "NonfungiblePositionManager.handleDecreaseLiquidity",
}

TRANSACTION_FIELDS = ("id", "blockNumber", "timestamp", "gasUsed", "gasPrice")
TRANSACTION_COMMON_HIT_OR_MISS_FIELDS = TRANSACTION_FIELDS[1:]

# These are exact canonical identities. The verifier independently
# requires every selected root to be reachable from IMPLEMENTATION_BASE_COMMIT
# while preserving the separate publication status of the aggregate candidate.
COMPONENTS: dict[str, dict[str, Any]] = {
    "factory": {
        "commit": "afaf3af9c25db029091d7699befe557276a442c7",
        "tree": "5c2e8f38721448039f09e06b195e019d11332d3f",
        "parent": "20b3864656bfa1fabb48cfeaba08518b26e81532",
        "path": "uniswap-v3/factory-static/v2/contract.json",
        "version": "uniswap-v3-factory-static/v2",
        "raw": "7437a95b9b1cff1c248b0685f59ec098a77fffe0ea4166b8f930a32ba6288118",
        "canonical": "adcd236a56b7a5627f956b23ba44daaeb6c58630b853ddf232516fec964373ef",
        "verifier": "scripts/verify-uniswap-v3-factory-static-v2.py",
        "verifier_sha256": "f735dc4c90c8b58c68664d2ba5c3c761d9f143b54cd4af9db9e0d8f5e2c94122",
        "test": "scripts/tests/test_uniswap_v3_factory_static_v2.py",
        "test_sha256": "2ca6b005465c7bff7af649d27ae1ff8eda61e69b00fc05ef55888989c91fd00a",
        "canonical_component": True,
        "validation_status": "canonical component; exact main push CI run 33359148975 at head afaf3af9c25db029091d7699befe557276a442c7: 6/6 jobs and 171/171 steps succeeded; zero failed or skipped steps",
        "handlers": ["factory"],
        "selected_predecessor": None,
    },
    "initialize": {
        "commit": "42c6d01f2e719993e41fca9db51be55d33da734c",
        "tree": "ba8531df0e102ba71fd30b4df2af2977355dabf3",
        "parent": "afaf3af9c25db029091d7699befe557276a442c7",
        "path": "uniswap-v3/pool-initialize/v2/contract.json",
        "version": "uniswap-v3-pool-initialize/v2",
        "raw": "6d9c36526ce4e041e18811ff5545efd5b5da96b4b2280c345b1f11379f202b84",
        "canonical": "c213d22dd95973f128059ca6fecfef2900ede9510dfdb344d4ceb3532bc9d224",
        "verifier": "scripts/verify-uniswap-v3-pool-initialize-v2.py",
        "verifier_sha256": "f14d88faeb0f1ca1f15567e74a581364c0300fe0feda100d42fedd251472cfd4",
        "test": "scripts/tests/test_uniswap_v3_pool_initialize_v2.py",
        "test_sha256": "f9fdb08d567c2024abb637c373c58257171eb00153ceca8ec386a4ce8e5393ed",
        "canonical_component": True,
        "validation_status": "canonical component; exact main push CI run 33362881880 at head 42c6d01f2e719993e41fca9db51be55d33da734c: 6/6 jobs and 172/172 steps succeeded; zero failed or skipped steps",
        "handlers": ["initialize"],
        "selected_predecessor": "factory",
    },
    "flash": {
        "commit": "796aa3ebd50a56a7b36a588a70fb0aa7fa092818",
        "tree": "638f8ee61b71111eebeb4a6d7901311e5c9e4018",
        "parent": "42c6d01f2e719993e41fca9db51be55d33da734c",
        "path": "uniswap-v3/pool-flash/v2/contract.json",
        "version": "uniswap-v3-pool-flash/v2",
        "raw": "8ca53bf7ca19bdc52a81abda624181030e07d42c30b6771aee1802723e1f1b9b",
        "canonical": "073f9c01ae8066122013d3c43f4f75133fa300ee9f0a1ee325144be08c9ec9f3",
        "verifier": "scripts/verify-uniswap-v3-pool-flash-v2.py",
        "verifier_sha256": "3206c9d1129806b097f7b1a7e2a556dee20235604a6b277c332ee9af99b45d64",
        "test": "scripts/tests/test_uniswap_v3_pool_flash_v2.py",
        "test_sha256": "1efdb3f5d295dc3d7e10f3c3743473cc6d449354d6ac01601ccf827910739ed2",
        "canonical_component": True,
        "validation_status": "canonical component; exact main push CI run 33371981478 at head 796aa3ebd50a56a7b36a588a70fb0aa7fa092818: 6/6 jobs and 173/173 steps succeeded; zero failed or skipped steps",
        "handlers": ["flash"],
        "selected_predecessor": "initialize",
    },
    "burn": {
        "commit": "54bfab587a55a7c81204a166990c03cb659ae113",
        "tree": "29616314b951850d0a8f5003c819e7e29baf216c",
        "parent": "796aa3ebd50a56a7b36a588a70fb0aa7fa092818",
        "path": "uniswap-v3/pool-burn/v2/contract.json",
        "version": "uniswap-v3-pool-burn/v2",
        "raw": "eab3d3e9555c6a2cae4c61de30da41d7af206eb66da76e42a7c34dd53ff5eb6d",
        "canonical": "1081e9d0061a17df58c83a5735f736c432aade2a286959f318bb5e623293790e",
        "verifier": "scripts/verify-uniswap-v3-pool-burn-v2.py",
        "verifier_sha256": "517f48ea1f39cc40a6f53dcefd0c3a0653d73c4bdd281e6cf6a3cf1a21c19722",
        "test": "scripts/tests/test_uniswap_v3_pool_burn_v2.py",
        "test_sha256": "3559810ab7fcc2a2ac4b0ad632ca743bd51ca3010458c3d129d1ee139b42d36d",
        "canonical_component": True,
        "validation_status": "canonical component; exact main push CI run 33377759861 at head 54bfab587a55a7c81204a166990c03cb659ae113: 6/6 jobs and 174/174 steps succeeded; zero failed or skipped steps",
        "handlers": ["burn"],
        "selected_predecessor": "flash",
    },
    "mint": {
        "commit": "7fdcdc915ab683c1081df307ef867cfde1f1bebd",
        "tree": "976d7c858a3f111bd8ca2380ccf12bfdfa6e1ee7",
        "parent": "54bfab587a55a7c81204a166990c03cb659ae113",
        "path": "uniswap-v3/pool-mint/v2/contract.json",
        "version": "uniswap-v3-pool-mint/v2",
        "raw": "0500fe9d45406e055298389dd3d1e6d44463f73c430469d4112be5ac09e4e013",
        "canonical": "cf1e1b990d0c400146c5615057ce705f8c49caf0d054cca96712bc15c41349f1",
        "verifier": "scripts/verify-uniswap-v3-pool-mint-v2.py",
        "verifier_sha256": "7be344a0e825684c9af7d6fd24eaef81ea3fca7608d906d8e8355a02f6532500",
        "test": "scripts/tests/test_uniswap_v3_pool_mint_v2.py",
        "test_sha256": "95b9f614419785f29b573529c1fa98c9986bd97138c5c5ddaa4101f0a36c46b7",
        "canonical_component": True,
        "validation_status": "canonical component; exact main push CI run 33382459957 at head 7fdcdc915ab683c1081df307ef867cfde1f1bebd: 6/6 jobs and 175/175 steps succeeded; zero failed or skipped steps",
        "handlers": ["mint"],
        "selected_predecessor": "burn",
    },
    "swap": {
        "commit": "8ac009d06ef05d077430aadac5782c6391a0ca0c",
        "tree": "2ddc9d94172eb8f61306280320d63a9029efcce3",
        "parent": "7fdcdc915ab683c1081df307ef867cfde1f1bebd",
        "path": "uniswap-v3/pool-swap/v2/contract.json",
        "version": "uniswap-v3-pool-swap/v2",
        "raw": "17cf23150f3cf097c65b2008533ebd61bea28e8b31ff79861c2450a03ae492ae",
        "canonical": "d002ae277913afc79e386911a7bb1a39eff73511a9f95e950f9d6f961ad79fdb",
        "verifier": "scripts/verify-uniswap-v3-pool-swap-v2.py",
        "verifier_sha256": "079144e472303aa814411f751472e84f97f5a241866ee32544a04516c4be8d04",
        "test": "scripts/tests/test_uniswap_v3_pool_swap_v2.py",
        "test_sha256": "97cb5508d4f8ae79fb822db75c9dffffd79b389e117c05049f102b9f49bd4477",
        "canonical_component": True,
        "validation_status": "canonical component; exact main push CI run 33406602088 at head 8ac009d06ef05d077430aadac5782c6391a0ca0c: 6/6 jobs and 176/176 steps succeeded; zero failed or skipped steps",
        "handlers": ["swap"],
        "selected_predecessor": "mint",
    },
    "transfer": {
        "commit": "0398e6184dc07fe848fcfef4ecd04ac0b64e8ece",
        "tree": "ca82557bd179527369f527c1c114a2d3d5ae252e",
        "parent": "8ac009d06ef05d077430aadac5782c6391a0ca0c",
        "path": "uniswap-v3/npm-transfer/v2/contract.json",
        "version": "uniswap-v3-npm-transfer/v2",
        "raw": "0fcadd7e68ca373ff1b1d202991818c1b36c5ba25ac8ede1515d1b8b1f041d7c",
        "canonical": "c208e1470767054553f8fcef68a2375f300cca90b8b5c1ba495639e7f0b75f12",
        "verifier": "scripts/verify-uniswap-v3-npm-transfer-v2.py",
        "verifier_sha256": "5c0fb7131ab98112457eb96a57f0c605bc6a1a52d31657be1dae14c91aaaf623",
        "test": "scripts/tests/test_uniswap_v3_npm_transfer_v2.py",
        "test_sha256": "f81b0ac2f374d97eb0a8f45f2909c43f9de242380ac2936b3456a9845d0af72f",
        "canonical_component": True,
        "validation_status": "canonical component; exact main push CI run 33418534257 at head 0398e6184dc07fe848fcfef4ecd04ac0b64e8ece: 6/6 jobs and 177/177 steps succeeded; zero failed or skipped steps",
        "handlers": ["transfer"],
        "selected_predecessor": "swap",
    },
    "collect": {
        "commit": "5ad75eca9857176e9a9ecdfa6aeff6dd2a763312",
        "tree": "78ae066e45d0175f9efd858969c1d8dd8c968ac3",
        "parent": "0398e6184dc07fe848fcfef4ecd04ac0b64e8ece",
        "path": "uniswap-v3/npm-collect/v2/contract.json",
        "version": "uniswap-v3-npm-collect/v2",
        "raw": "79bd851de40cf85f34d2a56b27f0aedf9792fa10bfa15f16728d857e0acfb139",
        "canonical": "cd82fcc5b0ae2ada53b5d2a21d8fbff6ebeee04cd078b3bae964598fa0f89ffe",
        "verifier": "scripts/verify-uniswap-v3-npm-collect-v2.py",
        "verifier_sha256": "8d1c75ac839f80d31e94dcff38b45188d8570f6c9ada4a4e2d10b75e4a3676dd",
        "test": "scripts/tests/test_uniswap_v3_npm_collect_v2.py",
        "test_sha256": "9ff074870c7e7ac6967196655cff757f0b888fb632b8017ed98fd756de161c6d",
        "canonical_component": True,
        "validation_status": "canonical component; exact main push CI run 33429253753 at head 5ad75eca9857176e9a9ecdfa6aeff6dd2a763312: 6/6 jobs and 178/178 steps succeeded; zero failed or skipped steps",
        "handlers": ["collect"],
        "selected_predecessor": "transfer",
    },
    "liquidity": {
        "commit": "09555b21c1a18767107b92ae7bef20dfb2da77c2",
        "tree": "4adcdd646b04ca49631fe33f4b8330bff6d7f905",
        "parent": "5ad75eca9857176e9a9ecdfa6aeff6dd2a763312",
        "path": "uniswap-v3/npm-liquidity/v2/contract.json",
        "version": "uniswap-v3-npm-liquidity/v2",
        "raw": "f0749606edc2fd72695b781692e4f3577db5bb79898529e78ae01f7e620a93ba",
        "canonical": "2673abf1c84388cddb11c9cecb16044eb23e8a71249a4ef4ef4e722847046388",
        "verifier": "scripts/verify-uniswap-v3-npm-liquidity-v2.py",
        "verifier_sha256": "ea980ae8c3af51684eb72c237eaf622d13070c47368bb4ce0909e3109800b373",
        "test": "scripts/tests/test_uniswap_v3_npm_liquidity_v2.py",
        "test_sha256": "9f3ffb866ac8ca8980185c9f9c0dba43e35914d6905c0633e2266aec7ca257f9",
        "canonical_component": True,
        "validation_status": "canonical component; exact main push CI run 33438242374 at head 09555b21c1a18767107b92ae7bef20dfb2da77c2: 6/6 jobs and 179/179 steps succeeded; zero failed or skipped steps",
        "handlers": ["increase", "decrease"],
        "selected_predecessor": "collect",
    },
}

EXPECTED_PER_SEGMENT = {
    "factory": (59, 1, 226, 13),
    "flash": (2, 27, 257, 13),
    "burn": (124, 63, 99, 13),
    "mint": (142, 46, 98, 13),
    "swap": (144, 45, 97, 13),
    "transfer": (38, 0, 248, 13),
    "collect": (38, 0, 248, 13),
    "increase": (38, 0, 248, 13),
    "decrease": (38, 0, 248, 13),
}

EXPECTED_ENTITY_AUTHORITIES = {
    "Bundle": ["factory", "initialize", "swap"],
    "Burn": ["burn"],
    "Factory": ["burn", "factory", "mint", "swap"],
    "Mint": ["mint"],
    "Pool": ["burn", "factory", "flash", "initialize", "mint", "swap"],
    "PoolDayData": ["burn", "initialize", "mint", "swap"],
    "PoolHourData": ["burn", "initialize", "mint", "swap"],
    "Position": ["collect", "decrease", "increase", "transfer"],
    "PositionSnapshot": ["collect", "decrease", "increase", "transfer"],
    "Swap": ["swap"],
    "Tick": ["burn", "mint", "swap"],
    "TickDayData": ["burn", "mint", "swap"],
    "Token": ["burn", "factory", "initialize", "mint", "swap"],
    "TokenDayData": ["burn", "mint", "swap"],
    "TokenHourData": ["burn", "mint", "swap"],
    "Transaction": ["burn", "collect", "decrease", "increase", "mint", "swap", "transfer"],
    "UniswapDayData": ["burn", "mint", "swap"],
}

TRUE_FLAGS = (
    "exact_canonical_component_roots_bound",
    "component_contract_and_verifier_digests_bound",
    "normalized_component_native_categories_preserved",
    "repaired_swap_exact_receiver_origin_overlap_taxonomy_bound",
    "repaired_npm_setter_path_classification_bound",
    "collect_and_liquidity_transaction_hit_miss_store_contracts_bound",
    "direct_three_schema_catalog_reconstruction_complete",
    "factory_299_field_projection_independently_derived",
    "ten_handler_eight_segment_299_field_partition_complete",
    "handler_relative_and_union_overlays_separated",
    "entity_setter_or_direct_write_authority_sets_statically_derived",
    "transaction_setter_or_direct_write_field_set_statically_closed",
    "manifest_handler_declaration_order_directly_parsed",
    "graph_node_reference_order_model_bound",
    "handler_and_aggregate_recursive_diffs_complete",
    "component_canonicality_and_publication_boundary_bound",
    "all_component_roots_canonical_and_ancestral",
    "component_ci_validation_complete",
    "post_merge_aggregate_publication_seal_required",
)

FALSE_FLAGS = (
    "canonical_publication_root_complete",
    "source_package_identity_proven",
    "imported_host_semantics_rederived",
    "imported_numeric_or_comparator_semantics_rederived",
    "arbitrary_alias_safety_complete",
    "uniform_setter_to_matching_store_path_proven",
    "uniform_setter_store_common_execution_path_proven",
    "uniform_setter_store_branch_correlation_proven",
    "uniform_setter_store_receiver_must_alias_proven",
    "no_setter_means_preserved_or_unchanged",
    "graph_store_visibility_or_version_proven",
    "graph_store_persistence_proven",
    "graph_store_rollback_proven",
    "post_fatal_execution_complete",
    "complete_entity_histories",
    "runtime_population_complete",
    "required_nonempty_certified",
    "target_runtime_identity_proven",
    "combined_handler_scheduler_implemented",
    "global_flattened_event_order_proven",
    "shared_entity_last_writer_complete",
    "transaction_last_writer_complete",
    "query_visibility_complete",
    "output_or_graph_out_complete",
    "store_consumer_complete",
    "package_consumer_complete",
    "boundary_continuity_proven",
    "provider_or_graph_oracle_compared",
    "logical_parity_proven",
    "physical_or_poi_parity_proven",
    "checkpoint_authority_complete",
    "backfill_ready",
    "deployment_ready",
    "production_ready",
    "readiness_complete",
    "issue_37_acceptance_criterion_completed",
    "issue_38_acceptance_criterion_completed",
    "issue_checkbox_completed",
    "issue_closed",
)


class VerificationError(RuntimeError):
    """Raised when retained evidence cannot reproduce the exact contract."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def raw_sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def render(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json_bytes(value: bytes, source: str) -> dict[str, Any]:
    try:
        result = json.loads(value, object_pairs_hook=reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise VerificationError(f"invalid JSON at {source}: {error}") from error
    require(isinstance(result, dict), f"JSON root is not an object: {source}")
    return result


def load_json(path: Path) -> dict[str, Any]:
    require(path.is_file(), f"JSON file missing: {path}")
    return load_json_bytes(path.read_bytes(), str(path))


def git_output(root: Path, *arguments: str) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(root), *arguments],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    require(completed.returncode == 0, f"git {' '.join(arguments)} failed: {completed.stderr.decode(errors='replace').strip()}")
    return completed.stdout


def git_text(root: Path, *arguments: str) -> str:
    return git_output(root, *arguments).decode().strip()


def git_blob(root: Path, commit: str, path: str) -> bytes:
    return git_output(root, "show", f"{commit}:{path}")


def is_ancestor(root: Path, ancestor: str, descendant: str) -> bool:
    completed = subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", ancestor, descendant],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    require(completed.returncode in (0, 1), f"cannot test ancestry {ancestor}..{descendant}")
    return completed.returncode == 0


def json_diff_paths(left: Any, right: Any, path: str = "$") -> list[str]:
    if type(left) is not type(right):
        return [path]
    if isinstance(left, dict):
        result: list[str] = []
        for key in sorted(set(left) | set(right)):
            child = f"{path}.{key}"
            if key not in left or key not in right:
                result.append(child)
            else:
                result.extend(json_diff_paths(left[key], right[key], child))
        return result
    if isinstance(left, list):
        result = []
        for index in range(max(len(left), len(right))):
            child = f"{path}[{index}]"
            if index >= len(left) or index >= len(right):
                result.append(child)
            else:
                result.extend(json_diff_paths(left[index], right[index], child))
        return result
    return [] if left == right else [path]


def compact_diff(left: Any, right: Any) -> dict[str, Any]:
    paths = json_diff_paths(left, right)
    return {
        "path_count": len(paths),
        "paths_sha256": canonical_sha256(paths),
        "left_sha256": canonical_sha256(left),
        "right_sha256": canonical_sha256(right),
        "nonempty": bool(paths),
    }


def parse_direct_schema(value: bytes) -> list[dict[str, str]]:
    text = value.decode()
    entity: str | None = None
    result: list[dict[str, str]] = []
    for line in text.splitlines():
        entity_match = re.match(r"^type\s+([A-Za-z_][A-Za-z0-9_]*)\s+@entity\s*\{\s*$", line)
        if entity_match:
            entity = entity_match.group(1)
            continue
        if entity is not None and line.strip() == "}":
            entity = None
            continue
        if entity is None or not line.startswith("  ") or line.lstrip().startswith("#"):
            continue
        field_match = re.match(
            r"^\s{2}([A-Za-z_][A-Za-z0-9_]*):\s+(\[[^\]]+\]!|[A-Za-z_][A-Za-z0-9_]*!?)(?:\s+(.*?))?\s*$",
            line,
        )
        require(field_match is not None, f"unparsed schema field line: {line!r}")
        directives = (field_match.group(3) or "").split("#", 1)[0].rstrip()
        result.append({
            "entity": entity,
            "field": field_match.group(1),
            "type": field_match.group(2),
            "directives": directives,
            "storage": "derived" if "@derivedFrom" in directives else "stored",
        })
    return result


def component_for_handler(handler: str) -> str:
    for component, spec in COMPONENTS.items():
        if handler in spec["handlers"]:
            return component
    raise VerificationError(f"component missing for handler: {handler}")


def extract_and_verify_component(
    root: Path,
    component: str,
    spec: dict[str, Any],
    wasm2wat: Path | None,
) -> None:
    with tempfile.TemporaryDirectory(prefix=f"all-handlers-{component}-") as temporary:
        temporary_path = Path(temporary)
        archive_path = temporary_path / "source.tar"
        checkout = temporary_path / "checkout"
        checkout.mkdir()
        completed = subprocess.run(
            ["git", "-C", str(root), "archive", "--format=tar", "-o", str(archive_path), spec["commit"]],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        require(completed.returncode == 0, f"cannot archive {component}: {completed.stderr.strip()}")
        with tarfile.open(archive_path, "r") as archive:
            archive.extractall(checkout, filter="data")
        verifier = checkout / spec["verifier"]
        require(verifier.is_file(), f"archived verifier missing for {component}")
        require(raw_sha256(verifier.read_bytes()) == spec["verifier_sha256"], f"archived verifier digest drift: {component}")
        command = [sys.executable, str(verifier), "--root", str(checkout)]
        if wasm2wat is not None:
            command.extend(("--wasm2wat", str(wasm2wat.resolve())))
        verified = subprocess.run(
            command,
            cwd=checkout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        require(
            verified.returncode == 0,
            f"{component} verifier regeneration failed: {verified.stderr.strip() or verified.stdout.strip()}",
        )


def load_component(
    root: Path,
    name: str,
    spec: dict[str, Any],
    *,
    regenerate: bool,
    wasm2wat: Path | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    identity = git_text(root, "show", "-s", "--format=%H %T %P", spec["commit"]).split()
    require(identity == [spec["commit"], spec["tree"], spec["parent"]], f"component Git identity drift: {name}")
    contract_bytes = git_blob(root, spec["commit"], spec["path"])
    require(raw_sha256(contract_bytes) == spec["raw"], f"component raw contract drift: {name}")
    contract = load_json_bytes(contract_bytes, f"{spec['commit']}:{spec['path']}")
    require(contract.get("contract_version") == spec["version"], f"component version drift: {name}")
    require(canonical_sha256(contract) == spec["canonical"], f"component canonical contract drift: {name}")
    verifier_bytes = git_blob(root, spec["commit"], spec["verifier"])
    test_bytes = git_blob(root, spec["commit"], spec["test"])
    require(raw_sha256(verifier_bytes) == spec["verifier_sha256"], f"component verifier drift: {name}")
    require(raw_sha256(test_bytes) == spec["test_sha256"], f"component test drift: {name}")
    require(len(contract.get("segment_diffs", [])) == 28, f"component segment diff count drift: {name}")
    require(contract.get("scope", {}).get("issue_acceptance_checkbox_completed") is False, f"component issue gate drift: {name}")
    if regenerate:
        extract_and_verify_component(root, name, spec, wasm2wat)
    selected_predecessor = spec["selected_predecessor"]
    predecessor_matches = (
        selected_predecessor is None
        or spec["parent"] == COMPONENTS[selected_predecessor]["commit"]
    )
    source_contracts = contract.get("source_contracts", {})
    manifest = {
        "component": name,
        "handlers": spec["handlers"],
        "commit": spec["commit"],
        "tree": spec["tree"],
        "parent": spec["parent"],
        "contract_path": spec["path"],
        "contract_version": spec["version"],
        "contract_raw_sha256": spec["raw"],
        "contract_canonical_sha256": spec["canonical"],
        "verifier_path": spec["verifier"],
        "verifier_raw_sha256": spec["verifier_sha256"],
        "test_path": spec["test"],
        "test_raw_sha256": spec["test_sha256"],
        "source_contracts_sha256": canonical_sha256(source_contracts),
        "scope_sha256": canonical_sha256(contract["scope"]),
        "truth_boundary_sha256": canonical_sha256(contract["truth_boundary"]),
        "segment_diffs_sha256": canonical_sha256(contract["segment_diffs"]),
        "canonical_component_commit": spec["canonical_component"],
        "reachable_from_implementation_base": is_ancestor(root, spec["commit"], IMPLEMENTATION_BASE_COMMIT),
        "selected_predecessor": selected_predecessor,
        "parent_matches_selected_predecessor": predecessor_matches,
        "provisional_for_final_publication": not (
            spec["canonical_component"]
            and is_ancestor(root, spec["commit"], IMPLEMENTATION_BASE_COMMIT)
            and predecessor_matches
        ),
        "component_regeneration_required_by_default": True,
        "validation_status": spec["validation_status"],
    }
    return contract, manifest


def schema_sources(root: Path, field_contract: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    ancestry_bytes = git_blob(root, SEGMENT_FIELD_COMMIT, "uniswap-v3/graft-ancestry/v2/contract.json")
    ancestry = load_json_bytes(ancestry_bytes, "graft ancestry v2")
    artifacts = {item["cid"]: item for item in ancestry["artifacts"]}
    schema_cids = sorted({
        segment["manifest"]["schema_cid"]
        for network in ancestry["networks"].values()
        for segment in network["segments"]
    })
    require(len(schema_cids) == 3, "direct schema CID count drift")
    catalog_projection = [
        {key: item[key] for key in ("entity", "field", "type", "directives", "storage")}
        for item in field_contract["field_catalog"]
    ]
    require(len(catalog_projection) == 299, "upstream field catalog count drift")
    bindings = []
    for cid in schema_cids:
        require(cid in artifacts, f"schema artifact missing from ancestry: {cid}")
        artifact = artifacts[cid]
        value = git_blob(root, SEGMENT_FIELD_COMMIT, artifact["path"])
        require(len(value) == artifact["bytes"], f"schema byte count drift: {cid}")
        require(raw_sha256(value) == artifact["sha256"], f"schema raw digest drift: {cid}")
        direct = parse_direct_schema(value)
        require(direct == catalog_projection, f"direct schema projection drift: {cid}")
        bindings.append({
            "cid": cid,
            "path": artifact["path"],
            "bytes": artifact["bytes"],
            "raw_sha256": artifact["sha256"],
            "field_count": len(direct),
            "ordered_field_catalog_projection_sha256": canonical_sha256(direct),
            "sorted_field_catalog_projection_sha256": canonical_sha256(
                sorted(direct, key=lambda item: (item["entity"], item["field"]))
            ),
        })
    storage = Counter(item["storage"] for item in catalog_projection)
    require(storage == Counter({"stored": 286, "derived": 13}), "schema storage split drift")
    require(len({item["entity"] for item in catalog_projection}) == 20, "schema entity count drift")
    require(canonical_sha256(field_contract["field_catalog"]) == FIELD_CATALOG_SHA256, "field catalog digest drift")
    summary = {
        "entity_count": 20,
        "field_count": 299,
        "stored_field_count": 286,
        "derived_field_count": 13,
        "field_catalog_sha256": FIELD_CATALOG_SHA256,
        "ordered_direct_projection_sha256": canonical_sha256(catalog_projection),
        "sorted_direct_projection_sha256": canonical_sha256(
            sorted(catalog_projection, key=lambda item: (item["entity"], item["field"]))
        ),
        "entity_field_pairs_sha256": canonical_sha256([
            [item["entity"], item["field"]] for item in catalog_projection
        ]),
        "direct_schema_binding_count": 3,
    }
    return {"summary": summary, "direct_schema_bindings": bindings, "field_catalog": catalog_projection}, ancestry["artifacts"]


def segment_boundary(segment: dict[str, Any]) -> dict[str, Any]:
    return {
        "segment_id": segment["segment_id"],
        "network": segment["network"],
        "deployment": segment["deployment"],
        "start_block_inclusive": segment["start_block_inclusive"],
        "end_block_inclusive": segment["end_block_inclusive"],
        "graft": segment["graft"],
    }


def component_segment(contract: dict[str, Any], segment_id: str) -> dict[str, Any]:
    matches = [item for item in contract["segments"] if item["segment_id"] == segment_id]
    require(len(matches) == 1, f"component segment binding drift: {segment_id}")
    return matches[0]


def source_surface(component: str, handler: str, segment: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]] | None]:
    if component == "factory":
        return segment["semantic_surface"], None
    if component == "liquidity":
        surface = segment["handler_surfaces"][handler]
        return surface, surface["semantic_surface"]["field_outcomes"]
    return segment, segment["semantic_surface"]["field_outcomes"]


def classify_swap_outcome(outcome: dict[str, Any]) -> str:
    require(
        set(SWAP_NATIVE_CATEGORY_BY_FLAG).issubset(outcome),
        "Swap repaired native category flags missing",
    )
    require(
        all(type(outcome[key]) is bool for key in SWAP_NATIVE_CATEGORY_BY_FLAG),
        "Swap repaired native category flag type drift",
    )
    active = [key for key in SWAP_NATIVE_CATEGORY_BY_FLAG if outcome[key]]
    require(len(active) == 1, "Swap repaired native category is not mutually exclusive")
    native, normalized = SWAP_NATIVE_CATEGORY_BY_FLAG[active[0]]
    require(outcome.get("lexical_static_category") == native, "Swap native category label drift")
    require(
        (outcome["storage"] == "derived") == (normalized == CATEGORY_DERIVED),
        "Swap storage/native category drift",
    )
    for key in (
        "setter_store_common_execution_path_proven",
        "setter_store_branch_correlation_proven",
        "setter_store_receiver_must_alias_proven",
    ):
        require(outcome.get(key) is False, f"Swap overclaim gate promoted: {key}")
    return normalized


def classify_npm_outcome(handler: str, outcome: dict[str, Any]) -> str:
    outside_flag = NPM_OUTSIDE_FLAG[handler]
    flags = {
        "classified_stored_target": (
            "classified_stored_target_with_path_qualified_schema_setter_authority",
            CATEGORY_SETTER,
        ),
        "saved_target_stored_no_setter": (
            "saved_target_stored_field_without_reachable_setter",
            CATEGORY_NO_SETTER,
        ),
        outside_flag: (f"stored_field_{outside_flag}", CATEGORY_OUTSIDE),
        "derived_query_field": (
            "derived_query_field_without_direct_store_transition",
            CATEGORY_DERIVED,
        ),
    }
    require(set(flags).issubset(outcome), f"{handler} repaired native category flags missing")
    require(all(type(outcome[key]) is bool for key in flags), f"{handler} native category flag type drift")
    active = [key for key in flags if outcome[key]]
    require(len(active) == 1, f"{handler} repaired native category is not mutually exclusive")
    native, normalized = flags[active[0]]
    require(outcome.get("path_qualified_category") == native, f"{handler} native category label drift")
    require(
        (outcome.get("storage") == "derived") == (normalized == CATEGORY_DERIVED),
        f"{handler} storage/native category drift",
    )
    paths = outcome.get("setter_before_matching_save_paths")
    require(isinstance(paths, list), f"{handler} setter path ledger missing")
    require(bool(paths) == (normalized == CATEGORY_SETTER), f"{handler} setter path/category drift")
    return normalized


def classify_component_outcome(handler: str, outcome: dict[str, Any]) -> str:
    if handler == "swap":
        return classify_swap_outcome(outcome)
    if handler in NPM_OUTSIDE_FLAG:
        return classify_npm_outcome(handler, outcome)
    if outcome["storage"] == "derived":
        return CATEGORY_DERIVED
    if handler == "initialize":
        if outcome["potential_direct_field_write"]:
            return CATEGORY_SETTER
        if outcome["direct_stored_field_association"]:
            return CATEGORY_NO_SETTER
        return CATEGORY_OUTSIDE
    if handler == "flash":
        if outcome["selected_fee_growth_setter_before_save"]:
            return CATEGORY_SETTER
        if outcome["other_stored_pool_without_reachable_schema_setter_before_save"]:
            return CATEGORY_NO_SETTER
        return CATEGORY_OUTSIDE
    if handler == "burn":
        if outcome["selected_pool_tvl_setter_before_same_pool_save"] or outcome["other_stored_field_with_setter_path_before_matching_store"]:
            return CATEGORY_SETTER
        if outcome.get(
            "stored_field_on_reachable_entity_store_without_setter_path",
            outcome.get("stored_field_on_reachable_store_without_setter_path", False),
        ):
            return CATEGORY_NO_SETTER
        return CATEGORY_OUTSIDE
    if handler == "mint":
        if outcome["stored_field_with_setter_path_before_matching_store"]:
            return CATEGORY_SETTER
        if outcome.get(
            "stored_field_on_reachable_entity_store_without_setter_path",
            outcome.get("stored_field_on_reachable_store_without_setter_path", False),
        ):
            return CATEGORY_NO_SETTER
        return CATEGORY_OUTSIDE
    raise VerificationError(f"outcome classifier missing: {handler}")


def source_native_category(handler: str, outcome: dict[str, Any]) -> str:
    value = (
        outcome.get("lexical_static_category")
        if handler == "swap"
        else outcome.get("path_qualified_category", outcome.get("static_transition"))
    )
    require(isinstance(value, str) and bool(value), f"source native category missing: {handler}")
    return value


def required_absent_overlay(handler: str, outcome: dict[str, Any]) -> bool:
    if handler == "flash":
        return outcome["flash_required_absent"]
    if handler in ("burn", "mint", "swap", "transfer", "collect", "increase", "decrease"):
        return outcome.get("required_absent_overlay", False)
    return False


def native_overlays(handler: str, outcome: dict[str, Any], required_absent: bool) -> list[str]:
    result = []
    if required_absent:
        result.append("required_absent_handler_relative")
    for key in (
        "mint_required_field_overlay",
        "mint_nullable_field_overlay",
        "swap_required_field_overlay",
        "swap_nullable_field_overlay",
        "pool_swap_core_selected_overlay",
        "pool_swap_fee_growth_selected_overlay",
    ):
        if outcome.get(key):
            result.append(key)
    return result


def child_association(handler: str, outcome: dict[str, Any]) -> dict[str, Any] | None:
    if handler == "initialize" and outcome["storage"] == "derived" and outcome["potential_query_visible_transition"]:
        child = outcome["schema_type"].replace("[", "").replace("]", "").replace("!", "")
        match = re.search(r'@derivedFrom\(field:\s*"([^"]+)"\)', outcome["directives"])
        require(match is not None, "Initialize child association directive drift")
        return {"child_entity": child, "child_field": match.group(1), "query_visibility_proven": False}
    if handler in ("burn", "mint", "swap"):
        association = outcome.get("derived_child_association")
        if association is not None:
            require(association["actual_graph_query_visibility_proven"] is False, "child query gate drift")
            return {
                "child_entity": association["child_entity"],
                "child_field": association["child_field"],
                "query_visibility_proven": False,
            }
    return None


def build_handler_surface(
    handler: str,
    component: str,
    contract: dict[str, Any],
    field_segment: dict[str, Any],
    catalog: list[dict[str, Any]],
) -> dict[str, Any]:
    segment = component_segment(contract, field_segment["segment_id"])
    source, outcomes = source_surface(component, handler, segment)
    records = []
    if handler == "factory":
        written = set(segment["semantic_surface"]["written_fields"])
        absent = set(segment["semantic_surface"]["required_absent_fields"])
        require(len(written) == 59 and absent == {"Pool.tick"}, "Factory 60-field authority drift")
        for catalog_record in catalog:
            identity = f"{catalog_record['entity']}.{catalog_record['field']}"
            category = (
                CATEGORY_DERIVED if catalog_record["storage"] == "derived"
                else CATEGORY_SETTER if identity in written
                else CATEGORY_NO_SETTER if identity in absent
                else CATEGORY_OUTSIDE
            )
            is_absent = identity in absent
            records.append({
                "entity": catalog_record["entity"],
                "field": catalog_record["field"],
                "category": category,
                "source_native_category": (
                    "factory_written_field" if identity in written
                    else "factory_handler_local_required_absence" if identity in absent
                    else "schema_derived_outside_factory_60_field_contract" if catalog_record["storage"] == "derived"
                    else "stored_outside_factory_60_field_contract"
                ),
                "required_absent_handler_relative": is_absent,
                "native_overlays": ["required_absent_handler_relative"] if is_absent else [],
                "child_association": None,
                "stored_relation_authority": False,
                "source_record_sha256": canonical_sha256({
                    "identity": identity,
                    "written": identity in written,
                    "required_absent": is_absent,
                    "source_semantic_surface_sha256": segment["semantic_surface_sha256"],
                }),
            })
    else:
        require(outcomes is not None and len(outcomes) == 299, f"source field outcome count drift: {handler}")
        for catalog_record, outcome in zip(catalog, outcomes, strict=True):
            require(
                (outcome["entity"], outcome["field"]) == (catalog_record["entity"], catalog_record["field"]),
                f"source field order drift: {handler}",
            )
            category = classify_component_outcome(handler, outcome)
            is_absent = required_absent_overlay(handler, outcome)
            records.append({
                "entity": outcome["entity"],
                "field": outcome["field"],
                "category": category,
                "source_native_category": source_native_category(handler, outcome),
                "required_absent_handler_relative": is_absent,
                "native_overlays": native_overlays(handler, outcome, is_absent),
                "child_association": child_association(handler, outcome),
                "stored_relation_authority": outcome.get("relation_field_authority_bound", False),
                "source_record_sha256": canonical_sha256(outcome),
            })
    require(len(records) == 299, f"normalized field count drift: {handler}")
    counts = Counter(item["category"] for item in records)
    if handler == "initialize":
        expected = (44, 43, 199, 13) if counts[CATEGORY_SETTER] == 44 else (42, 16, 228, 13)
    else:
        expected = EXPECTED_PER_SEGMENT[handler]
    observed = tuple(counts[key] for key in CATEGORIES)
    require(observed == expected, f"normalized category partition drift: {handler} {observed} != {expected}")
    semantic = {
        "handler": handler,
        "handler_id": HANDLERS[handler],
        "boundary": segment_boundary(field_segment),
        "category_counts": dict(zip(CATEGORIES, observed, strict=True)),
        "field_outcomes": records,
        "no_setter_is_preservation_or_unchanged_claim": False,
        "field_value_semantics_complete": False,
        "graph_store_persistence_proven": False,
    }
    provenance = {
        "handler": handler,
        "component": component,
        "component_commit": COMPONENTS[component]["commit"],
        "boundary": segment_boundary(field_segment),
        "source_semantic_surface_sha256": (
            source["semantic_surface_sha256"] if "semantic_surface_sha256" in source
            else segment["semantic_surface_sha256"]
        ),
        "source_provenance_surface_sha256": (
            source["provenance_surface_sha256"] if "provenance_surface_sha256" in source
            else segment["provenance_surface_sha256"]
        ),
    }
    return {
        "semantic_surface": semantic,
        "semantic_surface_sha256": canonical_sha256(semantic),
        "provenance_surface": provenance,
        "provenance_surface_sha256": canonical_sha256(provenance),
    }


def parse_manifest_order(
    root: Path,
    field_contract: dict[str, Any],
    ancestry_artifacts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    artifact_by_cid = {item["cid"]: item for item in ancestry_artifacts}
    results = []
    for segment in field_contract["segments"]:
        cid = segment["deployment"]
        require(cid in artifact_by_cid, f"manifest artifact missing: {cid}")
        artifact = artifact_by_cid[cid]
        value = git_blob(root, SEGMENT_FIELD_COMMIT, artifact["path"])
        require(len(value) == artifact["bytes"], f"manifest bytes drift: {cid}")
        require(raw_sha256(value) == artifact["sha256"], f"manifest raw digest drift: {cid}")
        text = value.decode()
        matches = list(re.finditer(r"^\s+handler:\s+([A-Za-z_][A-Za-z0-9_]*)\s*$", text, re.MULTILINE))
        handlers = [item.group(1) for item in matches]
        require(handlers == MANIFEST_HANDLER_ORDER, f"manifest handler declaration order drift: {cid}")
        template_offset = text.find("templates:")
        require(template_offset >= 0, f"manifest templates missing: {cid}")
        require(all(item.start() < template_offset for item in matches[:5]), f"manifest static handler split drift: {cid}")
        require(all(item.start() > template_offset for item in matches[5:]), f"manifest template handler split drift: {cid}")
        results.append({
            "segment_id": segment["segment_id"],
            "deployment": cid,
            "path": artifact["path"],
            "bytes": artifact["bytes"],
            "raw_sha256": artifact["sha256"],
            "factory_datasource_handlers": handlers[:1],
            "npm_datasource_handlers": handlers[1:5],
            "pool_dynamic_template_handlers": handlers[5:],
            "declaration_order_only_not_global_schedule": True,
        })
    require(len(results) == 8, "manifest order record count drift")
    return results


def build_npm_transaction_hit_miss_authority(contracts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    common = [f"Transaction.{field}" for field in TRANSACTION_COMMON_HIT_OR_MISS_FIELDS]
    hit_ledger = [*common, "Transaction.save"]
    miss_ledger = ["Transaction.id", *common, "Transaction.save"]
    collect_controls = []
    for proof in contracts["collect"]["mapping_proofs"]:
        shared = proof["shared_transaction_contract"]
        control = proof["semantic_invocation_contract"]["load_transaction_hit_or_miss_control_boundary"]
        require(shared["existing_position_invocation_count"] == 1, "Collect existing Transaction invocation drift")
        require(shared["new_position_invocation_count"] == 2, "Collect new Transaction invocation drift")
        require(shared["only_id_effect_is_store_miss_conditional"] is True, "Collect Transaction ID branch drift")
        require(shared["successful_hit_field_effect_count"] == 4, "Collect Transaction hit field count drift")
        require(shared["successful_miss_field_effect_count"] == 5, "Collect Transaction miss field count drift")
        require(
            shared["successful_invocation_transaction_store_set_count_on_hit_or_miss"] == 1,
            "Collect Transaction hit/miss store count drift",
        )
        require(
            shared["intra_handler_visibility_between_store_set_and_later_store_get_proven"] is False,
            "Collect Transaction visibility overclaim",
        )
        require(shared["shared_transaction_last_writer_complete"] is False, "Collect Transaction last-writer overclaim")
        require(control["successful_hit_effect_ledger"] == hit_ledger, "Collect Transaction hit ledger drift")
        require(control["successful_miss_effect_ledger"] == miss_ledger, "Collect Transaction miss ledger drift")
        require(control["transaction_save_after_common_setters_on_hit_or_miss"] is True, "Collect Transaction save branch drift")
        collect_controls.append(control)

    liquidity_controls = {"increase": [], "decrease": []}
    for proof in contracts["liquidity"]["mapping_proofs"]:
        for handler in liquidity_controls:
            shared = proof["handler_proofs"][handler]["shared_transaction_contract"]
            control = shared["retained_wat_control_contract"]
            require(shared["existing_position_invocation_count"] == 1, f"{handler} existing Transaction invocation drift")
            require(shared["new_position_invocation_count"] == 2, f"{handler} new Transaction invocation drift")
            require(shared["hit_field_effect_count"] == 4, f"{handler} Transaction hit field count drift")
            require(shared["miss_field_effect_count"] == 5, f"{handler} Transaction miss field count drift")
            require(shared["hit_store_set_count"] == shared["miss_store_set_count"] == 1, f"{handler} Transaction hit/miss store count drift")
            require(
                shared["intra_handler_visibility_between_store_set_and_later_store_get_proven"] is False,
                f"{handler} Transaction visibility overclaim",
            )
            require(shared["shared_transaction_last_writer_complete"] is False, f"{handler} Transaction last-writer overclaim")
            require(control["store_hit"]["field_effects"] == list(TRANSACTION_COMMON_HIT_OR_MISS_FIELDS), f"{handler} Transaction hit ledger drift")
            require(control["store_miss"]["field_effects"] == list(TRANSACTION_FIELDS), f"{handler} Transaction miss ledger drift")
            require(control["hit_and_miss_both_reach_transaction_store_set_unless_a_pre_store_trap_occurs"] is True, f"{handler} Transaction store branch drift")
            liquidity_controls[handler].append(control)

    require(len(collect_controls) == 6, "Collect retained Transaction control count drift")
    require(all(len(records) == 6 for records in liquidity_controls.values()), "Liquidity retained Transaction control count drift")
    source_controls = {
        "collect": collect_controls,
        "increase": liquidity_controls["increase"],
        "decrease": liquidity_controls["decrease"],
    }
    return {
        "components_with_direct_hit_miss_control_authority": ["collect", "increase", "decrease"],
        "retained_control_record_counts": {key: len(value) for key, value in source_controls.items()},
        "retained_control_records_sha256": canonical_sha256(source_controls),
        "successful_hit_field_effects": list(TRANSACTION_COMMON_HIT_OR_MISS_FIELDS),
        "successful_miss_field_effects": list(TRANSACTION_FIELDS),
        "successful_hit_field_effect_count": 4,
        "successful_miss_field_effect_count": 5,
        "successful_invocation_transaction_store_set_count_on_hit_or_miss": 1,
        "only_id_effect_is_store_miss_conditional": True,
        "new_position_invocation_count": 2,
        "existing_position_invocation_count": 1,
        "intra_handler_store_set_to_later_store_get_visibility_proven": False,
        "cross_handler_last_writer_complete": False,
    }


def build_setter_authority(
    segments: list[dict[str, Any]],
    contracts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    authorities: dict[str, set[str]] = {}
    for segment in segments:
        for handler, surface in segment["handler_surfaces"].items():
            for record in surface["semantic_surface"]["field_outcomes"]:
                if record["category"] == CATEGORY_SETTER:
                    authorities.setdefault(record["entity"], set()).add(handler)
    normalized = {entity: sorted(values) for entity, values in sorted(authorities.items())}
    require(normalized == EXPECTED_ENTITY_AUTHORITIES, "derived entity setter/direct-write authority set drift")
    transaction_fields = set(TRANSACTION_FIELDS)
    transaction_authorities = EXPECTED_ENTITY_AUTHORITIES["Transaction"]
    for segment in segments:
        for handler in transaction_authorities:
            records = segment["handler_surfaces"][handler]["semantic_surface"]["field_outcomes"]
            selected = {
                item["field"] for item in records
                if item["entity"] == "Transaction" and item["category"] == CATEGORY_SETTER
            }
            require(selected == transaction_fields, f"Transaction setter field drift: {handler}")
    return {
        "entity_setter_or_direct_write_authority_sets": normalized,
        "entities_without_setter_or_direct_write_authority": ["Collect", "Flash", "TickHourData"],
        "transaction": {
            "setter_or_direct_write_handlers": transaction_authorities,
            "setter_or_direct_write_fields": sorted(transaction_fields),
            "structural_key_model": "loadTransaction bytes-to-hex transaction identity; imported bytes/string meaning remains false",
            "npm_hit_miss_control_authority": build_npm_transaction_hit_miss_authority(contracts),
        },
    }


def build_overlays(segments: list[dict[str, Any]], field_contract: dict[str, Any]) -> dict[str, Any]:
    handler_counts: dict[str, int] = Counter()
    child_occurrences = []
    relation_occurrences = []
    distinct_handler_absence: dict[str, list[str]] = {}
    for segment in segments:
        segment_absent: set[str] = set()
        for handler, surface in segment["handler_surfaces"].items():
            for record in surface["semantic_surface"]["field_outcomes"]:
                identity = f"{record['entity']}.{record['field']}"
                if record["required_absent_handler_relative"]:
                    handler_counts[handler] += 1
                    segment_absent.add(identity)
                if record["child_association"] is not None:
                    child_occurrences.append({
                        "segment_id": segment["segment_id"],
                        "handler": handler,
                        "parent": identity,
                        **record["child_association"],
                    })
                if record["stored_relation_authority"]:
                    relation_occurrences.append({
                        "segment_id": segment["segment_id"],
                        "handler": handler,
                        "field": identity,
                    })
        require(len(segment_absent) == 34, f"handler-relative required-absence union drift: {segment['segment_id']}")
        distinct_handler_absence[segment["segment_id"]] = sorted(segment_absent)
    expected_handler_counts = {
        "factory": 8,
        "initialize": 0,
        "flash": 96,
        "burn": 264,
        "mint": 0,
        "swap": 0,
        "transfer": 264,
        "collect": 264,
        "increase": 264,
        "decrease": 264,
    }
    observed_handler_counts = {handler: handler_counts[handler] for handler in HANDLERS}
    require(observed_handler_counts == expected_handler_counts, "handler-relative required-absence count drift")
    population_absent = {
        f"{item['entity']}.{item['field']}"
        for item in field_contract["field_catalog"]
        if item["population_classification"] == "required_absent"
    }
    require(len(population_absent) == 33, "population required-absence union drift")
    require({item.split(".", 1)[0] for item in population_absent} == {"Collect", "Flash", "TickHourData"}, "population absence entities drift")
    required_nonempty = [
        f"{item['entity']}.{item['field']}"
        for item in field_contract["field_catalog"]
        if item["population_classification"] == "required_nonempty"
    ]
    require(required_nonempty == [], "required-nonempty authority unexpectedly promoted")
    require(len(child_occurrences) == 136, "handler-relative child association count drift")
    child_union = sorted({item["parent"] for item in child_occurrences})
    require(len(child_union) == 9, "child association distinct union drift")
    require(len(relation_occurrences) == 264, "handler-relative NPM relation count drift")
    relation_union = sorted({item["field"] for item in relation_occurrences})
    require(len(relation_union) == 9, "NPM relation distinct union drift")
    return {
        "required_absence": {
            "handler_relative_occurrence_count": sum(observed_handler_counts.values()),
            "handler_relative_counts": observed_handler_counts,
            "handler_relative_distinct_union_count_per_segment": 34,
            "handler_relative_distinct_union_count": 272,
            "handler_relative_distinct_unions": distinct_handler_absence,
            "population_required_absence_count_per_segment": 33,
            "population_required_absence_count": 264,
            "population_required_absence_fields": sorted(population_absent),
            "pool_tick_is_factory_handler_local_not_population_absence": True,
        },
        "required_nonempty": {
            "certified_field_count": 0,
            "certified_fields": required_nonempty,
            "runtime_population_complete": False,
        },
        "derived": {
            "handler_relative_derived_cell_count": 1040,
            "handler_relative_child_association_count": len(child_occurrences),
            "handler_relative_other_derived_count": 904,
            "distinct_child_association_field_count_per_segment": len(child_union),
            "distinct_child_association_fields": child_union,
            "child_association_occurrences_sha256": canonical_sha256(child_occurrences),
            "query_visibility_complete": False,
        },
        "stored_relations": {
            "handler_relative_occurrence_count": len(relation_occurrences),
            "handler_relative_counts": {"transfer": 48, "collect": 72, "increase": 72, "decrease": 72},
            "distinct_field_count_per_segment": len(relation_union),
            "distinct_fields": relation_union,
            "occurrences_sha256": canonical_sha256(relation_occurrences),
            "imported_value_or_alias_semantics_complete": False,
        },
    }


def build_diffs(segments: list[dict[str, Any]], contracts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    per_handler: dict[str, list[dict[str, Any]]] = {handler: [] for handler in HANDLERS}
    aggregate = []
    by_handler = {
        handler: {segment["segment_id"]: segment["handler_surfaces"][handler] for segment in segments}
        for handler in HANDLERS
    }
    for handler in HANDLERS:
        surfaces = by_handler[handler]
        for left, right in itertools.combinations(segments, 2):
            left_surface = surfaces[left["segment_id"]]
            right_surface = surfaces[right["segment_id"]]
            semantic = compact_diff(left_surface["semantic_surface"], right_surface["semantic_surface"])
            provenance = compact_diff(left_surface["provenance_surface"], right_surface["provenance_surface"])
            require(semantic["nonempty"] and provenance["nonempty"], f"empty handler diff: {handler}")
            per_handler[handler].append({
                "left_segment_id": left["segment_id"],
                "right_segment_id": right["segment_id"],
                "semantic": semantic,
                "provenance": provenance,
            })
        require(len(per_handler[handler]) == 28, f"handler diff count drift: {handler}")
    for left, right in itertools.combinations(segments, 2):
        left_surface = {
            "boundary": left["boundary"],
            "handler_semantic_sha256": {
                handler: left["handler_surfaces"][handler]["semantic_surface_sha256"]
                for handler in HANDLERS
            },
            "count_vector": left["aggregate_category_counts"],
        }
        right_surface = {
            "boundary": right["boundary"],
            "handler_semantic_sha256": {
                handler: right["handler_surfaces"][handler]["semantic_surface_sha256"]
                for handler in HANDLERS
            },
            "count_vector": right["aggregate_category_counts"],
        }
        diff = compact_diff(left_surface, right_surface)
        require(diff["nonempty"], "empty aggregate segment diff")
        aggregate.append({
            "left_segment_id": left["segment_id"],
            "right_segment_id": right["segment_id"],
            "count_vector_changed": left["aggregate_category_counts"] != right["aggregate_category_counts"],
            "recursive_diff": diff,
        })
    require(len(aggregate) == 28, "aggregate diff count drift")
    require(sum(item["count_vector_changed"] for item in aggregate) == 15, "aggregate count-vector diff split drift")
    liquidity = contracts["liquidity"]
    within = liquidity["within_segment_handler_diffs"]
    require(len(within) == 8, "Liquidity within-segment diff count drift")
    return {
        "per_handler_segment_pair_count": 28,
        "per_handler_total_count": 280,
        "per_handler": per_handler,
        "aggregate_segment_pair_count": 28,
        "aggregate_count_vector_changed_count": 15,
        "aggregate_identity_or_provenance_only_count": 13,
        "aggregate": aggregate,
        "liquidity_within_segment_handler_diff_count": 8,
        "liquidity_within_segment_handler_diffs_sha256": canonical_sha256(within),
        "total_records_including_liquidity_within_handler_axis": 316,
    }


def truth_boundary() -> dict[str, bool]:
    require(set(TRUE_FLAGS).isdisjoint(FALSE_FLAGS), "truth gate overlap")
    return {**{key: True for key in TRUE_FLAGS}, **{key: False for key in FALSE_FLAGS}}


def load_sources(
    root: Path,
    *,
    regenerate_components: bool = True,
    wasm2wat: Path | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    base_identity = git_text(root, "show", "-s", "--format=%H %T", IMPLEMENTATION_BASE_COMMIT).split()
    require(base_identity == [IMPLEMENTATION_BASE_COMMIT, IMPLEMENTATION_BASE_TREE], "implementation base identity drift")
    field_bytes = git_blob(root, SEGMENT_FIELD_COMMIT, SEGMENT_FIELD_PATH)
    require(raw_sha256(field_bytes) == SEGMENT_FIELD_RAW_SHA256, "segment-field v2 raw digest drift")
    field_contract = load_json_bytes(field_bytes, SEGMENT_FIELD_PATH)
    require(canonical_sha256(field_contract) == SEGMENT_FIELD_CANONICAL_SHA256, "segment-field v2 canonical digest drift")
    field_identity = git_text(root, "show", "-s", "--format=%H %T", SEGMENT_FIELD_COMMIT).split()
    require(field_identity == [SEGMENT_FIELD_COMMIT, SEGMENT_FIELD_TREE], "segment-field Git identity drift")
    execution_bytes = git_blob(root, EXECUTION_ORDER_COMMIT, EXECUTION_ORDER_PATH)
    require(raw_sha256(execution_bytes) == EXECUTION_ORDER_RAW_SHA256, "execution-order raw digest drift")
    execution = load_json_bytes(execution_bytes, EXECUTION_ORDER_PATH)
    require(canonical_sha256(execution) == EXECUTION_ORDER_CANONICAL_SHA256, "execution-order canonical digest drift")
    execution_identity = git_text(root, "show", "-s", "--format=%H %T", EXECUTION_ORDER_COMMIT).split()
    require(execution_identity == [EXECUTION_ORDER_COMMIT, EXECUTION_ORDER_TREE], "execution-order Git identity drift")
    contracts: dict[str, dict[str, Any]] = {}
    manifests = []
    for name, spec in COMPONENTS.items():
        contract, manifest = load_component(
            root,
            name,
            spec,
            regenerate=regenerate_components,
            wasm2wat=wasm2wat,
        )
        contracts[name] = contract
        manifests.append(manifest)
    schema, ancestry_artifacts = schema_sources(root, field_contract)
    return {
        "field_contract": field_contract,
        "execution_order": execution,
        "contracts": contracts,
        "component_manifest": manifests,
        "schema": schema,
        "ancestry_artifacts": ancestry_artifacts,
        "components_regenerated": regenerate_components,
    }


def expected_contract_from_sources(root: Path, sources: dict[str, Any]) -> dict[str, Any]:
    field_contract = sources["field_contract"]
    catalog = field_contract["field_catalog"]
    contracts = sources["contracts"]
    segments = []
    initialize_save_count = 0
    for field_segment in field_contract["segments"]:
        surfaces = {}
        for handler in HANDLERS:
            component = component_for_handler(handler)
            surfaces[handler] = build_handler_surface(
                handler,
                component,
                contracts[component],
                field_segment,
                catalog,
            )
        aggregate_counts = Counter()
        for surface in surfaces.values():
            aggregate_counts.update(surface["semantic_surface"]["category_counts"])
        observed = {key: aggregate_counts[key] for key in CATEGORIES}
        if observed[CATEGORY_SETTER] == 667:
            initialize_save_count += 1
            expected = {
                CATEGORY_SETTER: 667,
                CATEGORY_NO_SETTER: 225,
                CATEGORY_OUTSIDE: 1968,
                CATEGORY_DERIVED: 130,
            }
        else:
            expected = {
                CATEGORY_SETTER: 665,
                CATEGORY_NO_SETTER: 198,
                CATEGORY_OUTSIDE: 1997,
                CATEGORY_DERIVED: 130,
            }
        require(observed == expected, f"aggregate segment category drift: {field_segment['segment_id']}")
        require(sum(observed.values()) == 2990, "aggregate segment cell count drift")
        segments.append({
            "segment_id": field_segment["segment_id"],
            "boundary": segment_boundary(field_segment),
            "handler_surfaces": surfaces,
            "aggregate_category_counts": observed,
            "field_cell_count": 2990,
            "execution_model": "undecided",
            "backfill_allowed": False,
        })
    require(len(segments) == 8 and initialize_save_count == 3, "segment/save profile count drift")
    total_counts = Counter()
    for segment in segments:
        total_counts.update(segment["aggregate_category_counts"])
    expected_totals = {
        CATEGORY_SETTER: 5326,
        CATEGORY_NO_SETTER: 1665,
        CATEGORY_OUTSIDE: 15889,
        CATEGORY_DERIVED: 1040,
    }
    require({key: total_counts[key] for key in CATEGORIES} == expected_totals, "23,920-cell category total drift")
    require(sum(total_counts.values()) == 23920, "all-handler field cell total drift")

    component_manifest = sources["component_manifest"]
    require(len(component_manifest) == 9, "component manifest count drift")
    require(sum(len(item["handlers"]) for item in component_manifest) == 10, "component handler coverage drift")
    require(all(item["parent_matches_selected_predecessor"] for item in component_manifest), "selected predecessor edge drift")
    require(all(item["reachable_from_implementation_base"] for item in component_manifest), "component ancestry closure drift")
    require(all(item["canonical_component_commit"] for item in component_manifest), "noncanonical component root detected")
    require(
        {item["component"] for item in component_manifest if item["canonical_component_commit"]}
        == {"factory", "initialize", "flash", "burn", "mint", "swap", "transfer", "collect", "liquidity"},
        "canonical component set drift",
    )
    require(
        {item["component"] for item in component_manifest if item["provisional_for_final_publication"]}
        == set(),
        "provisional component set drift",
    )

    manifest_order = parse_manifest_order(root, field_contract, sources["ancestry_artifacts"])
    setter_authority = build_setter_authority(segments, contracts)
    overlays = build_overlays(segments, field_contract)
    diffs = build_diffs(segments, contracts)
    execution = sources["execution_order"]
    require(execution["graph_node_reference"]["commit"] == "77823b5a7adc4eac4abf03202c8dd7cb00dea31d", "Graph Node reference commit drift")
    physical_ledgers = {}
    for name, contract in contracts.items():
        projection = {"scope": contract["scope"]}
        if "aggregate_counts" in contract:
            projection["aggregate_counts"] = contract["aggregate_counts"]
        if "aggregate_inventory" in contract:
            projection["aggregate_inventory"] = contract["aggregate_inventory"]
        physical_ledgers[name] = {
            "projection": projection,
            "projection_sha256": canonical_sha256(projection),
        }

    source_roots = {
        "segment_field_semantics_v2": {
            "commit": SEGMENT_FIELD_COMMIT,
            "tree": SEGMENT_FIELD_TREE,
            "path": SEGMENT_FIELD_PATH,
            "raw_sha256": SEGMENT_FIELD_RAW_SHA256,
            "canonical_sha256": SEGMENT_FIELD_CANONICAL_SHA256,
        },
        "execution_order_v1": {
            "commit": EXECUTION_ORDER_COMMIT,
            "tree": EXECUTION_ORDER_TREE,
            "path": EXECUTION_ORDER_PATH,
            "raw_sha256": EXECUTION_ORDER_RAW_SHA256,
            "canonical_sha256": EXECUTION_ORDER_CANONICAL_SHA256,
            "graph_node_reference_commit": execution["graph_node_reference"]["commit"],
            "reference_truth_sha256": execution["reference_truth_sha256"],
        },
    }
    issue_mapping = {
        "issue_37": {
            "issue_number": 37,
            "checkboxes_completed_by_this_certificate": [],
            "issue_closed": False,
            "criterion_1_complete": False,
            "reason": "required-nonempty and runtime population authority remain incomplete; static schema-API provenance is narrower than the acceptance wording",
        },
        "issue_38": {
            "issue_number": 38,
            "checkboxes_completed_by_this_certificate": [],
            "issue_closed": False,
            "criterion_4_complete": False,
            "criterion_5_complete": False,
            "reason": "setter/store provenance and evidence-surface diffs do not complete field values, histories, population, or complete writer-contract diffs",
        },
    }
    return {
        "format_version": 1,
        "contract_version": CONTRACT_VERSION,
        "mode": "candidate-complete-conservative-all-handler-schema-api-classification-matrix",
        "scope": {
            "networks": ["mainnet", "base"],
            "handler_count": 10,
            "segment_count": 8,
            "schema_field_count": 299,
            "handler_segment_binding_count": 80,
            "field_cell_count": 23920,
            "component_contract_count": 9,
            "component_handler_coverage_count": 10,
            "per_handler_segment_pair_diff_count": 28,
            "all_handler_segment_pair_diff_count": 280,
            "aggregate_segment_pair_diff_count": 28,
            "liquidity_within_segment_handler_diff_count": 8,
            "issue_acceptance_checkbox_completed": False,
            "claim": "complete conservative normalization of ten independently certified static handler surfaces over eight retained segments and the directly reconstructed 299-field schema; component-native evidence is retained without promoting a uniform matching-store path, common execution, alias, runtime, Store, population, parity, backfill or readiness claim",
        },
        "authority_contract": {
            "implementation_base_commit": IMPLEMENTATION_BASE_COMMIT,
            "implementation_base_tree": IMPLEMENTATION_BASE_TREE,
            "component_publication_boundary": "canonical_reseal_required=false means only that the canonical Liquidity base contains every selected component in one linear canonical ancestry with matching predecessor edges and no component reseal remains; it does not publish the aggregate or complete its canonical publication root",
            "aggregate_publication_boundary": {
                "merge_to_main_required": True,
                "merge_to_main_sufficient": False,
                "post_merge_aggregate_publication_seal_required": True,
                "post_merge_aggregate_publication_seal_complete": False,
                "required_seal_bindings": [
                    "exact_canonical_aggregate_squash_commit",
                    "exact_canonical_aggregate_squash_tree",
                    "successful_exact_head_main_push_ci_run",
                ],
                "auto_promote_on_merge": False,
                "canonical_publication_root_complete": False,
            },
            "factory_projection_boundary": "Factory #77 natively certifies only 59 written fields plus handler-local absence of Pool.tick; the other 226 stored fields are outside that 60-field contract, not asserted outside runtime store reachability",
            "normalized_category_boundary": "the four categories are conservative handler-relative normalization buckets: setter/direct-write authority, component-native nonsetter classification, outside certified scope, and derived; they preserve exact source-native categories but do not uniformly prove a matching Store path, common execution, branch correlation, receiver must-alias, visibility or persistence",
            "swap_receiver_boundary": "repaired Swap binds exact setter receiver flows, exact store target/receiver/value flows, and lexically later same-group receiver-origin overlap; common execution, branch correlation and receiver must-alias remain false",
            "npm_transaction_boundary": "corrected Collect and Liquidity bind four common Transaction setters plus one Transaction save on either a completed hit or miss, with id additionally miss-only; visibility between two invocations and last-writer semantics remain false",
            "overlay_boundary": "handler-relative repeated evidence, distinct handler union, and population-required absence are separate denominators",
            "physical_ledger_boundary": "component physical ledgers have heterogeneous unique, weighted, expanded and site denominators and are retained separately rather than summed",
            "order_boundary": "manifest handler declaration order and the Graph Node reference-stage model are bound without claiming target runtime identity, a flattened global schedule, Store visibility, or last writer",
            "issue_boundary": "this static aggregation completes no additional issue #37 or #38 checkbox; checkboxes_completed_by_this_certificate remains empty for both and neither issue is closed",
        },
        "source_roots": source_roots,
        "source_roots_sha256": canonical_sha256(source_roots),
        "component_manifest": component_manifest,
        "component_manifest_sha256": canonical_sha256(component_manifest),
        "canonical_reseal_required": False,
        "canonical_reseal_order": [],
        "post_merge_aggregate_publication_seal_required": True,
        "schema_catalog": sources["schema"],
        "handler_catalog": [
            {
                "handler": handler,
                "handler_id": HANDLERS[handler],
                "component": component_for_handler(handler),
                "field_count_per_segment": 299,
            }
            for handler in HANDLERS
        ],
        "aggregate_category_counts": expected_totals,
        "physical_ledgers": physical_ledgers,
        "physical_ledgers_globally_summed": False,
        "segments": segments,
        "overlays": overlays,
        "setter_authority": setter_authority,
        "manifest_handler_order": {
            "records": manifest_order,
            "factory_datasource_handlers": MANIFEST_HANDLER_ORDER[:1],
            "npm_datasource_handlers": MANIFEST_HANDLER_ORDER[1:5],
            "pool_dynamic_template_handlers": MANIFEST_HANDLER_ORDER[5:],
            "manifest_declaration_is_global_category_schedule": False,
        },
        "execution_order_reference": {
            "contract_sha256": EXECUTION_ORDER_CANONICAL_SHA256,
            "execution_model": execution["execution_model"],
            "graph_node_reference": execution["graph_node_reference"],
            "target_runtime_identity_proven": False,
            "store_visibility_or_last_writer_proven": False,
        },
        "diffs": diffs,
        "issue_mapping": issue_mapping,
        "residual_blockers": {
            "publication": [
                "merging this aggregate to main as an exact canonical squash commit and tree is necessary but not sufficient for canonical publication",
                "after merge, a separate content-addressed publication seal must bind the exact canonical aggregate squash commit and tree plus a successful exact-head main-push CI run; this pre-merge candidate cannot auto-promote on merge",
            ],
            "semantic": [
                "imported host returns, numeric/comparator meaning, arbitrary aliases, Store visibility/persistence/rollback, post-fatal execution and field histories remain false",
                "normalized setter/direct-write cells do not uniformly prove matching-store execution; nonsetter cells make no preservation, unchanged-value, last-writer or persistence claim",
                "repaired Swap receiver-origin overlap does not prove common execution, branch correlation, or receiver must-alias",
                "handler-relative overlays do not imply population or query visibility",
            ],
            "execution": [
                "target runtime, integrated scheduler/output/Store/package, continuity, provider/oracle, parity, checkpoint, backfill, deployment, production and readiness remain false",
                "this certificate completes no additional #37 or #38 checkbox and neither issue is closed",
            ],
        },
        "truth_boundary": truth_boundary(),
    }


def verify_contract(
    root: Path,
    actual: dict[str, Any] | None = None,
    *,
    sources: dict[str, Any] | None = None,
    regenerate_components: bool = True,
    wasm2wat: Path | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    verified_sources = sources or load_sources(
        root,
        regenerate_components=regenerate_components,
        wasm2wat=wasm2wat,
    )
    expected = expected_contract_from_sources(root, verified_sources)
    if actual is None:
        path = root / CONTRACT_PATH
        require(path.is_file(), f"all-handlers v1 contract missing: {CONTRACT_PATH}")
        actual = load_json(path)
        require(path.read_text() == render(actual), "all-handlers v1 contract byte rendering drift")
    return verify_against_expected(actual, expected)


def verify_against_expected(actual: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    """Apply the final fail-closed equality and truth-gate checks."""

    require(canonical_bytes(actual) == canonical_bytes(expected), "all-handlers v1 contract differs from regenerated proof")
    truth = actual["truth_boundary"]
    require(set(truth) == set(TRUE_FLAGS) | set(FALSE_FLAGS), "truth-boundary key drift")
    for field in TRUE_FLAGS:
        require(truth[field] is True, f"proved gate drift: {field}")
    for field in FALSE_FLAGS:
        require(truth[field] is False, f"unproved gate promoted: {field}")
    return expected


def write_contract(
    root: Path,
    *,
    regenerate_components: bool = True,
    wasm2wat: Path | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    sources = load_sources(root, regenerate_components=regenerate_components, wasm2wat=wasm2wat)
    expected = expected_contract_from_sources(root, sources)
    path = root / CONTRACT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(expected))
    return expected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPOSITORY)
    parser.add_argument("--wasm2wat", type=Path)
    parser.add_argument("--write-contract", action="store_true")
    parser.add_argument(
        "--skip-component-regeneration",
        action="store_true",
        help="Only for focused mutation tests or a post-full detached byte check; source roots are still digest-bound.",
    )
    args = parser.parse_args()
    try:
        result = (
            write_contract(
                args.root,
                regenerate_components=not args.skip_component_regeneration,
                wasm2wat=args.wasm2wat,
            )
            if args.write_contract
            else verify_contract(
                args.root,
                regenerate_components=not args.skip_component_regeneration,
                wasm2wat=args.wasm2wat,
            )
        )
    except (OSError, subprocess.SubprocessError, tarfile.TarError, VerificationError) as error:
        print(f"Uniswap V3 all-handlers v1 verification failed: {error}", file=sys.stderr)
        return 1
    print(
        "verified candidate Uniswap V3 all-handlers v1: "
        f"{result['scope']['handler_count']} handlers x "
        f"{result['scope']['segment_count']} segments x "
        f"{result['scope']['schema_field_count']} fields = "
        f"{result['scope']['field_cell_count']} cells; all component roots canonical; aggregate publication pending; "
        "this certificate completes no additional #37/#38 checkbox; neither issue closed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
