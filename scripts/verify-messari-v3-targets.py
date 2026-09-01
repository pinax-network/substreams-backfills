#!/usr/bin/env python3
"""Verify the immutable Messari V3 BSC/Base target and source boundary."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import yaml


REPOSITORY = Path(__file__).resolve().parents[1]
CONTRACT_PATH = Path("docs/provenance/messari-v3-targets-v1.json")
PROFILE_PATH = Path("messari-v3/layout-profile-v1.json")
SOURCE_PROVENANCE_PATH = Path("docs/provenance/messari-v3-source.md")
ROOT_README_PATH = Path("README.md")
TARGET_README_PATH = Path("messari-v3/README.md")
PROVENANCE_INDEX_PATH = Path("docs/provenance/README.md")
SOURCE_PROVENANCE_BYTES = 2907
SOURCE_PROVENANCE_SHA256 = "758d4c34ee7b4028a8bbebe80d554110a7dcec7159db8c1a4e7e0dee814c02f4"

TARGET_ORDER = ("pancakeswap-v3-bsc", "uniswap-v3-base")
FAMILY_ISSUES = (85, 90, 92, 94, 95)
FAMILY_ISSUES_SEMANTICS = (
    "ordered exhaustive unique M9 issue set: BSC target #85, shared implementation #90, "
    "BSC certification #92, Base target #94, Base certification #95"
)
M9_DEPENDENCY_DAG = "#85 + #94 -> #90 -> #92 -> #95"
M9_DEPENDENCY_ORDER = (
    "Both target locks precede shared implementation, and BSC certification precedes "
    "Base certification."
)
ROOT_M9_ISSUE_LINK_ORDER = (85, 94, 90, 92, 95)
TARGET_M9_TRACEABILITY_ARRAYS = ((85, 90, 92), (94, 90, 95))

ROOT_M9_SECTION = "\n".join(
    (
        "9. **M9 — Messari V3 BSC + Base**: the dependency DAG is",
        "   `#85 + #94 -> #90 -> #92 -> #95`. Both target locks precede shared",
        (
            "   implementation, and BSC certification precedes Base certification. "
            "Complete the"
        ),
        "   PancakeSwap V3 BSC target lock in",
        (
            "   [#85](https://github.com/pinax-network/substreams-backfills/"
            "issues/85) and the"
        ),
        "   Uniswap V3 Base target lock in",
        (
            "   [#94](https://github.com/pinax-network/substreams-backfills/"
            "issues/94) before the shared"
        ),
        "   implementation and target adapters in",
        (
            "   [#90](https://github.com/pinax-network/substreams-backfills/"
            "issues/90); then certify and"
        ),
        (
            "   land BSC first in [#92](https://github.com/pinax-network/"
            "substreams-backfills/issues/92),"
        ),
        (
            "   followed by Base in [#95](https://github.com/pinax-network/"
            "substreams-backfills/issues/95)."
        ),
        "   Shared schema shape never substitutes for the separate target locks,",
        "   eligibility decisions, adapters, certifications, or paused landings.",
    )
)

TARGET_M9_SECTION = "\n".join(
    (
        "The provenance contract's top-level `issues` list is the ordered, exhaustive",
        "unique M9 issue set: BSC target #85, shared implementation #90, BSC",
        "certification #92, Base target #94, and Base certification #95. The target",
        "bindings retain target-local traceability associations, `[85, 90, 92]` and",
        "`[94, 90, 95]`; they are not independently executable chains. The dependency",
        "DAG is `#85 + #94 -> #90 -> #92 -> #95`. Both target locks precede shared",
        "implementation, and BSC certification precedes Base certification.",
    )
)

PROVENANCE_M9_SECTION = "\n".join(
    (
        (
            "[`messari-v3-targets-v1.json`](messari-v3-targets-v1.json) is the "
            "combined M9"
        ),
        "target contract for PancakeSwap V3 BSC and Uniswap V3 Base. It locks all 26",
        "deployed artifacts, exact manifest/schema/ABI/WASM structure, cross-target",
        "differences, and all-false operational gates. Its ordered top-level `issues`",
        (
            "list is exhaustive for M9; the per-target bindings retain distinct BSC "
            "and Base"
        ),
        (
            "traceability associations, not independently executable chains. The "
            "dependency"
        ),
        "DAG is `#85 + #94 -> #90 -> #92 -> #95`. Both target locks precede shared",
        (
            "implementation, and BSC certification precedes Base certification. "
            "The accompanying"
        ),
        (
            "[`messari-v3-source.md`](messari-v3-source.md) records the nearest "
            "pinned source"
        ),
        "anchors, matching malformed manifest metadata, unreproducible deleted gluegun",
        "dependency, and the strict source-to-WASM refusal boundary.",
    )
)

MILESTONE_HEADING_PATTERN = re.compile(r"(?m)^[0-9]+\. \*\*M[0-9]+ — ")
ISSUE_HREF_PATTERN = re.compile(
    r"https://github\.com/pinax-network/substreams-backfills/issues/([0-9]+)"
)
TRACEABILITY_ARRAY_PATTERN = re.compile(r"`\[([0-9]+(?:, [0-9]+)*)\]`")
ISSUE_DAG_PATTERN = re.compile(r"#[0-9]+(?:\s*(?:\+|->)\s*#[0-9]+)+")
CONTRADICTORY_M9_ORDERING_PATTERNS = (
    re.compile(
        r"\bbase certification (?:precedes|comes before|must precede) "
        r"bsc certification\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bbsc certification (?:follows|comes after|must follow) "
        r"base certification\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bshared implementation (?:precedes|comes before|must precede) "
        r"(?:both )?target locks\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:both )?target locks (?:follow|come after|must follow) "
        r"shared implementation\b",
        re.IGNORECASE,
    ),
)

FALSE_GATES = (
    "source_revision_pinned",
    "source_reproducible",
    "source_to_wasm_build_reproduced",
    "eligibility_24_hour_passed",
    "eligibility_72_hour_passed",
    "eligibility_complete",
    "implementation_complete",
    "handler_semantics_complete",
    "runtime_behavior_complete",
    "graph_store_order_complete",
    "error_behavior_complete",
    "logical_parity_complete",
    "physical_parity_complete",
    "vid_parity_complete",
    "poi_parity_complete",
    "backfill_ready",
    "deployment_ready",
    "production_ready",
    "readiness_complete",
)

SOURCE_ANCHORS = {
    "pancakeswap-v3-bsc": {
        "repository": "https://github.com/messari/subgraphs",
        "commit": "0c4618d6343b5011742a59ec308dd7ce07b9908b",
        "tree": "1a309dcd6e8827db41a00634eaab6d1e1ed70da6",
        "parent": "6af451686c1dc783f823e51b28686ef95d219c16",
        "committed_at": "2023-05-30T20:55:00Z",
        "schema_source_path": "subgraphs/uniswap-v3-forks/schema.graphql",
        "schema_byte_identical": True,
        "source_template_entity_metadata_matches_deployment": True,
        "abi_result": "Factory, NonFungiblePositionManager, Pool, and TickLens JSON values are semantically identical; deployed formatting remains independently locked",
    },
    "uniswap-v3-base": {
        "repository": "https://github.com/messari/subgraphs",
        "commit": "2c60bd10b5e1a090f6e3b55f0634f2a15ec91dbe",
        "tree": "3a2ff3eec89f6ab6f1f61d3c10a546c231c3f06b",
        "parent": "b16e506a84247a178a9eae09e799bc75787f4275",
        "committed_at": "2023-08-14T15:07:15Z",
        "schema_source_path": "subgraphs/uniswap-v3-forks/schema.graphql",
        "schema_byte_identical": True,
        "source_template_entity_metadata_matches_deployment": True,
        "abi_result": "Factory, NonFungiblePositionManager, and Pool match after removing one repository trailing LF; deployed TickLens remains independently locked",
    },
}

MISSING_MAPPING_ENTITIES_BY_ROLE = {
    "Factory": ["_PricesUSD", "_TokenTracker"],
    "NonFungiblePositionManager": [],
    "primary_pool": [
        "LiqudityPool",
        "PoolDailySnapshot",
        "_PricesUSD",
        "_Account",
        "_DailyActiveAccount",
        "_TokenTracker",
    ],
    "fee_only_template": ["LiqudityPool"],
}

DUPLICATE_MAPPING_ENTITIES_BY_ROLE = {
    "Factory": {},
    "NonFungiblePositionManager": {},
    "primary_pool": {"Token": 2},
    "fee_only_template": {},
}

SOURCE_REPRODUCTION = {
    "source_template_spec_version": "0.0.2",
    "deployed_manifest_spec_version": "0.0.4",
    "spec_version_mismatch": True,
    "deleted_dependency": {
        "repository": "https://github.com/edgeandnode/gluegun",
        "commit": "b34b9003d7bf556836da41b57ef36eb21570620a",
        "available": False,
        "checked_at": "2026-08-31",
        "frozen_yarn_install_succeeded": False,
        "frozen_npm_install_succeeded": False,
    },
    "boundary": "source commits are behavioral anchors, not exact mapping-WASM reproduction workspaces",
    "source_template_mapping_entity_metadata": {
        "matches_deployed_manifests_by_role": True,
        "missing_from_schema_type_declarations_by_role": MISSING_MAPPING_ENTITIES_BY_ROLE,
        "duplicate_multiplicity_by_role": DUPLICATE_MAPPING_ENTITIES_BY_ROLE,
        "normalization_allowed": False,
    },
}

EXPECTED_BINDINGS = {
    "pancakeswap-v3-bsc": {
        "path": "messari-v3/QmQjVBdmgZdjHpQsXGSC5uryWLmPkkTAunHN2AnDApZBa3.yaml",
        "bytes": 624,
        "sha256": "966aaac1fa23254e0704caf5337e827ea62e1ab5d6d0d5c9ca49eff92ac5c3c0",
        "value": {
            "deployment": "QmQjVBdmgZdjHpQsXGSC5uryWLmPkkTAunHN2AnDApZBa3",
            "family": "messari-v3",
            "variant": "pancakeswap-v3-bsc",
            "schema": "QmSY3DAk44RGNbywjXt8PznikJkNMpoNjM8UVde3Hnhocg",
            "chain": "bsc",
            "market_snapshot": {
                "measured_at": "2026-08-31T17:20:00Z",
                "queries_24h": 143319,
                "query_fees_grt_24h": "170.760",
                "authority": "https://github.com/pinax-network/substreams-backfills/issues/83",
            },
            "milestone": "M9",
            "issues": [85, 90, 92],
            "eligibility": {
                "policy": "graph-node-net-catchup-v1",
                "required_clusters": ["riv-subgraphs-a", "kan-subgraphs-a"],
                "latest": {
                    "decision": "indeterminate",
                    "reason": "no_fresh_evidence",
                    "measured_at": None,
                    "evidence": None,
                    "sha256": None,
                },
            },
        },
    },
    "uniswap-v3-base": {
        "path": "messari-v3/QmawEzRNeDyaTgjPKb1eRrbyzxczgSHUYzvTMaMnN8jyuh.yaml",
        "bytes": 620,
        "sha256": "686be8c73a8ef4be78f0eb88c64f665ef40b22bfb9ba080f13f692b578673d0b",
        "value": {
            "deployment": "QmawEzRNeDyaTgjPKb1eRrbyzxczgSHUYzvTMaMnN8jyuh",
            "family": "messari-v3",
            "variant": "uniswap-v3-base",
            "schema": "QmVrng7WZwwCMkcGuay4yEbwepyPFDJjamwmsBcC18Ef2o",
            "chain": "base",
            "market_snapshot": {
                "measured_at": "2026-08-31T17:20:00Z",
                "queries_24h": 17568,
                "query_fees_grt_24h": "21.000",
                "authority": "https://github.com/pinax-network/substreams-backfills/issues/83",
            },
            "milestone": "M9",
            "issues": [94, 90, 95],
            "eligibility": {
                "policy": "graph-node-net-catchup-v1",
                "required_clusters": ["riv-subgraphs-a", "kan-subgraphs-a"],
                "latest": {
                    "decision": "indeterminate",
                    "reason": "no_fresh_evidence",
                    "measured_at": None,
                    "evidence": None,
                    "sha256": None,
                },
            },
        },
    },
}

# target, role, target-relative path, CIDv0, bytes, raw SHA-256
ARTIFACT_ROWS = (
    ("pancakeswap-v3-bsc", "deployment", "deployment.yaml", "QmQjVBdmgZdjHpQsXGSC5uryWLmPkkTAunHN2AnDApZBa3", 5193, "b63daebd56e0044dcf997534a412ff1e0e9ef803f30cf44affd0f2d7329859b6"),
    ("pancakeswap-v3-bsc", "schema", "schema.graphql", "QmSY3DAk44RGNbywjXt8PznikJkNMpoNjM8UVde3Hnhocg", 47054, "efdc8cc4dd6838a065ec573e28cc9218d73e9ad8858694eb836acae0f977c64a"),
    ("pancakeswap-v3-bsc", "abi/ERC20", "abis/ERC20.json", "QmXuTbDkNrN27VydxbS2huvKRk62PMgUTdPDWkxcr2w7j2", 3684, "4b83c6645aed2df5e4e9a1d11f372453fc052ac8575348c8c04a33ceacd0ae90"),
    ("pancakeswap-v3-bsc", "abi/ERC20NameBytes", "abis/ERC20NameBytes.json", "QmQCP6Pdp1MqpwRv2qoPHuUTwZGy7Q3eDHg4w5kzwE9mBj", 268, "b874c853ffa5309e4b7fbf4934c1efdb4fe31e1a65f7041e67f4a7f2258ffb77"),
    ("pancakeswap-v3-bsc", "abi/ERC20SymbolBytes", "abis/ERC20SymbolBytes.json", "QmbHnhUFZa6qqqRyubUYhXntox1TCBxqryaBM1iNGqVJzT", 270, "9ccb9b5d95394b2ffb4ced54cffa0c5ea282917f4eec36c121ce28c257965193"),
    ("pancakeswap-v3-bsc", "abi/Factory", "abis/Factory.json", "QmYxaKG6NxTFjcWvF4VSb9Wk9F4TKLEQZidX9aC89E5CLd", 8559, "6040aedf8e250e4824078449f1d6957e6db1c5a03a070db0988d00d13177448a"),
    ("pancakeswap-v3-bsc", "abi/NonFungiblePositionManager", "abis/NonFungiblePositionManager.json", "QmaWAco4g2iX7B9ar65RhWXUSWSs8yQCpLxBVipzcsDycb", 24646, "a06cac5c70cae9069812dce3f9d8c746a3f6988bcbb76332340509049ed0c7e6"),
    ("pancakeswap-v3-bsc", "abi/Pool", "abis/Pool.json", "QmabUZX7w3JJ8QaYnpuNaZ1iHteB9LfvVwk98YATUg4hVt", 20622, "d11de4a76e9daeac0998eac4b36f17fc307193ce299d54b031940b88b61fecfc"),
    ("pancakeswap-v3-bsc", "abi/TickLens", "abis/TickLens.json", "Qmcew9GU9kikcwYqemJ3x6UqXq5aMs2RBJxqUPeD5Ld5dF", 909, "f99008073f8d236d60d63fcc2b17d8f084e0f6e1ec02d0ec8fd8017a152a2252"),
    ("pancakeswap-v3-bsc", "mapping/Factory", "mappings/Factory.wasm", "QmNyz8Cw8ZQCMcrGA9k64TJSpxsxY6duzkJhKdz2amUQ7i", 145347, "653f582fb473f29d94e16624f3714f43ac05c4d44044fc4c9e03ace1100c8f57"),
    ("pancakeswap-v3-bsc", "mapping/NonFungiblePositionManager", "mappings/NonFungiblePositionManager.wasm", "QmeaUSU4caeboxKLNfeMy4mjJyEND5ht3y7aAUqUnS3CoT", 93924, "89f92d94e83ee622c8b9a97288c6a1124a160ac21edc0b9ee3c917ddc3c5b6b5"),
    ("pancakeswap-v3-bsc", "mapping/Pool", "mappings/Pool.wasm", "QmZ8ncasTQBiLBzb9j7KKCV3Xc1zLLaqKUM9R3VkuS8f1L", 136709, "2e3a917c868d739d96a7f102d6872d110e3c09e80ca0a8ab039e3ffde61ece54"),
    ("pancakeswap-v3-bsc", "mapping/PancakeSwapPool", "mappings/PancakeSwapPool.wasm", "QmZh9pwyqnVEknPgTWraJweuyy1qbwzhA2rrSq43xmdgHL", 41036, "cd4d3e44fd7b749ab40baf691099dc6a67d206666f3016dd82bcf2164b41c136"),
    ("uniswap-v3-base", "deployment", "deployment.yaml", "QmawEzRNeDyaTgjPKb1eRrbyzxczgSHUYzvTMaMnN8jyuh", 5068, "d19dd5c0aa86c78161306a1beb7df754f2a5eeb066e33d99aece4251732e868b"),
    ("uniswap-v3-base", "schema", "schema.graphql", "QmVrng7WZwwCMkcGuay4yEbwepyPFDJjamwmsBcC18Ef2o", 47061, "e93bf39c118446d0695291d03cd1cbe959010d0b00e18d610e5739711fb3411c"),
    ("uniswap-v3-base", "abi/ERC20", "abis/ERC20.json", "QmXuTbDkNrN27VydxbS2huvKRk62PMgUTdPDWkxcr2w7j2", 3684, "4b83c6645aed2df5e4e9a1d11f372453fc052ac8575348c8c04a33ceacd0ae90"),
    ("uniswap-v3-base", "abi/ERC20NameBytes", "abis/ERC20NameBytes.json", "QmQCP6Pdp1MqpwRv2qoPHuUTwZGy7Q3eDHg4w5kzwE9mBj", 268, "b874c853ffa5309e4b7fbf4934c1efdb4fe31e1a65f7041e67f4a7f2258ffb77"),
    ("uniswap-v3-base", "abi/ERC20SymbolBytes", "abis/ERC20SymbolBytes.json", "QmbHnhUFZa6qqqRyubUYhXntox1TCBxqryaBM1iNGqVJzT", 270, "9ccb9b5d95394b2ffb4ced54cffa0c5ea282917f4eec36c121ce28c257965193"),
    ("uniswap-v3-base", "abi/Factory", "abis/Factory.json", "QmTU8eKx6pCgtff6Uvc7srAwR8BPiM3jTMBw9ahrXBjRzY", 3703, "daa769db333fa28d331cc0d866a666ebb98c995a915cb44828a801608ab0d1c1"),
    ("uniswap-v3-base", "abi/NonFungiblePositionManager", "abis/NonFungiblePositionManager.json", "QmaxxqQ7xzbGDPWu184uoq2g5sofazB9B9tEDrpPjmRZ8q", 23334, "456c1726a11497a2b12e719111381203a1e96178ea4547af63e8947dc19490cd"),
    ("uniswap-v3-base", "abi/Pool", "abis/Pool.json", "QmQ5rynzbQYpebSAUFfnTYm9KDUumWYF5eQb9QRwRLPfwB", 19599, "11ea051e74b9a1bbfa9263dcd28dd4bd9df4898d7b02a79b7fcf545e732dcd4d"),
    ("uniswap-v3-base", "abi/TickLens", "abis/TickLens.json", "Qmcew9GU9kikcwYqemJ3x6UqXq5aMs2RBJxqUPeD5Ld5dF", 909, "f99008073f8d236d60d63fcc2b17d8f084e0f6e1ec02d0ec8fd8017a152a2252"),
    ("uniswap-v3-base", "mapping/Factory", "mappings/Factory.wasm", "QmUJsAqcUbk4CpQxvQyJ7igo5PQknNJgAj1cupLiW21Ejc", 148830, "2bbbd2960df7e0e3761b08fac5fbb2d966dcda0c017c5ff1f22107131b895708"),
    ("uniswap-v3-base", "mapping/NonFungiblePositionManager", "mappings/NonFungiblePositionManager.wasm", "Qmb3aYhcaVXLT3ouQypKqvC9b62SsdkQwznuabnhdmYLd5", 97112, "f79d4563dbe0e0cef8bf4ff28bfc2e84b6e89e18e4ae39262f5deac18f767e6e"),
    ("uniswap-v3-base", "mapping/Pool", "mappings/Pool.wasm", "QmS9917TbXgmD87MaTpE3asELcn86umKBLJbJUENnZasaz", 140823, "a4df46dfbea334093106d21c1eb9553a8bfa65eb6ff3262c3cff0286a7cf6e96"),
    ("uniswap-v3-base", "mapping/UniswapPool", "mappings/UniswapPool.wasm", "QmXExJr8roifEnTDRLWx8AvooEQ7EzdrWTnLi4qVfvFh9f", 41790, "e997b968a6e656d5c57af1016510ed8cdbf4ee980bc4446dd87f6c01d6dc261f"),
)

EXPECTED_WASM_EXPORTS = {
    ("pancakeswap-v3-bsc", "mapping/Factory"): (170, "65b3cd9491855f2343c3d26761ee557057a0aea6976ef9a26dce850d28e4547a", ["handlePoolCreated"]),
    ("pancakeswap-v3-bsc", "mapping/NonFungiblePositionManager"): (173, "4844a2787ab3aeb78fe4bcfb6eac8f6674515737ffa6f4fd7d228484fdc34cb3", ["handleIncreaseLiquidity", "handleDecreaseLiquidity", "handleTransfer"]),
    ("pancakeswap-v3-bsc", "mapping/Pool"): (174, "0d40fcc7551dc2809e2bd9dbc1cf7fabaeebf83431eabd0276eec243d583cbb6", ["handleInitialize", "handleMint", "handleBurn", "handleSwap", "handleCollectPool"]),
    ("pancakeswap-v3-bsc", "mapping/PancakeSwapPool"): (170, "c1ec6e69f4417cff0edf9fc282c0ec4da00928fe3df9fd7efb0375747ef6ce24", ["handleSetFeeProtocol"]),
    ("uniswap-v3-base", "mapping/Factory"): (172, "e2ff41cc934187de9c320eba6b220dde316ceefd098a77c0fe8129090848468f", ["handlePoolCreated"]),
    ("uniswap-v3-base", "mapping/NonFungiblePositionManager"): (175, "8cd6408cbc8d7b9af50b6eb543f1dcce83ad994f14947723aed1dbeba4e742aa", ["handleIncreaseLiquidity", "handleDecreaseLiquidity", "handleTransfer"]),
    ("uniswap-v3-base", "mapping/Pool"): (176, "167c34cbc4468a36cf7a0f87e1c5cfe0f40b7f92116a028a6d0167aa45a60977", ["handleInitialize", "handleMint", "handleBurn", "handleSwap", "handleCollectPool"]),
    ("uniswap-v3-base", "mapping/UniswapPool"): (172, "d2176ed3a0944f05c0229de38f6e996e14a34ad8ea3d549e99992c0983a72d29", ["handleSetFeeProtocol"]),
}

TARGET_EXPECTATIONS = {
    "pancakeswap-v3-bsc": {
        "chain": "bsc",
        "deployment": "QmQjVBdmgZdjHpQsXGSC5uryWLmPkkTAunHN2AnDApZBa3",
        "schema": "QmSY3DAk44RGNbywjXt8PznikJkNMpoNjM8UVde3Hnhocg",
        "manifest_semantic_sha256": "9c436b233668a744805d509c32a5c05ad3c698db7adca89eb9958e2cf035cfe0",
        "components": [
            ("data_source", "Factory", {"abi": "Factory", "address": "0x0BFbCF9fa4f9C56B0F40a671Ad40E0805A091865", "startBlock": 26956207}, "mapping/Factory"),
            ("data_source", "NonFungiblePositionManager", {"abi": "NonFungiblePositionManager", "address": "0x46A15B0b27311cedF172AB29E4f4766fbE7F4364", "startBlock": 26931961}, "mapping/NonFungiblePositionManager"),
            ("template", "Pool", {"abi": "Pool"}, "mapping/Pool"),
            ("template", "PancakeSwapPool", {"abi": "Pool"}, "mapping/PancakeSwapPool"),
        ],
        "handlers": {
            "Factory": [("handlePoolCreated", "PoolCreated(indexed address,indexed address,indexed uint24,int24,address)")],
            "NonFungiblePositionManager": [
                ("handleIncreaseLiquidity", "IncreaseLiquidity(indexed uint256,uint128,uint256,uint256)"),
                ("handleDecreaseLiquidity", "DecreaseLiquidity(indexed uint256,uint128,uint256,uint256)"),
                ("handleTransfer", "Transfer(indexed address,indexed address,indexed uint256)"),
            ],
            "Pool": [
                ("handleInitialize", "Initialize(uint160,int24)"),
                ("handleSetFeeProtocol", "SetFeeProtocol(uint32,uint32,uint32,uint32)"),
                ("handleCollectPool", "Collect(indexed address,address,indexed int24,indexed int24,uint128,uint128)"),
                ("handleSwap", "Swap(indexed address,indexed address,int256,int256,uint160,uint128,int24,uint128,uint128)"),
                ("handleMint", "Mint(address,indexed address,indexed int24,indexed int24,uint128,uint256,uint256)"),
                ("handleBurn", "Burn(indexed address,indexed int24,indexed int24,uint128,uint256,uint256)"),
            ],
            "PancakeSwapPool": [("handleSetFeeProtocol", "SetFeeProtocol(uint32,uint32,uint32,uint32)")],
        },
    },
    "uniswap-v3-base": {
        "chain": "base",
        "deployment": "QmawEzRNeDyaTgjPKb1eRrbyzxczgSHUYzvTMaMnN8jyuh",
        "schema": "QmVrng7WZwwCMkcGuay4yEbwepyPFDJjamwmsBcC18Ef2o",
        "manifest_semantic_sha256": "e3475a732c94ab2985ae39c8bf058b80e411b5d6fbaf3a9f2f9aee29792e19bc",
        "components": [
            ("data_source", "Factory", {"abi": "Factory", "address": "0x33128a8fc17869897dce68ed026d694621f6fdfd", "startBlock": 1371670}, "mapping/Factory"),
            ("data_source", "NonFungiblePositionManager", {"abi": "NonFungiblePositionManager", "address": "0x03a520b32c04bf3beef7beb72e919cf822ed34f1", "startBlock": 1371704}, "mapping/NonFungiblePositionManager"),
            ("template", "Pool", {"abi": "Pool"}, "mapping/Pool"),
            ("template", "UniswapPool", {"abi": "Pool"}, "mapping/UniswapPool"),
        ],
        "handlers": {
            "Factory": [("handlePoolCreated", "PoolCreated(indexed address,indexed address,indexed uint24,int24,address)")],
            "NonFungiblePositionManager": [
                ("handleIncreaseLiquidity", "IncreaseLiquidity(indexed uint256,uint128,uint256,uint256)"),
                ("handleDecreaseLiquidity", "DecreaseLiquidity(indexed uint256,uint128,uint256,uint256)"),
                ("handleTransfer", "Transfer(indexed address,indexed address,indexed uint256)"),
            ],
            "Pool": [
                ("handleInitialize", "Initialize(uint160,int24)"),
                ("handleCollectPool", "Collect(indexed address,address,indexed int24,indexed int24,uint128,uint128)"),
                ("handleSwap", "Swap(indexed address,indexed address,int256,int256,uint160,uint128,int24)"),
                ("handleMint", "Mint(address,indexed address,indexed int24,indexed int24,uint128,uint256,uint256)"),
                ("handleBurn", "Burn(indexed address,indexed int24,indexed int24,uint128,uint256,uint256)"),
            ],
            "UniswapPool": [("handleSetFeeProtocol", "SetFeeProtocol(uint8,uint8,uint8,uint8)")],
        },
    },
}


class VerificationError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def render(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def load_json(path: Path) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            require(key not in result, f"duplicate JSON key in {path}: {key}")
            result[key] = value
        return result

    with path.open() as handle:
        return json.load(handle, object_pairs_hook=reject_duplicates)


class UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(loader: UniqueKeyLoader, node: yaml.nodes.MappingNode, deep: bool = False) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            require(key not in result, f"duplicate YAML key: {key!r}")
        except TypeError as error:
            raise VerificationError(f"unhashable YAML key: {key!r}") from error
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def load_yaml_unique(path: Path) -> Any:
    with path.open() as handle:
        return yaml.load(handle, Loader=UniqueKeyLoader)


def _encode_varint(value: int) -> bytes:
    output = bytearray()
    while value > 0x7F:
        output.append((value & 0x7F) | 0x80)
        value >>= 7
    output.append(value)
    return bytes(output)


def _base58btc(payload: bytes) -> str:
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    number = int.from_bytes(payload, "big")
    encoded = ""
    while number:
        number, remainder = divmod(number, 58)
        encoded = alphabet[remainder] + encoded
    return "1" * (len(payload) - len(payload.lstrip(b"\0"))) + encoded


def unixfs_file_cidv0(payload: bytes) -> str:
    require(len(payload) <= 262_144, "CID verifier accepts one default IPFS chunk only")
    unixfs = b"\x08\x02\x12" + _encode_varint(len(payload)) + payload
    unixfs += b"\x18" + _encode_varint(len(payload))
    node = b"\x0a" + _encode_varint(len(unixfs)) + unixfs
    return _base58btc(b"\x12\x20" + hashlib.sha256(node).digest())


def cid_from_file(value: Any) -> str:
    require(isinstance(value, dict) and set(value) == {"/"}, f"invalid IPFS file object: {value!r}")
    location = value["/"]
    require(isinstance(location, str) and location.startswith("/ipfs/Qm"), f"invalid IPFS path: {location!r}")
    return location.removeprefix("/ipfs/")


def _read_uleb(payload: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    for _ in range(5):
        require(offset < len(payload), "truncated WebAssembly ULEB128")
        byte = payload[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, offset
        shift += 7
    raise VerificationError("oversized WebAssembly ULEB128")


def wasm_export_table(payload: bytes) -> list[dict[str, Any]]:
    require(payload[:8] == b"\0asm\x01\0\0\0", "mapping is not WebAssembly v1")
    offset = 8
    export_table: list[dict[str, Any]] | None = None
    while offset < len(payload):
        section_id = payload[offset]
        offset += 1
        section_size, offset = _read_uleb(payload, offset)
        section_end = offset + section_size
        require(section_end <= len(payload), "WebAssembly section exceeds payload")
        if section_id == 7:
            require(export_table is None, "duplicate WebAssembly export section")
            count, cursor = _read_uleb(payload, offset)
            export_table = []
            seen: set[str] = set()
            kinds = {0: "function", 1: "table", 2: "memory", 3: "global"}
            for _ in range(count):
                length, cursor = _read_uleb(payload, cursor)
                end = cursor + length
                require(end <= section_end, "truncated WebAssembly export name")
                try:
                    name = payload[cursor:end].decode("utf-8")
                except UnicodeDecodeError as error:
                    raise VerificationError("non-UTF8 WebAssembly export") from error
                cursor = end
                require(cursor < section_end, "truncated WebAssembly export kind")
                kind = payload[cursor]
                cursor += 1
                index, cursor = _read_uleb(payload, cursor)
                require(kind in kinds, f"unknown WebAssembly export kind: {kind}")
                require(name not in seen, f"duplicate WebAssembly export: {name}")
                seen.add(name)
                export_table.append({"name": name, "kind": kinds[kind], "index": index})
            require(cursor == section_end, "WebAssembly export section trailing bytes")
        offset = section_end
    require(offset == len(payload), "WebAssembly trailing bytes")
    require(export_table is not None, "WebAssembly export section missing")
    return export_table


def _canonical_abi_type(item: dict[str, Any]) -> str:
    kind = str(item.get("type"))
    if not kind.startswith("tuple"):
        return kind
    suffix = kind.removeprefix("tuple")
    components = item.get("components")
    require(isinstance(components, list), "tuple ABI input is missing components")
    return "(" + ",".join(_canonical_abi_type(component) for component in components) + ")" + suffix


def _abi_signature(entry: dict[str, Any]) -> str:
    name = entry.get("name", entry.get("type"))
    inputs = entry.get("inputs", [])
    require(isinstance(name, str) and isinstance(inputs, list), "invalid ABI entry")
    return f"{name}({','.join(_canonical_abi_type(item) for item in inputs)})"


def _abi_entry_identity(entry: dict[str, Any]) -> str:
    kind = entry.get("type")
    require(isinstance(kind, str), "ABI entry type is missing")
    return f"{kind}:{_abi_signature(entry)}"


def _abi_component_semantics(component: Any) -> dict[str, Any]:
    require(isinstance(component, dict), "ABI component must be an object")
    result: dict[str, Any] = {"type": _canonical_abi_type(component)}
    if "indexed" in component:
        result["indexed"] = bool(component["indexed"])
    return result


def _abi_entry_semantics(entry: dict[str, Any]) -> dict[str, Any]:
    kind = entry["type"]
    result: dict[str, Any] = {"type": kind}
    if "name" in entry:
        require(isinstance(entry["name"], str), "ABI entry name must be a string")
        result["name"] = entry["name"]
    if "inputs" in entry:
        require(isinstance(entry["inputs"], list), "ABI entry inputs must be a list")
        result["inputs"] = [_abi_component_semantics(component) for component in entry["inputs"]]
    if "outputs" in entry:
        require(isinstance(entry["outputs"], list), "ABI entry outputs must be a list")
        result["outputs"] = [_abi_component_semantics(component) for component in entry["outputs"]]
    for field in ("stateMutability", "anonymous", "payable", "constant"):
        if field in entry:
            result[field] = entry[field]
    return result


def _abi_entry_catalog(value: Any) -> tuple[list[str], dict[str, dict[str, Any]]]:
    require(isinstance(value, list), "ABI must be a JSON array")
    order: list[str] = []
    catalog: dict[str, dict[str, Any]] = {}
    for entry in value:
        require(isinstance(entry, dict), "ABI entry must be an object")
        identity = _abi_entry_identity(entry)
        require(identity not in catalog, f"duplicate ABI entry identity: {identity}")
        order.append(identity)
        catalog[identity] = entry
    return order, catalog


def _json_pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _json_field_differences(left: Any, right: Any, path: str = "") -> list[dict[str, Any]]:
    if canonical_bytes(left) == canonical_bytes(right):
        return []
    if isinstance(left, dict) and isinstance(right, dict):
        result = []
        for key in sorted(set(left) | set(right)):
            child_path = f"{path}/{_json_pointer_token(key)}"
            if key not in left or key not in right:
                result.append({
                    "path": child_path,
                    "pancakeswap_present": key in left,
                    "base_present": key in right,
                    **({"pancakeswap": left[key]} if key in left else {}),
                    **({"base": right[key]} if key in right else {}),
                })
            else:
                result.extend(_json_field_differences(left[key], right[key], child_path))
        return result
    if isinstance(left, list) and isinstance(right, list):
        result = []
        for index in range(max(len(left), len(right))):
            child_path = f"{path}/{index}"
            if index >= len(left) or index >= len(right):
                result.append({
                    "path": child_path,
                    "pancakeswap_present": index < len(left),
                    "base_present": index < len(right),
                    **({"pancakeswap": left[index]} if index < len(left) else {}),
                    **({"base": right[index]} if index < len(right) else {}),
                })
            else:
                result.extend(_json_field_differences(left[index], right[index], child_path))
        return result
    return [{
        "path": path or "/",
        "pancakeswap_present": True,
        "base_present": True,
        "pancakeswap": left,
        "base": right,
    }]


def _exclusive_abi_entries(
    identities: set[str],
    catalog: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "identity": identity,
            "canonical_sha256": canonical_sha256(catalog[identity]),
            "entry": catalog[identity],
        }
        for identity in sorted(identities)
    ]


def abi_summary(value: Any) -> dict[str, Any]:
    require(isinstance(value, list), "ABI must be a JSON array")
    require(all(isinstance(item, dict) and isinstance(item.get("type"), str) for item in value), "ABI entries must be objects with a type")
    counts = Counter(str(item["type"]) for item in value)
    events = []
    functions = []
    for item in value:
        if item["type"] == "event":
            inputs = item.get("inputs", [])
            require(isinstance(inputs, list), "event ABI inputs must be a list")
            events.append({
                "signature": _abi_signature(item),
                "indexed": [bool(component.get("indexed")) for component in inputs],
                "anonymous": bool(item.get("anonymous")),
            })
        elif item["type"] == "function":
            functions.append(_abi_signature(item))
    return {
        "entry_count": len(value),
        "entry_type_counts": dict(sorted(counts.items())),
        "canonical_sha256": canonical_sha256(value),
        "events": events,
        "function_signatures": functions,
    }


def verify_artifacts(root: Path) -> tuple[list[dict[str, Any]], dict[str, dict[str, dict[str, Any]]]]:
    require(len(ARTIFACT_ROWS) == 26, "artifact lock must contain exactly 26 records")
    expected_paths = {
        Path("messari-v3/reference") / target / relative
        for target, _, relative, _, _, _ in ARTIFACT_ROWS
    }
    actual_paths = {
        path.relative_to(root)
        for path in (root / "messari-v3/reference").rglob("*")
        if path.is_file()
    }
    require(actual_paths == expected_paths, "Messari V3 retained artifact path closure drift")
    records: list[dict[str, Any]] = []
    by_target: dict[str, dict[str, dict[str, Any]]] = {target: {} for target in TARGET_ORDER}
    for target, role, relative, cid, expected_bytes, expected_sha in ARTIFACT_ROWS:
        require(target in by_target and role not in by_target[target], f"duplicate artifact role: {target}/{role}")
        vendored = Path("messari-v3/reference") / target / relative
        resolved = (root / vendored).resolve()
        require(root.resolve() in resolved.parents, f"artifact escapes root: {vendored}")
        payload = resolved.read_bytes()
        require(len(payload) == expected_bytes, f"artifact byte count drift: {target}/{role}")
        require(hashlib.sha256(payload).hexdigest() == expected_sha, f"artifact SHA-256 drift: {target}/{role}")
        require(unixfs_file_cidv0(payload) == cid, f"artifact CIDv0 drift: {target}/{role}")
        record: dict[str, Any] = {
            "target": target,
            "role": role,
            "cid": cid,
            "bytes": expected_bytes,
            "sha256": expected_sha,
            "vendored_path": vendored.as_posix(),
        }
        if role.startswith("abi/"):
            record["abi"] = abi_summary(load_json(resolved))
        elif role.startswith("mapping/"):
            exports = wasm_export_table(payload)
            function_exports = [item["name"] for item in exports if item["kind"] == "function"]
            handler_exports = [name for name in function_exports if name.startswith("handle")]
            export_table_sha256 = canonical_sha256(exports)
            expected_count, expected_table_sha256, expected_handlers = EXPECTED_WASM_EXPORTS[(target, role)]
            require(len(exports) == expected_count, f"WebAssembly export count drift: {target}/{role}")
            require(export_table_sha256 == expected_table_sha256, f"WebAssembly export table drift: {target}/{role}")
            require(handler_exports == expected_handlers, f"WebAssembly handler export order drift: {target}/{role}")
            record.update({
                "export_count": len(exports),
                "export_table_sha256": export_table_sha256,
                "function_exports": function_exports,
                "handler_exports": handler_exports,
                "export_table": exports,
            })
        by_target[target][role] = record
        records.append(record)
    require(all(len(by_target[target]) == 13 for target in TARGET_ORDER), "each target must retain 13 artifacts")
    require(set(EXPECTED_WASM_EXPORTS) == {
        (target, role)
        for target in TARGET_ORDER
        for role in by_target[target]
        if role.startswith("mapping/")
    }, "WebAssembly export expectation closure drift")
    return records, by_target


def normalize_event(value: Any) -> str:
    require(isinstance(value, str), "manifest event signature must be a string")
    return re.sub(r"\s+", " ", value).strip()


def manifest_profile(target: str, manifest: Any, artifacts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    expectation = TARGET_EXPECTATIONS[target]
    require(isinstance(manifest, dict), f"{target} manifest must be a mapping")
    require(canonical_sha256(manifest) == expectation["manifest_semantic_sha256"], f"{target} manifest semantic projection drift")
    require(set(manifest) == {"dataSources", "repository", "schema", "specVersion", "templates"}, f"{target} manifest root keys drift")
    require(manifest["repository"] == "https://github.com/messari/subgraphs", f"{target} repository drift")
    require(manifest["specVersion"] == "0.0.4", f"{target} deployed specVersion drift")
    require(cid_from_file(manifest["schema"]["file"]) == expectation["schema"], f"{target} schema CID drift")
    data_sources = manifest["dataSources"]
    templates = manifest["templates"]
    require(isinstance(data_sources, list) and len(data_sources) == 2, f"{target} data-source count drift")
    require(isinstance(templates, list) and len(templates) == 2, f"{target} template count drift")
    components: list[dict[str, Any]] = []
    referenced_cids = {expectation["schema"]}
    expected_components = expectation["components"]
    for index, (kind, name, source, mapping_role) in enumerate(expected_components):
        component = data_sources[index] if kind == "data_source" else templates[index - len(data_sources)]
        require(set(component) == {"kind", "mapping", "name", "network", "source"}, f"{target}/{name} component keys drift")
        require(component["kind"] == "ethereum/contract" and component["name"] == name, f"{target}/{name} identity drift")
        require(component["network"] == expectation["chain"] and component["source"] == source, f"{target}/{name} source drift")
        mapping = component["mapping"]
        require(isinstance(mapping, dict) and set(mapping) == {"abis", "apiVersion", "entities", "eventHandlers", "file", "kind", "language"}, f"{target}/{name} mapping keys drift")
        require(mapping["apiVersion"] == "0.0.6", f"{target}/{name} apiVersion drift")
        require(mapping["kind"] == "ethereum/events" and mapping["language"] == "wasm/assemblyscript", f"{target}/{name} runtime drift")
        mapping_cid = cid_from_file(mapping["file"])
        require(mapping_cid == artifacts[mapping_role]["cid"], f"{target}/{name} mapping CID drift")
        abi_bindings = []
        for entry in mapping["abis"]:
            require(isinstance(entry, dict) and set(entry) == {"file", "name"}, f"{target}/{name} ABI binding shape drift")
            abi_cid = cid_from_file(entry["file"])
            require(any(record["cid"] == abi_cid and role.startswith("abi/") for role, record in artifacts.items()), f"{target}/{name} references an unretained ABI")
            referenced_cids.add(abi_cid)
            abi_bindings.append({"name": entry["name"], "cid": abi_cid})
        source_abi = component["source"]["abi"]
        source_bindings = [entry for entry in abi_bindings if entry["name"] == source_abi]
        require(len(source_bindings) == 1, f"{target}/{name} source ABI alias does not resolve exact-case")
        source_abi_cid = source_bindings[0]["cid"]
        source_abi_records = [
            record
            for role, record in artifacts.items()
            if role.startswith("abi/") and record["cid"] == source_abi_cid
        ]
        require(len(source_abi_records) == 1, f"{target}/{name} source ABI artifact resolution drift")
        handlers = [{"handler": item["handler"], "event": normalize_event(item["event"])} for item in mapping["eventHandlers"]]
        expected_handlers = [{"handler": handler, "event": event} for handler, event in expectation["handlers"][name]]
        require(handlers == expected_handlers, f"{target}/{name} handler order or signature drift")
        source_events = {
            event["signature"]
            for event in source_abi_records[0]["abi"]["events"]
        }
        require(
            all(item["event"].replace("indexed ", "") in source_events for item in handlers),
            f"{target}/{name} declares an event absent from its exact source ABI",
        )
        referenced_cids.add(mapping_cid)
        exports = artifacts[mapping_role]["handler_exports"]
        declared = [item["handler"] for item in handlers]
        components.append({
            "kind": kind,
            "name": name,
            "network": component["network"],
            "source": component["source"],
            "mapping_role": mapping_role,
            "mapping_cid": mapping_cid,
            "mapping_api_version": mapping["apiVersion"],
            "mapping_kind": mapping["kind"],
            "mapping_language": mapping["language"],
            "abi_bindings": abi_bindings,
            "source_abi_binding": {
                "alias": source_abi,
                "cid": source_abi_cid,
                "exact_case_resolved": True,
                "all_declared_events_present": True,
            },
            "entities": mapping["entities"],
            "event_handlers": handlers,
            "handler_exports": exports,
            "missing_declared_handler_exports": [handler for handler in declared if handler not in exports],
            "undeclared_handler_exports": [handler for handler in exports if handler not in declared],
        })
    retained_non_deployment_cids = {record["cid"] for role, record in artifacts.items() if role != "deployment"}
    require(referenced_cids == retained_non_deployment_cids, f"{target} retained/referenced artifact closure drift")
    primary = components[2]
    expected_primary_entities = [
        "LiqudityPool", "Token", "Deposit", "Withdraw", "Swap", "LiquidityPool",
        "DexAmmProtocol", "Token", "UsageMetricsDailySnapshot", "FinancialsDailySnapshot",
        "PoolDailySnapshot", "_PricesUSD", "_Account", "_DailyActiveAccount",
        "_TokenTracker", "_LiquidityPoolAmount",
    ]
    require(primary["entities"] == expected_primary_entities, f"{target} primary Pool entity metadata drift")
    require(primary["entities"].count("Token") == 2 and "LiqudityPool" in primary["entities"], f"{target} template quirks normalized")
    require(components[3]["entities"] == ["LiqudityPool"], f"{target} fee-template entity metadata drift")
    if target == "pancakeswap-v3-bsc":
        require(primary["missing_declared_handler_exports"] == ["handleSetFeeProtocol"], "BSC primary Pool missing-export boundary drift")
        require(primary["handler_exports"] == ["handleInitialize", "handleMint", "handleBurn", "handleSwap", "handleCollectPool"], "BSC primary Pool export order drift")
        require(components[3]["mapping_cid"] == "QmZh9pwyqnVEknPgTWraJweuyy1qbwzhA2rrSq43xmdgHL" and components[3]["handler_exports"] == ["handleSetFeeProtocol"], "BSC fee mapping export drift")
    else:
        require(primary["missing_declared_handler_exports"] == [], "Base primary Pool invented missing export")
        require(components[3]["handler_exports"] == ["handleSetFeeProtocol"], "Base fee mapping export drift")
    return {
        "deployment_cid": expectation["deployment"],
        "schema_cid": expectation["schema"],
        "chain": expectation["chain"],
        "repository": manifest["repository"],
        "spec_version": manifest["specVersion"],
        "manifest_semantic_sha256": canonical_sha256(manifest),
        "components": components,
    }


def _normalized_directives(value: str) -> list[str]:
    return [re.sub(r"\s+", "", item) for item in re.findall(r"@[A-Za-z_][A-Za-z0-9_]*(?:\([^)]*\))?", value)]


def schema_profile(path: Path) -> dict[str, Any]:
    text = path.read_text()
    version_match = re.search(r"^# Version: ([0-9.]+)$", text, re.MULTILINE)
    require(version_match is not None, "schema version marker missing")
    entities: dict[str, dict[str, Any]] = {}
    current: str | None = None
    declaration = re.compile(r"^type\s+([_A-Za-z][_0-9A-Za-z]*)(.*?)\{\s*$")
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        match = declaration.match(line)
        if match and "@entity" in match.group(2):
            current = match.group(1)
            require(current not in entities, f"duplicate schema entity: {current}")
            entities[current] = {"directives": _normalized_directives(match.group(2)), "fields": []}
            continue
        if current and line == "}":
            current = None
            continue
        if current:
            field = re.match(r"^([_A-Za-z][_0-9A-Za-z]*)\s*:\s*([\[\]!_A-Za-z0-9]+)", line)
            if field:
                name, field_type = field.groups()
                require(all(item["name"] != name for item in entities[current]["fields"]), f"duplicate schema field: {current}.{name}")
                entities[current]["fields"].append({"name": name, "type": field_type})
    enum_match = re.search(r"enum Network\s*\{(.*?)\n\}", text, re.DOTALL)
    require(enum_match is not None, "Network enum missing")
    network_values = []
    for raw_line in enum_match.group(1).splitlines():
        value = raw_line.split("#", 1)[0].strip()
        if value:
            require(re.fullmatch(r"[_A-Z][_A-Z0-9]*", value) is not None, f"invalid Network enum value: {value}")
            network_values.append(value)
    field_catalog = {name: item["fields"] for name, item in entities.items()}
    declared_type_names = sorted(set(re.findall(
        r"^(?:type|interface|enum|scalar|input|union)\s+([_A-Za-z][_0-9A-Za-z]*)",
        text,
        re.MULTILINE,
    )))
    return {
        "schema_version": version_match.group(1),
        "entity_count": len(entities),
        "field_count": sum(len(item["fields"]) for item in entities.values()),
        "field_catalog_sha256": canonical_sha256(field_catalog),
        "entity_directives_sha256": canonical_sha256({name: item["directives"] for name, item in entities.items()}),
        "network_values": network_values,
        "declared_type_names": declared_type_names,
        "entities": entities,
    }


def verify_schema_pair(profiles: dict[str, dict[str, Any]]) -> dict[str, Any]:
    bsc = profiles["pancakeswap-v3-bsc"]
    base = profiles["uniswap-v3-base"]
    for target, profile, version in (("pancakeswap-v3-bsc", bsc, "4.0.0"), ("uniswap-v3-base", base, "4.0.1")):
        require(profile["schema_version"] == version, f"{target} schema version drift")
        require((profile["entity_count"], profile["field_count"]) == (24, 388), f"{target} schema denominator drift")
    require(bsc["field_catalog_sha256"] == base["field_catalog_sha256"] == "76ac4b0b03cb16e9cf6112335feff2a94d2a559132f8895842c9f5a5e5678840", "schema field catalog drift")
    directive_diff = {}
    for entity in sorted(set(bsc["entities"]) | set(base["entities"])):
        left = bsc["entities"].get(entity, {}).get("directives")
        right = base["entities"].get(entity, {}).get("directives")
        if left != right:
            directive_diff[entity] = {"pancakeswap-v3-bsc": left, "uniswap-v3-base": right}
    require(directive_diff == {
        "PositionSnapshot": {
            "pancakeswap-v3-bsc": ["@entity(immutable:true)", "@regularPolling"],
            "uniswap-v3-base": ["@entity(immutable:true)", "@hourlySnapshot"],
        }
    }, "schema directive diff drift")
    require(sorted(set(base["network_values"]) - set(bsc["network_values"])) == ["BASE"], "Network.BASE addition drift")
    require(set(bsc["network_values"]) - set(base["network_values"]) == set(), "unexpected BSC-only Network values")
    return {
        "field_catalog_identical": True,
        "field_catalog_sha256": bsc["field_catalog_sha256"],
        "schema_versions": {"pancakeswap-v3-bsc": "4.0.0", "uniswap-v3-base": "4.0.1"},
        "base_only_network_values": ["BASE"],
        "entity_directive_differences": directive_diff,
    }


def _signature_set(summary: dict[str, Any], key: str) -> set[str]:
    if key == "events":
        return {item["signature"] for item in summary[key]}
    return set(summary[key])


def _full_abi_entry_diff(left_value: Any, right_value: Any) -> dict[str, Any]:
    left_order, left = _abi_entry_catalog(left_value)
    right_order, right = _abi_entry_catalog(right_value)
    shared_metadata_differences = []
    shared_semantic_differences = []
    for identity in sorted(set(left) & set(right)):
        left_sha = canonical_sha256(left[identity])
        right_sha = canonical_sha256(right[identity])
        if left_sha == right_sha:
            continue
        left_semantics = _abi_entry_semantics(left[identity])
        right_semantics = _abi_entry_semantics(right[identity])
        semantic_equal = canonical_bytes(left_semantics) == canonical_bytes(right_semantics)
        shared_metadata_differences.append({
            "identity": identity,
            "pancakeswap_canonical_sha256": left_sha,
            "base_canonical_sha256": right_sha,
            "semantic_equal": semantic_equal,
            "field_differences": _json_field_differences(left[identity], right[identity]),
        })
        if not semantic_equal:
            shared_semantic_differences.append({
                "identity": identity,
                "pancakeswap": left_semantics,
                "base": right_semantics,
                "field_differences": _json_field_differences(left[identity], right[identity]),
            })
    return {
        "entry_order_sha256": {
            "pancakeswap-v3-bsc": canonical_sha256(left_order),
            "uniswap-v3-base": canonical_sha256(right_order),
        },
        "entry_identities_only_pancakeswap": sorted(set(left) - set(right)),
        "entry_identities_only_base": sorted(set(right) - set(left)),
        "entries_only_pancakeswap": _exclusive_abi_entries(set(left) - set(right), left),
        "entries_only_base": _exclusive_abi_entries(set(right) - set(left), right),
        "shared_identity_metadata_differences": shared_metadata_differences,
        "shared_identity_semantic_differences": shared_semantic_differences,
    }


def build_abi_diff(root: Path, by_target: dict[str, dict[str, dict[str, Any]]]) -> dict[str, Any]:
    bsc = by_target["pancakeswap-v3-bsc"]
    base = by_target["uniswap-v3-base"]
    names = ["ERC20", "ERC20NameBytes", "ERC20SymbolBytes", "Factory", "NonFungiblePositionManager", "Pool", "TickLens"]
    shared = []
    differing: dict[str, Any] = {}
    for name in names:
        left = bsc[f"abi/{name}"]["abi"]
        right = base[f"abi/{name}"]["abi"]
        if left["canonical_sha256"] == right["canonical_sha256"]:
            shared.append(name)
            continue
        left_value = load_json(root / bsc[f"abi/{name}"]["vendored_path"])
        right_value = load_json(root / base[f"abi/{name}"]["vendored_path"])
        differing[name] = {
            "pancakeswap_entry_count": left["entry_count"],
            "base_entry_count": right["entry_count"],
            "pancakeswap_canonical_sha256": left["canonical_sha256"],
            "base_canonical_sha256": right["canonical_sha256"],
            "events_only_pancakeswap": sorted(_signature_set(left, "events") - _signature_set(right, "events")),
            "events_only_base": sorted(_signature_set(right, "events") - _signature_set(left, "events")),
            "functions_only_pancakeswap": sorted(_signature_set(left, "function_signatures") - _signature_set(right, "function_signatures")),
            "functions_only_base": sorted(_signature_set(right, "function_signatures") - _signature_set(left, "function_signatures")),
            **_full_abi_entry_diff(left_value, right_value),
        }
    require(shared == ["ERC20", "ERC20NameBytes", "ERC20SymbolBytes", "TickLens"], "shared ABI set drift")
    require(list(differing) == ["Factory", "NonFungiblePositionManager", "Pool"], "differing ABI set drift")
    require(differing["Factory"]["events_only_pancakeswap"] == ["FeeAmountExtraInfoUpdated(uint24,bool,bool)", "SetLmPoolDeployer(address)", "WhiteListAdded(address,bool)"], "Factory event diff drift")
    require(differing["Pool"]["events_only_pancakeswap"] == ["SetFeeProtocol(uint32,uint32,uint32,uint32)", "SetLmPoolEvent(address)", "Swap(address,address,int256,int256,uint160,uint128,int24,uint128,uint128)"], "Pool BSC event diff drift")
    require(differing["Pool"]["events_only_base"] == ["SetFeeProtocol(uint8,uint8,uint8,uint8)", "Swap(address,address,int256,int256,uint160,uint128,int24)"], "Pool Base event diff drift")
    expected_entry_ledgers = {
        "Factory": {
            "entry_identities_only_pancakeswap": [
                "constructor:constructor(address)",
                "event:FeeAmountExtraInfoUpdated(uint24,bool,bool)",
                "event:SetLmPoolDeployer(address)",
                "event:WhiteListAdded(address,bool)",
                "function:collectProtocol(address,address,uint128,uint128)",
                "function:feeAmountTickSpacingExtraInfo(uint24)",
                "function:lmPoolDeployer()",
                "function:poolDeployer()",
                "function:setFeeAmountExtraInfo(uint24,bool,bool)",
                "function:setFeeProtocol(address,uint32,uint32)",
                "function:setLmPool(address,address)",
                "function:setLmPoolDeployer(address)",
                "function:setWhiteListAddress(address,bool)",
            ],
            "entry_identities_only_base": [],
            "metadata_difference_identities": [
                "function:feeAmountTickSpacing(uint24)",
                "function:getPool(address,address,uint24)",
            ],
            "semantic_difference_identities": [],
            "field_difference_paths": {
                "function:feeAmountTickSpacing(uint24)": ["/inputs/0/name"],
                "function:getPool(address,address,uint24)": [
                    "/inputs/0/name",
                    "/inputs/1/name",
                    "/inputs/2/name",
                    "/outputs/0/name",
                ],
            },
        },
        "NonFungiblePositionManager": {
            "entry_identities_only_pancakeswap": [
                "constructor:constructor(address,address,address,address)",
                "function:collect((uint256,address,uint128,uint128))",
                "function:decreaseLiquidity((uint256,uint128,uint256,uint256,uint256))",
                "function:deployer()",
                "function:increaseLiquidity((uint256,uint256,uint256,uint256,uint256,uint256))",
                "function:pancakeV3MintCallback(uint256,uint256,bytes)",
                "function:refundETH()",
            ],
            "entry_identities_only_base": [
                "constructor:constructor(address,address,address)",
                "function:collect(uint256,address,uint128,uint128)",
                "function:decreaseLiquidity(uint256,uint128,uint256,uint256,uint256)",
                "function:increaseLiquidity(uint256,uint256,uint256,uint256,uint256,uint256)",
                "function:uniswapV3MintCallback(uint256,uint256,bytes)",
            ],
            "metadata_difference_identities": [
                "function:createAndInitializePoolIfNecessary(address,address,uint24,uint160)",
            ],
            "semantic_difference_identities": [],
            "field_difference_paths": {
                "function:createAndInitializePoolIfNecessary(address,address,uint24,uint160)": [
                    "/inputs/0/name",
                    "/inputs/1/name",
                ],
            },
        },
        "Pool": {
            "entry_identities_only_pancakeswap": [
                "event:SetFeeProtocol(uint32,uint32,uint32,uint32)",
                "event:SetLmPoolEvent(address)",
                "event:Swap(address,address,int256,int256,uint160,uint128,int24,uint128,uint128)",
                "function:lmPool()",
                "function:setFeeProtocol(uint32,uint32)",
                "function:setLmPool(address)",
            ],
            "entry_identities_only_base": [
                "event:SetFeeProtocol(uint8,uint8,uint8,uint8)",
                "event:Swap(address,address,int256,int256,uint160,uint128,int24)",
                "function:setFeeProtocol(uint8,uint8)",
            ],
            "metadata_difference_identities": [
                "event:Burn(address,int24,int24,uint128,uint256,uint256)",
                "function:observations(uint256)",
                "function:positions(bytes32)",
                "function:slot0()",
                "function:tickBitmap(int16)",
                "function:ticks(int24)",
            ],
            "semantic_difference_identities": ["function:slot0()"],
            "field_difference_paths": {
                "event:Burn(address,int24,int24,uint128,uint256,uint256)": [
                    "/inputs/4/internalType",
                ],
                "function:observations(uint256)": ["/inputs/0/name"],
                "function:positions(bytes32)": [
                    "/inputs/0/name",
                    "/outputs/0/name",
                ],
                "function:slot0()": [
                    "/outputs/5/internalType",
                    "/outputs/5/type",
                ],
                "function:tickBitmap(int16)": ["/inputs/0/name"],
                "function:ticks(int24)": ["/inputs/0/name"],
            },
        },
    }
    for name, expected in expected_entry_ledgers.items():
        observed = differing[name]
        require(observed["entry_identities_only_pancakeswap"] == expected["entry_identities_only_pancakeswap"], f"{name} full-entry BSC-only ABI diff drift")
        require(observed["entry_identities_only_base"] == expected["entry_identities_only_base"], f"{name} full-entry Base-only ABI diff drift")
        require([item["identity"] for item in observed["entries_only_pancakeswap"]] == expected["entry_identities_only_pancakeswap"], f"{name} full BSC-only ABI entry projection drift")
        require([item["identity"] for item in observed["entries_only_base"]] == expected["entry_identities_only_base"], f"{name} full Base-only ABI entry projection drift")
        require([item["identity"] for item in observed["shared_identity_metadata_differences"]] == expected["metadata_difference_identities"], f"{name} same-identity ABI metadata diff drift")
        require([item["identity"] for item in observed["shared_identity_semantic_differences"]] == expected["semantic_difference_identities"], f"{name} same-identity ABI semantic diff drift")
        require(
            {
                item["identity"]: [field["path"] for field in item["field_differences"]]
                for item in observed["shared_identity_metadata_differences"]
            } == expected["field_difference_paths"],
            f"{name} exact ABI field-difference path drift",
        )
    return {"byte_and_semantic_identical_abis": shared, "differing_abis": differing}


def build_wasm_diff(by_target: dict[str, dict[str, dict[str, Any]]]) -> dict[str, Any]:
    bsc = by_target["pancakeswap-v3-bsc"]
    base = by_target["uniswap-v3-base"]
    pairs = (
        ("Factory", "mapping/Factory", "mapping/Factory"),
        ("NonFungiblePositionManager", "mapping/NonFungiblePositionManager", "mapping/NonFungiblePositionManager"),
        ("primary_pool", "mapping/Pool", "mapping/Pool"),
        ("fee_only_pool", "mapping/PancakeSwapPool", "mapping/UniswapPool"),
    )
    expected_base_only = [
        {"name": "TypeId.CosmosMessageData", "kind": "global"},
        {"name": "TypeId.CosmosTransactionContext", "kind": "global"},
    ]
    expected_index_differences = {
        "Factory": [
            ("TypeId.ArweaveBlock", "global", 183, 185),
            ("TypeId.ArweaveProofOfAccess", "global", 184, 186),
            ("TypeId.ArweaveTag", "global", 185, 187),
            ("TypeId.ArweaveTagArray", "global", 186, 188),
            ("TypeId.ArweaveTransaction", "global", 187, 189),
            ("TypeId.ArweaveTransactionArray", "global", 188, 190),
            ("TypeId.ArweaveTransactionWithBlockPtr", "global", 189, 191),
            ("__rtti_base", "global", 190, 192),
        ],
        "NonFungiblePositionManager": [
            ("TypeId.ArweaveBlock", "global", 176, 178),
            ("TypeId.ArweaveProofOfAccess", "global", 177, 179),
            ("TypeId.ArweaveTag", "global", 178, 180),
            ("TypeId.ArweaveTagArray", "global", 179, 181),
            ("TypeId.ArweaveTransaction", "global", 180, 182),
            ("TypeId.ArweaveTransactionArray", "global", 181, 183),
            ("TypeId.ArweaveTransactionWithBlockPtr", "global", 182, 184),
            ("__collect", "function", 138, 136),
            ("__rtti_base", "global", 183, 185),
            ("__unpin", "function", 137, 135),
            ("_start", "function", 143, 141),
            ("allocate", "function", 136, 134),
            ("handleDecreaseLiquidity", "function", 133, 131),
            ("handleIncreaseLiquidity", "function", 132, 130),
            ("handleTransfer", "function", 134, 132),
            ("id_of_type", "function", 135, 133),
        ],
        "primary_pool": [
            ("TypeId.ArweaveBlock", "global", 177, 179),
            ("TypeId.ArweaveProofOfAccess", "global", 178, 180),
            ("TypeId.ArweaveTag", "global", 179, 181),
            ("TypeId.ArweaveTagArray", "global", 180, 182),
            ("TypeId.ArweaveTransaction", "global", 181, 183),
            ("TypeId.ArweaveTransactionArray", "global", 182, 184),
            ("TypeId.ArweaveTransactionWithBlockPtr", "global", 183, 185),
            ("__rtti_base", "global", 184, 186),
        ],
        "fee_only_pool": [
            ("TypeId.ArweaveBlock", "global", 169, 171),
            ("TypeId.ArweaveProofOfAccess", "global", 170, 172),
            ("TypeId.ArweaveTag", "global", 171, 173),
            ("TypeId.ArweaveTagArray", "global", 172, 174),
            ("TypeId.ArweaveTransaction", "global", 173, 175),
            ("TypeId.ArweaveTransactionArray", "global", 174, 176),
            ("TypeId.ArweaveTransactionWithBlockPtr", "global", 175, 177),
            ("__collect", "function", 48, 49),
            ("__rtti_base", "global", 176, 178),
            ("__unpin", "function", 47, 48),
            ("_start", "function", 50, 51),
            ("allocate", "function", 46, 47),
            ("handleSetFeeProtocol", "function", 44, 45),
            ("id_of_type", "function", 45, 46),
        ],
    }
    result: dict[str, Any] = {}
    observed_roles: set[tuple[str, str]] = set()
    for name, bsc_role, base_role in pairs:
        left = bsc[bsc_role]
        right = base[base_role]
        left_catalog = {item["name"]: item for item in left["export_table"]}
        right_catalog = {item["name"]: item for item in right["export_table"]}
        only_bsc = [
            {"name": export, "kind": left_catalog[export]["kind"]}
            for export in sorted(set(left_catalog) - set(right_catalog))
        ]
        only_base = [
            {"name": export, "kind": right_catalog[export]["kind"]}
            for export in sorted(set(right_catalog) - set(left_catalog))
        ]
        kind_differences = [
            {
                "name": export,
                "pancakeswap_kind": left_catalog[export]["kind"],
                "base_kind": right_catalog[export]["kind"],
            }
            for export in sorted(set(left_catalog) & set(right_catalog))
            if left_catalog[export]["kind"] != right_catalog[export]["kind"]
        ]
        index_differences = [
            {
                "name": export,
                "kind": left_catalog[export]["kind"],
                "pancakeswap_index": left_catalog[export]["index"],
                "base_index": right_catalog[export]["index"],
            }
            for export in sorted(set(left_catalog) & set(right_catalog))
            if left_catalog[export]["index"] != right_catalog[export]["index"]
        ]
        require(only_bsc == [], f"{name} unexpected BSC-only WebAssembly export")
        require(only_base == expected_base_only, f"{name} Base-only Cosmos TypeId export drift")
        require(kind_differences == [], f"{name} shared WebAssembly export kind drift")
        require(
            [
                (item["name"], item["kind"], item["pancakeswap_index"], item["base_index"])
                for item in index_differences
            ] == expected_index_differences[name],
            f"{name} shared WebAssembly export index diff drift",
        )
        require(left["handler_exports"] == right["handler_exports"], f"{name} paired handler export drift")
        observed_roles.add((bsc_role, base_role))
        result[name] = {
            "pancakeswap_mapping_role": bsc_role,
            "base_mapping_role": base_role,
            "pancakeswap_cid": left["cid"],
            "base_cid": right["cid"],
            "pancakeswap_sha256": left["sha256"],
            "base_sha256": right["sha256"],
            "pancakeswap_export_count": left["export_count"],
            "base_export_count": right["export_count"],
            "pancakeswap_export_table_sha256": left["export_table_sha256"],
            "base_export_table_sha256": right["export_table_sha256"],
            "exports_only_pancakeswap": only_bsc,
            "exports_only_base": only_base,
            "shared_export_kind_differences": kind_differences,
            "shared_export_index_differences": index_differences,
            "handler_exports": left["handler_exports"],
            "handler_exports_identical": True,
        }
    require(
        observed_roles == {
            ("mapping/Factory", "mapping/Factory"),
            ("mapping/NonFungiblePositionManager", "mapping/NonFungiblePositionManager"),
            ("mapping/Pool", "mapping/Pool"),
            ("mapping/PancakeSwapPool", "mapping/UniswapPool"),
        },
        "paired WebAssembly mapping-role closure drift",
    )
    return {
        "pairing_complete": True,
        "base_only_cosmos_type_id_globals": expected_base_only,
        "runtime_equivalence_claimed": False,
        "pairs": result,
    }


def verify_bindings(root: Path) -> list[dict[str, Any]]:
    expected_paths = {Path(value["path"]) for value in EXPECTED_BINDINGS.values()}
    actual_paths = {
        path.relative_to(root)
        for path in (root / "messari-v3").glob("Qm*.yaml")
        if path.is_file()
    }
    require(actual_paths == expected_paths, "Messari V3 target binding path closure drift")
    result = []
    for target in TARGET_ORDER:
        expected = EXPECTED_BINDINGS[target]
        path = root / expected["path"]
        payload = path.read_bytes()
        require(len(payload) == expected["bytes"], f"{target} binding byte count drift")
        require(hashlib.sha256(payload).hexdigest() == expected["sha256"], f"{target} binding SHA-256 drift")
        require(load_yaml_unique(path) == expected["value"], f"{target} binding semantic drift")
        result.append({"target": target, "path": expected["path"], "bytes": expected["bytes"], "sha256": expected["sha256"], "value": expected["value"]})
    return result


def verify_source_document(root: Path) -> None:
    payload = (root / SOURCE_PROVENANCE_PATH).read_bytes()
    require(len(payload) == SOURCE_PROVENANCE_BYTES, "source provenance byte count drift")
    require(hashlib.sha256(payload).hexdigest() == SOURCE_PROVENANCE_SHA256, "source provenance SHA-256 drift")
    text = payload.decode()
    for anchor in SOURCE_ANCHORS.values():
        for key in ("repository", "commit", "tree", "parent"):
            require(str(anchor[key]) in text, f"source provenance omits {key} {anchor[key]}")
    dependency = SOURCE_REPRODUCTION["deleted_dependency"]
    require(dependency["repository"] in text and dependency["commit"] in text, "source provenance omits deleted gluegun dependency")
    require("spec `0.0.2`" in text and "deployed manifests declare `0.0.4`" in text, "source provenance omits spec mismatch")
    for names in MISSING_MAPPING_ENTITIES_BY_ROLE.values():
        for name in names:
            require(f"`{name}`" in text, f"source provenance omits mapping.entities defect {name}")
    require("`Token` exactly twice" in text, "source provenance omits primary Pool Token multiplicity")
    require("`Protocol`" in text and "declared interface" in text, "source provenance misclassifies or omits Protocol")


def bind_manifest_entity_metadata(target: str, manifest: dict[str, Any], schema: dict[str, Any]) -> None:
    declared = set(schema["declared_type_names"])
    expected_missing = {
        "Factory": MISSING_MAPPING_ENTITIES_BY_ROLE["Factory"],
        "NonFungiblePositionManager": MISSING_MAPPING_ENTITIES_BY_ROLE["NonFungiblePositionManager"],
        "Pool": MISSING_MAPPING_ENTITIES_BY_ROLE["primary_pool"],
        "PancakeSwapPool" if target == "pancakeswap-v3-bsc" else "UniswapPool": MISSING_MAPPING_ENTITIES_BY_ROLE["fee_only_template"],
    }
    expected_duplicates = {
        "Factory": DUPLICATE_MAPPING_ENTITIES_BY_ROLE["Factory"],
        "NonFungiblePositionManager": DUPLICATE_MAPPING_ENTITIES_BY_ROLE["NonFungiblePositionManager"],
        "Pool": DUPLICATE_MAPPING_ENTITIES_BY_ROLE["primary_pool"],
        "PancakeSwapPool" if target == "pancakeswap-v3-bsc" else "UniswapPool": DUPLICATE_MAPPING_ENTITIES_BY_ROLE["fee_only_template"],
    }
    for component in manifest["components"]:
        entities = component["entities"]
        missing = list(dict.fromkeys(name for name in entities if name not in declared))
        duplicates = {
            name: count
            for name, count in sorted(Counter(entities).items())
            if count > 1
        }
        require(missing == expected_missing[component["name"]], f"{target}/{component['name']} missing mapping.entities inventory drift")
        require(duplicates == expected_duplicates[component["name"]], f"{target}/{component['name']} mapping.entities multiplicity drift")
        component["entity_metadata_contract"] = {
            "declared_order": entities,
            "missing_from_schema_type_declarations": missing,
            "duplicate_multiplicity": duplicates,
            "normalization_allowed": False,
        }


def build_state(root: Path) -> dict[str, Any]:
    bindings = verify_bindings(root)
    artifact_records, by_target = verify_artifacts(root)
    manifests = {}
    schemas = {}
    for target in TARGET_ORDER:
        deployment_path = root / by_target[target]["deployment"]["vendored_path"]
        manifests[target] = manifest_profile(target, load_yaml_unique(deployment_path), by_target[target])
        schemas[target] = schema_profile(root / by_target[target]["schema"]["vendored_path"])
        bind_manifest_entity_metadata(target, manifests[target], schemas[target])
    schema_diff = verify_schema_pair(schemas)
    abi_diff = build_abi_diff(root, by_target)
    wasm_diff = build_wasm_diff(by_target)
    verify_source_document(root)
    return {
        "bindings": bindings,
        "artifact_records": artifact_records,
        "by_target": by_target,
        "manifests": manifests,
        "schemas": schemas,
        "schema_diff": schema_diff,
        "abi_diff": abi_diff,
        "wasm_diff": wasm_diff,
    }


def truth_boundary() -> dict[str, bool]:
    return {gate: False for gate in FALSE_GATES}


def build_cross_target_diff(state: dict[str, Any]) -> dict[str, Any]:
    bsc = state["manifests"]["pancakeswap-v3-bsc"]
    base = state["manifests"]["uniswap-v3-base"]
    role_indexes = {
        "Factory": 0,
        "NonFungiblePositionManager": 1,
        "primary_pool": 2,
        "fee_only_template": 3,
    }
    for role, index in role_indexes.items():
        left = bsc["components"][index]["entity_metadata_contract"]
        right = base["components"][index]["entity_metadata_contract"]
        require(left == right, f"cross-target {role} mapping.entities metadata drift")
    return {
        "exact": True,
        "deployment_cids": {"pancakeswap-v3-bsc": bsc["deployment_cid"], "uniswap-v3-base": base["deployment_cid"]},
        "chains": {"pancakeswap-v3-bsc": "bsc", "uniswap-v3-base": "base"},
        "factory_sources": {"pancakeswap-v3-bsc": bsc["components"][0]["source"], "uniswap-v3-base": base["components"][0]["source"]},
        "position_manager_sources": {"pancakeswap-v3-bsc": bsc["components"][1]["source"], "uniswap-v3-base": base["components"][1]["source"]},
        "schema": state["schema_diff"],
        "abis": state["abi_diff"],
        "wasm_exports": state["wasm_diff"],
        "primary_pool": {
            "pancakeswap_swap": TARGET_EXPECTATIONS["pancakeswap-v3-bsc"]["handlers"]["Pool"][3][1],
            "base_swap": TARGET_EXPECTATIONS["uniswap-v3-base"]["handlers"]["Pool"][2][1],
            "pancakeswap_set_fee_protocol": "SetFeeProtocol(uint32,uint32,uint32,uint32)",
            "base_set_fee_protocol": "SetFeeProtocol(uint8,uint8,uint8,uint8)",
            "pancakeswap_declared_missing_export": "handleSetFeeProtocol",
            "pancakeswap_separate_fee_mapping_exports_handler": True,
            "base_primary_pool_declares_set_fee_protocol": False,
            "base_separate_fee_mapping_exports_handler": True,
        },
        "shared_manifest_quirks": {
            "misspelled_template_entity": "LiqudityPool",
            "primary_pool_token_entity_occurrences": 2,
            "metadata_identical_across_targets_by_role": True,
            "missing_from_schema_type_declarations_by_role": MISSING_MAPPING_ENTITIES_BY_ROLE,
            "duplicate_multiplicity_by_role": DUPLICATE_MAPPING_ENTITIES_BY_ROLE,
            "normalization_allowed": False,
        },
        "runtime_equivalence_claimed": False,
    }


def build_profile(state: dict[str, Any]) -> dict[str, Any]:
    targets = []
    for target in TARGET_ORDER:
        artifact_map = state["by_target"][target]
        targets.append({
            "target": target,
            "binding": next(item for item in state["bindings"] if item["target"] == target),
            "deployment": state["manifests"][target],
            "schema": state["schemas"][target],
            "abis": {role.removeprefix("abi/"): artifact_map[role]["abi"] for role in sorted(artifact_map) if role.startswith("abi/")},
            "mappings": {
                role.removeprefix("mapping/"): {
                    "cid": artifact_map[role]["cid"],
                    "bytes": artifact_map[role]["bytes"],
                    "sha256": artifact_map[role]["sha256"],
                    "export_count": artifact_map[role]["export_count"],
                    "export_table_sha256": artifact_map[role]["export_table_sha256"],
                    "function_exports": artifact_map[role]["function_exports"],
                    "handler_exports": artifact_map[role]["handler_exports"],
                    "export_table": artifact_map[role]["export_table"],
                }
                for role in sorted(artifact_map)
                if role.startswith("mapping/")
            },
            "source_anchor": SOURCE_ANCHORS[target],
        })
    return {
        "format_version": 1,
        "profile_id": "messari-v3-targets/v1",
        "status": "immutable_deployed_artifact_and_static_layout_baseline_only",
        "family": "messari-v3",
        "milestone": "M9",
        "artifact_count": 26,
        "targets": targets,
        "cross_target_diff": build_cross_target_diff(state),
        "source_reproduction": SOURCE_REPRODUCTION,
        "truth_boundary": truth_boundary(),
    }


def _contract_artifact_record(record: dict[str, Any]) -> dict[str, Any]:
    result = {key: record[key] for key in ("target", "role", "cid", "bytes", "sha256", "vendored_path")}
    if "abi" in record:
        result["abi"] = record["abi"]
    if "export_count" in record:
        result.update({key: record[key] for key in ("export_count", "export_table_sha256", "function_exports", "handler_exports")})
    return result


def build_contract(state: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    rendered_profile = render(profile).encode()
    return {
        "format_version": 1,
        "contract_id": "messari-v3-targets/v1",
        "status": "immutable_target_baseline_only",
        "family": "messari-v3",
        "milestone": "M9",
        "issues": list(FAMILY_ISSUES),
        "issues_semantics": FAMILY_ISSUES_SEMANTICS,
        "artifact_count": 26,
        "target_count": 2,
        "artifact_lock": [_contract_artifact_record(record) for record in state["artifact_records"]],
        "binding_lock": state["bindings"],
        "layout_profile": {
            "path": PROFILE_PATH.as_posix(),
            "bytes": len(rendered_profile),
            "sha256": hashlib.sha256(rendered_profile).hexdigest(),
            "canonical_sha256": canonical_sha256(profile),
        },
        "source_provenance": {
            "path": SOURCE_PROVENANCE_PATH.as_posix(),
            "bytes": SOURCE_PROVENANCE_BYTES,
            "sha256": SOURCE_PROVENANCE_SHA256,
            "anchors": SOURCE_ANCHORS,
            "reproduction": SOURCE_REPRODUCTION,
        },
        "cross_target_diff": build_cross_target_diff(state),
        "eligibility": {
            "policy": "graph-node-net-catchup-v1",
            "required_clusters": ["riv-subgraphs-a", "kan-subgraphs-a"],
            "required_forecast_windows_hours": [24, 72],
            "minimum_eta_days_exclusive": 28,
            "current_decision": "indeterminate",
            "reason": "no_fresh_evidence",
        },
        "boundary": "the contract binds deployed bytes and static layout differences only; source-to-WASM reproduction, handler semantics, runtime behavior, store/error order, parity, backfill, deployment, production, and readiness remain unproved",
        "truth_boundary": truth_boundary(),
    }


def verify_committed(root: Path, state: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    verified = state or build_state(root)
    expected_profile = build_profile(verified)
    profile_path = root / PROFILE_PATH
    actual_profile = load_json(profile_path)
    require(profile_path.read_text() == render(actual_profile), "Messari V3 layout profile byte rendering drift")
    require(canonical_bytes(actual_profile) == canonical_bytes(expected_profile), "Messari V3 layout profile differs from retained artifacts")
    expected_contract = build_contract(verified, expected_profile)
    contract_path = root / CONTRACT_PATH
    actual_contract = load_json(contract_path)
    require(contract_path.read_text() == render(actual_contract), "Messari V3 provenance contract byte rendering drift")
    require(actual_contract.get("issues") == list(FAMILY_ISSUES), "Messari V3 exhaustive family issue linkage drift")
    require(actual_contract.get("issues_semantics") == FAMILY_ISSUES_SEMANTICS, "Messari V3 family issue linkage semantics drift")
    require(canonical_bytes(actual_contract) == canonical_bytes(expected_contract), "Messari V3 provenance contract differs from retained artifacts")
    require(all(actual_contract["truth_boundary"][gate] is False for gate in FALSE_GATES), "Messari V3 false gate promoted")
    return expected_contract, expected_profile


def extract_milestone_section(text: str, marker: str, label: str) -> str:
    require(text.count(marker) == 1, f"Messari V3 {label} marker inventory drift")
    _, tail = text.split(marker, 1)
    next_milestone = MILESTONE_HEADING_PATTERN.search(tail)
    if next_milestone is None:
        section = tail.split("\n\n", 1)[0]
    else:
        section = tail[: next_milestone.start()]
    return marker + section.rstrip("\n")


def extract_paragraph(text: str, marker: str, label: str) -> str:
    require(text.count(marker) == 1, f"Messari V3 {label} marker inventory drift")
    _, tail = text.split(marker, 1)
    return marker + tail.split("\n\n", 1)[0].rstrip("\n")


def parse_traceability_arrays(section: str) -> tuple[tuple[int, ...], ...]:
    return tuple(
        tuple(int(value) for value in match.split(", "))
        for match in TRACEABILITY_ARRAY_PATTERN.findall(section)
    )


def verify_dependency_documentation(root: Path) -> None:
    documents = {
        "root roadmap": (root / ROOT_README_PATH).read_text(),
        "target README": (root / TARGET_README_PATH).read_text(),
        "provenance index": (root / PROVENANCE_INDEX_PATH).read_text(),
    }
    sections = {
        "root roadmap": extract_milestone_section(
            documents["root roadmap"],
            "9. **M9 — Messari V3 BSC + Base**",
            "root roadmap M9",
        ),
        "target README": extract_paragraph(
            documents["target README"],
            "The provenance contract's top-level `issues` list",
            "target README M9",
        ),
        "provenance index": extract_paragraph(
            documents["provenance index"],
            "[`messari-v3-targets-v1.json`](messari-v3-targets-v1.json)",
            "provenance index M9",
        ),
    }
    expected_sections = {
        "root roadmap": ROOT_M9_SECTION,
        "target README": TARGET_M9_SECTION,
        "provenance index": PROVENANCE_M9_SECTION,
    }
    for label, section in sections.items():
        require(
            section == expected_sections[label],
            f"Messari V3 {label} exact bounded M9 section drift",
        )

    root_issue_links = tuple(
        int(value) for value in ISSUE_HREF_PATTERN.findall(sections["root roadmap"])
    )
    require(
        root_issue_links == ROOT_M9_ISSUE_LINK_ORDER,
        "Messari V3 root roadmap exact M9 issue-link order drift",
    )
    require(
        parse_traceability_arrays(sections["target README"])
        == TARGET_M9_TRACEABILITY_ARRAYS,
        "Messari V3 target README exact traceability-array order drift",
    )

    for label, section in sections.items():
        normalized = " ".join(section.split())
        require(
            ISSUE_DAG_PATTERN.findall(normalized) == [M9_DEPENDENCY_DAG],
            f"Messari V3 {label} exact dependency DAG inventory drift",
        )
        require(
            normalized.count(M9_DEPENDENCY_ORDER) == 1,
            f"Messari V3 {label} exact dependency order inventory drift",
        )

    for label, text in documents.items():
        normalized = " ".join(text.split())
        require(
            not any(
                pattern.search(normalized)
                for pattern in CONTRADICTORY_M9_ORDERING_PATTERNS
            ),
            f"Messari V3 {label} contradictory dependency ordering",
        )


def write_contracts(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    state = build_state(root)
    profile = build_profile(state)
    contract = build_contract(state, profile)
    (root / PROFILE_PATH).parent.mkdir(parents=True, exist_ok=True)
    (root / PROFILE_PATH).write_text(render(profile))
    (root / CONTRACT_PATH).parent.mkdir(parents=True, exist_ok=True)
    (root / CONTRACT_PATH).write_text(render(contract))
    return contract, profile


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPOSITORY)
    parser.add_argument("--write-contract", action="store_true")
    args = parser.parse_args()
    try:
        root = args.root.resolve()
        verify_dependency_documentation(root)
        if args.write_contract:
            contract, profile = write_contracts(root)
        else:
            contract, profile = verify_committed(root)
    except (OSError, json.JSONDecodeError, yaml.YAMLError, VerificationError) as error:
        print(f"Messari V3 target verification failed: {error}", file=sys.stderr)
        return 1
    print(
        "verified Messari V3 M9 target baseline: "
        f"{contract['target_count']} targets, {contract['artifact_count']} artifacts, "
        f"{sum(target['schema']['entity_count'] for target in profile['targets'])} entity bindings, "
        "all runtime/parity/backfill/readiness gates false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
