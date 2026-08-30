#!/usr/bin/env python3
"""Generate and fail-closed verify bounded Factory fee-growth initialization v1."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import itertools
import json
import re
import sys
from pathlib import Path
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[1]
CONTRACT_PATH = Path("uniswap-v3/factory-fee-growth-init/v1/contract.json")
CONTRACT_VERSION = "uniswap-v3-factory-fee-growth-initialization/v1"
HANDLER_ID = "Factory.handlePoolCreated"
HANDLER_EXPORT = "handlePoolCreated"
SELECTED_FIELDS = ("feeGrowthGlobal0X128", "feeGrowthGlobal1X128")
LEGACY_MAP_SET = (
    "~lib/@graphprotocol/graph-ts/index/TypedMap<~lib/string/String_"
    "~lib/@graphprotocol/graph-ts/index/Value>#set"
)

FACTORY_EFFECTS_VERIFIER_PATH = REPOSITORY / "scripts/verify-uniswap-v3-factory-effects.py"
FACTORY_EFFECTS_VERIFIER_SHA256 = "547cd30d69cf8a149d50b7e35accda423dbec123e1b61bb73d7371bd16d45ee0"
FACTORY_EFFECTS_CONTRACT_PATH = Path("uniswap-v3/factory-effects/v1/contract.json")
FACTORY_EFFECTS_CONTRACT_SHA256 = "f737d67550721ed418d8b5fb83424a55e429dceea7596643c69748458c5ac892"

MODERN_VERIFIER_PATH = REPOSITORY / "scripts/verify-uniswap-v3-modern-factory-static.py"
MODERN_VERIFIER_SHA256 = "140d7e5649c03e3f59027ba2c3505196fd98b5a2211868e535e9cd4a32a60eb3"
MODERN_CONTRACT_PATH = Path("uniswap-v3/factory-static/v1/contract.json")
MODERN_CONTRACT_SHA256 = "c5a71b98fc28082aff3dea6b0b22916c86e7efb8ccbec24b2af228948091ed51"
MODERN_CONTRACT_VERSION = "uniswap-v3-modern-factory-static/v1"

FEE_GROWTH_VERIFIER_PATH = REPOSITORY / "scripts/verify-uniswap-v3-pool-swap-fee-growth.py"
FEE_GROWTH_VERIFIER_SHA256 = "392fcebecd72abe912af34d256bbc01b42f1ddb4b9b04dab645d6c1669f42932"
FEE_GROWTH_CONTRACT_PATH = Path("uniswap-v3/pool-swap-fee-growth/v1/contract.json")
FEE_GROWTH_CONTRACT_SHA256 = "28e12268ebd6ddf78c4d6e59805967793630c6475ca6f0b332fefcf46c5b6b9b"
FEE_GROWTH_CONTRACT_VERSION = "uniswap-v3-pool-swap-fee-growth-semantics/v1"

WRITER_COMPATIBILITY_PATH = Path("uniswap-v3/graft-ancestry/v2/writer-compatibility.json")
WRITER_COMPATIBILITY_SHA256 = "259481724561d5aa725c17f90b5a19ea93ad6f7cd6074cf2cb8a8661c39f81c4"
V2_VERIFIER_PATH = REPOSITORY / "scripts/verify-uniswap-v3-segment-field-semantics-v2.py"
V2_VERIFIER_SHA256 = "e14a7ad95f9124861c36f72b60927f02200cfc02ad06eddf31eb36d7cc54e5ec"
V2_CONTRACT_PATH = Path("uniswap-v3/segment-field-semantics/v2/contract.json")
V2_CONTRACT_SHA256 = "0ca8708bd2ed60d4799559d52b3f7e0602abfd7c3edbd35f579476f00baba6ef"
MATRIX_VERIFIER_PATH = REPOSITORY / "scripts/verify-uniswap-v3-segment-writer-matrix.py"
MATRIX_VERIFIER_SHA256 = "1e9055f66517c1dada37b6dadd4770fddf505f38d2578349c7a07b46e567fc2f"
MATRIX_CONTRACT_PATH = Path("uniswap-v3/segment-writer-matrix/v1/contract.json")
MATRIX_CONTRACT_SHA256 = "7f6d1a34a8c885fe5ddcd81895818ba7ae8a0d736d541b881c1cc7cd54275161"
RUNTIME_PATH = Path("scripts/uniswap_v3_wat_runtime.py")
RUNTIME_SHA256 = "bd555b5d44bed144777e35b361fcb63e275d7f21b774db3ffe0e08bef3bf4411"

CANONICAL_BASE = {
    "canonical_merge_commit": "cf4d096304c09f150a7ee2ea85de5d479d5ec7ef",
    "canonical_merge_tree": "346c9ba3eb141ada18d4ee1589a725919b349351",
    "canonical_merge_parent": "27dc439b150bbade46b6552d9e8611bc3c00da6f",
    "canonical_merge_parent_tree": "1345a42221c47c56783fbb0d5f3acbc6707a04ce",
    "audited_candidate_commit": "4e173177089ae0781e389588d11dfe1a8d013391",
    "audited_candidate_tree": "346c9ba3eb141ada18d4ee1589a725919b349351",
    "candidate_tree_equals_canonical_merge_tree": True,
    "status": "exact canonical PR 71 squash merge; tree equality with the independently audited candidate verified before deterministic regeneration",
}


class VerificationError(RuntimeError):
    pass


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
    output: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in output, f"duplicate JSON key: {key}")
        output[key] = value
    return output


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(), object_pairs_hook=reject_duplicate_keys)
    except (OSError, json.JSONDecodeError) as error:
        raise VerificationError(f"cannot load {path}: {error}") from error


def load_module(name: str, path: Path, digest: str) -> Any:
    require(path.is_file(), f"required verifier missing: {path}")
    require(raw_sha256(path) == digest, f"verifier digest drift: {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"cannot load verifier: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


MODERN = load_module("uniswap_v3_modern_factory_static_for_fee_growth_init", MODERN_VERIFIER_PATH, MODERN_VERIFIER_SHA256)
FEE_GROWTH = load_module("uniswap_v3_pool_swap_fee_growth_for_factory_init", FEE_GROWTH_VERIFIER_PATH, FEE_GROWTH_VERIFIER_SHA256)
EFFECTS = MODERN.EFFECTS
V2 = EFFECTS.V2
WRITER = EFFECTS.WRITER
RUNTIME = MODERN.RUNTIME


def normalized(line: str) -> str:
    return EFFECTS.normalized(line)


def call_name(line: str) -> str | None:
    return EFFECTS.call_name(line)


def function_sha256(function: Any) -> str:
    return hashlib.sha256(function.payload).hexdigest()


def function_by_suffix(context: dict[str, Any], suffix: str) -> Any:
    matches = [function for name, function in context["functions"].items() if name.endswith(suffix)]
    require(len(matches) == 1, f"{context['cid']} expected one function ending {suffix}, got {len(matches)}")
    return matches[0]


def slice_sha256(function: Any, start: int, end: int, *, normalize: bool = False) -> str:
    lines = function.lines[start:end]
    if normalize:
        lines = [normalized(line) for line in lines]
    return hashlib.sha256(("\n".join(lines) + "\n").encode()).hexdigest()


def decoded_constant(line: str, memory: bytearray) -> str | None:
    return V2.decoded_wat_constant(line, memory)


EXPECTED: dict[str, dict[str, Any]] = {
    "legacy-base-root": {
        "cid": "QmUN4pxwjMTfNem7rf1sKNFNHDsfzpbcTP93RxPAczgkvj",
        "wasm_bytes": 21108,
        "wasm_sha256": "0855ce1d5260cd8395628dfac2e18db063909168c58e7d5de118612fee9f9a4e",
        "wat_sha256": "c2e7425784b498481ee8a822be18b59edd7aa6dd27712d8d093696cf0b8b1684",
        "wat_line_count": 4647,
        "handler_start": 4000,
        "handler_sha256": "8c2c0b729892664f7f57430de9a933ec594899ce14d17a70ad0eee8b28b1c006",
        "setter_keys": [3984, 4032],
        "setter_sha256": "e7e8cedaba31ae83a371f9f54fec98c5bce8024050b5bc2516c03a923cafb4c4",
        "through_save_sha256": "6922be0f2b3929a944af90a0b4dcba5f2f48f2913def443c93f3e3249f547107",
        "pool_save": [3904, "c718f4d0f930b733fbf3212321702fa2364c52c117c15c21efed55ec9468044d", 1208, 4656],
        "constructor_sha256": "15a42bc481a223c54f4c2b31c2ec471c86e5464f90bf6c232867739b45d9ecd8",
        "global_definition_sha256": "7bd16e7d1562a9677f4cd3a1e229f214032cb57bad48f3f705b09b9b44c20ed7",
        "start": [4502, "ead89f6e651aba5608849ebe1ae69c326baa48f40296c2be2dd2367a415d304f", 320],
        "constants": ["c3324635ceff39f7aca750567229a2db8782142480af611d4c96789f807d2aae", 5040],
        "static": [3127, 38, "013e364b16701b5105ebebeafcfd1fa4895e221e2b73707ef782657dbb07af0d"],
        "mutation": [101, "1cdcdf861ec9dfaf3373ebf04a48882e8a71dbdea6b3b9daf9fe870d3d73a4c4", 146, "b3abe0f91674b16cbb77e24b5d7130d424ffaf2029f44807a3fbba053d91abcf", 44, "4a092c36de00fd8db33a127b4ae96f39526a5151617a5512077310e64eef9abd"],
    },
    "legacy-mainnet-qmrv": {
        "cid": "QmT8CKmLDFFCgwYnubFhKXUsuer5rfJKPT4PrCsv9tTwjV",
        "wasm_bytes": 23945,
        "wasm_sha256": "c90c4b86b184d8ffed606f3264d6f3b921421ef7dce2cb35484dd7faaf452cd4",
        "wat_sha256": "4263d51999d58769c06bef6da1aed4c24c1c846f4b0aaed9142bf3bd912ecf9b",
        "wat_line_count": 4767,
        "handler_start": 4087,
        "handler_sha256": "e28b09377fd2e7fa10dfa0a7afaccd7f120b35d4b9be5f4be6a5c6c819a41f2c",
        "setter_keys": [6376, 6424],
        "setter_sha256": "4233edda056571a72b02c2fd515399d77a2f86005b46fe9388d3430eccf1d8e0",
        "through_save_sha256": "d95897c7401132facd1020aa7298befe4ea61e199447c9a4dc19bbf57d589a9f",
        "pool_save": [3991, "d9e40b5591d57db0db268e836ba92ca92370a47bbc18705d416f41329dfe7323", 2976, 7048],
        "constructor_sha256": "f8fa45c869143c601df6e63b9961a01b6c834d81b5ef7b52de720380eae248aa",
        "global_definition_sha256": "93c5508d50be6ca89d3e1e5a7d86f6c79d9fe7079d008fbd83787bd5480fb220",
        "start": [4589, "7984496d059477d42684a3929def1e2ad4c8ee93b903549c359ee1b2d4ea3ced", 2424],
        "constants": ["4fc4de5cd334c480810784e72bf47e2f056bac6f035eaca2d2c5963c90256b33", 7432],
        "static": [3156, 59, "15748b7c0c837b067fec5d182936fecccbae943d83dcdf979ee24729b0515e07"],
        "mutation": [103, "c7296eae5fd3e6d462ef9a1c00c6eff2af2f0b780ea56b94c165a987ae0f3d88", 154, "ea227a317874c09469b14e3370d76380ce01662f5c7f2e6afa1bd9f48ef2ae96", 44, "4a092c36de00fd8db33a127b4ae96f39526a5151617a5512077310e64eef9abd"],
    },
    "legacy-mainnet-root": {
        "cid": "QmUu9rnGvUiBbF9pLnuJQab1wHXqjooo3bY5cZDVTyQQgr",
        "wasm_bytes": 23850,
        "wasm_sha256": "ab7c84297665ab608ce3c6b8cc71f1c584ae7f2a94ebe674993b069d6b8b5c98",
        "wat_sha256": "1fbcd7b7305dd0e0eb2e9de2e64ecb023e9aa5abe29f7562be4dad72bf561f4d",
        "wat_line_count": 4766,
        "handler_start": 4087,
        "handler_sha256": "266f6faad4b727316ecdb49a8fd0994fb9f33a0d007dad32c6308a6305529417",
        "setter_keys": [6288, 6336],
        "setter_sha256": "8f3e9000df4cae64f5afa6096ba591eccaf598d9759d67237c7ad66cf400f522",
        "through_save_sha256": "fc5187adc4d368daab0407ab263c3d32bf1779d1526bdf99d8afa34992e3729d",
        "pool_save": [3991, "1c51965d0530b2abf946b398e383aae4fe60b575270b91b7ff815789c49bd4a1", 2888, 6960],
        "constructor_sha256": "df4449b5dc9aa60c5afdcfabf89a8a44e682fbc093d9dab42627ddda59563206",
        "global_definition_sha256": "a51fe10d184a5f0023c7fcd7e96952c394572d9285ac4ce020033903e28b5990",
        "start": [4589, "c66ac7f29dea788cfdb7e3b643286a1c546edbcd06e7d0dab09449eee2b7e7eb", 2336],
        "constants": ["183998f25d49e79fe20072b83a65cfea8c9633f42146a168b0d620f34dccc1aa", 7344],
        "static": [3156, 59, "9051574d3c857731cd1a22305d56178da12f4e25f5a75a75bfed87b8a299bc4a"],
        "mutation": [103, "3ae22ab5bc71f14befb82a144d54d0e45c7b001f4d84ea690048fdea69c59f29", 154, "ea227a317874c09469b14e3370d76380ce01662f5c7f2e6afa1bd9f48ef2ae96", 44, "4a092c36de00fd8db33a127b4ae96f39526a5151617a5512077310e64eef9abd"],
    },
    "legacy-mainnet-stable": {
        "cid": "QmcsaU3DrUqZHZLzrrWT9aW4EVQuS54wxNHynq8g1PvESL",
        "wasm_bytes": 23986,
        "wasm_sha256": "1bde476d96fd4ba7720246a351c4de0f129693d838f9a39a660097c85d1edead",
        "wat_sha256": "d44ed8c0bbd1bdf62635871b475fbe1a22c8d3a4b88e5d77e6827e3e61b70f81",
        "wat_line_count": 4769,
        "handler_start": 4087,
        "handler_sha256": "cfaa881acf0c9a45f3f71af203c0587f86bad622083db6c15c2c4f77a8274a09",
        "setter_keys": [6416, 6464],
        "setter_sha256": "47684f79093eeef6007b2df760a3bda3ec39b2210ede74958c708708cc36031a",
        "through_save_sha256": "ec7223aeda5e8c713037b3f90529ce4a0f8832193a5df6744e1fed2c692568b1",
        "pool_save": [3991, "04167d2b1470287c00c69402ae80ca14018c2c407f41f875e52ec3a2621e0c05", 3016, 7088],
        "constructor_sha256": "ec0bcc5ed6c841a72638cb8311501d994c5565b3a6b339999b870397a943503c",
        "global_definition_sha256": "a51fe10d184a5f0023c7fcd7e96952c394572d9285ac4ce020033903e28b5990",
        "start": [4589, "a9fc8a85c7c82a64842272758f7c712d08a99ab8f974f3ace7b31d71d61fe878", 2464],
        "constants": ["60a188481251f4cb6107347db621a80d0ad72c0129e9d688fa9c41d787bcb246", 7472],
        "static": [3156, 59, "8ec71a3c882bc75982b9004a79e8a5b100e853b9826ff63c0f12eef194707e6e"],
        "mutation": [103, "55f3f553c2cc35606ffd8b725291c4e28d832c8d44f865f69729d2f6df2ea1c1", 154, "ea227a317874c09469b14e3370d76380ce01662f5c7f2e6afa1bd9f48ef2ae96", 44, "4a092c36de00fd8db33a127b4ae96f39526a5151617a5512077310e64eef9abd"],
    },
}

ORIGIN_RAW_SHA256 = "e29ee02582698d960339c9f080f461a9db90f0e97d8b62d7f99d33f624f3f95c"
ORIGIN_NORMALIZED_SHA256 = "c8091502d50ab53483cac7a778ffce1c9c05b1280bf7f4c29c59c35aae38cdae"
GLOBAL_SET_INVENTORY_SHA256 = "2d6aeacb9c69e6e4d68a641f6abe75359df13f1003db16e6ae6bd2910d45b9bf"
EXPORT_INVENTORY_SHA256 = "88f75c961ddb24afb7caa6e5d7586fd56b30287ed4a9106bc246f830945fd553"
IMPORT_INVENTORY_SHA256 = "3669e431606d1581abd1c97b6b2dbfc7178dbf141863e2b1510280c08f396408"
BYTE_ARRAY_FROM_I32_SHA256 = "0f22bbd2551c99534fb72e257c747fd8d191774176d7bba1f4d75787f829229c"
VALUE_FROM_BIGINT_SHA256 = "d6229f3af9fbb690bcb4820127a2aaf953eebcf9785a26d7c01be7517973cc6b"
TYPED_MAP_SET_SHA256 = "5ab31969af87a734b8fb29f32ae0046b68dade3b74c24b320bab0fbdd4fde923"
TOTAL_SUPPLY_SHA256 = "9deb6953c179c0de5f6b3cab30a38c9f9ee62af22daadce8f9c56eeaada0ae07"
MEMORY_RESET_SHA256 = "9767c060a0ccee2ec358b573bf2c7334e08e0cca9e14f7618c01cffa39d50c1c"
EXPANDED_MAP_WRITE_INVOCATIONS_SHA256 = "e1786369ca1dccbf1328ec9f0534c5f2059851dbc65bc8a2c2a940f85be6b3a9"
SETTER_DECODED_KEY_NORMALIZED_SHA256 = "92d6e327b1e98bb4a0889af7f18c4b55d24e1afc6872950df9f52cc91b420605"
THROUGH_SAVE_DECODED_STRING_NORMALIZED_SHA256 = "1e50d552ad313df092f2c6c271ff49eb81ccf17fc14de542d3c64547c8f14b79"

EXPECTED_GLOBAL_WRITERS = {
    "$g0": [["start:src/utils/constants", 2]],
    "$g1": [["~lib/allocator/arena/__memory_allocate", 59], ["start:src/utils/constants", 4], ["~lib/memory/memory.reset", 2]],
    "$g2": [["start:src/utils/constants", 7]],
    "$g3": [["start:src/utils/constants", 10]],
    "$g4": [["start:src/utils/constants", 13]],
    "$g5": [["start:src/utils/constants", 16]],
    "$g6": [["start:src/utils/constants", 19]],
    "$g7": [["start:src/utils/constants", 24]],
    "$g8": [],
    "$g9": [["start", 4]],
    "$g10": [["start", 6]],
    "$g11": [["~lib/@graphprotocol/graph-ts/index/ByteArray.fromHexString", 45]],
}

TRUE_FLAGS = (
    "factory_effects_parent_recomputed_and_pinned",
    "modern_factory_static_parent_recomputed_and_pinned",
    "pool_swap_fee_growth_parent_recomputed_and_pinned",
    "four_exact_legacy_factory_artifacts_and_handlers_bound",
    "four_native_start_and_complete_global_writer_inventories_bound",
    "four_pool_receiver_origin_flows_bound",
    "eight_legacy_fee_growth_setter_call_operand_flows_bound",
    "four_same_receiver_setter_call_through_pool_save_call_flows_bound",
    "four_pool_save_id_trap_and_store_capsules_bound",
    "four_excluded_pool_and_decimals_return_boundaries_bound",
    "four_reachable_mutation_and_store_inventories_bound",
    "six_legacy_segment_projections_present",
    "twelve_legacy_segment_field_records_present",
    "two_modern_parent_segment_projections_present",
    "sixteen_total_initialization_records_present",
    "all_twenty_eight_scoped_pairwise_diffs_present",
    "cumulative_field_ledger_remains_36_selected_230_residual",
    "cumulative_factory_closure_remains_14_of_18",
)

FALSE_FLAGS = (
    "legacy_factory_complete_static_handler_contracts_proven",
    "all_six_factory_complete_static_handler_contracts_proven",
    "all_sixty_legacy_stored_fields_proven",
    "legacy_static_arrays_safe",
    "legacy_total_supply_decodes_erc20_return_data",
    "actual_historic_handler_outcomes_bound",
    "runtime_population_complete",
    "numeric_zero_preserved_across_host_reset_lifecycle",
    "cross_handler_allocator_freshness_proven",
    "fresh_value_allocation_proven",
    "typed_map_get_entry_semantics_rederived",
    "typed_map_get_semantics_rederived",
    "typed_map_entry_constructor_semantics_rederived",
    "typed_map_entry_array_push_semantics_rederived",
    "entity_constructor_semantics_rederived",
    "entity_backing_array_construction_semantics_rederived",
    "value_to_string_semantics_rederived",
    "legacy_selected_field_mutation_proven",
    "imported_host_semantics_rederived",
    "bytes_to_hex_host_semantics_rederived",
    "numeric_host_semantics_rederived",
    "graph_store_host_semantics_rederived",
    "graph_handler_rollback_proven_by_retained_wat",
    "post_fatal_execution_modeled",
    "selected_persistence_proven",
    "no_later_selected_field_overwrites_proven",
    "complete_factory_entity_history",
    "complete_pool_entity_history",
    "complete_fee_growth_history",
    "dynamic_datasource_combined_handler_order_implemented",
    "writer_package_consumes_projection",
    "configured_package_identity_bound",
    "boundary_continuity_complete",
    "graph_oracle_complete",
    "logical_parity_complete",
    "physical_parity_complete",
    "poi_parity_complete",
    "checkpoint_authority",
    "issue_37_acceptance_criterion_complete",
    "issue_38_acceptance_criterion_complete",
    "backfill_ready",
    "deployment_authority",
    "production_ready",
    "readiness_complete",
)


def _stripped_inventory(module_text: str, prefix: str) -> tuple[list[str], str]:
    lines = [line.strip() for line in module_text.splitlines() if line.strip().startswith(prefix)]
    digest = hashlib.sha256(("\n".join(lines) + "\n").encode()).hexdigest()
    return lines, digest


def _complete_global_writer_inventory(functions: dict[str, Any]) -> dict[str, list[list[Any]]]:
    result: dict[str, list[list[Any]]] = {f"$g{index}": [] for index in range(12)}
    for function_name, function in functions.items():
        for index, raw_line in enumerate(function.lines):
            match = re.fullmatch(r"global\.set (\$g\d+)\)?", normalized(raw_line))
            if match is not None:
                require(match.group(1) in result, f"writer targets unexpected global {match.group(1)}")
                result[match.group(1)].append([function_name, index])
    return result


def prove_artifact_authority(context: dict[str, Any]) -> dict[str, Any]:
    profile = context["profile"]["profile_id"]
    require(profile in EXPECTED, f"unexpected legacy Factory profile: {profile}")
    expected = EXPECTED[profile]
    handler = context["handler"]
    wat_text = context.get("wat_text")
    require(context["cid"] == expected["cid"], f"{profile} Factory CID drift")
    require(context["profile"]["metadata_generation"] == "legacy", f"{profile} is no longer legacy")
    require(isinstance(wat_text, str), f"{profile} complete WAT text missing")
    require(context["analysis"]["bytes"] == expected["wasm_bytes"], f"{profile} WASM byte count drift")
    require(context["analysis"]["sha256"] == expected["wasm_sha256"], f"{profile} WASM digest drift")
    require(hashlib.sha256(wat_text.encode()).hexdigest() == expected["wat_sha256"], f"{profile} WAT digest drift")
    require(len(wat_text.splitlines()) == expected["wat_line_count"], f"{profile} WAT line count drift")
    require(
        (handler.start_line, len(handler.lines), function_sha256(handler))
        == (expected["handler_start"], 443, expected["handler_sha256"]),
        f"{profile} exact handlePoolCreated binding drift",
    )
    calls = [call_name(line) for line in handler.lines if call_name(line) is not None]
    local_writes = [
        [index, normalized(line)]
        for index, line in enumerate(handler.lines)
        if re.fullmatch(r"local\.(?:set|tee) \$[lp]\d+\)?", normalized(line))
    ]
    direct_writes = [
        [index, normalized(line)]
        for index, line in enumerate(handler.lines)
        if RUNTIME.is_direct_memory_write(line, normalized)
    ]
    returns = [index for index, line in enumerate(handler.lines) if normalized(line) == "return"]
    require(len(calls) == 182, f"{profile} handler direct-call count drift")
    require(len(local_writes) == 15, f"{profile} handler local-write count drift")
    require(len(direct_writes) == 1, f"{profile} handler direct-memory-write count drift")
    require(returns == [8, 137, 211], f"{profile} handler return inventory drift")
    return {
        "mapping_cid": context["cid"],
        "artifact_path": context["artifact_path"],
        "wasm_bytes": expected["wasm_bytes"],
        "wasm_sha256": expected["wasm_sha256"],
        "wat_sha256": expected["wat_sha256"],
        "wat_line_count": expected["wat_line_count"],
        "handler_function": handler.name,
        "handler_wat_start_line": handler.start_line,
        "handler_line_count": len(handler.lines),
        "handler_body_sha256": function_sha256(handler),
        "handler_direct_call_count": len(calls),
        "handler_local_write_count": len(local_writes),
        "handler_direct_memory_write_count": len(direct_writes),
        "handler_return_relative_wat_lines": returns,
    }


def prove_native_start_and_g2(context: dict[str, Any]) -> dict[str, Any]:
    profile = context["profile"]["profile_id"]
    expected = EXPECTED[profile]
    module_text = context["wat_text"]
    exports = context["exports"]
    functions = context["functions"]
    require(RUNTIME.native_start_directives(module_text) == ["(start $start)"], f"{profile} native start drift")
    require("_start" not in exports, f"{profile} acquired _start export")
    require(exports.get(HANDLER_EXPORT) == context["handler"].name, f"{profile} handler export drift")
    export_lines, export_digest = _stripped_inventory(module_text, "(export ")
    import_lines, import_digest = _stripped_inventory(module_text, "(import ")
    global_lines, global_digest = _stripped_inventory(module_text, "(global ")
    require(len(export_lines) == 7 and export_digest == EXPORT_INVENTORY_SHA256, f"{profile} export inventory drift")
    require(len(import_lines) == 11 and import_digest == IMPORT_INVENTORY_SHA256, f"{profile} import inventory drift")
    require(len(global_lines) == 12 and global_digest == expected["global_definition_sha256"], f"{profile} global definitions drift")
    writers = _complete_global_writer_inventory(functions)
    require(writers == EXPECTED_GLOBAL_WRITERS, f"{profile} complete global writer inventory drift")
    require(canonical_sha256(writers) == GLOBAL_SET_INVENTORY_SHA256, f"{profile} global writer digest drift")

    start = functions.get("start")
    require(start is not None, f"{profile} start function missing")
    start_line, start_digest, decimal_pointer = expected["start"]
    require((start.start_line, len(start.lines), function_sha256(start)) == (start_line, 7, start_digest), f"{profile} start body drift")
    require(
        [normalized(line) for line in start.lines[1:7]]
        == [
            "call $start:src/utils/constants",
            f"i32.const {decimal_pointer}",
            "call $~lib/@graphprotocol/graph-ts/index/bigDecimal.fromString",
            "global.set $g9",
            "call $~lib/math/NativeMath.pow",
            "global.set $g10)",
        ],
        f"{profile} native start dependency flow drift",
    )

    constants = functions.get("start:src/utils/constants")
    require(constants is not None, f"{profile} constants initializer missing")
    constants_digest, allocator_floor = expected["constants"]
    require((constants.start_line, len(constants.lines)) == (492, 25), f"{profile} constants function binding drift")
    constant_lines = [normalized(line) for line in constants.lines]
    require(
        constant_lines[1:11]
        == [
            f"i32.const {allocator_floor}",
            "global.set $g0",
            "global.get $g0",
            "global.set $g1",
            "i32.const 0",
            "call $~lib/@graphprotocol/graph-ts/index/ByteArray.fromI32",
            "global.set $g2",
            "i32.const 1",
            "call $~lib/@graphprotocol/graph-ts/index/ByteArray.fromI32",
            "global.set $g3",
        ],
        f"{profile} zero/one constant construction drift",
    )
    require(function_sha256(constants) == constants_digest, f"{profile} constants body drift")
    require(writers["$g2"] == [["start:src/utils/constants", 7]], f"{profile} $g2 is not uniquely initialized")

    byte_array = function_by_suffix(context, "index/ByteArray.fromI32")
    require((byte_array.start_line, len(byte_array.lines), function_sha256(byte_array)) == (431, 34, BYTE_ARRAY_FROM_I32_SHA256), f"{profile} ByteArray.fromI32 drift")
    memory_reset = function_by_suffix(context, "~lib/memory/memory.reset")
    require(len(memory_reset.lines) == 3 and function_sha256(memory_reset) == MEMORY_RESET_SHA256, f"{profile} memory.reset drift")
    require(
        [normalized(line) for line in memory_reset.lines[1:3]] == ["global.get $g0", "global.set $g1)"],
        f"{profile} memory.reset floor flow drift",
    )
    require(exports.get("memory.reset") == memory_reset.name, f"{profile} memory.reset export drift")
    table_lines, _ = _stripped_inventory(module_text, "(table ")
    element_lines, _ = _stripped_inventory(module_text, "(elem ")
    require(table_lines == ["(table $table 1 funcref)"], f"{profile} table drift")
    require(element_lines == ["(elem $e0 (i32.const 0) func $null)"], f"{profile} table element drift")
    indirect_sites = [
        [name, index]
        for name, function in functions.items()
        for index, line in enumerate(function.lines)
        if "call_indirect" in normalized(line)
    ]
    reset_calls = [
        [name, index]
        for name, function in functions.items()
        for index, line in enumerate(function.lines)
        if call_name(line) == memory_reset.name
    ]
    require(indirect_sites == [], f"{profile} acquired call_indirect")
    require(reset_calls == [], f"{profile} acquired internal memory.reset call")
    reachable = WRITER.reachable_functions(functions, context["handler"], tuple(context["indirect"]))
    require(memory_reset.name not in reachable, f"{profile} handler reaches memory.reset")
    return {
        "native_start_directive": "(start $start)",
        "native_start_function": start.name,
        "native_start_body_sha256": function_sha256(start),
        "underscore_start_export_present": False,
        "constants_function": constants.name,
        "constants_body_sha256": function_sha256(constants),
        "zero_to_byte_array_to_g2_relative_wat_lines": [5, 6, 7],
        "byte_array_from_i32": {"function": byte_array.name, "body_sha256": function_sha256(byte_array)},
        "complete_module_surface": {
            "export_count": len(export_lines),
            "export_inventory_sha256": export_digest,
            "import_count": len(import_lines),
            "ordered_import_inventory_sha256": import_digest,
            "global_definition_count": len(global_lines),
            "global_definition_inventory_sha256": global_digest,
        },
        "complete_global_set_inventory": writers,
        "complete_global_set_inventory_sha256": canonical_sha256(writers),
        "g2_unique_internal_writer_machine_proven": True,
        "table_and_reset_boundary": {
            "table": table_lines[0],
            "element": element_lines[0],
            "call_indirect_sites": indirect_sites,
            "internal_memory_reset_callsites": reset_calls,
            "memory_reset_export": "memory.reset",
            "memory_reset_body_sha256": function_sha256(memory_reset),
            "handler_reaches_memory_reset": False,
            "cross_handler_allocator_freshness_proven": False,
        },
        "numeric_zero_preserved_across_host_reset_lifecycle": False,
        "imported_host_semantics_rederived": False,
    }


def prove_receiver_origin(context: dict[str, Any]) -> dict[str, Any]:
    profile = context["profile"]["profile_id"]
    expected = EXPECTED[profile]
    handler = context["handler"]
    require(
        [normalized(line) for line in handler.lines[84:90]]
        == [
            "local.get $p0",
            "call $src/types/Factory/Factory/PoolCreated__Params#constructor",
            "call $src/types/Factory/Factory/PoolCreated__Params#get:pool",
            "call $~lib/@graphprotocol/graph-ts/index/typeConversion.bytesToHex",
            "call $src/types/schema/Factory#constructor",
            "local.set $l1",
        ],
        f"{profile} event-to-Pool receiver flow drift",
    )
    require(slice_sha256(handler, 84, 90) == ORIGIN_RAW_SHA256, f"{profile} Pool origin raw slice drift")
    require(slice_sha256(handler, 84, 90, normalize=True) == ORIGIN_NORMALIZED_SHA256, f"{profile} Pool origin normalized slice drift")
    constructor = function_by_suffix(context, "src/types/schema/Factory#constructor")
    require(len(constructor.lines) == 11, f"{profile} generic entity constructor length drift")
    constructor_lines = [normalized(line) for line in constructor.lines]
    require(
        constructor_lines[2:11]
        == [
            "i32.const 4",
            "call $~lib/allocator/arena/__memory_allocate",
            "call $~lib/@graphprotocol/graph-ts/index/Entity#constructor",
            "local.tee $l1",
            constructor_lines[6],
            "local.get $p0",
            "call $~lib/@graphprotocol/graph-ts/index/Value.fromString",
            f"call ${LEGACY_MAP_SET}",
            "local.get $l1)",
        ],
        f"{profile} generic entity constructor receiver/ID flow drift",
    )
    require(decoded_constant(constructor.lines[6], context["memory"]) == "id", f"{profile} constructor ID key drift")
    require(function_sha256(constructor) == expected["constructor_sha256"], f"{profile} generic entity constructor body drift")
    return {
        "event_parameter_local": "$p0",
        "event_params_constructor": "src/types/Factory/Factory/PoolCreated__Params#constructor",
        "event_pool_getter": "src/types/Factory/Factory/PoolCreated__Params#get:pool",
        "bytes_to_hex": "~lib/@graphprotocol/graph-ts/index/typeConversion.bytesToHex",
        "misleading_entity_constructor_symbol": "src/types/schema/Factory#constructor",
        "constructor_body_sha256": function_sha256(constructor),
        "constructor_decoded_id_key": "id",
        "selected_pool_receiver_local": "$l1",
        "relative_wat_lines": [84, 89],
        "absolute_wat_lines": [handler.start_line + 84, handler.start_line + 89],
        "raw_slice_sha256": slice_sha256(handler, 84, 90),
        "normalized_slice_sha256": slice_sha256(handler, 84, 90, normalize=True),
        "event_pool_to_generic_constructor_result_and_same_receiver_call_operand_flow_machine_proven": True,
        "entity_constructor_semantics_rederived": False,
        "constructor_id_field_mutation_proven": False,
        "symbol_name_used_as_semantic_authority": False,
        "bytes_to_hex_host_semantics_rederived": False,
    }


def decoded_string_normalized_slice_sha256(
    function: Any, memory: bytearray, start: int, end: int
) -> str:
    lines: list[str] = []
    for raw_line in function.lines[start:end]:
        line = raw_line.strip().replace("generated/schema/", "src/types/schema/")
        match = re.fullmatch(r"(i32\.const )(-?\d+)(.*)", line)
        if match is not None:
            value = WRITER.decode_assemblyscript_string(memory, int(match.group(2)))
            if value is not None:
                digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
                line = f"{match.group(1)}STATIC_STRING_{digest}{match.group(3)}"
        lines.append(line)
    return hashlib.sha256(("\n".join(lines) + "\n").encode()).hexdigest()


def prove_value_from_bigint(context: dict[str, Any]) -> dict[str, Any]:
    profile = context["profile"]["profile_id"]
    function = function_by_suffix(context, "Value.fromBigInt")
    require((function.start_line, len(function.lines)) == (2774, 11), f"{profile} Value.fromBigInt function binding drift")
    lines = [normalized(line) for line in function.lines]
    require(call_name(function.lines[2]) == "~lib/@graphprotocol/graph-ts/index/Value#constructor", f"{profile} Value allocation drift")
    result_match = re.fullmatch(r"local\.tee (\$l\d+)", lines[3])
    require(result_match is not None, f"{profile} Value result local drift")
    result_local = result_match.group(1)
    require(
        lines[4:11]
        == [
            "i32.const 7",
            "i32.store",
            f"local.get {result_local}",
            "local.get $p0",
            "i64.extend_i32_u",
            "i64.store offset=8",
            f"local.get {result_local})",
        ],
        f"{profile} Value kind/payload/return identity drift",
    )
    require(function_sha256(function) == VALUE_FROM_BIGINT_SHA256, f"{profile} Value.fromBigInt body drift")
    return {
        "function": function.name,
        "wat_start_line": function.start_line,
        "body_sha256": function_sha256(function),
        "value_kind": 7,
        "payload_input": "$p0",
        "payload_offset": 8,
        "same_constructor_return_pointer_receives_kind_payload_and_is_returned_machine_proven": True,
        "value_constructor_allocation_semantics_rederived": False,
        "fresh_value_allocation_proven": False,
    }


def prove_typed_map_set(context: dict[str, Any]) -> dict[str, Any]:
    profile = context["profile"]["profile_id"]
    function = function_by_suffix(context, LEGACY_MAP_SET)
    require((function.start_line, len(function.lines)) == (2742, 21), f"{profile} TypedMap#set function binding drift")
    lines = [normalized(line) for line in function.lines]
    require(
        lines[2:21]
        == [
            "local.get $p0",
            "local.get $p1",
            f"call ${LEGACY_MAP_SET.removesuffix('#set')}#getEntry",
            "local.tee $l3",
            "if $I0",
            "local.get $l3",
            "local.get $p2",
            "i32.store offset=4",
            "else",
            "i32.const 0",
            "local.get $p1",
            "local.get $p2",
            "call $~lib/@graphprotocol/graph-ts/chain/ethereum/ethereum.SmartContract#constructor",
            "local.set $p1",
            "local.get $p0",
            "i32.load",
            "local.get $p1",
            "call $~lib/array/Array<~lib/@graphprotocol/graph-ts/index/TypedMapEntry<~lib/string/String_~lib/@graphprotocol/graph-ts/index/Value>>#push",
            "end)",
        ],
        f"{profile} TypedMap outer update/entry-construction/push call-operand flow drift",
    )
    require(function_sha256(function) == TYPED_MAP_SET_SHA256, f"{profile} TypedMap#set body drift")
    return {
        "function": function.name,
        "wat_start_line": function.start_line,
        "body_sha256": function_sha256(function),
        "receiver_parameter": "$p0",
        "key_parameter": "$p1",
        "value_parameter": "$p2",
        "existing_entry_offset_4_store_operand_flow_machine_proven": True,
        "missing_entry_constructor_key_value_and_push_call_operand_flow_machine_proven": True,
        "get_entry_search_semantics_rederived": False,
        "entry_constructor_semantics_rederived": False,
        "entry_array_push_and_reallocation_semantics_rederived": False,
        "entity_backing_array_construction_semantics_rederived": False,
        "selected_field_mutation_proven": False,
    }


def prove_pool_save(context: dict[str, Any]) -> dict[str, Any]:
    profile = context["profile"]["profile_id"]
    expected = EXPECTED[profile]
    function = function_by_suffix(context, "src/types/schema/Pool#save")
    start, digest, id_pointer, pool_pointer = expected["pool_save"]
    require((function.start_line, len(function.lines)) == (start, 32), f"{profile} Pool#save function binding drift")
    lines = [normalized(line) for line in function.lines]
    require(lines[2] == "local.get $p0", f"{profile} Pool#save entity input drift")
    require(lines[3] == f"i32.const {id_pointer}" and decoded_constant(function.lines[3], context["memory"]) == "id", f"{profile} Pool#save ID key drift")
    require(call_name(function.lines[4]) == LEGACY_MAP_SET.removesuffix("#set") + "#get", f"{profile} Pool#save ID lookup drift")
    require(
        lines[5:15]
        == [
            "local.tee $l1",
            "i32.eqz",
            "if $I0",
            lines[8],
            lines[9],
            "i32.const 377",
            "i32.const 4",
            "call $~lib/env/abort",
            "unreachable",
            "end",
        ],
        f"{profile} Pool#save missing-ID trap drift",
    )
    require(decoded_constant(function.lines[8], context["memory"]) == "Cannot save Pool entity without an ID", f"{profile} missing-ID message drift")
    require(
        lines[15:27]
        == [
            "local.get $l1",
            "i32.load",
            "if $I1",
            lines[18],
            lines[19],
            "call $~lib/string/String.__concat",
            lines[21],
            "i32.const 378",
            "i32.const 4",
            "call $~lib/env/abort",
            "unreachable",
            "end",
        ],
        f"{profile} Pool#save wrong-kind trap drift",
    )
    require(decoded_constant(function.lines[18], context["memory"]) == "Cannot save Pool entity with non-string ID. ", f"{profile} wrong-kind message drift")
    require(lines[27] == f"i32.const {pool_pointer}" and decoded_constant(function.lines[27], context["memory"]) == "Pool", f"{profile} Pool store target drift")
    require(
        lines[28:32]
        == [
            "local.get $l1",
            "call $~lib/@graphprotocol/graph-ts/index/Value#toString",
            "local.get $p0",
            "call $~lib/@graphprotocol/graph-ts/index/store.set)",
        ],
        f"{profile} Pool#save store operands drift",
    )
    require(function_sha256(function) == digest, f"{profile} Pool#save body drift")
    return {
        "function": function.name,
        "wat_start_line": function.start_line,
        "line_count": len(function.lines),
        "body_sha256": function_sha256(function),
        "decoded_id_key": "id",
        "decoded_store_target": "Pool",
        "null_get_result_branch_abort_unreachable_machine_proven": True,
        "returned_value_non_string_kind_branch_abort_unreachable_machine_proven": True,
        "typed_map_get_semantics_rederived": False,
        "id_value_to_string_call_operand_flow_machine_proven": True,
        "value_to_string_semantics_rederived": False,
        "same_save_parameter_is_store_set_call_value_operand_machine_proven": True,
        "graph_store_host_semantics_rederived": False,
    }


def prove_selected_setter_through_save(context: dict[str, Any]) -> dict[str, Any]:
    profile = context["profile"]["profile_id"]
    expected = EXPECTED[profile]
    handler = context["handler"]
    memory = context["memory"]
    fields: list[dict[str, Any]] = []
    for ordinal, base in enumerate((341, 346)):
        field = SELECTED_FIELDS[ordinal]
        pointer = expected["setter_keys"][ordinal]
        require(
            [normalized(line) for line in handler.lines[base : base + 5]]
            == [
                "local.get $l1",
                f"i32.const {pointer}",
                "global.get $g2",
                "call $~lib/@graphprotocol/graph-ts/index/Value.fromBigInt",
                f"call ${LEGACY_MAP_SET}",
            ],
            f"{profile} {field} exact receiver/key/g2/Value/set flow drift",
        )
        require(decoded_constant(handler.lines[base + 1], memory) == field, f"{profile} {field} decoded key drift")
        fields.append(
            {
                "entity": "Pool",
                "field": field,
                "schema_type": "BigInt!",
                "receiver_local": "$l1",
                "decoded_key": field,
                "key_pointer": pointer,
                "value_global": "$g2",
                "value_wrapper": "Value.fromBigInt",
                "value_kind": 7,
                "setter": LEGACY_MAP_SET,
                "setter_relative_wat_line": base + 4,
                "setter_absolute_wat_line": handler.start_line + base + 4,
                "receiver_key_value_to_typed_map_set_call_machine_proven": True,
                "selected_field_mutation_proven": False,
            }
        )

    forbidden: list[dict[str, Any]] = []
    for index in range(341, 421):
        instruction = normalized(handler.lines[index])
        opcode = instruction.split(maxsplit=1)[0].lstrip("(").rstrip(")") if instruction else ""
        if opcode in {"return", "br", "br_if", "br_table", "if", "else", "end", "block", "loop", "select"}:
            forbidden.append({"relative_wat_line": index, "instruction": instruction})
    receiver_writes = [
        [index, normalized(handler.lines[index])]
        for index in range(90, 421)
        if normalized(handler.lines[index]) in {"local.set $l1", "local.tee $l1"}
    ]
    require(forbidden == [], f"{profile} selected setter-through-save control bypass drift")
    require(receiver_writes == [], f"{profile} selected Pool receiver reassignment drift")
    require(normalized(handler.lines[419]) == "local.get $l1", f"{profile} Pool save receiver drift")
    require(call_name(handler.lines[420]) == "src/types/schema/Pool#save", f"{profile} Pool save call drift")
    depths = V2.wat_control_depths(handler.lines)
    require(all(depths[index] == 0 for index in (341, 345, 346, 350, 419, 420)), f"{profile} selected flow control depth drift")
    require(slice_sha256(handler, 341, 351) == expected["setter_sha256"], f"{profile} selected setter raw slice drift")
    require(slice_sha256(handler, 341, 421) == expected["through_save_sha256"], f"{profile} setter-through-save raw slice drift")
    require(decoded_string_normalized_slice_sha256(handler, memory, 341, 351) == SETTER_DECODED_KEY_NORMALIZED_SHA256, f"{profile} decoded-key normalized setter drift")
    require(decoded_string_normalized_slice_sha256(handler, memory, 341, 421) == THROUGH_SAVE_DECODED_STRING_NORMALIZED_SHA256, f"{profile} decoded-string normalized through-save drift")
    return {
        "selected_fields": fields,
        "setter_raw_slice_relative_wat_lines": [341, 350],
        "setter_raw_slice_absolute_wat_lines": [handler.start_line + 341, handler.start_line + 350],
        "setter_raw_slice_sha256": slice_sha256(handler, 341, 351),
        "setter_decoded_key_normalized_sha256": decoded_string_normalized_slice_sha256(handler, memory, 341, 351),
        "setter_through_save_relative_wat_lines": [341, 420],
        "setter_through_save_absolute_wat_lines": [handler.start_line + 341, handler.start_line + 420],
        "setter_through_save_raw_sha256": slice_sha256(handler, 341, 421),
        "setter_through_save_decoded_string_normalized_sha256": decoded_string_normalized_slice_sha256(handler, memory, 341, 421),
        "forbidden_bypass_instructions": forbidden,
        "selected_pool_receiver_reassignments_after_origin_before_save": receiver_writes,
        "same_receiver_for_both_setter_calls_and_pool_save_call_machine_proven": True,
        "selected_field_mutation_proven": False,
        "conditional_normal_continuation_to_selected_region_only": True,
        "selected_persistence_proven": False,
        "no_later_selected_field_overwrites_proven": False,
    }


def prove_guard_and_return_boundaries(context: dict[str, Any]) -> dict[str, Any]:
    profile = context["profile"]["profile_id"]
    handler = context["handler"]
    lines = [normalized(line) for line in handler.lines]
    require(context["profile"]["excluded_pool"] == "0x8fe8d9bb8eeba3ed688069c3d6b556c9ca258248", f"{profile} excluded Pool literal drift")
    require(
        lines[2:10]
        == [
            "local.get $p0",
            "call $src/types/Factory/Factory/PoolCreated__Params#constructor",
            "call $src/types/Factory/Factory/PoolCreated__Params#get:pool",
            "call $~lib/@graphprotocol/graph-ts/index/ByteArray.fromHexString",
            "call $~lib/@graphprotocol/graph-ts/index/ByteArray#equals",
            "if $I0",
            "return",
            "end",
        ],
        f"{profile} excluded Pool return prefix drift",
    )
    for label, start, return_index in (("token0", 128, 137), ("token1", 202, 211)):
        require(lines[start] == "local.get $p0", f"{profile} {label} decimals event source drift")
        require(call_name(handler.lines[start + 1]) == "src/types/Factory/Factory/PoolCreated__Params#constructor", f"{profile} {label} params drift")
        require(call_name(handler.lines[start + 2]) == f"src/types/Factory/Factory/PoolCreated__Params#get:{label}", f"{profile} {label} getter drift")
        require(call_name(handler.lines[start + 3]) == "src/utils/token/fetchTokenDecimals", f"{profile} {label} decimals helper drift")
        require(lines[start + 4 : start + 6] == ["local.tee $l5", "i32.eqz"], f"{profile} {label} null test drift")
        require(lines[start + 6].startswith("if $"), f"{profile} {label} null branch drift")
        require(call_name(handler.lines[start + 8]) == "~lib/@graphprotocol/graph-ts/index/log.debug", f"{profile} {label} log drift")
        require(lines[return_index] == "return" and lines[return_index + 1] == "end", f"{profile} {label} early return drift")
    return {
        "excluded_pool": context["profile"]["excluded_pool"],
        "excluded_pool_return_relative_wat_line": 8,
        "token0_decimals_return_relative_wat_line": 137,
        "token1_decimals_return_relative_wat_line": 211,
        "selected_setters_reached_only_on_normal_continuation": True,
        "imported_helpers_may_trap": True,
        "actual_historic_handler_outcomes_bound": False,
    }


def prove_legacy_static_residuals(context: dict[str, Any]) -> dict[str, Any]:
    profile = context["profile"]["profile_id"]
    expected = EXPECTED[profile]
    metadata = context["profile"]["metadata_evidence"]
    require(context["profile"]["complete_static_handler_contract"] is False, f"{profile} complete-static path unexpectedly promoted")
    require(context["profile"]["safe_literal_array"] is False, f"{profile} legacy static array unexpectedly safe")
    require(metadata["initial_array_slots"] == 6 and metadata["leading_uninitialized_slots"] == 6, f"{profile} static array holes drift")
    total_supply = function_by_suffix(context, "fetchTokenTotalSupply")
    require((total_supply.start_line, len(total_supply.lines)) == ((3344 if profile == "legacy-base-root" else 3431), 12), f"{profile} totalSupply helper binding drift")
    require(
        [normalized(line) for line in total_supply.lines[1:12]]
        == [
            "local.get $p0",
            "call $src/types/Factory/ERC20/ERC20.bind",
            "call $src/types/Factory/ERC20/ERC20#try_totalSupply",
            "local.tee $p0",
            "call $~lib/@graphprotocol/graph-ts/chain/ethereum/ethereum.CallResult<~lib/array/Array<~lib/@graphprotocol/graph-ts/chain/ethereum/ethereum.Value>>#get:reverted",
            "if $I0 (result i32)",
            "i32.const 0",
            "else",
            "local.get $p0",
            "end",
            "call $~lib/@graphprotocol/graph-ts/index/ByteArray.fromI32)",
        ],
        f"{profile} totalSupply pointer/revert flow drift",
    )
    require(function_sha256(total_supply) == TOTAL_SUPPLY_SHA256, f"{profile} totalSupply helper body drift")

    static_start, static_lines, static_digest = expected["static"]
    if profile == "legacy-base-root":
        static_function = function_by_suffix(context, "StaticTokenDefinition.fromAddress")
        require((static_function.start_line, len(static_function.lines), function_sha256(static_function)) == (static_start, static_lines, static_digest), f"{profile} Base static-array helper drift")
        static_profile = {
            "profile": "base-six-leading-holes",
            "initial_array_slots": 6,
            "appended_static_entries": 0,
            "leading_uninitialized_slots": 6,
            "from_address_body_sha256": static_digest,
        }
    else:
        tuple_constructor = function_by_suffix(context, "StaticTokenDefinition#constructor")
        definitions = function_by_suffix(context, "StaticTokenDefinition.getStaticDefinitions")
        from_address = function_by_suffix(context, "StaticTokenDefinition.fromAddress")
        require((tuple_constructor.start_line, len(tuple_constructor.lines), function_sha256(tuple_constructor)) == (3127, 29, "b7cf5b946468c51d45fe5e88d591cd0baa6ed6cb5244e6fb53b7a8bdc3a944de"), f"{profile} static tuple constructor drift")
        require((definitions.start_line, len(definitions.lines), function_sha256(definitions)) == (static_start, static_lines, static_digest), f"{profile} static definitions drift")
        require((from_address.start_line, len(from_address.lines), function_sha256(from_address)) == (3215, 37, "141f7c8c5e816266609cbc7798f93e774192fec406b899f3f45fc887d08a1758"), f"{profile} static lookup drift")
        static_profile = {
            "profile": "mainnet-six-leading-holes-plus-six-entries",
            "initial_array_slots": 6,
            "appended_static_entries": 6,
            "leading_uninitialized_slots": 6,
            "tuple_constructor_body_sha256": function_sha256(tuple_constructor),
            "get_static_definitions_body_sha256": function_sha256(definitions),
            "from_address_body_sha256": function_sha256(from_address),
        }
    return {
        "complete_static_handler_contract": False,
        "all_sixty_stored_fields_proven": False,
        "static_array_profile": static_profile,
        "static_array_safe": False,
        "total_supply_helper": {
            "function": total_supply.name,
            "wat_start_line": total_supply.start_line,
            "body_sha256": function_sha256(total_supply),
            "success_passes_call_result_pointer_to_ByteArray_fromI32": True,
            "revert_passes_zero_to_ByteArray_fromI32": True,
            "erc20_result_data_decoded": False,
        },
    }


def prove_reachable_residual_inventory(
    context: dict[str, Any], upstream_effect: dict[str, Any]
) -> dict[str, Any]:
    profile = context["profile"]["profile_id"]
    functions = context["functions"]
    reachable = sorted(WRITER.reachable_functions(functions, context["handler"], tuple(context["indirect"])))
    bodies = [{"function": name, "body_sha256": function_sha256(functions[name])} for name in reachable]
    writes = [
        {"function": name, "relative_wat_line": index, "instruction": normalized(line)}
        for name in reachable
        for index, line in enumerate(functions[name].lines)
        if RUNTIME.is_direct_memory_write(line, normalized)
    ]
    sets = [
        {"function": name, "relative_wat_line": index, "target": call_name(line)}
        for name in reachable
        for index, line in enumerate(functions[name].lines)
        if call_name(line) == LEGACY_MAP_SET
    ]
    actual = [len(reachable), canonical_sha256(bodies), len(writes), canonical_sha256(writes), len(sets), canonical_sha256(sets)]
    require(actual == EXPECTED[profile]["mutation"], f"{profile} reachable mutation inventory drift")
    expanded = []
    for index, line in enumerate(context["handler"].lines):
        target = call_name(line)
        if target == LEGACY_MAP_SET or (
            target in functions and any(call_name(candidate) == LEGACY_MAP_SET for candidate in functions[target].lines)
        ):
            expanded.append(index)
    require(len(expanded) == 78 and canonical_sha256(expanded) == EXPANDED_MAP_WRITE_INVOCATIONS_SHA256, f"{profile} expanded map-write invocation inventory drift")
    closure = upstream_effect["reachable_effect_closure"]
    require(closure["reachable_function_count"] == actual[0], f"{profile} inherited reachable function count drift")
    require(closure["reachable_function_body_bindings_sha256"] == actual[1], f"{profile} inherited body authority drift")
    require(closure["reachable_store_set_targets"] == ["Bundle", "Factory", "Pool", "Token"], f"{profile} Graph store targets drift")
    require(len(closure["reachable_store_set_sites"]) == 4, f"{profile} Graph store site count drift")
    require(closure["reachable_call_indirect_sites"] == [] and closure["conservative_indirect_targets"] == ["null"], f"{profile} indirect closure drift")
    return {
        "reachable_function_count": actual[0],
        "reachable_function_body_inventory_sha256": actual[1],
        "reachable_direct_memory_write_site_count": actual[2],
        "reachable_direct_memory_write_site_inventory_sha256": actual[3],
        "reachable_typed_map_set_site_count": actual[4],
        "reachable_typed_map_set_site_inventory_sha256": actual[5],
        "selected_typed_map_set_site_count": 2,
        "unclassified_typed_map_set_site_count": actual[4] - 2,
        "direct_memory_write_sites_without_selected_payload_alias_proof": actual[2],
        "expanded_lexical_map_write_invocation_count": len(expanded),
        "expanded_lexical_map_write_invocations_sha256": canonical_sha256(expanded),
        "expanded_invocations_are_potential_paths_not_simultaneous_writes": True,
        "reachable_graph_store_set_site_count": len(closure["reachable_store_set_sites"]),
        "reachable_graph_store_targets": closure["reachable_store_set_targets"],
        "selected_graph_store_target": "Pool",
        "all_other_reachable_typed_map_receiver_key_value_semantics_classified": False,
        "general_heap_alias_semantics_rederived": False,
    }


def prove_legacy_context(
    context: dict[str, Any], upstream_effect: dict[str, Any]
) -> dict[str, Any]:
    require(upstream_effect["mapping_cid"] == context["cid"], "Factory effect parent mapping mismatch")
    authority = prove_artifact_authority(context)
    module_state = prove_native_start_and_g2(context)
    receiver = prove_receiver_origin(context)
    value = prove_value_from_bigint(context)
    typed_map = prove_typed_map_set(context)
    flow = prove_selected_setter_through_save(context)
    save = prove_pool_save(context)
    guards = prove_guard_and_return_boundaries(context)
    static = prove_legacy_static_residuals(context)
    residual = prove_reachable_residual_inventory(context, upstream_effect)
    return {
        "profile_id": context["profile"]["profile_id"],
        "mapping_cid": context["cid"],
        "control_generation": "legacy",
        "artifact_and_handler_authority": authority,
        "upstream_factory_effect_proof_sha256": canonical_sha256(upstream_effect),
        "native_start_and_g2": module_state,
        "pool_entity_receiver_origin": receiver,
        "value_from_bigint": value,
        "typed_map_set": typed_map,
        "selected_setter_through_save": flow,
        "pool_save_capsule": save,
        "guard_and_return_boundaries": guards,
        "reachable_residual_inventory": residual,
        "legacy_static_residual_boundary": static,
        "selected_initialization_setter_and_save_call_operand_flow_machine_proven": True,
        "selected_field_mutation_proven": False,
        "complete_static_handler_contract": False,
        "selected_persistence_proven": False,
        "complete_pool_or_factory_history": False,
    }


def _bind_source_file(root: Path, relative: Path, digest: str) -> None:
    path = root / relative
    require(path.is_file() and raw_sha256(path) == digest, f"source file digest drift: {relative}")


def load_sources(
    root: Path,
    *,
    recompute_wat: bool = True,
    wasm2wat: Path | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    for relative, digest in (
        (FACTORY_EFFECTS_VERIFIER_PATH.relative_to(REPOSITORY), FACTORY_EFFECTS_VERIFIER_SHA256),
        (FACTORY_EFFECTS_CONTRACT_PATH, FACTORY_EFFECTS_CONTRACT_SHA256),
        (MODERN_VERIFIER_PATH.relative_to(REPOSITORY), MODERN_VERIFIER_SHA256),
        (MODERN_CONTRACT_PATH, MODERN_CONTRACT_SHA256),
        (FEE_GROWTH_VERIFIER_PATH.relative_to(REPOSITORY), FEE_GROWTH_VERIFIER_SHA256),
        (FEE_GROWTH_CONTRACT_PATH, FEE_GROWTH_CONTRACT_SHA256),
        (WRITER_COMPATIBILITY_PATH, WRITER_COMPATIBILITY_SHA256),
        (V2_VERIFIER_PATH.relative_to(REPOSITORY), V2_VERIFIER_SHA256),
        (V2_CONTRACT_PATH, V2_CONTRACT_SHA256),
        (MATRIX_VERIFIER_PATH.relative_to(REPOSITORY), MATRIX_VERIFIER_SHA256),
        (MATRIX_CONTRACT_PATH, MATRIX_CONTRACT_SHA256),
        (RUNTIME_PATH, RUNTIME_SHA256),
    ):
        _bind_source_file(root, relative, digest)

    factory_effects_contract = EFFECTS.verify_contract(root, wasm2wat=wasm2wat)
    require(factory_effects_contract["contract_version"] == "uniswap-v3-factory-effects/v1", "Factory effects parent version drift")
    modern_contract = MODERN.verify_contract(root, wasm2wat=wasm2wat)
    require(modern_contract["contract_version"] == MODERN_CONTRACT_VERSION, "modern Factory parent version drift")
    require(modern_contract["scope"]["cumulative_closed_after_this_supplement"] == 14 and modern_contract["scope"]["residual_after_this_supplement"] == 4, "modern Factory 14/18 boundary drift")
    fee_sources = FEE_GROWTH.load_sources(root, recompute_wat=recompute_wat, wasm2wat=wasm2wat)
    fee_growth_contract = FEE_GROWTH.verify_contract(root, sources=fee_sources, recompute_wat=False)
    require(fee_growth_contract["contract_version"] == FEE_GROWTH_CONTRACT_VERSION, "Pool Swap fee-growth parent version drift")
    require(fee_growth_contract["scope"]["cumulative_selected_field_count"] == 36 and fee_growth_contract["scope"]["cumulative_residual_field_count"] == 230, "36/230 field ledger drift")

    contexts: list[dict[str, Any]] = []
    upstream_effects: dict[str, dict[str, Any]] = {}
    executable = WRITER.resolve_wasm2wat(wasm2wat)
    for context in EFFECTS.load_contexts(root, wasm2wat):
        profile = context["profile"]["profile_id"]
        if profile not in EXPECTED:
            continue
        upstream = EFFECTS.prove_factory_effects(context)
        artifact_relative = Path("uniswap-v3/graft-ancestry/v1/artifacts") / context["cid"]
        wat_payload = WRITER.run_wasm2wat(executable, root / artifact_relative)
        wat_text = wat_payload.decode()
        memory, functions, indirect, exports = WRITER.parse_wat(wat_text)
        require(memory == context["memory"], f"{profile} full-WAT memory parse drift")
        require(set(functions) == set(context["functions"]), f"{profile} full-WAT function inventory drift")
        require(tuple(indirect) == tuple(context["indirect"]), f"{profile} full-WAT table inventory drift")
        parsed_handler = WRITER.resolve_handler(functions, exports, HANDLER_EXPORT)
        require(parsed_handler.payload == context["handler"].payload, f"{profile} full-WAT handler parse drift")
        context.update(
            {
                "artifact_path": artifact_relative.as_posix(),
                "wat_text": wat_text,
                "module_text": wat_text,
                "exports": exports,
                "wasm2wat": executable,
            }
        )
        contexts.append(context)
        upstream_effects[context["cid"]] = upstream
    require([context["profile"]["profile_id"] for context in contexts] == list(EXPECTED), "legacy Factory context order/set drift")
    proofs = [prove_legacy_context(context, upstream_effects[context["cid"]]) for context in contexts] if recompute_wat else []
    return {
        "factory_effects_contract": factory_effects_contract,
        "modern_factory_static_contract": modern_contract,
        "pool_swap_fee_growth_contract": fee_growth_contract,
        "v2_contract": fee_sources["v2_contract"],
        "matrix_contract": fee_sources["matrix_contract"],
        "legacy_contexts": contexts,
        "legacy_proofs": proofs,
        "upstream_factory_effects": upstream_effects,
    }


def _field_catalog_binding(v2_contract: dict[str, Any], field: str) -> dict[str, Any]:
    matches = [
        item
        for item in v2_contract["field_catalog"]
        if item["entity"] == "Pool" and item["field"] == field
    ]
    require(len(matches) == 1, f"v2 Pool.{field} catalog binding drift")
    return matches[0]


def _modern_selected_flows(proof: dict[str, Any]) -> dict[str, dict[str, Any]]:
    selected = {
        item["field"]: item
        for item in proof["field_contract"]["simple_global_value_flows"]
        if item["entity"] == "Pool" and item["field"] in SELECTED_FIELDS
    }
    require(set(selected) == set(SELECTED_FIELDS), f"{proof['profile_id']} modern selected field flow set drift")
    for field, flow in selected.items():
        require(
            flow["value"] == "ZERO_BI"
            and flow["value_kind"] == "BigInt"
            and flow["machine_proven"] is True
            and flow["set_binding"]["field_key"] == field
            and flow["set_binding"]["entity_receiver"] == "$l6"
            and flow["set_binding"]["value_kind_tag"] == 7
            and flow["set_binding"]["exact_receiver_key_kind_payload_final_operand_and_set_call_proven"] is True,
            f"{proof['profile_id']} modern Pool.{field} flow drift",
        )
    return selected


def build_segments(
    matrix_contract: dict[str, Any],
    v2_contract: dict[str, Any],
    legacy_proofs: list[dict[str, Any]],
    modern_contract: dict[str, Any],
) -> list[dict[str, Any]]:
    legacy_by_cid = {proof["mapping_cid"]: proof for proof in legacy_proofs}
    modern_by_cid = {proof["mapping_cid"]: proof for proof in modern_contract["modern_factory_static_proofs"]}
    require(len(legacy_by_cid) == 4 and len(modern_by_cid) == 2, "Factory proof mapping inventory drift")
    catalog = {field: _field_catalog_binding(v2_contract, field) for field in SELECTED_FIELDS}
    results: list[dict[str, Any]] = []
    legacy_count = 0
    modern_count = 0
    for segment in matrix_contract["segments"]:
        handlers = [item for item in segment["handlers"] if item["handler_id"] == HANDLER_ID]
        require(len(handlers) == 1, f"{segment['segment_id']} Factory handler binding drift")
        handler = handlers[0]
        cid = handler["mapping_cid"]
        if cid in legacy_by_cid:
            proof = legacy_by_cid[cid]
            flows = {
                item["field"]: item
                for item in proof["selected_setter_through_save"]["selected_fields"]
            }
            generation = "legacy"
            profile_id = proof["profile_id"]
            proof_sha256 = canonical_sha256(proof)
            complete_static = False
            legacy_count += 1
            origin = proof["pool_entity_receiver_origin"]
            save = proof["pool_save_capsule"]
        else:
            require(cid in modern_by_cid, f"{segment['segment_id']} Factory mapping has no selected proof: {cid}")
            proof = modern_by_cid[cid]
            flows = _modern_selected_flows(proof)
            generation = "modern"
            profile_id = proof["profile_id"]
            proof_sha256 = canonical_sha256(proof)
            complete_static = True
            modern_count += 1
            origin = proof["field_contract"]["entity_receiver_origins"]["Pool"]
            save = {
                "parent_complete_static_handler_contract": True,
                "selected_field_flow_is_part_of_parent_59_written_fields": True,
                "selected_persistence_proven": False,
            }
        fields = []
        for field in SELECTED_FIELDS:
            inherited = catalog[field]
            fields.append(
                {
                    "entity": "Pool",
                    "field": field,
                    "schema_type": "BigInt!",
                    "population_classification": "conditional",
                    "initialization_value_source": "pointer returned by ByteArray.fromI32(0), stored in $g2, via Value.fromBigInt" if generation == "legacy" else "ZERO_BI",
                    "selected_factory_initialization_setter_and_save_call_operand_flow_machine_proven": True,
                    "selected_field_mutation_proven": generation == "modern",
                    "selected_persistence_proven": False,
                    "complete_entity_history": False,
                    "selected_flow_sha256": canonical_sha256(flows[field]),
                    "v2_field_catalog_record_sha256": canonical_sha256(inherited),
                    "residual_history_blocker": "host/store/reset semantics, persistence, complete Factory and Pool histories, combined scheduling, boundary/oracle/parity, backfill, and production remain open",
                }
            )
        semantic = {
            "handler_id": HANDLER_ID,
            "mapping_cid": cid,
            "profile_id": profile_id,
            "control_generation": generation,
            "pool_receiver_origin": origin,
            "selected_field_flows": flows,
            "selected_save_boundary": save,
            "fields": fields,
            "selected_factory_initialization_setter_and_save_call_operand_flow_machine_proven": True,
            "selected_field_mutation_proven": generation == "modern",
            "complete_static_handler_contract": complete_static,
            "selected_persistence_proven": False,
            "complete_factory_entity_history": False,
            "complete_pool_entity_history": False,
        }
        provenance = {
            "mapping_cid": cid,
            "profile_id": profile_id,
            "generation": generation,
            "proof_sha256": proof_sha256,
            "source_handler_record_sha256": canonical_sha256(handler),
            "factory_effect_parent_sha256": (
                proof["upstream_factory_effect_proof_sha256"]
                if generation == "legacy"
                else proof["upstream_effect_proof_sha256"]
            ),
        }
        results.append(
            {
                "segment_id": segment["segment_id"],
                "network": segment["network"],
                "deployment": segment["deployment"],
                "start_block_inclusive": segment["start_block_inclusive"],
                "end_block_inclusive": segment["end_block_inclusive"],
                "semantic_surface": semantic,
                "semantic_surface_sha256": canonical_sha256(semantic),
                "provenance_surface": provenance,
                "provenance_surface_sha256": canonical_sha256(provenance),
                "execution_model": "undecided",
                "backfill_allowed": False,
            }
        )
    require(len(results) == 8, "Factory initialization segment count drift")
    require(legacy_count == 6 and modern_count == 2, "legacy/modern Factory segment projection count drift")
    require(sum(len(item["semantic_surface"]["fields"]) for item in results) == 16, "Factory initialization field-record count drift")
    require(
        [
            (item["network"], item["start_block_inclusive"], item["end_block_inclusive"])
            for item in results
            if item["semantic_surface"]["control_generation"] == "legacy"
        ]
        == [
            ("mainnet", 12369621, 13450880),
            ("mainnet", 13450881, 13498328),
            ("mainnet", 13498329, 13591197),
            ("mainnet", 13591198, 13605860),
            ("mainnet", 13605861, 19470000),
            ("base", 1371679, 19852000),
        ],
        "six legacy Factory segment ranges drift",
    )
    return results


def build_segment_diffs(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
    for left, right in itertools.combinations(segments, 2):
        semantic_paths = FEE_GROWTH.INITIALIZE.json_diff_paths(left["semantic_surface"], right["semantic_surface"])
        provenance_paths = FEE_GROWTH.INITIALIZE.json_diff_paths(left["provenance_surface"], right["provenance_surface"])
        results.append(
            {
                "left_segment_id": left["segment_id"],
                "right_segment_id": right["segment_id"],
                "scoped_semantic_equal": not semantic_paths,
                "scoped_semantic_diff_paths": semantic_paths,
                "provenance_equal": not provenance_paths,
                "provenance_diff_paths": provenance_paths,
                "left_semantic_surface_sha256": left["semantic_surface_sha256"],
                "right_semantic_surface_sha256": right["semantic_surface_sha256"],
                "left_provenance_surface_sha256": left["provenance_surface_sha256"],
                "right_provenance_surface_sha256": right["provenance_surface_sha256"],
                "complete_writer_semantics_compared": False,
                "boundary_state_compared": False,
                "graph_oracle_compared": False,
            }
        )
    require(len(results) == 28, "Factory initialization pairwise diff count drift")
    return results


def truth_boundary() -> dict[str, bool]:
    require(len(TRUE_FLAGS) == len(set(TRUE_FLAGS)), "duplicate true truth gate")
    require(len(FALSE_FLAGS) == len(set(FALSE_FLAGS)), "duplicate false truth gate")
    require(set(TRUE_FLAGS).isdisjoint(FALSE_FLAGS), "truth gate overlap")
    return {**{name: True for name in TRUE_FLAGS}, **{name: False for name in FALSE_FLAGS}}


def expected_contract_from_sources(sources: dict[str, Any]) -> dict[str, Any]:
    proofs = sources["legacy_proofs"]
    require(isinstance(proofs, list) and len(proofs) == 4, "four recomputed legacy Factory proofs required")
    segments = build_segments(
        sources["matrix_contract"],
        sources["v2_contract"],
        proofs,
        sources["modern_factory_static_contract"],
    )
    diffs = build_segment_diffs(segments)
    residuals = {
        proof["profile_id"]: {
            "unclassified_typed_map_set_site_count": proof["reachable_residual_inventory"]["unclassified_typed_map_set_site_count"],
            "direct_memory_write_sites_without_selected_payload_alias_proof": proof["reachable_residual_inventory"]["direct_memory_write_sites_without_selected_payload_alias_proof"],
            "reachable_graph_store_targets": proof["reachable_residual_inventory"]["reachable_graph_store_targets"],
        }
        for proof in proofs
    }
    fixtures = [
        {"fixture": "CID, WASM/WAT, handler range/body, or parent digest", "expected_rejection_layer": "retained artifact and parent authority"},
        {"fixture": "Pool getter, bytesToHex, generic constructor, ID, or receiver local", "expected_rejection_layer": "Pool receiver origin"},
        {"fixture": "swapped, duplicated, misspelled, or substituted fee-growth key", "expected_rejection_layer": "decoded selected-key binding"},
        {"fixture": "$g2 changed to another global, wrapper, Value kind, or payload", "expected_rejection_layer": "selected setter and Value capsule"},
        {"fixture": "native start removed/rebound, zero changed, second g2 writer, or reset writes g2", "expected_rejection_layer": "native-start and complete global-writer inventory"},
        {"fixture": "return, branch, structured control, select, receiver reassignment, or overwrite before save", "expected_rejection_layer": "same-receiver setter-through-save closure"},
        {"fixture": "save receiver, target, ID lookup, missing-ID trap, or kind trap", "expected_rejection_layer": "Pool save capsule"},
        {"fixture": "outer TypedMap receiver/key/value, update-store, entry-constructor, or push-call operand", "expected_rejection_layer": "TypedMap dispatcher call-operand boundary"},
        {"fixture": "excluded-pool guard or either decimals return", "expected_rejection_layer": "normal-continuation guard boundary"},
        {"fixture": "reachable function, body, direct write, TypedMap set, store site, or target", "expected_rejection_layer": "complete residual mutation/store inventory"},
        {"fixture": "missing, duplicate, or mis-profiled segment/field/diff record", "expected_rejection_layer": "eight-segment deterministic projection"},
        {"fixture": "safe legacy array or decoded legacy totalSupply claim", "expected_rejection_layer": "legacy static residual boundary"},
        {"fixture": "promoted false gate, changed 36/230 or 14/18, issue completion, or readiness", "expected_rejection_layer": "strict truth and refusal boundary"},
        {"fixture": "duplicate JSON key", "expected_rejection_layer": "strict JSON loader"},
    ]
    source_contracts = {
        "factory_effects": {"path": FACTORY_EFFECTS_CONTRACT_PATH.as_posix(), "raw_sha256": FACTORY_EFFECTS_CONTRACT_SHA256, "contract_version": "uniswap-v3-factory-effects/v1"},
        "factory_effects_verifier": {"path": FACTORY_EFFECTS_VERIFIER_PATH.relative_to(REPOSITORY).as_posix(), "raw_sha256": FACTORY_EFFECTS_VERIFIER_SHA256},
        "modern_factory_static": {"path": MODERN_CONTRACT_PATH.as_posix(), "raw_sha256": MODERN_CONTRACT_SHA256, "contract_version": MODERN_CONTRACT_VERSION},
        "modern_factory_static_verifier": {"path": MODERN_VERIFIER_PATH.relative_to(REPOSITORY).as_posix(), "raw_sha256": MODERN_VERIFIER_SHA256},
        "pool_swap_fee_growth": {"path": FEE_GROWTH_CONTRACT_PATH.as_posix(), "raw_sha256": FEE_GROWTH_CONTRACT_SHA256, "contract_version": FEE_GROWTH_CONTRACT_VERSION},
        "pool_swap_fee_growth_verifier": {"path": FEE_GROWTH_VERIFIER_PATH.relative_to(REPOSITORY).as_posix(), "raw_sha256": FEE_GROWTH_VERIFIER_SHA256},
        "writer_compatibility": {"path": WRITER_COMPATIBILITY_PATH.as_posix(), "raw_sha256": WRITER_COMPATIBILITY_SHA256},
        "segment_field_v2": {"path": V2_CONTRACT_PATH.as_posix(), "raw_sha256": V2_CONTRACT_SHA256, "contract_version": "uniswap-v3-segment-field-semantics/v2"},
        "segment_field_v2_verifier": {"path": V2_VERIFIER_PATH.relative_to(REPOSITORY).as_posix(), "raw_sha256": V2_VERIFIER_SHA256},
        "segment_writer_matrix": {"path": MATRIX_CONTRACT_PATH.as_posix(), "raw_sha256": MATRIX_CONTRACT_SHA256, "contract_version": "uniswap-v3-segment-writer-matrix/v1"},
        "segment_writer_matrix_verifier": {"path": MATRIX_VERIFIER_PATH.relative_to(REPOSITORY).as_posix(), "raw_sha256": MATRIX_VERIFIER_SHA256},
        "shared_wat_runtime": {"path": RUNTIME_PATH.as_posix(), "raw_sha256": RUNTIME_SHA256},
    }
    return {
        "format_version": 1,
        "contract_version": CONTRACT_VERSION,
        "mode": "retained-wat-factory-fee-growth-initialization-call-flow-certificate",
        "scope": {
            "networks": ["mainnet", "base"],
            "handler": HANDLER_ID,
            "unique_legacy_mapping_count": 4,
            "legacy_segment_count": 6,
            "modern_parent_segment_count": 2,
            "segment_count": 8,
            "selected_fields": [f"Pool.{field}" for field in SELECTED_FIELDS],
            "selected_field_count": 2,
            "legacy_segment_field_call_flow_record_count": 12,
            "total_initialization_record_count": 16,
            "pairwise_scoped_diff_count": 28,
            "cumulative_selected_field_count": 36,
            "cumulative_residual_field_count": 230,
            "factory_upstream_path_count": 18,
            "factory_paths_closed_before_and_after": 14,
            "factory_paths_residual_before_and_after": 4,
            "legacy_complete_static_paths_newly_closed": 0,
            "reachable_effect_residuals_by_profile": residuals,
            "claim": "exact retained-WAT conditional Factory.handlePoolCreated event-pool to generic-constructor result used as the Pool setter/save receiver, feeGrowthGlobal0X128/1X128 g2-to-Value-to-setter-call operand flow, and same-receiver Pool.save call path for four unique legacy mappings projected to six legacy segments, composed with the recomputed two-segment modern parent; legacy Entity/TypedMap mutation semantics, persistence, complete legacy static semantics, history, host behavior, and readiness remain false",
        },
        "source_contracts": source_contracts,
        "authority_contract": {
            "semantic_authority": "four exact retained deployed legacy Factory WASM artifacts and checksum-pinned WABT 1.0.35 --generate-names WAT projections",
            "source_text_role": "corroboration only",
            "legacy_symbol_boundary": "the retained schema/Factory#constructor symbol is a generic entity constructor; decoded ID, event-pool operand flow, receiver identity, keys, and exact bodies are authority",
            "normal_continuation_boundary": "the selected flow is conditional on bypassing the excluded-pool return, both decimals returns, and all helper/import traps",
            "g2_boundary": "$g2 has one exact internal writer from ByteArray.fromI32(0), but numeric-zero preservation across host reset/lifecycle behavior is not asserted",
            "save_boundary": "both setter calls and Pool.save receive the same unreassigned entity local without a return, branch, structured control, or select in the selected pre-save region; legacy TypedMap mutation semantics, Graph persistence, and later overwrites remain open",
            "effect_closure_rule": "pin every reachable body, direct-memory write, TypedMap set, Graph store site, and target; only the exact call operands of two of 44 map-set sites per mapping are selected",
            "canonical_base": dict(CANONICAL_BASE),
        },
        "toolchain": {
            "name": "WABT wasm2wat and wat2wasm",
            "version": WRITER.WABT_VERSION,
            "wasm2wat_command": ["wasm2wat", "--generate-names", "<retained-factory-wasm>"],
            "mutation_fixture_command": ["wat2wasm", "--debug-names", "<mutated.wat>"],
        },
        "valid_wat_mutation_fixture_layers": fixtures,
        "legacy_mapping_proofs": proofs,
        "segments": segments,
        "segment_diffs": diffs,
        "residual_blockers": {
            "field_count": 230,
            "factory": [
                "the four legacy complete-static paths and 58 other stored-field contracts remain unproved",
                "legacy static arrays retain six leading holes, and legacy totalSupply passes a CallResult pointer rather than decoding ERC20 return data",
                "host/reset/numeric/store behavior, persistence, later overwrites, historic outcomes, runtime population, and complete Factory/Pool/fee-growth histories remain open",
            ],
            "execution": [
                "combined handler/dynamic-datasource order, package identity, continuity, oracle/parity, checkpoint, backfill, deployment, production, and readiness remain false",
                "issues #37 and #38 gain no completed acceptance checkbox from this bounded initialization call-flow slice",
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
        require(path.is_file(), f"Factory fee-growth initialization contract missing: {CONTRACT_PATH}")
        actual = load_json(path)
        require(path.read_text() == render(actual), "Factory fee-growth initialization contract byte rendering drift")
    require(canonical_bytes(actual) == canonical_bytes(expected), "Factory fee-growth initialization contract differs from generated proof")
    truth = actual["truth_boundary"]
    require(all(type(value) is bool for value in truth.values()), "truth gates must be strict booleans")
    require({key for key, value in truth.items() if value} == set(TRUE_FLAGS), "true truth-gate set drift")
    require({key for key, value in truth.items() if not value} == set(FALSE_FLAGS), "false truth-gate set drift")
    return expected


def write_contract(root: Path, wasm2wat: Path | None = None) -> dict[str, Any]:
    sources = load_sources(root.resolve(), recompute_wat=True, wasm2wat=wasm2wat)
    expected = expected_contract_from_sources(sources)
    path = root.resolve() / CONTRACT_PATH
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
        result = write_contract(args.root, args.wasm2wat) if args.write_contract else verify_contract(args.root, wasm2wat=args.wasm2wat)
    except (
        VerificationError,
        MODERN.VerificationError,
        FEE_GROWTH.VerificationError,
        EFFECTS.VerificationError,
        V2.VerificationError,
        WRITER.VerificationError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(
        "verified Uniswap V3 Factory fee-growth initialization v1: "
        f"{len(result['legacy_mapping_proofs'])} unique legacy mappings, "
        f"{result['scope']['legacy_segment_field_call_flow_record_count']} legacy and "
        f"{result['scope']['total_initialization_record_count']} total initialization records, "
        f"{len(result['segment_diffs'])} diffs"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
