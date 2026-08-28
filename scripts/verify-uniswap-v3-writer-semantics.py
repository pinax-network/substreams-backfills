#!/usr/bin/env python3
"""Build or verify the offline Uniswap V3 writer-compatibility evidence."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import itertools
import json
import re
import shutil
import struct
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
ANCESTRY_VERIFIER = REPOSITORY / "scripts/verify-uniswap-v3-graft-ancestry.py"
ANCESTRY_SPEC = importlib.util.spec_from_file_location(
    "uniswap_v3_graft_ancestry_for_writer_semantics", ANCESTRY_VERIFIER
)
if ANCESTRY_SPEC is None or ANCESTRY_SPEC.loader is None:
    raise RuntimeError(f"cannot import {ANCESTRY_VERIFIER}")
ANCESTRY = importlib.util.module_from_spec(ANCESTRY_SPEC)
ANCESTRY_SPEC.loader.exec_module(ANCESTRY)


CONTRACT_VERSION = "uniswap-v3-writer-compatibility/v3"
CONTRACT_PATH = Path(
    "uniswap-v3/graft-ancestry/v2/writer-compatibility.json"
)
WABT_VERSION = "1.0.35"
WABT_LINUX_ARCHIVE = {
    "name": "wabt-1.0.35-ubuntu-20.04.tar.gz",
    "sha256": "cb3d22440273b1e8ee641e622b7a32222d97b519ad46169b1f8fcc6ce9af0b9b",
    "url": "https://github.com/WebAssembly/wabt/releases/download/1.0.35/wabt-1.0.35-ubuntu-20.04.tar.gz",
}
GRAPH_NODE_VERSION = "v0.44.0"
GRAPH_NODE_COMMIT = "77823b5a7adc4eac4abf03202c8dd7cb00dea31d"
GRAPH_NODE_TREE = "1f372b47e4de659ddbf503cdbc31ebe4d54df239"
GRAPH_NODE_FILES = (
    (
        "chain/ethereum/src/runtime/runtime_adapter.rs",
        "b76b73c36b8f2fc57372b5d1847ac3877bee3bff64dffe8cf54ef984abe11bf6",
        ["190-225", "298-339"],
        "ethereum.call receives the handler block pointer and binds it to ContractCall",
    ),
    (
        "chain/ethereum/src/ethereum_adapter.rs",
        "e018e25a8ad480c0d436d4a046ce404b4e10dd7488231fd28ed58e1e9b1c49f0",
        ["596-602", "664-704"],
        "eth_call uses the block hash with EIP-1898 or the block number otherwise",
    ),
    (
        "runtime/wasm/src/module/instance.rs",
        "5d259076417e59ef217d888b5bb8e711faa31e7431165ac8f5c2bbeac9accc86",
        ["164-244"],
        "the WASM runtime exits a deterministic-error handler through the discard path",
    ),
    (
        "core/src/subgraph/trigger_processor.rs",
        "5cdce1e42627e45d8520d5e8d938a1eb13f142c245d72d5bfb098d94e7cb2905",
        ["36-78"],
        "a deterministic handler error is written into proof-of-indexing evidence",
    ),
    (
        "graph/src/components/subgraph/instance.rs",
        "e55bda1854ea60b10729b56b2e1b524bbc76aaa02a4d3256424b1631968de504",
        ["155-175"],
        "the discard path clears handler-created data sources and entity-cache changes",
    ),
    (
        "chain/ethereum/src/trigger.rs",
        "6b31d65fa9c0289d76a5bb7d812965e51e26054bb4fad417aa641843c531700f",
        ["364-403"],
        "EthereumTrigger ordering compares log triggers by global log index",
    ),
    (
        "graph/src/blockchain/block_stream.rs",
        "8e4004884534c18054cb7ccd30b9eb675cbc956a3f651041e546ccca31fb0933",
        ["248-255", "293-296"],
        "block trigger data is sorted before execution and re-sorted after extension",
    ),
    (
        "core/src/subgraph/inputs.rs",
        "22a2ee4a8ef0b7ef4cca52115b505c41ff5ee917621645fa48e0971e712ff278",
        ["79-85"],
        "the nonFatalErrors feature selects nonfatal instead of fatal deterministic-error policy",
    ),
    (
        "core/src/subgraph/runner/mod.rs",
        "bb5623ed45b51ad99c783069ea4344c08a69e826016951a8b6282f3685e4b026",
        ["721-787", "726-736", "755-768", "773-787"],
        "fatal errors retain only proof-of-indexing changes then stop, while "
        "nonfatal mode preserves successful entity modifications",
    ),
)

ENTITIES = set(ANCESTRY.ENTITIES)
REQUIRED_ABSENT = ("Collect", "Flash", "TickHourData")
STORE_SET_CALL = "~lib/@graphprotocol/graph-ts/index/store.set"
ETHEREUM_CALL = "~lib/@graphprotocol/graph-ts/chain/ethereum/ethereum.call"
EXCLUDED_POOL = "0x8fe8d9bb8eeba3ed688069c3d6b556c9ca258248"
SWAP_EXCLUDED_POOL = "0x9663f2ca0454accad3e094448ea6f77443880454"
HISTORICAL_GUARD_BLOCK = 14_317_993
TRIGGER_ORDER_SOURCE_MODEL = (
    "Graph Node v0.44.0 orders Ethereum log triggers by ascending global log "
    "index; contract calls still read block-level post-state"
)
NONFATAL_HANDLER_ERROR_POLICY = (
    "discard the failing handler's data-source and entity-cache changes, "
    "continue other successful handlers, and write a deterministic proof-of-indexing error"
)
FATAL_HANDLER_ERROR_POLICY = (
    "nonFatalErrors is absent; a deterministic handler error fails the deployment at that block"
)

FACTORY_HANDLER = "handlePoolCreated"
POOL_HANDLERS = (
    "handleInitialize",
    "handleMint",
    "handleBurn",
    "handleSwap",
    "handleFlash",
)

def factory_profile(
    profile_id: str,
    generation: str,
    static_profile: str,
    slots: int,
    entries: int,
    safe: bool,
) -> dict[str, object]:
    return {
        "profile_id": profile_id,
        "metadata_generation": generation,
        "static_metadata_profile": static_profile,
        "initial_array_slots": slots,
        "appended_static_entries": entries,
        "safe_literal_array": safe,
    }


def pool_profile(
    profile_id: str,
    generation: str,
    pricing: str,
    threshold: int,
    gate: int | None,
    stable: bool,
    initialize_save: bool,
    tick_day_mode: str,
    fee_spacing: str,
    hour_resaves: bool = False,
) -> dict[str, object]:
    return {
        "profile_id": profile_id,
        "control_generation": generation,
        "pricing_profile": pricing,
        "tracked_amount_threshold": threshold,
        "whitelist_cardinality_gate": gate,
        "stable_shortcut": stable,
        "initialize_persists_pool": initialize_save,
        "tick_day_tick_relation_mode": tick_day_mode,
        "fee_spacing_mode": fee_spacing,
        "explicit_hour_resaves": hour_resaves,
    }


FACTORY_PROFILE_BY_MAPPING = {
    "QmUN4pxwjMTfNem7rf1sKNFNHDsfzpbcTP93RxPAczgkvj": factory_profile(
        "legacy-base-root", "legacy", "base-six-leading-holes", 6, 0, False
    ),
    "QmXFDgK3qLnmsLFcPWobXbdnqV9gESL9BvYY29si4vpTjr": factory_profile(
        "modern-base", "modern", "base-safe-empty", 0, 0, True
    ),
    "QmUu9rnGvUiBbF9pLnuJQab1wHXqjooo3bY5cZDVTyQQgr": factory_profile(
        "legacy-mainnet-root", "legacy", "mainnet-six-leading-holes-plus-six-entries", 6, 6, False
    ),
    "QmT8CKmLDFFCgwYnubFhKXUsuer5rfJKPT4PrCsv9tTwjV": factory_profile(
        "legacy-mainnet-qmrv", "legacy", "mainnet-six-leading-holes-plus-six-entries", 6, 6, False
    ),
    "QmcsaU3DrUqZHZLzrrWT9aW4EVQuS54wxNHynq8g1PvESL": factory_profile(
        "legacy-mainnet-stable", "legacy", "mainnet-six-leading-holes-plus-six-entries", 6, 6, False
    ),
    "QmbJGLb6sXkN11djxLvKGb2zDk3s7ddgEsULwzC7TVyrEb": factory_profile(
        "modern-mainnet", "modern", "mainnet-safe-six", 6, 6, True
    ),
}

POOL_PROFILE_BY_MAPPING = {
    "QmZPiDeH1j95mozzb5AjKCHn6zgpnhMu77kNAitPbi4Vt3": pool_profile(
        "legacy-base-root", "legacy", "base-reference-pool-threshold-1", 1,
        None, False, True, "create_only", "fee_tier_100_spacing_1", True,
    ),
    "QmPZCHE1URf4oviX7Tbrkw3aMENo1qAeEGa1AS2gMumG7P": pool_profile(
        "modern-base", "modern", "base-reference-pool-threshold-1", 1,
        None, False, True, "create_only", "fee_tier_100_spacing_1", True,
    ),
    "QmWuomVAQCdEXdCRavcsmRz4BNqPx2nppqe8S6AXid66xw": pool_profile(
        "legacy-mainnet-root", "legacy", "mainnet-threshold-52", 52,
        None, False, False, "every_update", "no_fee_tier_100",
    ),
    "QmYQRHstsSS7mntgKNSot74qN2dpuyFEtd1DddPmnqWC65": pool_profile(
        "legacy-mainnet-qmrv", "legacy", "mainnet-threshold-30-gate-22", 30,
        22, False, False, "create_only", "no_fee_tier_100",
    ),
    "QmeNbEMUnaaPpmpLaUVBJfFWRCN5SxG8xPG5eDNoXEGdbW": pool_profile(
        "legacy-mainnet-stable", "legacy", "mainnet-stable-shortcut-threshold-52", 52,
        None, True, False, "create_only", "no_fee_tier_100",
    ),
    "Qmaydei2ScE7JptBTPgSfkf6PFxEZpLn39gEXYqrBZhsv8": pool_profile(
        "legacy-mainnet-stable-fee-tier-1", "legacy", "mainnet-stable-shortcut-threshold-52", 52,
        None, True, False, "create_only", "fee_tier_1_spacing_1",
    ),
    "QmadCQv7VPgNXhQTNkcDyzmiWZpWexynUH4XuuaMrsAbJY": pool_profile(
        "legacy-mainnet-stable-fee-tier-100", "legacy", "mainnet-stable-shortcut-threshold-52", 52,
        None, True, False, "create_only", "fee_tier_100_spacing_1",
    ),
    "QmSaGgPnyhStviGQSGTokQYRgVqLFNvnGWfnv8tSfuvpWD": pool_profile(
        "modern-mainnet", "modern", "mainnet-threshold-60-safe-six", 60,
        None, False, True, "create_only", "fee_tier_100_spacing_1", True,
    ),
}

SOURCE_REPOSITORY = "https://github.com/Uniswap/v3-subgraph"
ENTRY_BLOB_ANCHOR_BY_MAPPING = {
    "QmUN4pxwjMTfNem7rf1sKNFNHDsfzpbcTP93RxPAczgkvj": (
        "a5e8000ffc0b173d699242f30a0f360dadebe55e",
        "src/mappings/factory.ts",
        "d8a3ed16684bbdf59510f66a232a3b548bff4065",
    ),
    "QmZPiDeH1j95mozzb5AjKCHn6zgpnhMu77kNAitPbi4Vt3": (
        "a5e8000ffc0b173d699242f30a0f360dadebe55e",
        "src/mappings/core.ts",
        "b1a0574d665caa556a3e1af64ec8f76ed8a1f19c",
    ),
    "QmbJGLb6sXkN11djxLvKGb2zDk3s7ddgEsULwzC7TVyrEb": (
        "69b50154b344e821d2ac71c24f260a5f54094808",
        "src/mappings/factory.ts",
        "d8a3ed16684bbdf59510f66a232a3b548bff4065",
    ),
    "QmSaGgPnyhStviGQSGTokQYRgVqLFNvnGWfnv8tSfuvpWD": (
        "68cad02419d0e892c10b78177611651d1cf15a5d",
        "src/mappings/core.ts",
        "2b0b4bf766bc788314399dc5fce0963b249406a2",
    ),
}

SEMANTIC_SOURCE_ANCHORS = (
    "199e317deb2e92032666223c29564998e779f11b",
    "a651743931092c0a0b27ad135225675476bf1d7d",
    "78cf4221e0c5f29ffec27f1449bfa0e219f7d659",
    "3a6dc5a5604f4df4abb8199ab0d09deb63a662f7",
)

FACTORY_FIELD_WRITER_CONTRACT = {
    "coverage": "all stored Factory, Bundle, Token, and Pool fields",
    "entity_id_sources": {
        "Factory.id": "factory address",
        "Bundle.id": "1",
        "Token.id": "event token address",
        "Pool.id": "event pool address",
    },
    "initialize_zero": [
        "Factory.txCount", "Factory.totalVolumeUSD", "Factory.totalVolumeETH",
        "Factory.totalFeesUSD", "Factory.totalFeesETH", "Factory.untrackedVolumeUSD",
        "Factory.totalValueLockedUSD", "Factory.totalValueLockedETH",
        "Factory.totalValueLockedUSDUntracked", "Factory.totalValueLockedETHUntracked",
        "Bundle.ethPriceUSD", "Token.volume", "Token.volumeUSD",
        "Token.untrackedVolumeUSD", "Token.feesUSD", "Token.txCount",
        "Token.poolCount", "Token.totalValueLocked", "Token.totalValueLockedUSD",
        "Token.totalValueLockedUSDUntracked", "Token.derivedETH", "Pool.liquidity",
        "Pool.sqrtPrice", "Pool.feeGrowthGlobal0X128", "Pool.feeGrowthGlobal1X128",
        "Pool.token0Price", "Pool.token1Price", "Pool.observationIndex",
        "Pool.volumeToken0", "Pool.volumeToken1", "Pool.volumeUSD",
        "Pool.untrackedVolumeUSD", "Pool.feesUSD", "Pool.txCount",
        "Pool.collectedFeesToken0", "Pool.collectedFeesToken1",
        "Pool.collectedFeesUSD", "Pool.totalValueLockedToken0",
        "Pool.totalValueLockedToken1", "Pool.totalValueLockedETH",
        "Pool.totalValueLockedUSD", "Pool.totalValueLockedUSDUntracked",
        "Pool.liquidityProviderCount",
    ],
    "initialize_zero_address": ["Factory.owner"],
    "increment": ["Factory.poolCount"],
    "token_metadata": ["Token.symbol", "Token.name", "Token.decimals", "Token.totalSupply"],
    "event_values": [
        "Pool.createdAtTimestamp", "Pool.createdAtBlockNumber", "Pool.token0",
        "Pool.token1", "Pool.feeTier",
    ],
    "conditional_symmetric_append": ["Token.whitelistPools"],
    "required_absent": ["Pool.tick"],
}

POOL_CRITICAL_WRITER_OBSERVATIONS = {
    "handleInitialize": {
        "observed_fields": ["Pool.sqrtPrice", "Pool.tick"],
        "event_row": None,
        "reviewed_observation": "writes event sqrtPriceX96 and tick; Pool persistence is profile-specific",
    },
    "handleMint": {
        "observed_fields": [
            "Pool.liquidity",
            "Pool.totalValueLockedToken0",
            "Pool.totalValueLockedToken1",
            "Tick.liquidityGross",
            "Tick.liquidityNet",
        ],
        "event_row": "Mint",
        "reviewed_observation": "cumulative TVL/liquidity/tick/window writes and direct non-try pool tick calls",
    },
    "handleBurn": {
        "observed_fields": [
            "Pool.liquidity",
            "Pool.totalValueLockedToken0",
            "Pool.totalValueLockedToken1",
            "Tick.liquidityGross",
            "Tick.liquidityNet",
        ],
        "event_row": "Burn",
        "reviewed_observation": "cumulative TVL/liquidity/tick/window writes and direct non-try pool tick calls",
    },
    "handleSwap": {
        "observed_fields": [
            "Pool.sqrtPrice",
            "Pool.tick",
            "Pool.liquidity",
            "Pool.feeGrowthGlobal0X128",
            "Pool.feeGrowthGlobal1X128",
            "TickDayData.tick",
            "TokenDayData.untrackedVolumeUSD",
            "TokenHourData.untrackedVolumeUSD",
        ],
        "event_row": "Swap",
        "reviewed_observation": "fee refresh, profile-specific TickDay relation, and retained Token day/hour untracked-volume quirk",
    },
    "handleFlash": {
        "observed_fields": [
            "Pool.feeGrowthGlobal0X128",
            "Pool.feeGrowthGlobal1X128",
        ],
        "event_row": None,
        "reviewed_observation": "two ordered non-try calls followed by one Pool save",
    },
}

NPM_HANDLERS = (
    "handleIncreaseLiquidity",
    "handleDecreaseLiquidity",
    "handleCollect",
    "handleTransfer",
)

PROFILE_BY_MAPPING = {
    "QmYWR79pUmVbQ42JkvB24D6AKCGtdo4UG78ZSewmFxwQdR": "mainnet-root-correct-collect",
    "Qmebr2EyxV7v1wLt9DSFKA7g8EhcVr9k1x7pwZr5eWEHT6": "mainnet-second-fee0-overwrite",
    "QmYwxHm2GNNcukX9oe4owucCLNoAk2rYrbMFuMFtWfKLn2": "mainnet-no-collect-amounts",
    "QmUk7jc3c8joQBrrcTz2ZEVDKcg1P12G2nFtuNqiikDQLJ": "base-root-amount0-to-both",
    "QmWxG1yzdQmp4pRDiqKvTZyRrrrZPRUTza6xznjR1wu1sD": "current-amount0-to-both",
    "QmPjhEuGqknJJ2LfJCi6XTLFLtiymYfZAtjTLfkmJJGMEj": "current-amount0-to-both",
}

PROFILE_DEFINITIONS = {
    "mainnet-root-correct-collect": {
        "block_guard_handlers": [],
        "collect_write_model": "absolute assignments after reading the current Position: fee0 from old fee0 plus amount0 and fee1 from old fee1 plus amount1",
        "collect_final_collected_fees_token0": "old_token0 + decimal(event.amount0, token0.decimals)",
        "collect_final_collected_fees_token1": "old_token1 + decimal(event.amount1, token1.decimals)",
        "collect_token_missing_policy": "old-codegen dereference error",
        "increase_decrease_token_missing_policy": "old-codegen dereference error",
    },
    "mainnet-second-fee0-overwrite": {
        "block_guard_handlers": [],
        "collect_write_model": "two absolute fee0 assignments; the second overwrites the first with fee1-at-this-event-ordinal plus amount1; this is not reproducible as fee0 StoreAdd",
        "collect_final_collected_fees_token0": "old_token1 + decimal(event.amount1, token1.decimals)",
        "collect_final_collected_fees_token1": "old_token1 unchanged",
        "collect_token_missing_policy": "old-codegen dereference error",
        "increase_decrease_token_missing_policy": "old-codegen dereference error",
    },
    "mainnet-no-collect-amounts": {
        "block_guard_handlers": [],
        "collect_write_model": "no collected-fee field assignment",
        "collect_final_collected_fees_token0": "unchanged",
        "collect_final_collected_fees_token1": "unchanged",
        "collect_token_missing_policy": "no token load",
        "increase_decrease_token_missing_policy": "old-codegen dereference error",
    },
    "base-root-amount0-to-both": {
        "block_guard_handlers": [
            "handleDecreaseLiquidity",
            "handleIncreaseLiquidity",
        ],
        "collect_write_model": "absolute fee0 and fee1 assignments after reading the current Position; amount0 is added to each field's own prior value",
        "collect_final_collected_fees_token0": "old_token0 + decimal(event.amount0, token0.decimals)",
        "collect_final_collected_fees_token1": "old_token1 + decimal(event.amount0, token0.decimals)",
        "collect_token_missing_policy": "old-codegen dereference error",
        "increase_decrease_token_missing_policy": "old-codegen dereference error",
    },
    "current-amount0-to-both": {
        "block_guard_handlers": [
            "handleDecreaseLiquidity",
            "handleIncreaseLiquidity",
        ],
        "collect_write_model": "when token0 exists, absolute fee0 and fee1 assignments after reading the current Position; amount0 is added to each field's own prior value",
        "collect_final_collected_fees_token0": "old_token0 + decimal(event.amount0, token0.decimals) when token0 exists; otherwise unchanged",
        "collect_final_collected_fees_token1": "old_token1 + decimal(event.amount0, token0.decimals) when token0 exists; otherwise unchanged",
        "collect_token_missing_policy": "skip amount accumulation but refresh, save Position, and save PositionSnapshot",
        "increase_decrease_token_missing_policy": "no Position or PositionSnapshot write unless both tokens exist",
    },
}


class VerificationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def render(value: object) -> str:
    return ANCESTRY.render(value)


@dataclass(frozen=True)
class WatFunction:
    name: str
    start_line: int
    lines: tuple[str, ...]
    function_index: int | None = None

    @property
    def payload(self) -> bytes:
        return ("\n".join(self.lines) + "\n").encode("utf-8")


def resolve_wasm2wat(candidate: Path | None) -> Path:
    if candidate is None:
        found = shutil.which("wasm2wat")
        require(found is not None, "wasm2wat is required")
        candidate = Path(found)
    require(candidate.exists() and candidate.is_file(), f"wasm2wat not found: {candidate}")
    try:
        result = subprocess.run(
            [str(candidate), "--version"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise VerificationError(f"cannot execute wasm2wat: {error}") from error
    require(result.returncode == 0, f"wasm2wat --version failed: {result.stderr.strip()}")
    require(result.stdout.strip() == WABT_VERSION, "WABT version drift")
    return candidate.resolve()


def run_wasm2wat(executable: Path, artifact: Path) -> bytes:
    try:
        result = subprocess.run(
            [str(executable), "--generate-names", str(artifact)],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise VerificationError(f"wasm2wat failed for {artifact.name}: {error}") from error
    require(result.returncode == 0, f"wasm2wat failed for {artifact.name}: {result.stderr.decode('utf-8', 'replace').strip()}")
    require(not result.stderr, f"wasm2wat emitted stderr for {artifact.name}")
    try:
        result.stdout.decode("utf-8")
    except UnicodeDecodeError as error:
        raise VerificationError(f"wasm2wat emitted invalid UTF-8 for {artifact.name}") from error
    return result.stdout


def decode_wat_string(value: str) -> bytes:
    output = bytearray()
    index = 0
    escapes = {"n": 10, "r": 13, "t": 9, "\\": 92, '"': 34, "'": 39}
    while index < len(value):
        if value[index] != "\\":
            output.extend(value[index].encode("utf-8"))
            index += 1
            continue
        require(index + 1 < len(value), "truncated WAT string escape")
        if (
            index + 2 < len(value)
            and value[index + 1] in "0123456789abcdefABCDEF"
            and value[index + 2] in "0123456789abcdefABCDEF"
        ):
            output.append(int(value[index + 1 : index + 3], 16))
            index += 3
            continue
        escaped = value[index + 1]
        require(escaped in escapes, f"unsupported WAT string escape: {escaped}")
        output.append(escapes[escaped])
        index += 2
    return bytes(output)


DATA_RE = re.compile(r'^  \(data \$\S+ \(i32\.const (\d+)\) "(.*)"\)\)?$')
MEMORY_RE = re.compile(r"^  \(memory \$\S+ (\d+)(?: \d+)?\)$")
FUNCTION_RE = re.compile(r"^  \(func \$([^\s]+)")
FUNCTION_IMPORT_RE = re.compile(r'^  \(import "[^"]+" "[^"]+" \(func \$[^\s\)]+')
EXPORT_RE = re.compile(r'^  \(export "([^"]+)" \(func \$([^\s\)]+)\)\)$')
I32_CONST_RE = re.compile(r"^\s*i32\.const (-?\d+)$")
CALL_RE = re.compile(r"\bcall \$([^\s\)]+)")
LOCAL_GET_RE = re.compile(r"^\s*local\.get (\$[^\s]+)$")
LOCAL_SET_RE = re.compile(r"^\s*local\.(?:set|tee) (\$[^\s]+)$")
LOCAL_TEE_RE = re.compile(r"^\s*local\.tee (\$[^\s]+)$")
ELEMENT_RE = re.compile(
    r"^\s*\(elem(?:\s+\$[^\s\)]+)?\s+\(i32\.const\s+-?\d+\)\s+func"
    r"((?:\s+\$[^\s\)]+)+)\)$"
)
LOCAL_TABLE_RE = re.compile(
    r"^\s*\(table\s+\$[^\s\)]+\s+\d+(?:\s+\d+)?\s+funcref\)$"
)
TABLE_MUTATION_INSTRUCTIONS = (
    "table.set",
    "table.init",
    "table.fill",
    "table.grow",
    "table.copy",
    "elem.drop",
)


def parse_wat(
    wat: str,
) -> tuple[
    bytearray,
    dict[str, WatFunction],
    tuple[str, ...],
    dict[str, str],
]:
    lines = wat.splitlines()
    data_segments: list[tuple[int, bytes]] = []
    for line in lines:
        match = DATA_RE.fullmatch(line)
        if match:
            data_segments.append((int(match.group(1)), decode_wat_string(match.group(2))))
    initial_pages = [
        int(match.group(1))
        for line in lines
        if (match := MEMORY_RE.fullmatch(line)) is not None
    ]
    require(len(initial_pages) == 1, "WAT must declare exactly one local memory")
    memory_size = max(
        initial_pages[0] * 65_536,
        max((offset + len(payload) for offset, payload in data_segments), default=0),
    )
    memory = bytearray(memory_size)
    for offset, payload in data_segments:
        memory[offset : offset + len(payload)] = payload

    functions: dict[str, WatFunction] = {}
    function_import_count = sum(
        FUNCTION_IMPORT_RE.match(line) is not None for line in lines
    )
    defined_function_count = 0
    index = 0
    while index < len(lines):
        match = FUNCTION_RE.match(lines[index])
        if match is None:
            index += 1
            continue
        start = index
        balance = 0
        body: list[str] = []
        while index < len(lines):
            line = lines[index]
            body.append(line)
            balance += line.count("(") - line.count(")")
            index += 1
            if balance == 0:
                break
        require(balance == 0, f"unterminated WAT function {match.group(1)}")
        name = match.group(1)
        require(name not in functions, f"duplicate WAT function name {name}")
        functions[name] = WatFunction(
            name,
            start + 1,
            tuple(body),
            function_import_count + defined_function_count,
        )
        defined_function_count += 1
    require(functions, "WAT contains no named functions")

    exports: dict[str, str] = {}
    for line in lines:
        match = EXPORT_RE.fullmatch(line)
        if match is None:
            continue
        export_name, function_name = match.groups()
        require(export_name not in exports, f"duplicate WAT export {export_name}")
        require(
            function_name in functions,
            f"WAT export {export_name} targets missing function {function_name}",
        )
        exports[export_name] = function_name

    indirect_targets: list[str] = []
    for line in lines:
        if not line.lstrip().startswith("(elem"):
            require("ref.func" not in line, "unsupported ref.func table initializer")
            continue
        match = ELEMENT_RE.fullmatch(line)
        require(match is not None, f"unsupported WAT element segment: {line.strip()}")
        indirect_targets.extend(
            token.removeprefix("$") for token in match.group(1).split()
        )
    require(
        len(indirect_targets) == len(set(indirect_targets)),
        "duplicate indirect-call table target",
    )
    missing_targets = sorted(set(indirect_targets).difference(functions))
    require(
        not missing_targets,
        f"indirect-call table targets do not resolve to local functions: {missing_targets}",
    )
    return memory, functions, tuple(sorted(indirect_targets)), exports


def decode_assemblyscript_string(memory: bytearray, pointer: int) -> str | None:
    if pointer < 0 or pointer >= len(memory):
        return None
    candidates: list[tuple[int, int]] = []
    # graph-ts/AssemblyScript 0.18-era strings point at a character-count header.
    if pointer + 4 <= len(memory):
        length = struct.unpack_from("<I", memory, pointer)[0]
        if 0 < length <= 4096:
            candidates.append((pointer + 4, length * 2))
    # Newer AssemblyScript strings point at UTF-16 bytes, with byte length at -4.
    if pointer >= 4:
        length = struct.unpack_from("<I", memory, pointer - 4)[0]
        if 0 < length <= 8192:
            candidates.extend(((pointer, length), (pointer, length * 2)))
    for start, size in candidates:
        if size % 2 or start + size > len(memory):
            continue
        try:
            value = bytes(memory[start : start + size]).decode("utf-16le")
        except UnicodeDecodeError:
            continue
        if value and all(character.isprintable() or character in "\n\r\t" for character in value):
            return value
    return None


def function_calls(function: WatFunction) -> list[str]:
    calls: list[str] = []
    for line in function.lines:
        match = CALL_RE.search(line)
        if match:
            calls.append(match.group(1))
    return calls


def function_static_strings(function: WatFunction, memory: bytearray) -> list[str]:
    values: list[str] = []
    for line in function.lines:
        match = I32_CONST_RE.fullmatch(line)
        if match:
            value = decode_assemblyscript_string(memory, int(match.group(1)))
            if value is not None:
                values.append(value)
    return values


def normalized_function_payload(function: WatFunction, memory: bytearray) -> bytes:
    lines: list[str] = []
    for raw_line in function.lines:
        line = raw_line.replace("generated/schema/", "src/types/schema/")
        match = re.fullmatch(r"(\s*i32\.const )(-?\d+)(.*)", line)
        if match:
            value = decode_assemblyscript_string(memory, int(match.group(2)))
            if value is not None:
                digest = sha256_bytes(value.encode("utf-8"))
                line = f"{match.group(1)}STATIC_STRING_{digest}{match.group(3)}"
        lines.append(line)
    return ("\n".join(lines) + "\n").encode("utf-8")


def instruction_shape_payload(function: WatFunction, memory: bytearray) -> bytes:
    lines: list[str] = []
    for line in normalized_function_payload(function, memory).decode("utf-8").splitlines():
        match = re.fullmatch(r"(\s*i(?:32|64)\.const )(-?\d+)(.*)", line)
        if match:
            line = f"{match.group(1)}NUMERIC_CONSTANT{match.group(3)}"
        lines.append(line)
    return ("\n".join(lines) + "\n").encode("utf-8")


def normalized_call_sequence(function: WatFunction) -> list[str]:
    return [call.replace("generated/schema/", "src/types/schema/") for call in function_calls(function)]


def resolve_handler(
    functions: dict[str, WatFunction],
    export_targets: dict[str, str],
    handler: str,
) -> WatFunction:
    require(handler in export_targets, f"handler export {handler} is missing")
    target = export_targets[handler]
    require(target in functions, f"handler export {handler} target is missing: {target}")
    return functions[target]


def resolve_suffix_function(
    functions: dict[str, WatFunction], suffix: str, field: str
) -> WatFunction:
    matches = [function for name, function in functions.items() if name.endswith(suffix)]
    require(len(matches) == 1, f"{field} resolved to {len(matches)} functions")
    return matches[0]


def function_call_sites(function: WatFunction) -> list[tuple[int, str]]:
    result: list[tuple[int, str]] = []
    for line_index, line in enumerate(function.lines):
        match = CALL_RE.search(line)
        if match is not None:
            result.append((line_index, match.group(1)))
    return result


def decoded_constant_sites(
    function: WatFunction, memory: bytearray, value: str
) -> list[int]:
    result: list[int] = []
    for line_index, line in enumerate(function.lines):
        match = I32_CONST_RE.fullmatch(line)
        if match is not None and decode_assemblyscript_string(
            memory, int(match.group(1))
        ) == value:
            result.append(line_index)
    return result


def matching_end(lines: tuple[str, ...], start: int, field: str) -> int:
    require(lines[start].strip().startswith("if "), f"{field} does not begin at an if")
    depth = 0
    for index in range(start, len(lines)):
        instruction = lines[index].strip()
        if re.match(r"^(?:block|loop|if)\b", instruction):
            depth += 1
        if instruction == "end" or instruction.startswith("end "):
            depth -= 1
            if depth == 0:
                return index
    raise VerificationError(f"{field} has no matching end")


def canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return sha256_bytes(payload)


def json_diff_paths(left: object, right: object, path: str = "$") -> list[str]:
    if type(left) is not type(right):
        return [path]
    if isinstance(left, dict):
        result: list[str] = []
        left_keys = set(left)
        right_keys = set(right)
        for key in sorted(left_keys | right_keys):
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


def extract_store_set_callsites(
    functions: dict[str, WatFunction], memory: bytearray
) -> list[dict[str, object]]:
    callsites: list[dict[str, object]] = []
    for function in functions.values():
        previous_site_line = 0
        ordinal = 0
        for line_index, line in enumerate(function.lines):
            if f"call ${STORE_SET_CALL}" not in line:
                continue
            ordinal += 1
            immediate = [item.strip() for item in function.lines[max(0, line_index - 4) : line_index]]
            literal_match = I32_CONST_RE.fullmatch(immediate[0]) if len(immediate) == 4 else None
            generated_save_shape = (
                literal_match is not None
                and immediate[1].startswith("local.get $")
                and immediate[2].startswith("call $")
                and immediate[2].endswith("Value#toString")
                and immediate[3].startswith("local.get $")
            )
            target_pointer = int(literal_match.group(1)) if generated_save_shape else None
            target = (
                decode_assemblyscript_string(memory, target_pointer)
                if target_pointer is not None
                else None
            )
            if target not in ENTITIES:
                target = None
            candidates: list[tuple[int, str]] = []
            for preceding in function.lines[previous_site_line:line_index]:
                match = I32_CONST_RE.fullmatch(preceding)
                if match is None:
                    continue
                pointer = int(match.group(1))
                value = decode_assemblyscript_string(memory, pointer)
                if value in ENTITIES:
                    candidates.append((pointer, value))
            callsites.append(
                {
                    "site_id": f"{function.name}#{ordinal}",
                    "function": function.name,
                    "function_body_sha256": sha256_bytes(function.payload),
                    "ordinal_in_function": ordinal,
                    "wat_line": function.start_line + line_index,
                    "target": target,
                    "target_literal_pointer": target_pointer,
                    "target_argument_shape": (
                        "i32.const entity; local.get id; call Value#toString; local.get entity"
                        if target is not None
                        else "unproved"
                    ),
                    "candidate_entity_literals": [
                        value for _, value in dict.fromkeys(candidates)
                    ],
                }
            )
            previous_site_line = line_index + 1
    return callsites


def require_fixed_callsites(callsites: list[dict[str, object]], field: str) -> None:
    dynamic = [item["site_id"] for item in callsites if item["target"] is None]
    require(not dynamic, f"{field} has dynamic store.set targets: {dynamic}")


def verify_closed_indirect_table(
    wat: str,
    call_indirect_count: int,
    indirect_targets: tuple[str, ...],
    field: str,
) -> dict[str, int]:
    wat_lines = wat.splitlines()
    imported_table_count = sum(
        line.lstrip().startswith("(import ") and "(table " in line
        for line in wat_lines
    )
    exported_table_count = sum(
        line.lstrip().startswith("(export ") and "(table " in line
        for line in wat_lines
    )
    local_table_count = sum(
        LOCAL_TABLE_RE.fullmatch(line) is not None for line in wat_lines
    )
    table_mutation_count = sum(
        wat.count(instruction) for instruction in TABLE_MUTATION_INSTRUCTIONS
    )
    call_ref_count = wat.count("call_ref")
    require(call_ref_count == 0, f"{field} uses unsupported call_ref dispatch")
    require(
        call_indirect_count == 0 or imported_table_count == 0,
        f"{field} imports an indirect-call table",
    )
    require(
        call_indirect_count == 0 or exported_table_count == 0,
        f"{field} exports an indirect-call table",
    )
    require(
        call_indirect_count == 0 or table_mutation_count == 0,
        f"{field} has mutable indirect-call table state",
    )
    require(
        call_indirect_count == 0 or indirect_targets,
        f"{field} has call_indirect without a closed local table target inventory",
    )
    require(
        call_indirect_count == 0 or local_table_count == 1,
        f"{field} indirect-call target inventory is not bound to one local table",
    )
    return {
        "call_indirect_local_table_count": local_table_count,
        "call_indirect_imported_table_count": imported_table_count,
        "call_indirect_exported_table_count": exported_table_count,
        "call_indirect_table_mutation_instruction_count": table_mutation_count,
        "unsupported_call_ref_instruction_count": call_ref_count,
    }


def reachable_functions(
    functions: dict[str, WatFunction],
    root: WatFunction,
    indirect_targets: tuple[str, ...] = (),
) -> set[str]:
    seen: set[str] = set()
    pending = [root.name]
    while pending:
        name = pending.pop()
        if name in seen or name not in functions:
            continue
        seen.add(name)
        pending.extend(
            call for call in function_calls(functions[name]) if call in functions
        )
        if any("call_indirect" in line for line in functions[name].lines):
            pending.extend(indirect_targets)
    return seen


def historical_guard_proof(function: WatFunction) -> dict[str, object] | None:
    instructions = [
        line.strip()
        for line in function.lines[1:]
        if not line.strip().startswith("(local ")
    ]
    guard_instruction = f"i32.const {HISTORICAL_GUARD_BLOCK}"
    guard_count = instructions.count(guard_instruction)
    if guard_count == 0:
        return None
    require(guard_count == 1, f"{function.name} historical guard literal count drift")
    require(
        "(param $p0 i32)" in function.lines[0],
        f"{function.name} historical guard event parameter drift",
    )
    shared_prefix = [
        "local.get $p0",
        "i32.load offset=16",
        "i32.load offset=28",
        guard_instruction,
    ]
    models = (
        (
            "old-codegen-byte-array-equality",
            [
                "call $~lib/@graphprotocol/graph-ts/index/ByteArray.fromI32",
                "call $~lib/@graphprotocol/graph-ts/index/BigInt#equals",
            ],
            [],
        ),
        (
            "modern-big-int-compare-equals-zero",
            [
                "call $~lib/@graphprotocol/graph-ts/common/numbers/BigInt.fromI32",
                "call $~lib/@graphprotocol/graph-ts/common/numbers/BigInt.compare",
            ],
            ["i32.eqz"],
        ),
    )
    for comparison_model, comparison_calls, condition_instructions in models:
        prefix = shared_prefix + comparison_calls + condition_instructions
        if instructions[: len(prefix)] != prefix:
            continue
        tail = instructions[len(prefix) : len(prefix) + 3]
        require(
            len(tail) == 3
            and re.fullmatch(r"if \$[^\s]+", tail[0]) is not None
            and tail[1:] == ["return", "end"],
            f"{function.name} historical guard is not a conditional early return",
        )
        proved_prefix = prefix + tail
        return {
            "handler_function": function.name,
            "event_parameter": "$p0",
            "event_block_pointer_load_offset": 16,
            "block_number_load_offset": 28,
            "block": HISTORICAL_GUARD_BLOCK,
            "comparison_model": comparison_model,
            "comparison_calls": [
                item.removeprefix("call $") for item in comparison_calls
            ],
            "condition_instructions": condition_instructions,
            "conditional_instruction": tail[0],
            "conditional_early_return": True,
            "instruction_prefix_sha256": sha256_bytes(
                ("\n".join(proved_prefix) + "\n").encode("utf-8")
            ),
            "wat_start_line": function.start_line,
        }
    raise VerificationError(
        f"{function.name} historical guard literal is not bound to "
        "event.block.number equality and a conditional early return"
    )


def handler_record(function: WatFunction, memory: bytearray) -> dict[str, object]:
    call_sequence = function_calls(function)
    normalized_calls = normalized_call_sequence(function)
    return {
        "function": function.name,
        "wat_function_index": function.function_index,
        "body_sha256": sha256_bytes(function.payload),
        "normalized_body_sha256": sha256_bytes(
            normalized_function_payload(function, memory)
        ),
        "instruction_shape_sha256": sha256_bytes(
            instruction_shape_payload(function, memory)
        ),
        "call_sequence_sha256": sha256_bytes(
            ("\n".join(call_sequence) + "\n").encode("utf-8")
        ),
        "normalized_call_sequence_sha256": sha256_bytes(
            ("\n".join(normalized_calls) + "\n").encode("utf-8")
        ),
        "call_count": len(call_sequence),
        "wat_start_line": function.start_line,
    }


def analyze_mapping(
    root: Path,
    wasm2wat: Path,
    mapping: dict[str, object],
    artifact: dict[str, object],
) -> tuple[dict[str, object], dict[str, WatFunction], bytearray]:
    cid = mapping["cid"]
    artifact_path = root / artifact["path"]
    wat_payload = run_wasm2wat(wasm2wat, artifact_path)
    wat_sha256 = sha256_bytes(wat_payload)
    require(
        wat_sha256 == mapping["manual_wat_sha256"],
        f"WAT SHA-256 drift for {cid}",
    )
    wat = wat_payload.decode("utf-8")
    memory, functions, indirect_targets, exports = parse_wat(wat)
    require(
        sum(FUNCTION_IMPORT_RE.match(line) is not None for line in wat.splitlines())
        == mapping["function_import_count"],
        f"WAT/raw function import count drift for {cid}",
    )
    require(
        len(functions) == mapping["defined_function_count"],
        f"WAT/raw defined function count drift for {cid}",
    )
    callsites = extract_store_set_callsites(functions, memory)
    require_fixed_callsites(callsites, str(cid))
    store_import_marker = f'(import "index" "store.set" (func ${STORE_SET_CALL}'
    store_import_count = wat.count(store_import_marker)
    require(store_import_count == 1, f"{cid} store.set import drift")
    indirect_store_references = sum(
        1
        for line in wat.splitlines()
        if (line.lstrip().startswith("(elem ") or "ref.func" in line)
        and STORE_SET_CALL in line
    )
    require(indirect_store_references == 0, f"{cid} has an indirect store.set reference")
    call_indirect_count = sum(
        line.count("call_indirect")
        for function in functions.values()
        for line in function.lines
    )
    table_evidence = verify_closed_indirect_table(
        wat,
        call_indirect_count,
        indirect_targets,
        str(cid),
    )

    indirect_target_closure: set[str] = set()
    for target in indirect_targets:
        indirect_target_closure.update(
            reachable_functions(functions, functions[target], indirect_targets)
        )
    indirect_target_sites = [
        item
        for item in callsites
        if item["function"] in indirect_target_closure
    ]

    handlers: dict[str, object] = {}
    registered_export_targets: dict[str, str] = {}
    numeric_export_bindings = mapping[
        "registered_handler_export_function_indices"
    ]
    for handler, raw_function_index in numeric_export_bindings.items():
        function = resolve_handler(functions, exports, handler)
        require(
            function.function_index == raw_function_index,
            f"raw WASM/WAT function index drift for {cid} {handler}",
        )
        handlers[handler] = handler_record(function, memory)
        registered_export_targets[handler] = function.name

    targets = sorted({str(item["target"]) for item in callsites})
    return (
        {
            "cid": cid,
            "component": mapping["component"],
            "bytes": artifact["bytes"],
            "sha256": artifact["sha256"],
            "wat_sha256": wat_sha256,
            "registered_handlers": handlers,
            "registered_handler_export_function_indices": numeric_export_bindings,
            "registered_handler_export_targets": registered_export_targets,
            "store_set_callsite_count": len(callsites),
            "store_set_import_count": store_import_count,
            "store_set_callsites": callsites,
            "fixed_store_set_targets": targets,
            "dynamic_store_set_target_count": 0,
            "indirect_store_set_reference_count": indirect_store_references,
            "call_indirect_instruction_count": call_indirect_count,
            "call_indirect_table_target_count": len(indirect_targets),
            "call_indirect_table_targets": list(indirect_targets),
            **table_evidence,
            "call_indirect_target_closure_function_count": len(
                indirect_target_closure
            ),
            "call_indirect_target_closure_store_set_site_ids": [
                item["site_id"] for item in indirect_target_sites
            ],
            "call_indirect_target_closure_store_set_targets": sorted(
                {item["target"] for item in indirect_target_sites}
            ),
        },
        functions,
        memory,
    )


def critical_reachability(
    analysis: dict[str, object],
    functions: dict[str, WatFunction],
    handler_name: str,
) -> dict[str, object]:
    handler = resolve_handler(
        functions,
        analysis["registered_handler_export_targets"],
        handler_name,
    )
    indirect_targets = tuple(analysis["call_indirect_table_targets"])
    reachable = reachable_functions(functions, handler, indirect_targets)
    reachable_call_indirect_count = sum(
        line.count("call_indirect")
        for name in reachable
        for line in functions[name].lines
    )
    sites = [
        item
        for item in analysis["store_set_callsites"]
        if item["function"] in reachable
    ]
    return {
        "handler": handler_name,
        "handler_function": handler.name,
        "reachable_function_count": len(reachable),
        "reachable_call_indirect_instruction_count": reachable_call_indirect_count,
        "conservative_call_indirect_table_targets": (
            list(indirect_targets) if reachable_call_indirect_count else []
        ),
        "reachable_store_set_site_ids": [item["site_id"] for item in sites],
        "reachable_store_set_targets": sorted({item["target"] for item in sites}),
        "dynamic_reachable_store_set_target_count": sum(
            item["target"] is None for item in sites
        ),
    }


def compact_handler_binding(
    analysis: dict[str, object], handler: str
) -> dict[str, object]:
    record = analysis["registered_handlers"][handler]
    return {
        "mapping_cid": analysis["cid"],
        "handler": handler,
        "record_sha256": canonical_sha256(record),
    }


def compact_reachability(record: dict[str, object]) -> dict[str, object]:
    site_ids = record["reachable_store_set_site_ids"]
    return {
        "handler": record["handler"],
        "handler_function": record["handler_function"],
        "reachable_function_count": record["reachable_function_count"],
        "reachable_store_set_site_count": len(site_ids),
        "reachable_store_set_site_ids_sha256": canonical_sha256(site_ids),
        "reachable_store_set_targets": record["reachable_store_set_targets"],
        "reachable_call_indirect_instruction_count": record[
            "reachable_call_indirect_instruction_count"
        ],
        "dynamic_reachable_store_set_target_count": record[
            "dynamic_reachable_store_set_target_count"
        ],
    }


def factory_effect_order_observation(
    cid: str,
    analysis: dict[str, object],
    handler: WatFunction,
) -> dict[str, object]:
    direct_sites = {
        int(item["wat_line"]): item
        for item in analysis["store_set_callsites"]
        if item["function"] == handler.name
    }
    effects: list[dict[str, object]] = []
    save_re = re.compile(r"(?:src/types|generated)/schema/([^/]+)#save$")
    for line_index, call in function_call_sites(handler):
        wat_line = handler.start_line + line_index
        match = save_re.search(call)
        if match is not None:
            effects.append(
                {
                    "kind": "entity_save",
                    "entity": match.group(1),
                    "call": call,
                    "wat_line": wat_line,
                }
            )
        elif call == STORE_SET_CALL:
            require(wat_line in direct_sites, f"{cid} Factory direct save site drift")
            effects.append(
                {
                    "kind": "entity_save",
                    "entity": direct_sites[wat_line]["target"],
                    "call": call,
                    "site_id": direct_sites[wat_line]["site_id"],
                    "wat_line": wat_line,
                }
            )
        elif call.endswith("dataSource.create"):
            effects.append(
                {
                    "kind": "dynamic_data_source_create",
                    "call": call,
                    "wat_line": wat_line,
                }
            )
    tail = effects[-5:]
    observed = [
        item.get("entity", "PoolTemplate")
        for item in tail
    ]
    require(
        observed == ["Pool", "PoolTemplate", "Token", "Token", "Factory"],
        f"{cid} Factory PoolCreated effect order drift: {observed}",
    )
    return {
        "reviewed_order": [
            "Pool.save",
            "PoolTemplate.create",
            "Token[token0].save",
            "Token[token1].save",
            "Factory.save",
        ],
        "machine_checked_lexical_tail": tail,
        "same_path_or_dataflow_machine_proven": False,
        "evidence_kind": (
            "digest-bound reviewed order plus lexical callsite inventory; "
            "control-flow reachability, template identity, and argument dataflow are not proved"
        ),
        "handler_body_sha256": sha256_bytes(handler.payload),
    }


def factory_metadata_evidence(
    cid: str,
    profile: dict[str, object],
    functions: dict[str, WatFunction],
    memory: bytearray,
) -> dict[str, object]:
    total_supply = resolve_suffix_function(
        functions, "/fetchTokenTotalSupply", f"{cid} total-supply helper"
    )
    calls = function_calls(total_supply)
    generation = profile["metadata_generation"]
    if generation == "legacy":
        require(
            any(call.endswith("#try_totalSupply") for call in calls)
            and any(call.endswith("#get:reverted") for call in calls)
            and not any(call.endswith("#get:value") for call in calls)
            and calls[-1].endswith("ByteArray.fromI32"),
            f"{cid} legacy total-supply pointer/allocation model drift",
        )
        total_supply_model = (
            "on success convert the CallResult pointer/allocation with "
            "ByteArray.fromI32 rather than reading the ERC20 result"
        )
    else:
        require(
            any(call.endswith("ethereum.SmartContract#tryCall") for call in calls)
            and any(call.endswith("#get:value") for call in calls)
            and any(call.endswith("ethereum.Value#toBigInt") for call in calls)
            and not calls[-1].endswith("ByteArray.fromI32"),
            f"{cid} modern total-supply decoded-result model drift",
        )
        total_supply_model = "decode the ERC20 totalSupply result as BigInt"

    from_address = resolve_suffix_function(
        functions,
        "StaticTokenDefinition.fromAddress",
        f"{cid} static metadata lookup",
    )
    static_function = from_address
    definitions = [
        function
        for name, function in functions.items()
        if name.endswith("StaticTokenDefinition.getStaticDefinitions")
    ]
    if definitions:
        require(len(definitions) == 1, f"{cid} static definition helper drift")
        static_function = definitions[0]
    static_calls = function_calls(static_function)
    constants = [
        int(match.group(1))
        for line in static_function.lines
        if (match := I32_CONST_RE.fullmatch(line)) is not None
    ]
    require(constants, f"{cid} static metadata slot constant missing")
    initial_slots = int(profile["initial_array_slots"])
    require(constants[0] == initial_slots, f"{cid} static metadata slot count drift")
    if generation == "legacy":
        appended = sum(call.endswith("#push") for call in static_calls)
        require(
            any(call.endswith("#constructor") and "Array<" in call for call in static_calls),
            f"{cid} legacy static array constructor drift",
        )
    else:
        appended = sum(
            call.endswith("StaticTokenDefinition#constructor") for call in static_calls
        )
        require(
            any(call.endswith("__newArray") for call in static_calls),
            f"{cid} modern literal static array drift",
        )
    require(
        appended == profile["appended_static_entries"],
        f"{cid} static metadata populated-entry count drift",
    )
    return {
        "metadata_generation": generation,
        "total_supply_model": total_supply_model,
        "total_supply_helper": {
            "function": total_supply.name,
            "body_sha256": sha256_bytes(total_supply.payload),
            "wat_start_line": total_supply.start_line,
        },
        "static_metadata_profile": profile["static_metadata_profile"],
        "initial_array_slots": initial_slots,
        "appended_static_entries": appended,
        "leading_uninitialized_slots": (
            initial_slots if generation == "legacy" else 0
        ),
        "safe_literal_array": profile["safe_literal_array"],
        "static_definition_helper": {
            "function": static_function.name,
            "body_sha256": sha256_bytes(static_function.payload),
            "wat_start_line": static_function.start_line,
        },
    }


def verify_factory_profile_evidence(
    cid: str,
    profile: dict[str, object],
    analysis: dict[str, object],
    functions: dict[str, WatFunction],
    memory: bytearray,
) -> dict[str, object]:
    handler = resolve_handler(
        functions,
        analysis["registered_handler_export_targets"],
        FACTORY_HANDLER,
    )
    reachability = critical_reachability(analysis, functions, FACTORY_HANDLER)
    require(
        reachability["reachable_store_set_targets"]
        == ["Bundle", "Factory", "Pool", "Token"],
        f"{cid} Factory writer reachability drift",
    )
    reachable = reachable_functions(
        functions, handler, tuple(analysis["call_indirect_table_targets"])
    )
    strings = [
        value
        for name in reachable
        for value in function_static_strings(functions[name], memory)
    ]
    calls = [
        call for name in reachable for call in function_calls(functions[name])
    ]
    require(EXCLUDED_POOL in strings, f"{cid} Factory excluded pool drift")
    require(
        any(call.endswith(("ByteArray#equals", "String.__eq")) for call in calls),
        f"{cid} Factory excluded pool is not bound to equality",
    )
    require(
        "tick" not in strings
        and not any(call.endswith("schema/Pool#set:tick") for call in calls),
        f"{cid} Factory must leave Pool.tick unset",
    )
    return {
        "mapping_cid": cid,
        **profile,
        "handler": FACTORY_HANDLER,
        "handler_body_binding": compact_handler_binding(analysis, FACTORY_HANDLER),
        "reachable_writers": compact_reachability(reachability),
        "excluded_pool": EXCLUDED_POOL,
        "excluded_pool_guard_observation": {
            "literal_present_machine_checked": True,
            "some_equality_call_present_machine_checked": True,
            "event_pool_to_comparison_to_early_return_machine_proven": False,
            "evidence_kind": (
                "digest-bound reviewed ignored-pool guard; literal and equality "
                "presence alone do not prove guard control flow"
            ),
            "handler_body_sha256": sha256_bytes(handler.payload),
        },
        "pool_tick_write": "absent",
        "whitelist_pool_update": "symmetric token0/token1 append when the peer token is whitelisted",
        "pool_created_effect_order_observation": factory_effect_order_observation(
            cid, analysis, handler
        ),
        "pool_created_event_row_write": False,
        "metadata_evidence": factory_metadata_evidence(
            cid, profile, functions, memory
        ),
        "complete_static_handler_contract": False,
    }


def typed_map_field_set_evidence(
    cid: str,
    function: WatFunction,
    memory: bytearray,
    field: str,
    after_line: int = -1,
    required_value_local: str | None = None,
) -> dict[str, object]:
    field_sites = [
        line_index
        for line_index in decoded_constant_sites(function, memory, field)
        if line_index > after_line
    ]
    require(len(field_sites) == 1, f"{cid} {field} field literal count drift")
    field_site = field_sites[0]
    require(field_site > 0, f"{cid} {field} field literal has no receiver")
    receiver = LOCAL_GET_RE.fullmatch(function.lines[field_site - 1])
    require(receiver is not None, f"{cid} {field} field literal is not receiver-bound")
    setter_sites = [
        (line_index, call)
        for line_index, call in function_call_sites(function)
        if line_index > field_site
        and "TypedMap<" in call
        and call.endswith("#set")
    ]
    require(setter_sites, f"{cid} {field} field literal has no map setter")
    setter_site, setter_call = setter_sites[0]
    forbidden = {"drop", "return", "unreachable"}
    between = [line.strip() for line in function.lines[field_site + 1 : setter_site]]
    require(
        not any(
            instruction in forbidden
            or instruction.startswith(("br ", "br_if ", "br_table "))
            for instruction in between
        ),
        f"{cid} {field} field literal is discarded or leaves its setter path",
    )
    require(
        any(LOCAL_GET_RE.fullmatch(line) for line in function.lines[field_site + 1 : setter_site]),
        f"{cid} {field} setter has no value operand",
    )
    if required_value_local is not None:
        require(
            f"local.get {required_value_local}" in between,
            f"{cid} {field} setter is not bound to {required_value_local}",
        )
    return {
        "field_literal_wat_line": function.start_line + field_site,
        "setter_call": setter_call,
        "setter_wat_line": function.start_line + setter_site,
        "receiver_local": receiver.group(1),
        "lexical_receiver_key_value_setter_shape_checked": True,
        "decoded_key_to_setter_machine_checked": False,
        "structural_stack_binding_machine_checked": False,
    }


def tick_day_relation_evidence(
    cid: str,
    expected_mode: str,
    functions: dict[str, WatFunction],
    memory: bytearray,
    reachable_from_swap: set[str],
) -> dict[str, object]:
    function = resolve_suffix_function(
        functions, "/updateTickDayData", f"{cid} TickDay update helper"
    )
    require(
        function.name in reachable_from_swap,
        f"{cid} TickDay helper is not reachable from exported handleSwap",
    )
    setter = typed_map_field_set_evidence(cid, function, memory, "tick")
    setter_site = int(setter["setter_wat_line"]) - function.start_line
    store_get_sites = [
        line_index
        for line_index, call in function_call_sites(function)
        if call.endswith("index/store.get")
    ]
    require(len(store_get_sites) == 1, f"{cid} TickDay store.get callsite drift")
    store_get_site = store_get_sites[0]
    require(
        store_get_site + 3 < len(function.lines)
        and LOCAL_TEE_RE.fullmatch(function.lines[store_get_site + 1]) is not None
        and function.lines[store_get_site + 2].strip() == "i32.eqz"
        and function.lines[store_get_site + 3].strip().startswith("if "),
        f"{cid} TickDay store.get result is not bound to the creation null branch",
    )
    branch = store_get_site + 3
    branch_end = matching_end(
        function.lines, int(branch), f"{cid} TickDay creation branch"
    )
    if int(branch) < setter_site < branch_end:
        mode = "create_only"
    else:
        require(
            setter_site > branch_end,
            f"{cid} TickDay.tick setter precedes the store.get creation branch",
        )
        mode = "every_update"
    require(mode == expected_mode, f"{cid} TickDay.tick relation mode drift")
    return {
        "mode": mode,
        "function": function.name,
        "body_sha256": sha256_bytes(function.payload),
        "tick_setter_binding": setter,
        "creation_store_get_wat_line": function.start_line + store_get_site,
        "creation_store_get_result_to_eqz_to_if_machine_checked": True,
        "reachable_from_exact_exported_handle_swap": True,
        "relation_semantics_machine_checked": False,
        "evidence_kind": (
            "digest-bound reviewed TickDay relation plus lexical decoded-key/setter "
            "and branch-placement shape; decoded key stack dataflow is not proved"
        ),
        "creation_branch_wat_lines": [
            function.start_line + int(branch),
            function.start_line + branch_end,
        ],
    }


def hour_resave_evidence(
    cid: str,
    expected: bool,
    handler: WatFunction,
) -> dict[str, object]:
    helper_sites = [
        line_index
        for line_index, call in function_call_sites(handler)
        if call.endswith("/updatePoolHourData")
    ]
    require(len(helper_sites) == 1, f"{cid} Pool hour helper callsite drift")
    save_sites = [
        line_index
        for line_index, call in function_call_sites(handler)
        if call.endswith("schema/PoolHourData#save")
    ]
    require(
        all(line_index > helper_sites[0] for line_index in save_sites),
        f"{cid} Pool hour direct save precedes its helper",
    )
    observed = bool(save_sites)
    require(observed is expected, f"{cid} explicit Pool hour resave drift")
    return {
        "explicit_hour_resaves_observed": observed,
        "hour_helper_callsite_count": len(helper_sites),
        "direct_resave_callsite_count": len(save_sites),
        "hour_helper_wat_line": handler.start_line + helper_sites[0],
        "direct_resave_wat_lines": [
            handler.start_line + line_index for line_index in save_sites
        ],
        "all_direct_resaves_lexically_after_helper": True,
        "control_flow_reachability_machine_proven": False,
        "handler_body_sha256": sha256_bytes(handler.payload),
    }


def fee_spacing_pairs(function: WatFunction) -> list[list[int]]:
    pairs: list[list[int]] = []
    lines = function.lines
    for index, line in enumerate(lines):
        match = I32_CONST_RE.fullmatch(line)
        if match is None:
            continue
        fee = int(match.group(1))
        if fee not in {1, 100, 500, 3000, 10000}:
            continue
        if index == 0 or LOCAL_GET_RE.fullmatch(lines[index - 1]) is None:
            continue
        comparison_tail = [line.strip() for line in lines[index + 1 : index + 5]]
        if not comparison_tail or not (
            comparison_tail[0].startswith("call $")
            and comparison_tail[0].endswith(("BigInt.fromI32", "ByteArray.fromI32"))
        ):
            continue
        if len(comparison_tail) < 3 or not (
            comparison_tail[1].startswith("call $")
            and comparison_tail[1].endswith(("BigInt#equals", "BigInt.compare"))
        ):
            continue
        comparison_call = comparison_tail[1]
        if comparison_call.endswith("BigInt#equals"):
            branch_offset = 2
            if comparison_tail[branch_offset] == "i32.eqz":
                continue
        else:
            if len(comparison_tail) < 4 or comparison_tail[2] != "i32.eqz":
                continue
            branch_offset = 3
        if not comparison_tail[branch_offset].startswith("if "):
            continue
        branch = index + 1 + branch_offset
        branch_end = matching_end(lines, branch, f"{function.name} fee branch")
        body = [line.strip() for line in lines[branch + 1 : branch_end]]
        if len(body) != 3:
            continue
        spacing_match = I32_CONST_RE.fullmatch(body[0])
        if not (
            spacing_match is not None
            and body[1].startswith("call $")
            and body[1].endswith(("BigInt.fromI32", "ByteArray.fromI32"))
            and body[2] == "return"
        ):
            continue
        spacing = int(spacing_match.group(1))
        if spacing not in {1, 10, 60, 200}:
            continue
        pair = [fee, spacing]
        if pair not in pairs:
            pairs.append(pair)
    return pairs


def fee_spacing_evidence(
    cid: str,
    profile: dict[str, object],
    analysis: dict[str, object],
    functions: dict[str, WatFunction],
    memory: bytearray,
    reachable_from_swap: set[str],
) -> dict[str, object]:
    expected = [[10000, 200], [3000, 60], [500, 10]]
    mode = profile["fee_spacing_mode"]
    if mode == "fee_tier_1_spacing_1":
        expected.append([1, 1])
    elif mode == "fee_tier_100_spacing_1":
        expected.append([100, 1])
    helpers = [
        function
        for name, function in functions.items()
        if name.endswith("/feeTierToTickSpacing")
    ]
    if helpers:
        require(len(helpers) == 1, f"{cid} fee-spacing helper drift")
        function = helpers[0]
        require(
            function.name in reachable_from_swap,
            f"{cid} fee-spacing helper is not reachable from exported handleSwap",
        )
        pairs = fee_spacing_pairs(function)
        proof_kind = "machine-checked exact comparison-branch return binding"
        machine_checked_complete = True
    else:
        function = resolve_handler(
            functions,
            analysis["registered_handler_export_targets"],
            "handleSwap",
        )
        calls = function_calls(function)
        constants = [
            int(match.group(1))
            for line in function.lines
            if (match := I32_CONST_RE.fullmatch(line)) is not None
        ]
        require(
            calls.count(
                "~lib/@graphprotocol/graph-ts/common/numbers/BigInt.compare"
            )
            >= len(expected)
            and all(value in constants for pair in expected for value in pair),
            f"{cid} inlined fee-spacing structural evidence drift",
        )
        pairs = expected
        proof_kind = (
            "digest-bound independently reviewed inlined comparison branches; "
            "numeric presence and comparison count are machine checked"
        )
        machine_checked_complete = False
    require(
        function.name in reachable_from_swap,
        f"{cid} fee-spacing evidence is dormant from exported handleSwap",
    )
    require(pairs == expected, f"{cid} fee-spacing comparison binding drift: {pairs}")
    return {
        "mode": mode,
        "fee_tier_to_tick_spacing": pairs,
        "proof_kind": proof_kind,
        "comparison_to_return_machine_checked": machine_checked_complete,
        "reachable_from_exact_exported_handle_swap": True,
        "function": function.name,
        "body_sha256": sha256_bytes(function.payload),
        "normalized_body_sha256": sha256_bytes(
            normalized_function_payload(function, memory)
        ),
    }


def initialize_persistence_observation(
    cid: str,
    expected: bool,
    handler: WatFunction,
) -> dict[str, object]:
    save_sites = [
        line_index
        for line_index, call in function_call_sites(handler)
        if call.endswith("schema/Pool#save")
    ]
    observed = bool(save_sites)
    require(observed is expected, f"{cid} Initialize Pool save callsite drift")
    return {
        "lexical_pool_save_callsite_present": observed,
        "pool_save_callsite_count": len(save_sites),
        "pool_save_wat_lines": [
            handler.start_line + line_index for line_index in save_sites
        ],
        "same_path_machine_proven": False,
        "evidence_kind": (
            "digest-bound reviewed persistence observation plus lexical Pool.save "
            "callsite inventory; executable-path reachability is not proved"
        ),
        "handler_body_sha256": sha256_bytes(handler.payload),
    }


def verify_pool_profile_evidence(
    cid: str,
    profile: dict[str, object],
    analysis: dict[str, object],
    functions: dict[str, WatFunction],
    memory: bytearray,
) -> dict[str, object]:
    handlers: dict[str, object] = {}
    for handler_name in POOL_HANDLERS:
        handlers[handler_name] = {
            "body_binding": compact_handler_binding(analysis, handler_name),
            "reachable_writers": compact_reachability(
                critical_reachability(analysis, functions, handler_name)
            ),
            **POOL_CRITICAL_WRITER_OBSERVATIONS[handler_name],
        }

    initialize = resolve_handler(
        functions,
        analysis["registered_handler_export_targets"],
        "handleInitialize",
    )
    initialize_calls = function_calls(initialize)
    initialize_strings = function_static_strings(initialize, memory)
    for field in ("sqrtPrice", "tick"):
        require(
            field in initialize_strings
            or any(call.endswith(f"schema/Pool#set:{field}") for call in initialize_calls),
            f"{cid} Initialize Pool.{field} writer drift",
        )
    initialize_persistence = initialize_persistence_observation(
        cid,
        bool(profile["initialize_persists_pool"]),
        initialize,
    )

    swap = resolve_handler(
        functions,
        analysis["registered_handler_export_targets"],
        "handleSwap",
    )
    swap_reachable = reachable_functions(
        functions, swap, tuple(analysis["call_indirect_table_targets"])
    )
    swap_strings = [
        value
        for name in swap_reachable
        for value in function_static_strings(functions[name], memory)
    ]
    require(SWAP_EXCLUDED_POOL in swap_strings, f"{cid} Swap excluded pool drift")

    return {
        "mapping_cid": cid,
        **profile,
        "handlers": handlers,
        "initialize_writes": ["Pool.sqrtPrice", "Pool.tick"],
        "initialize_persistence_observation": initialize_persistence,
        "tick_day_relation_evidence": tick_day_relation_evidence(
            cid,
            str(profile["tick_day_tick_relation_mode"]),
            functions,
            memory,
            swap_reachable,
        ),
        "fee_spacing_evidence": fee_spacing_evidence(
            cid, profile, analysis, functions, memory, swap_reachable
        ),
        "hour_resave_evidence": hour_resave_evidence(
            cid, bool(profile["explicit_hour_resaves"]), swap
        ),
        "swap_excluded_pool": SWAP_EXCLUDED_POOL,
        "emitted_event_rows": ["Burn", "Mint", "Swap"],
        "required_absent_event_rows": [
            "Collect",
            "Flash",
            "Initialize",
            "PoolCreated",
            "TickHourData",
        ],
        "mint_burn_tick_calls": (
            "direct non-try pool ticks calls; a missing result aborts and rolls back the handler"
        ),
        "flash_reviewed_observation": (
            "feeGrowthGlobal0X128 then feeGrowthGlobal1X128, both non-try, then Pool save; exact digest and lexical shapes retained without same-path proof"
        ),
        "trigger_order": "ascending global Ethereum log index",
        "deterministic_failure_scope": "handler atomic under the pinned Graph Node source model",
        "profile_axis_evidence": {
            "machine_checked_axes": [],
            "lexical_callsite_checked_axes": ["explicit_hour_resaves"],
            "partially_machine_checked_axis": "fee_spacing_mode",
            "digest_bound_reviewed_axes": [
                "control_generation",
                "pricing_profile",
                "tracked_amount_threshold",
                "whitelist_cardinality_gate",
                "stable_shortcut",
                "initialize_persists_pool",
                "tick_day_tick_relation_mode",
            ],
            "all_profile_axes_machine_proven": False,
            "retained_mapping_sha256": analysis["sha256"],
        },
        "profile_axis_binding_complete": False,
        "critical_observations_digest_bound": True,
        "complete_static_handler_contract": False,
    }


def observed_guard_proofs(
    mapping_cid: str,
    analysis: dict[str, object],
    functions: dict[str, WatFunction],
) -> list[dict[str, object]]:
    del mapping_cid
    result: list[dict[str, object]] = []
    for handler in NPM_HANDLERS:
        function = resolve_handler(
            functions,
            analysis["registered_handler_export_targets"],
            handler,
        )
        proof = historical_guard_proof(function)
        if proof is not None:
            result.append({"handler": handler, **proof})
    return sorted(result, key=lambda item: str(item["handler"]))


def verify_npm_profile_evidence(
    cid: str,
    profile_id: str,
    analysis: dict[str, object],
    functions: dict[str, WatFunction],
    memory: bytearray,
) -> dict[str, object]:
    expected = PROFILE_DEFINITIONS[profile_id]
    export_targets = analysis["registered_handler_export_targets"]
    guard_proofs = observed_guard_proofs(cid, analysis, functions)
    guards = [str(item["handler"]) for item in guard_proofs]
    require(guards == expected["block_guard_handlers"], f"{cid} block guard profile drift")
    pool_guards = []
    for handler in NPM_HANDLERS:
        handler_function = resolve_handler(
            functions,
            analysis["registered_handler_export_targets"],
            handler,
        )
        reachable = reachable_functions(
            functions,
            handler_function,
            tuple(analysis["call_indirect_table_targets"]),
        )
        if any(
            EXCLUDED_POOL in function_static_strings(functions[name], memory)
            for name in reachable
        ):
            require(
                any(
                    call.endswith("ByteArray#equals")
                    for name in reachable
                    for call in function_calls(functions[name])
                ),
                f"{cid} {handler} excluded-pool literal is not bound to equality",
            )
            pool_guards.append(handler)
    pool_guards.sort()
    require(
        pool_guards
        == ["handleCollect", "handleDecreaseLiquidity", "handleIncreaseLiquidity"],
        f"{cid} excluded-pool guard drift",
    )
    update_fee = next(
        (
            function
            for name, function in functions.items()
            if name.endswith("/updateFeeVars")
        ),
        None,
    )
    require(update_fee is not None, f"{cid} updateFeeVars missing")
    update_calls = function_calls(update_fee)
    require(
        any(call.endswith("#try_positions") for call in update_calls),
        f"{cid} updateFeeVars no longer uses try_positions",
    )
    try_positions = next(
        (
            function
            for name, function in functions.items()
            if name.endswith("#try_positions")
        ),
        None,
    )
    require(try_positions is not None, f"{cid} try_positions missing")
    require(
        ETHEREUM_CALL in function_calls(try_positions),
        f"{cid} try_positions no longer calls ethereum.call",
    )
    fee_refresh_handlers = [
        handler
        for handler in NPM_HANDLERS
        if any(
            call.endswith("/updateFeeVars")
            for call in function_calls(
                resolve_handler(functions, export_targets, handler)
            )
        )
    ]
    require(
        fee_refresh_handlers
        == [
            "handleIncreaseLiquidity",
            "handleDecreaseLiquidity",
            "handleCollect",
        ],
        f"{cid} fee-refresh handler inventory drift",
    )
    snapshot_handlers = [
        handler
        for handler in NPM_HANDLERS
        if any(
            call.endswith("/savePositionSnapshot")
            for call in function_calls(
                resolve_handler(functions, export_targets, handler)
            )
        )
    ]
    require(
        snapshot_handlers == list(NPM_HANDLERS),
        f"{cid} snapshot handler inventory drift",
    )
    transfer_handler = resolve_handler(functions, export_targets, "handleTransfer")
    transfer_calls = function_calls(transfer_handler)
    require(
        (
            any(call.endswith("schema/Position#set:owner") for call in transfer_calls)
            or "owner"
            in function_static_strings(transfer_handler, memory)
        )
        and any(call.endswith("schema/Position#save") for call in transfer_calls),
        f"{cid} direct Transfer writer drift",
    )
    reachability = critical_reachability(analysis, functions, "handleCollect")
    require(
        reachability["reachable_store_set_targets"]
        == ["Position", "PositionSnapshot", "Transaction"],
        f"{cid} Collect reachability drift",
    )
    return {
        "profile_id": profile_id,
        "mapping_cid": cid,
        "audited_semantic_scope": "cumulative NPM operations, Collect quirk, historical guards, fee refresh, snapshots, and direct Transfer only",
        "increase_update_mode": "old liquidity plus event liquidity; old deposited amounts plus event amounts",
        "decrease_update_mode": "old liquidity minus event liquidity; old withdrawn amounts plus event amounts",
        "collect_final_collected_fees_token0": expected[
            "collect_final_collected_fees_token0"
        ],
        "collect_final_collected_fees_token1": expected[
            "collect_final_collected_fees_token1"
        ],
        "collect_write_model": expected["collect_write_model"],
        "collect_token_missing_policy": expected["collect_token_missing_policy"],
        "increase_decrease_token_missing_policy": expected[
            "increase_decrease_token_missing_policy"
        ],
        "block_guard_handlers": guards,
        "block_guard_proofs": guard_proofs,
        "excluded_pool": EXCLUDED_POOL,
        "excluded_pool_handlers": pool_guards,
        "fee_refresh_handlers": [
            "handleCollect",
            "handleDecreaseLiquidity",
            "handleIncreaseLiquidity",
        ],
        "fee_refresh_call_kind": "generated try_positions; a null ethereum.call result becomes CallResult.reverted and preserves prior fee-growth fields",
        "fee_refresh_body_bindings": {
            "try_positions": {
                "function": try_positions.name,
                "body_sha256": sha256_bytes(try_positions.payload),
            },
            "update_fee_vars": {
                "function": update_fee.name,
                "body_sha256": sha256_bytes(update_fee.payload),
            },
        },
        "contract_call_temporal_source_model": "Graph Node v0.44.0 passes the trigger block pointer to ethereum.call, which reads post-block state by block hash when supported or block number otherwise; this is not log-ordinal state",
        "snapshot_handlers": snapshot_handlers,
        "snapshot_id_model": "position id plus # plus block number; later same-position events in a block overwrite that snapshot id",
        "transfer_model": "direct NPM event sets owner to event.to; no parent Pool event required",
        "collect_reachability": reachability,
        "handler_body_bindings": {
            handler: analysis["registered_handlers"][handler]
            for handler in NPM_HANDLERS
        },
        "evidence_kind": "machine-checked reachability and digest-bound independently reviewed WAT observations; not a complete handler or field-writer proof",
        "complete_field_writer_semantics": False,
    }


def local_result_after_call(
    cid: str,
    function: WatFunction,
    call_site: int,
    field: str,
) -> tuple[str, int]:
    for line_index in range(call_site + 1, min(len(function.lines), call_site + 8)):
        instruction = function.lines[line_index].strip()
        require(
            instruction not in {"drop", "return", "unreachable"}
            and not instruction.startswith(("br ", "br_if ", "br_table ")),
            f"{cid} Flash {field} result is discarded before assignment",
        )
        match = LOCAL_SET_RE.fullmatch(function.lines[line_index])
        if match is not None:
            return match.group(1), line_index
    raise VerificationError(f"{cid} Flash {field} result local is missing")


def direct_field_set_evidence(
    cid: str,
    function: WatFunction,
    field: str,
    result_local: str,
) -> dict[str, object] | None:
    sites = [
        (line_index, call)
        for line_index, call in function_call_sites(function)
        if call.endswith(f"schema/Pool#set:{field}")
        or call.endswith(f"schema/PoolDayData#set:{field}")
    ]
    if not sites:
        return None
    require(len(sites) == 1, f"{cid} Flash {field} direct setter count drift")
    setter_site, setter_call = sites[0]
    require(setter_site >= 2, f"{cid} Flash {field} direct setter operands missing")
    receiver = LOCAL_GET_RE.fullmatch(function.lines[setter_site - 2])
    value = LOCAL_GET_RE.fullmatch(function.lines[setter_site - 1])
    require(
        receiver is not None
        and value is not None
        and value.group(1) == result_local,
        f"{cid} Flash {field} direct setter is not result-bound",
    )
    return {
        "setter_call": setter_call,
        "setter_wat_line": function.start_line + setter_site,
        "receiver_local": receiver.group(1),
        "structural_stack_binding_machine_checked": True,
    }


def flash_field_flow_evidence(
    cid: str,
    handler: WatFunction,
    memory: bytearray,
    field: str,
    wrapper_model: bool,
) -> dict[str, object]:
    call_sites = function_call_sites(handler)
    if wrapper_model:
        getter_sites = [
            line_index
            for line_index, call in call_sites
            if call.endswith(f"#{field}")
        ]
        getter_literal_binding: dict[str, object] = {
            "wrapper_call_name_machine_checked": True,
        }
    else:
        getter_sites = []
        field_literals = decoded_constant_sites(handler, memory, field)
        signature = f"{field}():(uint256)"
        signature_literals = decoded_constant_sites(handler, memory, signature)
        for line_index, call in call_sites:
            if not call.endswith("ethereum.SmartContract#call"):
                continue
            if any(
                line_index - 8 <= field_site < signature_site < line_index
                for field_site in field_literals
                for signature_site in signature_literals
            ):
                getter_sites.append(line_index)
        require(
            len(field_literals) >= 1 and len(signature_literals) == 1,
            f"{cid} Flash {field} method/signature literal drift",
        )
        getter_literal_binding = {
            "method_literal": field,
            "signature_literal": signature,
            "method_literal_to_signature_to_call_lexical_shape_checked": True,
        }
    require(len(getter_sites) == 1, f"{cid} Flash {field} getter callsite drift")
    getter_site = getter_sites[0]
    result_local, assignment_site = local_result_after_call(
        cid, handler, getter_site, field
    )
    setter = direct_field_set_evidence(cid, handler, field, result_local)
    if wrapper_model:
        require(setter is not None, f"{cid} Flash {field} wrapper setter missing")
        setter["same_path_machine_proven"] = False
    else:
        require(setter is None, f"{cid} Flash {field} inline setter model drift")
        setter = typed_map_field_set_evidence(
            cid,
            handler,
            memory,
            field,
            after_line=getter_site,
        )
        setter["structural_stack_binding_machine_checked"] = False
        setter["field_literal_to_typed_map_set_lexical_shape_checked"] = True
        setter["result_value_to_setter_machine_checked"] = False
        setter["same_path_machine_proven"] = False
    return {
        "field": field,
        "getter_wat_line": handler.start_line + getter_site,
        "result_local": result_local,
        "result_assignment_wat_line": handler.start_line + assignment_site,
        **getter_literal_binding,
        **setter,
    }


def flash_sequence_evidence(
    cid: str,
    handler: WatFunction,
    memory: bytearray,
) -> dict[str, object]:
    calls = function_calls(handler)
    wrapper_model = any(call.endswith("#feeGrowthGlobal0X128") for call in calls)
    fee0 = flash_field_flow_evidence(
        cid, handler, memory, "feeGrowthGlobal0X128", wrapper_model
    )
    fee1 = flash_field_flow_evidence(
        cid, handler, memory, "feeGrowthGlobal1X128", wrapper_model
    )
    require(
        fee0["getter_wat_line"] != fee1["getter_wat_line"]
        and fee0["result_local"] != fee1["result_local"],
        f"{cid} Flash fee fields do not have distinct getter calls/results",
    )
    save_sites = [
        line_index
        for line_index, call in function_call_sites(handler)
        if call.endswith("schema/Pool#save")
    ]
    require(len(save_sites) == 1, f"{cid} Flash Pool save callsite drift")
    save_site = save_sites[0]
    require(save_site > 0, f"{cid} Flash Pool save receiver missing")
    save_receiver = LOCAL_GET_RE.fullmatch(handler.lines[save_site - 1])
    require(save_receiver is not None, f"{cid} Flash Pool save is not receiver-bound")
    order = [
        int(fee0["getter_wat_line"]),
        int(fee1["getter_wat_line"]),
        int(fee0["setter_wat_line"]),
        int(fee1["setter_wat_line"]),
        handler.start_line + save_site,
    ]
    require(order == sorted(order), f"{cid} Flash field-flow order drift")
    require(
        fee0["receiver_local"]
        == fee1["receiver_local"]
        == save_receiver.group(1),
        f"{cid} Flash setters/save do not target one Pool receiver",
    )
    return {
        "codegen_model": "wrapper" if wrapper_model else "inline",
        "fee_growth_0_flow": fee0,
        "fee_growth_1_flow": fee1,
        "pool_save_wat_line": handler.start_line + save_site,
        "pool_receiver_local": save_receiver.group(1),
        "distinct_getter_calls_and_results_machine_checked": True,
        "lexical_call_setter_save_order_checked": True,
        "ordered_field_flow_machine_checked": False,
        "same_path_machine_proven": False,
        "evidence_kind": (
            "digest-bound reviewed Flash behavior plus lexical call/local/setter/save "
            "shape checks; CFG dominance and same-path execution are not proved"
        ),
        "handler_body_sha256": sha256_bytes(handler.payload),
    }


def verify_flash_evidence(
    cid: str,
    analysis: dict[str, object],
    functions: dict[str, WatFunction],
    memory: bytearray,
) -> dict[str, object]:
    handler = resolve_handler(
        functions,
        analysis["registered_handler_export_targets"],
        "handleFlash",
    )
    calls = function_calls(handler)
    old_wrapper_model = any(call.endswith("#feeGrowthGlobal0X128") for call in calls)
    if old_wrapper_model:
        wrappers = [
            function
            for name, function in functions.items()
            if name.endswith("#feeGrowthGlobal0X128")
            or name.endswith("#feeGrowthGlobal1X128")
        ]
        require(len(wrappers) == 2, f"{cid} Flash getter wrapper drift")
        for wrapper in wrappers:
            require(
                any(call.endswith("ethereum.SmartContract#call") for call in function_calls(wrapper)),
                f"{cid} Flash getter is not a non-try SmartContract call",
            )
    else:
        direct_calls = [
            call for call in calls if call.endswith("ethereum.SmartContract#call")
        ]
        require(len(direct_calls) == 2, f"{cid} Flash direct-call count drift")
    sequence = flash_sequence_evidence(cid, handler, memory)
    smart_contract_call = next(
        (
            function
            for name, function in functions.items()
            if name.endswith("ethereum.SmartContract#call")
        ),
        None,
    )
    require(smart_contract_call is not None, f"{cid} SmartContract#call missing")
    direct = function_calls(smart_contract_call)
    require(ETHEREUM_CALL in direct, f"{cid} SmartContract#call host call drift")
    require(
        any("unreachable" in line for line in smart_contract_call.lines)
        and any(call.endswith("/abort") for call in direct),
        f"{cid} SmartContract#call no longer aborts on a null result",
    )
    reachability = critical_reachability(analysis, functions, "handleFlash")
    require(
        reachability["reachable_store_set_targets"] == ["Pool"],
        f"{cid} Flash reachability drift",
    )
    return {
        "mapping_cid": cid,
        "handler_body_binding": analysis["registered_handlers"]["handleFlash"],
        "field_flow_evidence": sequence,
        "reviewed_call_order": [
            "feeGrowthGlobal0X128",
            "feeGrowthGlobal1X128",
            "set both Pool fields",
            "save Pool",
        ],
        "contract_call_kind": "generated non-try SmartContract#call; null result aborts the handler",
        "contract_state_read": "Pool feeGrowthGlobal0X128 and feeGrowthGlobal1X128 at the handler block pointer",
        "contract_call_temporal_source_model": "Graph Node v0.44.0 reads post-block state by block hash when supported or block number otherwise; this is not intra-block log-ordinal state",
        "reachable_writers": reachability,
        "flash_entity_write": False,
        "evidence_kind": "digest-bound reviewed getter/setter/save behavior with exact export, distinct getter/result, lexical shape/order, non-try call, and conservative writer-closure checks; same-path execution is not machine-proven",
        "complete_pool_field_writer_semantics": False,
    }


def identity_group(
    group_id: str,
    mode: str,
    members: list[tuple[str, str]],
    analyses: dict[str, dict[str, object]],
) -> dict[str, object]:
    field = {
        "body": "body_sha256",
        "normalized_body": "normalized_body_sha256",
        "instruction_shape": "instruction_shape_sha256",
        "normalized_call_sequence": "normalized_call_sequence_sha256",
    }[mode]
    digests = [
        analyses[cid]["registered_handlers"][handler][field]
        for cid, handler in members
    ]
    require(len(set(digests)) == 1, f"handler identity group {group_id} drift")
    return {
        "group_id": group_id,
        "identity_mode": mode,
        "members": [f"{cid}:{handler}" for cid, handler in members],
        "shared_sha256": digests[0],
    }


def component_record(
    segment: dict[str, object], component_name: str
) -> dict[str, object]:
    matches = [
        component
        for component in segment["manifest"]["components"]
        if component["name"] == component_name
    ]
    require(
        len(matches) == 1,
        f"{segment['deployment']} {component_name} manifest component drift",
    )
    return matches[0]


def ancestry_segment_anchors(
    ancestry: dict[str, object],
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for network in ("mainnet", "base"):
        for segment in ancestry["networks"][network]["segments"]:
            factory = component_record(segment, "Factory")
            npm = component_record(segment, "NonfungiblePositionManager")
            pool = component_record(segment, "Pool")
            flash_handlers = [
                handler
                for handler in pool["mapping"]["handlers"]
                if handler["handler"] == "handleFlash"
            ]
            require(
                len(flash_handlers) == 1,
                f"{segment['deployment']} ancestry Pool Flash handler drift",
            )
            result.append(
                {
                    "network": network,
                    "deployment": segment["deployment"],
                    "start_block_inclusive": segment["start_block_inclusive"],
                    "end_block_inclusive": segment["end_block_inclusive"],
                    "factory_mapping_cid": factory["mapping"]["wasm_cid"],
                    "npm_mapping_cid": npm["mapping"]["wasm_cid"],
                    "pool_mapping_cid": pool["mapping"]["wasm_cid"],
                    "npm_event_handlers_in_manifest_order": list(
                        npm["mapping"]["handlers"]
                    ),
                    "pool_flash_event_handler": flash_handlers[0],
                    "manifest_features": list(segment["manifest"]["features"]),
                    "execution_model": segment["execution_model"],
                }
            )
    return result


def graph_node_source_evidence() -> dict[str, object]:
    return {
        "version": GRAPH_NODE_VERSION,
        "commit": GRAPH_NODE_COMMIT,
        "tree": GRAPH_NODE_TREE,
        "tag_ref_url": "https://api.github.com/repos/graphprotocol/graph-node/git/ref/tags/v0.44.0",
        "commit_url": f"https://github.com/graphprotocol/graph-node/commit/{GRAPH_NODE_COMMIT}",
        "files": [
            {
                "path": path,
                "sha256": digest,
                "immutable_url": f"https://github.com/graphprotocol/graph-node/blob/{GRAPH_NODE_COMMIT}/{path}",
                "relevant_lines": lines,
                "claim": claim,
            }
            for path, digest, lines, claim in GRAPH_NODE_FILES
        ],
        "source_model": {
            "ethereum_log_order": "ascending global log index",
            "ethereum_call_state": "post-block state selected by EIP-1898 block hash when supported, otherwise by block number; the number fallback is not fork/hash-bound and neither model is log-ordinal state",
            "deterministic_handler_error": "discard the failing handler's created data sources and entity-cache changes; nonFatalErrors permits other successful handler writes to continue; record a deterministic proof-of-indexing error",
        },
        "target_runtime_binary_or_source_identity_bound": False,
        "status": "primary-source reference model only; not proof of target runtime identity",
    }


def source_provenance_bindings(
    analyses: dict[str, dict[str, object]],
) -> list[dict[str, object]]:
    cids = sorted(set(FACTORY_PROFILE_BY_MAPPING) | set(POOL_PROFILE_BY_MAPPING))
    result: list[dict[str, object]] = []
    for cid in cids:
        exact = ENTRY_BLOB_ANCHOR_BY_MAPPING.get(cid)
        if exact is None:
            limitations = [
                "no exact committed source entry blob anchor is assigned to this mapping",
                "historic semantic anchors are intentionally unassigned and cannot replace the retained deployed WASM",
            ]
            if cid in {
                "QmYQRHstsSS7mntgKNSot74qN2dpuyFEtd1DddPmnqWC65",
                "QmXFDgK3qLnmsLFcPWobXbdnqV9gESL9BvYY29si4vpTjr",
                "QmPZCHE1URf4oviX7Tbrkw3aMENo1qAeEGa1AS2gMumG7P",
            }:
                limitations.insert(
                    0,
                    "the exact audit found no matching committed source tree for this deployed mapping",
                )
            binding = {
                "mapping_cid": cid,
                "component": analyses[cid]["component"],
                "match_kind": "none_found",
                "repository": SOURCE_REPOSITORY,
                "commit": None,
                "entry_path": None,
                "entry_blob_sha1": None,
                "artifact_authority": "retained_mapping_wasm",
                "artifact_sha256": analyses[cid]["sha256"],
                "limitations": limitations,
            }
        else:
            commit, entry_path, entry_blob_sha1 = exact
            binding = {
                "mapping_cid": cid,
                "component": analyses[cid]["component"],
                "match_kind": "exact_entry_blob_anchor",
                "repository": SOURCE_REPOSITORY,
                "commit": commit,
                "entry_path": entry_path,
                "entry_blob_sha1": entry_blob_sha1,
                "artifact_authority": "retained_mapping_wasm",
                "artifact_sha256": analyses[cid]["sha256"],
                "limitations": [
                    "the commit and mapping entry blob are exact source anchors only; no reproducible source-to-WASM build correspondence is proved",
                    "retained deployed WASM remains authoritative",
                ],
            }
        result.append(binding)
    return result


def segment_writer_contract_from_record(
    segment: dict[str, object],
) -> dict[str, object]:
    factory_cid = str(segment["factory_mapping_cid"])
    npm_cid = str(segment["npm_mapping_cid"])
    pool_cid = str(segment["pool_mapping_cid"])
    require(factory_cid in FACTORY_PROFILE_BY_MAPPING, "unknown segment Factory mapping CID")
    require(npm_cid in PROFILE_BY_MAPPING, "unknown segment NPM mapping CID")
    require(pool_cid in POOL_PROFILE_BY_MAPPING, "unknown segment Pool mapping CID")
    factory_profile = FACTORY_PROFILE_BY_MAPPING[factory_cid]
    npm_profile_id = PROFILE_BY_MAPPING[npm_cid]
    pool_profile = POOL_PROFILE_BY_MAPPING[pool_cid]
    artifact_bindings = {
        "factory": {
            "mapping_cid": factory_cid,
            "profile_id": factory_profile["profile_id"],
        },
        "nonfungible_position_manager": {
            "mapping_cid": npm_cid,
            "profile_id": npm_profile_id,
        },
        "pool": {
            "mapping_cid": pool_cid,
            "profile_id": pool_profile["profile_id"],
        },
    }
    semantic_contract = {
        "factory": {
            key: value
            for key, value in factory_profile.items()
            if key != "profile_id"
        },
        "nonfungible_position_manager": PROFILE_DEFINITIONS[npm_profile_id],
        "pool": {
            key: value
            for key, value in pool_profile.items()
            if key != "profile_id"
        },
        "manifest_features": segment["manifest_features"],
        "deterministic_handler_error_policy_under_source_model": segment[
            "deterministic_handler_error_policy_under_source_model"
        ],
        "trigger_order_source_model": segment["trigger_order_source_model"],
    }
    return {
        "segment_id": f"{segment['network']}:{segment['deployment']}",
        "network": segment["network"],
        "deployment": segment["deployment"],
        "start_block_inclusive": segment["start_block_inclusive"],
        "end_block_inclusive": segment["end_block_inclusive"],
        "artifact_bindings": artifact_bindings,
        "semantic_contract": semantic_contract,
        "artifact_identity_sha256": canonical_sha256(artifact_bindings),
        "semantic_contract_sha256": canonical_sha256(semantic_contract),
        "execution_model": "undecided",
        "backfill_allowed": False,
    }


def build_segment_writer_contracts(
    ancestry: dict[str, object],
    segment_records: list[dict[str, object]],
) -> list[dict[str, object]]:
    records_by_deployment = {
        item["deployment"]: item for item in segment_records
    }
    result: list[dict[str, object]] = []
    for network in ("mainnet", "base"):
        for segment in ancestry["networks"][network]["segments"]:
            deployment = segment["deployment"]
            record = records_by_deployment[deployment]
            expected_identity = {
                "network": network,
                "deployment": deployment,
                "start_block_inclusive": segment["start_block_inclusive"],
                "end_block_inclusive": segment["end_block_inclusive"],
                "factory_mapping_cid": component_record(segment, "Factory")[
                    "mapping"
                ]["wasm_cid"],
                "npm_mapping_cid": component_record(
                    segment, "NonfungiblePositionManager"
                )["mapping"]["wasm_cid"],
                "pool_mapping_cid": component_record(segment, "Pool")["mapping"][
                    "wasm_cid"
                ],
            }
            require(
                all(record[key] == value for key, value in expected_identity.items()),
                f"{deployment} legacy segment identity/CID drift",
            )
            result.append(segment_writer_contract_from_record(record))
    return result


def build_segment_writer_diffs(
    segments: list[dict[str, object]],
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for left, right in itertools.combinations(segments, 2):
        if left["network"] != right["network"]:
            relation = "cross_network"
            boundary = None
        elif (
            left["end_block_inclusive"] is not None
            and right["start_block_inclusive"]
            == left["end_block_inclusive"] + 1
        ):
            relation = "adjacent_graft"
            boundary = left["end_block_inclusive"]
        else:
            relation = "same_network_nonadjacent"
            boundary = None
        artifact_paths = json_diff_paths(
            left["artifact_bindings"], right["artifact_bindings"]
        )
        semantic_paths = json_diff_paths(
            left["semantic_contract"], right["semantic_contract"]
        )
        result.append(
            {
                "left_segment_id": left["segment_id"],
                "right_segment_id": right["segment_id"],
                "relation": relation,
                "boundary_block": boundary,
                "artifact_equal": not artifact_paths,
                "semantic_equal": not semantic_paths,
                "artifact_diff_paths": artifact_paths,
                "semantic_diff_paths": semantic_paths,
                "left_artifact_identity_sha256": left[
                    "artifact_identity_sha256"
                ],
                "right_artifact_identity_sha256": right[
                    "artifact_identity_sha256"
                ],
                "left_semantic_contract_sha256": left[
                    "semantic_contract_sha256"
                ],
                "right_semantic_contract_sha256": right[
                    "semantic_contract_sha256"
                ],
            }
        )
    return result


def build_contract(root: Path, wasm2wat: Path | None = None) -> dict[str, object]:
    root = root.resolve()
    executable = resolve_wasm2wat(wasm2wat)
    ancestry = ANCESTRY.verify(root)
    artifacts = {item["cid"]: item for item in ancestry["artifacts"]}
    mappings = {item["cid"]: item for item in ancestry["mapping_writer_inventories"]}

    analyses: dict[str, dict[str, object]] = {}
    functions_by_cid: dict[str, dict[str, WatFunction]] = {}
    memory_by_cid: dict[str, bytearray] = {}
    for cid in sorted(mappings):
        analysis, functions, memory = analyze_mapping(
            root, executable, mappings[cid], artifacts[cid]
        )
        analyses[cid] = analysis
        functions_by_cid[cid] = functions
        memory_by_cid[cid] = memory

    npm_profiles_by_mapping: dict[str, dict[str, object]] = {}
    for cid, profile_id in sorted(PROFILE_BY_MAPPING.items()):
        npm_profiles_by_mapping[cid] = verify_npm_profile_evidence(
            cid,
            profile_id,
            analyses[cid],
            functions_by_cid[cid],
            memory_by_cid[cid],
        )

    factory_profiles = [
        verify_factory_profile_evidence(
            cid,
            FACTORY_PROFILE_BY_MAPPING[cid],
            analyses[cid],
            functions_by_cid[cid],
            memory_by_cid[cid],
        )
        for cid in sorted(FACTORY_PROFILE_BY_MAPPING)
    ]

    pool_cids = sorted(
        cid for cid, mapping in mappings.items() if mapping["component"] == "Pool"
    )
    require(
        pool_cids == sorted(POOL_PROFILE_BY_MAPPING),
        "Pool profile mapping closure drift",
    )
    pool_profiles = [
        verify_pool_profile_evidence(
            cid,
            POOL_PROFILE_BY_MAPPING[cid],
            analyses[cid],
            functions_by_cid[cid],
            memory_by_cid[cid],
        )
        for cid in pool_cids
    ]
    flash_evidence = [
        verify_flash_evidence(
            cid, analyses[cid], functions_by_cid[cid], memory_by_cid[cid]
        )
        for cid in pool_cids
    ]

    old_npm = [
        "QmYWR79pUmVbQ42JkvB24D6AKCGtdo4UG78ZSewmFxwQdR",
        "Qmebr2EyxV7v1wLt9DSFKA7g8EhcVr9k1x7pwZr5eWEHT6",
        "QmYwxHm2GNNcukX9oe4owucCLNoAk2rYrbMFuMFtWfKLn2",
    ]
    current_npm = [
        "QmWxG1yzdQmp4pRDiqKvTZyRrrrZPRUTza6xznjR1wu1sD",
        "QmPjhEuGqknJJ2LfJCi6XTLFLtiymYfZAtjTLfkmJJGMEj",
    ]
    pre_current_pools = [
        "QmWuomVAQCdEXdCRavcsmRz4BNqPx2nppqe8S6AXid66xw",
        "QmYQRHstsSS7mntgKNSot74qN2dpuyFEtd1DddPmnqWC65",
        "QmeNbEMUnaaPpmpLaUVBJfFWRCN5SxG8xPG5eDNoXEGdbW",
        "Qmaydei2ScE7JptBTPgSfkf6PFxEZpLn39gEXYqrBZhsv8",
        "QmadCQv7VPgNXhQTNkcDyzmiWZpWexynUH4XuuaMrsAbJY",
        "QmZPiDeH1j95mozzb5AjKCHn6zgpnhMu77kNAitPbi4Vt3",
    ]
    identity_groups = []
    for handler in (
        "handleIncreaseLiquidity",
        "handleDecreaseLiquidity",
        "handleTransfer",
    ):
        identity_groups.append(
            identity_group(
                f"pre-current-npm-{handler}",
                "body",
                [(cid, handler) for cid in old_npm],
                analyses,
            )
        )
    for handler in NPM_HANDLERS:
        identity_groups.append(
            identity_group(
                f"current-mainnet-base-npm-{handler}",
                "normalized_body",
                [(cid, handler) for cid in current_npm],
                analyses,
            )
        )
    identity_groups.append(
        identity_group(
            "pre-current-pool-handleFlash",
            "body",
            [(cid, "handleFlash") for cid in pre_current_pools],
            analyses,
        )
    )
    identity_groups.append(
        identity_group(
            "current-mainnet-base-pool-handleFlash-instruction-shape",
            "instruction_shape",
            [
                (
                    "QmSaGgPnyhStviGQSGTokQYRgVqLFNvnGWfnv8tSfuvpWD",
                    "handleFlash",
                ),
                (
                    "QmPZCHE1URf4oviX7Tbrkw3aMENo1qAeEGa1AS2gMumG7P",
                    "handleFlash",
                ),
            ],
            analyses,
        )
    )

    segments: list[dict[str, object]] = []
    for network in ("mainnet", "base"):
        for segment in ancestry["networks"][network]["segments"]:
            factory_component = component_record(segment, "Factory")
            npm_component = component_record(segment, "NonfungiblePositionManager")
            pool_component = component_record(segment, "Pool")
            factory_cid = factory_component["mapping"]["wasm_cid"]
            npm_cid = npm_component["mapping"]["wasm_cid"]
            pool_cid = pool_component["mapping"]["wasm_cid"]
            profile_id = PROFILE_BY_MAPPING[npm_cid]
            profile = npm_profiles_by_mapping[npm_cid]
            start = segment["start_block_inclusive"]
            end = segment["end_block_inclusive"]
            block_in_segment = start <= HISTORICAL_GUARD_BLOCK and (
                end is None or HISTORICAL_GUARD_BLOCK <= end
            )
            guard_present = bool(profile["block_guard_handlers"])
            features = list(segment["manifest"]["features"])
            nonfatal = "nonFatalErrors" in features
            flash_handlers = [
                handler
                for handler in pool_component["mapping"]["handlers"]
                if handler["handler"] == "handleFlash"
            ]
            require(
                len(flash_handlers) == 1,
                f"{segment['deployment']} Pool Flash handler registration drift",
            )
            segments.append(
                {
                    "network": network,
                    "deployment": segment["deployment"],
                    "start_block_inclusive": start,
                    "end_block_inclusive": end,
                    "factory_mapping_cid": factory_cid,
                    "npm_mapping_cid": npm_cid,
                    "pool_mapping_cid": pool_cid,
                    "npm_profile_id": profile_id,
                    "npm_event_handlers_in_manifest_order": list(
                        npm_component["mapping"]["handlers"]
                    ),
                    "pool_flash_event_handler": flash_handlers[0],
                    "trigger_order_source_model": TRIGGER_ORDER_SOURCE_MODEL,
                    "manifest_features": features,
                    "historical_guard": {
                        "block": HISTORICAL_GUARD_BLOCK,
                        "present_in_mapping": guard_present,
                        "handler_proofs": profile["block_guard_proofs"],
                        "block_in_segment": block_in_segment,
                        "effective_in_segment": guard_present and block_in_segment,
                    },
                    "deterministic_handler_error_policy_under_source_model": (
                        NONFATAL_HANDLER_ERROR_POLICY
                        if nonfatal
                        else FATAL_HANDLER_ERROR_POLICY
                    ),
                    "target_runtime_identity_bound": False,
                    "execution_model": segment["execution_model"],
                    "backfill_allowed": False,
                }
            )

    all_callsites = [
        site for analysis in analyses.values() for site in analysis["store_set_callsites"]
    ]
    all_targets = sorted({site["target"] for site in all_callsites})
    total_dynamic = sum(site["target"] is None for site in all_callsites)
    total_indirect = sum(
        analysis["indirect_store_set_reference_count"] for analysis in analyses.values()
    )
    require(len(analyses) == 20, "mapping closure must contain 20 mappings")
    require(len(all_callsites) == 162, "global store.set callsite count drift")
    require(total_dynamic == 0, "global dynamic store.set target detected")
    require(total_indirect == 0, "global indirect store.set target detected")
    require(
        set(REQUIRED_ABSENT).isdisjoint(all_targets),
        "required-absent entity has a writer callsite",
    )

    absence = [
        {
            "entity": entity,
            "scope": "all functions in all 20 mapping artifacts across the complete mainnet and Base ancestry",
            "matching_store_set_callsite_count": sum(
                site["target"] == entity for site in all_callsites
            ),
            "dynamic_store_set_target_count": total_dynamic,
            "indirect_store_set_reference_count": total_indirect,
            "static_writer_absence_certified": True,
            "runtime_population_certified": False,
        }
        for entity in REQUIRED_ABSENT
    ]

    grouped_profiles: list[dict[str, object]] = []
    for profile_id in PROFILE_DEFINITIONS:
        bindings = [
            profile
            for profile in npm_profiles_by_mapping.values()
            if profile["profile_id"] == profile_id
        ]
        grouped_profiles.append(
            {
                "profile_id": profile_id,
                "mapping_cids": sorted(profile["mapping_cid"] for profile in bindings),
                "definition": PROFILE_DEFINITIONS[profile_id],
                "mapping_evidence": sorted(bindings, key=lambda item: item["mapping_cid"]),
                "full_handler_or_field_writer_audit_complete": False,
            }
        )

    ancestry_contract_path = root / ANCESTRY.CONTRACT_PATH
    segment_writer_contracts = build_segment_writer_contracts(
        ancestry, segments
    )
    segment_writer_diffs = build_segment_writer_diffs(segment_writer_contracts)
    return {
        "format_version": 3,
        "contract_version": CONTRACT_VERSION,
        "ancestry_contract": {
            "path": ANCESTRY.CONTRACT_PATH.as_posix(),
            "sha256": sha256_bytes(ancestry_contract_path.read_bytes()),
            "format_version": ancestry["format_version"],
            "contract_version": ancestry["contract_version"],
            "artifact_count": len(ancestry["artifacts"]),
            "mapping_count": len(ancestry["mapping_writer_inventories"]),
            "registered_handler_binding_count": sum(
                len(mapping["registered_handler_export_function_indices"])
                for mapping in ancestry["mapping_writer_inventories"]
            ),
        },
        "toolchain": {
            "name": "WABT wasm2wat",
            "version": WABT_VERSION,
            "command": ["wasm2wat", "--generate-names", "<mapping-wasm>"],
            "official_linux_archive": WABT_LINUX_ARCHIVE,
            "host_executable_path_recorded": False,
        },
        "graph_node_source_evidence": graph_node_source_evidence(),
        "global_store_set_closure": {
            "mapping_count": len(analyses),
            "registered_handler_count": sum(
                len(analysis["registered_handlers"])
                for analysis in analyses.values()
            ),
            "store_set_callsite_count": len(all_callsites),
            "fixed_target_callsite_count": len(all_callsites) - total_dynamic,
            "dynamic_target_callsite_count": total_dynamic,
            "indirect_store_set_reference_count": total_indirect,
            "fixed_targets": all_targets,
            "target_argument_shape": "every direct store.set is immediately fed by i32.const entity, local.get id, Value#toString, and local.get entity",
            "complete_all_function_scan": True,
        },
        "mapping_analyses": [analyses[cid] for cid in sorted(analyses)],
        "handler_identity_groups": identity_groups,
        "npm_semantic_profiles": grouped_profiles,
        "source_provenance_bindings": source_provenance_bindings(analyses),
        "semantic_source_anchors": [
            {
                "repository": SOURCE_REPOSITORY,
                "commit": commit,
                "match_kind": "semantic_anchor",
                "mapping_assignment": None,
                "artifact_authority": "retained_mapping_wasm",
                "limitations": [
                    "historic semantic reference only; not an exact mapping-source entry anchor"
                ],
            }
            for commit in SEMANTIC_SOURCE_ANCHORS
        ],
        "factory_writer_contract": {
            "contract_id": "factory-pool-created/v1",
            "mapping_count": len(factory_profiles),
            "registered_handler_count": len(factory_profiles),
            "handler": FACTORY_HANDLER,
            "common": {
                "excluded_pool": EXCLUDED_POOL,
                "pool_tick_write": "required_absent",
                "reviewed_effect_order": [
                    "Pool.save",
                    "PoolTemplate.create",
                    "Token[token0].save",
                    "Token[token1].save",
                    "Factory.save",
                ],
                "pool_created_event_row_write": False,
                "field_writer_contract": FACTORY_FIELD_WRITER_CONTRACT,
                "complete_static_handler_contract": False,
            },
            "mapping_bindings": factory_profiles,
        },
        "pool_writer_contract": {
            "contract_id": "pool-handlers/v1",
            "mapping_count": len(pool_profiles),
            "registered_handler_count": len(pool_profiles) * len(POOL_HANDLERS),
            "handlers": list(POOL_HANDLERS),
            "common": {
                "emitted_event_rows": ["Burn", "Mint", "Swap"],
                "required_absent_event_rows": [
                    "Collect",
                    "Flash",
                    "Initialize",
                    "PoolCreated",
                    "TickHourData",
                ],
                "swap_excluded_pool": SWAP_EXCLUDED_POOL,
                "trigger_order": "ascending global Ethereum log index",
                "critical_writer_observations": POOL_CRITICAL_WRITER_OBSERVATIONS,
                "observation_evidence_kind": (
                    "digest-bound independently reviewed WAT observations; structural "
                    "checks cover exact handler exports, Initialize save callsites, "
                    "TickDay store.get branch and lexical setter shapes, legacy fee-spacing returns, Pool-hour "
                    "resave callsites, Flash distinct getters and lexical shapes, and writer reachability; "
                    "remaining profile axes are not machine-proven"
                ),
                "complete_field_value_semantics": False,
            },
            "mapping_bindings": pool_profiles,
        },
        "pool_flash_evidence": flash_evidence,
        "segments": segments,
        "segment_writer_contracts": segment_writer_contracts,
        "segment_writer_diffs": segment_writer_diffs,
        "required_absence_certifications": absence,
        "truth_boundary": {
            "registered_handler_export_binding_chain_complete": True,
            "wabt_analysis_ci_recomputed": True,
            "global_store_set_callsite_closure_complete": True,
            "constant_store_set_target_inventory_complete": True,
            "npm_collect_and_pool_flash_conservative_writer_closure_complete": True,
            "required_absence_static_certified": True,
            "factory_static_writer_observations_digest_bound": True,
            "pool_static_writer_observations_digest_bound": True,
            "factory_pool_profile_axis_catalog_digest_bound": True,
            "factory_pool_critical_writer_observations_bound": True,
            "segment_writer_contracts_complete": True,
            "segment_writer_diff_complete": True,
            "source_binding_inventory_complete": True,
            "field_writer_audit_complete": False,
            "npm_collect_and_pool_flash_reachability_complete": False,
            "factory_static_writer_provenance_complete": False,
            "pool_static_writer_provenance_complete": False,
            "factory_pool_profile_axis_bindings_complete": False,
            "factory_pool_full_field_writer_semantics_complete": False,
            "full_handler_semantics_complete": False,
            "runtime_population_complete": False,
            "boundary_state_continuity_complete": False,
            "logical_oracle_complete": False,
            "physical_parity_complete": False,
            "poi_parity_complete": False,
            "target_graph_node_runtime_identity_bound": False,
            "segment_execution_models_decided": False,
            "backfill_ready": False,
            "production_ready": False,
        },
    }


TOP_LEVEL_KEYS = {
    "format_version",
    "contract_version",
    "ancestry_contract",
    "toolchain",
    "graph_node_source_evidence",
    "global_store_set_closure",
    "mapping_analyses",
    "handler_identity_groups",
    "npm_semantic_profiles",
    "source_provenance_bindings",
    "semantic_source_anchors",
    "factory_writer_contract",
    "pool_writer_contract",
    "pool_flash_evidence",
    "segments",
    "segment_writer_contracts",
    "segment_writer_diffs",
    "required_absence_certifications",
    "truth_boundary",
}

WRITER_TRUE_FLAGS = (
    "registered_handler_export_binding_chain_complete",
    "wabt_analysis_ci_recomputed",
    "global_store_set_callsite_closure_complete",
    "constant_store_set_target_inventory_complete",
    "npm_collect_and_pool_flash_conservative_writer_closure_complete",
    "required_absence_static_certified",
    "factory_static_writer_observations_digest_bound",
    "pool_static_writer_observations_digest_bound",
    "factory_pool_profile_axis_catalog_digest_bound",
    "factory_pool_critical_writer_observations_bound",
    "segment_writer_contracts_complete",
    "segment_writer_diff_complete",
    "source_binding_inventory_complete",
)

WRITER_FALSE_FLAGS = (
    "field_writer_audit_complete",
    "npm_collect_and_pool_flash_reachability_complete",
    "factory_static_writer_provenance_complete",
    "pool_static_writer_provenance_complete",
    "factory_pool_profile_axis_bindings_complete",
    "factory_pool_full_field_writer_semantics_complete",
    "full_handler_semantics_complete",
    "runtime_population_complete",
    "boundary_state_continuity_complete",
    "logical_oracle_complete",
    "physical_parity_complete",
    "poi_parity_complete",
    "target_graph_node_runtime_identity_bound",
    "segment_execution_models_decided",
    "backfill_ready",
    "production_ready",
)


def validate_internal_contract(
    contract: object,
    verified_ancestry: dict[str, object] | None = None,
    root: Path = REPOSITORY,
) -> dict[str, object]:
    root = root.resolve()
    ancestry = verified_ancestry or ANCESTRY.verify(root)
    contract = ANCESTRY.exact_keys(contract, TOP_LEVEL_KEYS, "writer contract")
    require(contract["format_version"] == 3, "writer format version drift")
    require(contract["contract_version"] == CONTRACT_VERSION, "writer contract version drift")
    require(
        ancestry["format_version"] == 2
        and ancestry["contract_version"] == "uniswap-v3-graft-ancestry/v2",
        "writer requires immutable ancestry contract v2",
    )
    ancestry_path = root / ANCESTRY.CONTRACT_PATH
    expected_ancestry_metadata = {
        "path": ANCESTRY.CONTRACT_PATH.as_posix(),
        "sha256": sha256_bytes(ancestry_path.read_bytes()),
        "format_version": ancestry["format_version"],
        "contract_version": ancestry["contract_version"],
        "artifact_count": len(ancestry["artifacts"]),
        "mapping_count": len(ancestry["mapping_writer_inventories"]),
        "registered_handler_binding_count": sum(
            len(mapping["registered_handler_export_function_indices"])
            for mapping in ancestry["mapping_writer_inventories"]
        ),
    }
    require(
        contract["ancestry_contract"] == expected_ancestry_metadata,
        "writer ancestry metadata is not bound to the verified immutable ancestry",
    )
    toolchain = contract["toolchain"]
    require(toolchain["version"] == WABT_VERSION, "writer tool version drift")
    require(toolchain["official_linux_archive"] == WABT_LINUX_ARCHIVE, "writer WABT archive identity drift")
    closure = contract["global_store_set_closure"]
    require(closure["mapping_count"] == 20, "writer mapping closure drift")
    require(closure["registered_handler_count"] == 70, "writer handler closure drift")
    require(closure["store_set_callsite_count"] == 162, "writer callsite closure drift")
    require(closure["fixed_target_callsite_count"] == 162, "writer fixed-target closure drift")
    require(closure["dynamic_target_callsite_count"] == 0, "writer dynamic target detected")
    require(closure["indirect_store_set_reference_count"] == 0, "writer indirect target detected")
    require(closure["complete_all_function_scan"] is True, "writer all-function scan is unproved")

    mappings = contract["mapping_analyses"]
    require(isinstance(mappings, list) and len(mappings) == 20, "writer mapping analyses malformed")
    mapping_by_cid = {mapping["cid"]: mapping for mapping in mappings}
    require(len(mapping_by_cid) == 20, "writer mapping analysis CID closure drift")
    ancestry_mapping_by_cid = {
        mapping["cid"]: mapping
        for mapping in ancestry["mapping_writer_inventories"]
    }
    require(
        set(mapping_by_cid) == set(ancestry_mapping_by_cid),
        "writer mapping analysis CID closure drift from ancestry",
    )
    numeric_binding_count = 0
    for mapping in mappings:
        expected_numeric_bindings = ancestry_mapping_by_cid[mapping["cid"]][
            "registered_handler_export_function_indices"
        ]
        numeric_bindings = mapping[
            "registered_handler_export_function_indices"
        ]
        require(
            numeric_bindings == expected_numeric_bindings,
            "writer raw WASM numeric handler binding drift from ancestry",
        )
        numeric_binding_count += len(numeric_bindings)
        export_targets = mapping["registered_handler_export_targets"]
        registered_handlers = mapping["registered_handlers"]
        require(
            set(numeric_bindings) == set(export_targets) == set(registered_handlers)
            and all(
                registered_handlers[handler]["function"] == target
                and registered_handlers[handler]["wat_function_index"]
                == numeric_bindings[handler]
                for handler, target in export_targets.items()
            ),
            "writer handler evidence is not rooted at its raw numeric and exact WAT export targets",
        )
        require(mapping["store_set_import_count"] == 1, "writer store.set import drift")
        require(
            mapping["store_set_callsite_count"]
            == len(mapping["store_set_callsites"]),
            "writer per-mapping callsite count drift",
        )
        require(
            mapping["dynamic_store_set_target_count"] == 0,
            "writer per-mapping dynamic target detected",
        )
        require(
            mapping["indirect_store_set_reference_count"] == 0,
            "writer per-mapping indirect target detected",
        )
        require(
            mapping["call_indirect_table_target_count"]
            == len(mapping["call_indirect_table_targets"]),
            "writer indirect-call table target count drift",
        )
        require(
            mapping["unsupported_call_ref_instruction_count"] == 0,
            "writer unsupported call_ref dispatch detected",
        )
        require(
            mapping["call_indirect_instruction_count"] == 0
            or (
                mapping["call_indirect_imported_table_count"] == 0
                and mapping["call_indirect_exported_table_count"] == 0
            ),
            "writer indirect-call table ownership drift",
        )
        require(
            mapping["call_indirect_instruction_count"] == 0
            or mapping["call_indirect_table_mutation_instruction_count"] == 0,
            "writer mutable indirect-call table detected",
        )
        require(
            mapping["call_indirect_instruction_count"] == 0
            or mapping["call_indirect_table_targets"],
            "writer indirect-call target closure is unproved",
        )
        require(
            mapping["call_indirect_instruction_count"] == 0
            or mapping["call_indirect_local_table_count"] == 1,
            "writer indirect-call local table closure drift",
        )
        require(
            mapping["call_indirect_target_closure_store_set_site_ids"] == []
            and mapping["call_indirect_target_closure_store_set_targets"] == [],
            "writer indirect-call table target reaches a store writer",
        )
    require(numeric_binding_count == 70, "writer numeric handler binding closure drift")
    all_sites = [site for mapping in mappings for site in mapping["store_set_callsites"]]
    require(len(all_sites) == 162, "writer retained callsite count drift")
    require(
        all(site["target"] in ENTITIES for site in all_sites),
        "writer retained callsite target is dynamic or unknown",
    )
    require(
        all(site["target_argument_shape"].startswith("i32.const entity") for site in all_sites),
        "writer retained callsite target shape is unproved",
    )
    require(
        {site["target"] for site in all_sites} == set(closure["fixed_targets"]),
        "writer retained target inventory drift",
    )
    profiles = contract["npm_semantic_profiles"]
    require(len(profiles) == 5, "writer semantic profile count drift")
    require(len(contract["segments"]) == 8, "writer segment count drift")
    profile_ids = {item["profile_id"] for item in profiles}
    profile_evidence_by_mapping: dict[str, dict[str, object]] = {}
    require(profile_ids == set(PROFILE_DEFINITIONS), "writer semantic profile identity drift")
    for profile in profiles:
        profile_id = profile["profile_id"]
        require(
            profile["definition"] == PROFILE_DEFINITIONS[profile_id],
            "writer semantic profile definition drift",
        )
        expected_cids = sorted(
            cid
            for cid, expected_profile in PROFILE_BY_MAPPING.items()
            if expected_profile == profile_id
        )
        require(
            profile["mapping_cids"] == expected_cids,
            "writer semantic profile mapping drift",
        )
        require(
            profile["full_handler_or_field_writer_audit_complete"] is False,
            "writer semantic profile overclaim",
        )
        for evidence in profile["mapping_evidence"]:
            profile_evidence_by_mapping[evidence["mapping_cid"]] = evidence
            proofs = evidence["block_guard_proofs"]
            require(
                evidence["block_guard_handlers"]
                == [item["handler"] for item in proofs],
                "writer historical guard proof inventory drift",
            )
            for proof in proofs:
                require(
                    proof["block"] == HISTORICAL_GUARD_BLOCK
                    and proof["event_parameter"] == "$p0"
                    and proof["event_block_pointer_load_offset"] == 16
                    and proof["block_number_load_offset"] == 28
                    and proof["conditional_early_return"] is True,
                    "writer historical guard effectiveness is unproved",
                )
            reachability = evidence["collect_reachability"]
            analysis = mapping_by_cid[evidence["mapping_cid"]]
            require(
                reachability["conservative_call_indirect_table_targets"]
                == (
                    analysis["call_indirect_table_targets"]
                    if reachability["reachable_call_indirect_instruction_count"]
                    else []
                ),
                "writer Collect indirect-call closure drift",
            )
            require(
                reachability["reachable_store_set_targets"]
                == ["Position", "PositionSnapshot", "Transaction"],
                "writer Collect reachability drift",
            )
            require(
                reachability["dynamic_reachable_store_set_target_count"] == 0,
                "writer Collect dynamic reachability drift",
            )
            require(
                evidence["complete_field_writer_semantics"] is False,
                "writer NPM field-semantics overclaim",
            )

    factory = contract["factory_writer_contract"]
    factory_bindings = factory["mapping_bindings"]
    factory_by_cid = {item["mapping_cid"]: item for item in factory_bindings}
    require(
        factory["contract_id"] == "factory-pool-created/v1"
        and factory["mapping_count"] == factory["registered_handler_count"] == 6
        and factory["handler"] == FACTORY_HANDLER
        and factory["common"]["field_writer_contract"] == FACTORY_FIELD_WRITER_CONTRACT
        and len(factory_by_cid) == len(factory_bindings) == 6,
        "Factory writer contract closure drift",
    )
    require(
        {
            cid: {key: item[key] for key in FACTORY_PROFILE_BY_MAPPING[cid]}
            for cid, item in factory_by_cid.items()
        }
        == FACTORY_PROFILE_BY_MAPPING,
        "Factory profile axis drift",
    )
    require(
        all(
            item["pool_tick_write"] == "absent"
            and item["pool_created_event_row_write"] is False
            and item["complete_static_handler_contract"] is False
            and item["excluded_pool_guard_observation"][
                "event_pool_to_comparison_to_early_return_machine_proven"
            ]
            is False
            and item["pool_created_effect_order_observation"][
                "same_path_or_dataflow_machine_proven"
            ]
            is False
            and item["pool_created_effect_order_observation"]["reviewed_order"]
            == factory["common"]["reviewed_effect_order"]
            for item in factory_bindings
        ),
        "Factory critical writer evidence drift",
    )

    pool = contract["pool_writer_contract"]
    pool_bindings = pool["mapping_bindings"]
    pool_by_cid = {item["mapping_cid"]: item for item in pool_bindings}
    require(
        pool["contract_id"] == "pool-handlers/v1"
        and pool["mapping_count"] == 8
        and pool["registered_handler_count"] == 40
        and pool["handlers"] == list(POOL_HANDLERS)
        and pool["common"]["critical_writer_observations"]
        == POOL_CRITICAL_WRITER_OBSERVATIONS
        and pool["common"]["complete_field_value_semantics"] is False
        and len(pool_by_cid) == len(pool_bindings) == 8,
        "Pool writer contract closure drift",
    )
    require(
        {
            cid: {key: item[key] for key in POOL_PROFILE_BY_MAPPING[cid]}
            for cid, item in pool_by_cid.items()
        }
        == POOL_PROFILE_BY_MAPPING,
        "Pool profile axis drift",
    )
    require(
        all(
            set(item["handlers"]) == set(POOL_HANDLERS)
            and item["profile_axis_binding_complete"] is False
            and item["profile_axis_evidence"][
                "all_profile_axes_machine_proven"
            ]
            is False
            and item["critical_observations_digest_bound"] is True
            and item["complete_static_handler_contract"] is False
            and item["initialize_persistence_observation"][
                "lexical_pool_save_callsite_present"
            ]
            is item["initialize_persists_pool"]
            and item["initialize_persistence_observation"][
                "same_path_machine_proven"
            ]
            is False
            and item["tick_day_relation_evidence"]["mode"]
            == item["tick_day_tick_relation_mode"]
            and item["tick_day_relation_evidence"][
                "relation_semantics_machine_checked"
            ]
            is False
            and item["tick_day_relation_evidence"]["tick_setter_binding"][
                "decoded_key_to_setter_machine_checked"
            ]
            is False
            and item["tick_day_relation_evidence"][
                "reachable_from_exact_exported_handle_swap"
            ]
            is True
            and item["fee_spacing_evidence"]["mode"] == item["fee_spacing_mode"]
            and item["fee_spacing_evidence"][
                "reachable_from_exact_exported_handle_swap"
            ]
            is True
            and item["hour_resave_evidence"][
                "explicit_hour_resaves_observed"
            ]
            is item["explicit_hour_resaves"]
            and item["hour_resave_evidence"]["hour_helper_callsite_count"] == 1
            and (
                item["hour_resave_evidence"]["direct_resave_callsite_count"] > 0
            )
            is item["explicit_hour_resaves"]
            for item in pool_bindings
        ),
        "Pool critical writer evidence drift",
    )

    provenance = contract["source_provenance_bindings"]
    provenance_by_cid = {item["mapping_cid"]: item for item in provenance}
    expected_provenance = source_provenance_bindings(mapping_by_cid)
    require(
        len(provenance_by_cid) == len(provenance) == 14
        and set(provenance_by_cid)
        == set(FACTORY_PROFILE_BY_MAPPING) | set(POOL_PROFILE_BY_MAPPING)
        and provenance == expected_provenance,
        "source provenance tuple drift or overclaim",
    )
    require(
        [item["commit"] for item in contract["semantic_source_anchors"]]
        == list(SEMANTIC_SOURCE_ANCHORS)
        and all(item["mapping_assignment"] is None for item in contract["semantic_source_anchors"]),
        "semantic source anchor assignment overclaim",
    )

    require(
        len(contract["pool_flash_evidence"]) == 8,
        "writer Pool Flash evidence count drift",
    )
    for evidence in contract["pool_flash_evidence"]:
        reachability = evidence["reachable_writers"]
        analysis = mapping_by_cid[evidence["mapping_cid"]]
        require(
            reachability["conservative_call_indirect_table_targets"]
            == (
                analysis["call_indirect_table_targets"]
                if reachability["reachable_call_indirect_instruction_count"]
                else []
            ),
            "writer Flash indirect-call closure drift",
        )
        require(
            reachability["reachable_store_set_targets"] == ["Pool"],
            "writer Flash reachability drift",
        )
        require(
            reachability["dynamic_reachable_store_set_target_count"] == 0,
            "writer Flash dynamic reachability drift",
        )
        require(evidence["flash_entity_write"] is False, "writer Flash write drift")
        flow = evidence["field_flow_evidence"]
        fee0 = flow["fee_growth_0_flow"]
        fee1 = flow["fee_growth_1_flow"]
        require(
            flow["ordered_field_flow_machine_checked"] is False
            and flow["same_path_machine_proven"] is False
            and flow["distinct_getter_calls_and_results_machine_checked"] is True
            and flow["lexical_call_setter_save_order_checked"] is True
            and fee0["field"] == "feeGrowthGlobal0X128"
            and fee1["field"] == "feeGrowthGlobal1X128"
            and fee0["getter_wat_line"] != fee1["getter_wat_line"]
            and fee0["result_local"] != fee1["result_local"]
            and fee0["receiver_local"]
            == fee1["receiver_local"]
            == flow["pool_receiver_local"]
            and [
                fee0["getter_wat_line"],
                fee1["getter_wat_line"],
                fee0["setter_wat_line"],
                fee1["setter_wat_line"],
                flow["pool_save_wat_line"],
            ]
            == sorted(
                [
                    fee0["getter_wat_line"],
                    fee1["getter_wat_line"],
                    fee0["setter_wat_line"],
                    fee1["setter_wat_line"],
                    flow["pool_save_wat_line"],
                ]
            ),
            "writer Flash getter/setter/save field-flow drift",
        )
        require(
            evidence["complete_pool_field_writer_semantics"] is False,
            "writer Pool field-semantics overclaim",
        )
    effective_guards: list[tuple[str, str]] = []
    nonfatal_deployments: list[str] = []
    segments = contract["segments"]
    ancestry_anchors = ancestry_segment_anchors(ancestry)
    require(
        isinstance(segments, list) and len(segments) == len(ancestry_anchors) == 8,
        "writer top-level segment count drift from verified ancestry",
    )
    anchor_fields = tuple(ancestry_anchors[0])
    for segment, anchor in zip(segments, ancestry_anchors, strict=True):
        require(
            all(segment[field] == anchor[field] for field in anchor_fields),
            "writer top-level segment identity, range, CID, handler, feature, or execution-model drift from verified ancestry",
        )
        require(segment["npm_profile_id"] in profile_ids, "writer segment profile mis-selection")
        require(
            segment["npm_profile_id"] == PROFILE_BY_MAPPING[segment["npm_mapping_cid"]],
            "writer segment profile mis-selection",
        )
        require(
            [item["handler"] for item in segment["npm_event_handlers_in_manifest_order"]]
            == list(NPM_HANDLERS),
            "writer NPM manifest handler order drift",
        )
        require(
            segment["pool_flash_event_handler"]["handler"] == "handleFlash",
            "writer Pool Flash manifest handler drift",
        )
        guard = segment["historical_guard"]
        require(guard["block"] == HISTORICAL_GUARD_BLOCK, "writer guard block drift")
        start = anchor["start_block_inclusive"]
        end = anchor["end_block_inclusive"]
        expected_block_in_segment = start <= HISTORICAL_GUARD_BLOCK and (
            end is None or HISTORICAL_GUARD_BLOCK <= end
        )
        require(
            guard["block_in_segment"] is expected_block_in_segment,
            "writer historical guard block-in-segment drift from verified ancestry range",
        )
        expected_guard_proofs = profile_evidence_by_mapping[segment["npm_mapping_cid"]][
            "block_guard_proofs"
        ]
        require(
            guard["handler_proofs"] == expected_guard_proofs
            and guard["present_in_mapping"] is bool(expected_guard_proofs),
            "writer segment historical guard proof drift",
        )
        require(
            guard["effective_in_segment"]
            is (guard["present_in_mapping"] and guard["block_in_segment"]),
            "writer guard effectiveness drift",
        )
        if guard["effective_in_segment"]:
            effective_guards.append((segment["network"], segment["deployment"]))
        nonfatal = "nonFatalErrors" in anchor["manifest_features"]
        if nonfatal:
            nonfatal_deployments.append(segment["deployment"])
        require(
            segment["trigger_order_source_model"] == TRIGGER_ORDER_SOURCE_MODEL
            and segment[
                "deterministic_handler_error_policy_under_source_model"
            ]
            == (
                NONFATAL_HANDLER_ERROR_POLICY
                if nonfatal
                else FATAL_HANDLER_ERROR_POLICY
            ),
            "writer segment source-model policy drift",
        )
        require(segment["target_runtime_identity_bound"] is False, "writer target runtime overclaim")
        require(segment["execution_model"] == "undecided", "writer execution model overclaim")
        require(segment["backfill_allowed"] is False, "writer improperly allows backfill")
    require(
        effective_guards
        == [("base", "QmPWDTWRfS8XewMJhxXoQiZX6RkrUMYH7BFnnB846v6wzR")],
        "writer effective guard inventory drift",
    )
    require(
        nonfatal_deployments
        == [
            "QmTZ8ejXJxRo7vDBS4uwqBeGoxLSWbhaA7oXa1RvxunLy7",
            "QmPWDTWRfS8XewMJhxXoQiZX6RkrUMYH7BFnnB846v6wzR",
            "Qmb4VUcAY9LsVgeCuCCMs7X1XrkbRcaiuAbSK8SqhmsAfP",
        ],
        "writer nonFatalErrors feature policy drift",
    )

    segment_contracts = contract["segment_writer_contracts"]
    require(
        isinstance(segment_contracts, list) and len(segment_contracts) == 8,
        "segment writer contract count drift",
    )
    segment_ids = [item["segment_id"] for item in segment_contracts]
    require(len(segment_ids) == len(set(segment_ids)), "segment writer IDs repeat")
    expected_segment_contracts = [
        segment_writer_contract_from_record(segment)
        for segment in contract["segments"]
    ]
    require(
        segment_contracts == expected_segment_contracts,
        "segment writer contract is not cross-bound to legacy identity, range, CIDs, and selected profile semantics",
    )
    for segment in segment_contracts:
        bindings = segment["artifact_bindings"]
        factory_binding = bindings["factory"]
        npm_binding = bindings["nonfungible_position_manager"]
        pool_binding = bindings["pool"]
        require(
            factory_binding["profile_id"]
            == FACTORY_PROFILE_BY_MAPPING[factory_binding["mapping_cid"]][
                "profile_id"
            ],
            "segment Factory profile selection drift",
        )
        require(
            npm_binding["profile_id"]
            == PROFILE_BY_MAPPING[npm_binding["mapping_cid"]],
            "segment NPM profile selection drift",
        )
        require(
            pool_binding["profile_id"]
            == POOL_PROFILE_BY_MAPPING[pool_binding["mapping_cid"]][
                "profile_id"
            ],
            "segment Pool profile selection drift",
        )
        require(
            segment["artifact_identity_sha256"] == canonical_sha256(bindings)
            and segment["semantic_contract_sha256"]
            == canonical_sha256(segment["semantic_contract"]),
            "segment writer canonical hash drift",
        )
        require(
            segment["execution_model"] == "undecided"
            and segment["backfill_allowed"] is False,
            "segment writer promotion overclaim",
        )
    diffs = contract["segment_writer_diffs"]
    require(
        isinstance(diffs, list) and len(diffs) == 28,
        "segment writer pairwise diff closure drift",
    )
    require(
        diffs == build_segment_writer_diffs(segment_contracts),
        "segment writer diff content drift",
    )
    require(
        sum(item["relation"] == "adjacent_graft" for item in diffs) == 6,
        "segment adjacent-graft diff inventory drift",
    )

    absence = contract["required_absence_certifications"]
    require(
        [item["entity"] for item in absence] == list(REQUIRED_ABSENT),
        "writer required-absence inventory drift",
    )
    for item in absence:
        require(item["matching_store_set_callsite_count"] == 0, f"{item['entity']} has a writer")
        require(item["dynamic_store_set_target_count"] == 0, f"{item['entity']} dynamic writer gap")
        require(item["indirect_store_set_reference_count"] == 0, f"{item['entity']} indirect writer gap")
        require(item["static_writer_absence_certified"] is True, f"{item['entity']} static absence not certified")
        require(item["runtime_population_certified"] is False, f"{item['entity']} runtime population overclaim")
        require(
            not any(site["target"] == item["entity"] for site in all_sites),
            f"{item['entity']} false absence certification",
        )

    source = contract["graph_node_source_evidence"]
    require(source["version"] == GRAPH_NODE_VERSION, "graph-node source version drift")
    require(source["commit"] == GRAPH_NODE_COMMIT, "graph-node source commit drift")
    require(source["tree"] == GRAPH_NODE_TREE, "graph-node source tree drift")
    require(source["target_runtime_binary_or_source_identity_bound"] is False, "graph-node runtime identity overclaim")
    expected_files = graph_node_source_evidence()["files"]
    require(source["files"] == expected_files, "graph-node source evidence drift")

    truth = ANCESTRY.exact_keys(
        contract["truth_boundary"],
        set(WRITER_TRUE_FLAGS) | set(WRITER_FALSE_FLAGS),
        "writer truth_boundary",
    )
    for field in WRITER_TRUE_FLAGS:
        require(truth[field] is True, f"writer proved evidence flag drift: {field}")
    for field in WRITER_FALSE_FLAGS:
        require(truth[field] is False, f"unproved writer promotion claim: {field}")
    return contract


def verify(
    root: Path,
    contract_path: Path | None = None,
    wasm2wat: Path | None = None,
) -> dict[str, object]:
    root = root.resolve()
    path = contract_path or root / CONTRACT_PATH
    ancestry = ANCESTRY.verify(root)
    actual = validate_internal_contract(
        ANCESTRY.load_json(path), ancestry, root
    )
    expected = build_contract(root, wasm2wat)
    require(actual == expected, "writer contract content drift from recomputed WAT evidence")
    return actual


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=REPOSITORY)
    parser.add_argument("--contract", type=Path)
    parser.add_argument("--wasm2wat", type=Path)
    parser.add_argument("--write-contract", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        if args.write_contract:
            contract = build_contract(root, args.wasm2wat)
            output = args.contract or root / CONTRACT_PATH
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(render(contract), encoding="utf-8")
            print(f"wrote {output}")
        else:
            contract = verify(root, args.contract, args.wasm2wat)
            print(
                "verified Uniswap V3 writer compatibility: "
                f"{contract['global_store_set_closure']['mapping_count']} mappings, "
                f"{contract['global_store_set_closure']['store_set_callsite_count']} fixed store.set callsites, "
                f"{len(contract['npm_semantic_profiles'])} NPM semantic profiles"
            )
        return 0
    except (OSError, VerificationError, ANCESTRY.VerificationError) as error:
        print(f"writer compatibility verification failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
