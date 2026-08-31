#!/usr/bin/env python3
"""Build or verify the complete retained-WAT NPM Collect v2 certificate."""

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
CONTRACT_PATH = Path("uniswap-v3/npm-collect/v2/contract.json")
CONTRACT_VERSION = "uniswap-v3-npm-collect/v2"
HANDLER_ID = "NonfungiblePositionManager.handleCollect"
HANDLER_EXPORT = "handleCollect"

IMPLEMENTATION_BASE_COMMIT = "0398e6184dc07fe848fcfef4ecd04ac0b64e8ece"
IMPLEMENTATION_BASE_TREE = "ca82557bd179527369f527c1c114a2d3d5ae252e"
RETAINED_AUTHORITY_COMMIT = "42c6d01f2e719993e41fca9db51be55d33da734c"
RETAINED_AUTHORITY_TREE = "ba8531df0e102ba71fd30b4df2af2977355dabf3"

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
        "function_count": 107,
        "direct_call_count": 407,
        "direct_target_count": 118,
        "memory_write_count": 177,
        "generic_setter_site_count": 22,
        "named_setter_invocation_count": 32,
        "store_get_site_count": 3,
        "store_set_site_count": 3,
        "store_remove_site_count": 0,
        "schema_unset_site_count": 0,
        "ethereum_call_site_count": 2,
        "call_indirect_count": 0,
        "abort_call_site_count": 29,
        "unreachable_instruction_count": 38,
        "unreachable_function_count": 31,
        "handler_body_sha256": "aa4f760f0288396a00a8beafce8533c89f642ff21d7cc7deb4be12364ed1a444",
        "handler_normalized_body_sha256": "aa4f760f0288396a00a8beafce8533c89f642ff21d7cc7deb4be12364ed1a444",
        "handler_instruction_shape_sha256": "aa4f760f0288396a00a8beafce8533c89f642ff21d7cc7deb4be12364ed1a444",
        "handler_call_sequence_sha256": "e0a16e321a7a5441da34a4d41fa32f77d97610eb50b3b556a4f4ab7ab2189202",
        "handler_normalized_call_sequence_sha256": "e0a16e321a7a5441da34a4d41fa32f77d97610eb50b3b556a4f4ab7ab2189202",
        "handler_call_count": 30,
        "handler_function_index": 124,
        "handler_start_line": 4196,
    },
    "Qmebr2EyxV7v1wLt9DSFKA7g8EhcVr9k1x7pwZr5eWEHT6": {
        "same_as": "QmYWR79pUmVbQ42JkvB24D6AKCGtdo4UG78ZSewmFxwQdR",
        "raw_sha256": "bdb35f971e9a03b4bdc92b140d42285e27fdff6efb4edf14fe0f3eaad0c80537",
        "wat_sha256": "19d7511d0a1ba05caeb115d4d820c89c61210c373b9253682915bc40d0d38d5d",
        "handler_body_sha256": "149d239f1b44af4389ce575d3b664deda06d06f10480829b9f888c23a6c92be1",
        "handler_normalized_body_sha256": "149d239f1b44af4389ce575d3b664deda06d06f10480829b9f888c23a6c92be1",
        "handler_instruction_shape_sha256": "149d239f1b44af4389ce575d3b664deda06d06f10480829b9f888c23a6c92be1",
        "handler_call_sequence_sha256": "4233f0454b85c41c0e441998848669d360fd91f797c40fca82b90996d46d70bd",
        "handler_normalized_call_sequence_sha256": "4233f0454b85c41c0e441998848669d360fd91f797c40fca82b90996d46d70bd",
    },
    "QmYwxHm2GNNcukX9oe4owucCLNoAk2rYrbMFuMFtWfKLn2": {
        "same_as": "QmYWR79pUmVbQ42JkvB24D6AKCGtdo4UG78ZSewmFxwQdR",
        "bytes": 20_604,
        "raw_sha256": "b09ba105e25bbca52949325f57c2006fa2e441139617380d5f81e3945dfbbe02",
        "wat_sha256": "c68a6ea285b643a301f7931ec8bebc3acd88c047a7c84b5773ffd2aa8570f9c3",
        "function_count": 93,
        "direct_call_count": 352,
        "direct_target_count": 99,
        "memory_write_count": 173,
        "named_setter_invocation_count": 30,
        "store_get_site_count": 2,
        "abort_call_site_count": 29,
        "unreachable_instruction_count": 37,
        "unreachable_function_count": 30,
        "handler_body_sha256": "07a0418da9b8aad3eb13ae7a033a8ccd5d4fd25dd0555cff6ee0c0625a856b64",
        "handler_normalized_body_sha256": "07a0418da9b8aad3eb13ae7a033a8ccd5d4fd25dd0555cff6ee0c0625a856b64",
        "handler_instruction_shape_sha256": "07a0418da9b8aad3eb13ae7a033a8ccd5d4fd25dd0555cff6ee0c0625a856b64",
        "handler_call_sequence_sha256": "3ed5a9abdd85aaae05af33869d4e6be8a9de188517daa6265c69c10c0b0cf4cb",
        "handler_normalized_call_sequence_sha256": "3ed5a9abdd85aaae05af33869d4e6be8a9de188517daa6265c69c10c0b0cf4cb",
        "handler_call_count": 12,
        "handler_function_index": 122,
        "handler_start_line": 4190,
    },
    "QmWxG1yzdQmp4pRDiqKvTZyRrrrZPRUTza6xznjR1wu1sD": {
        "generation": "current-generic-setters",
        "bytes": 48_593,
        "raw_sha256": "34487685c81672436f34b79f3749f41e6b3c724b52dd8cb24b933e3cb5006124",
        "wat_sha256": "6febde6b56e441b694f1708821a5e507f766ddfac3056a8efbce026826a9dced",
        "function_count": 63,
        "direct_call_count": 430,
        "direct_target_count": 74,
        "memory_write_count": 304,
        "generic_setter_site_count": 42,
        "named_setter_invocation_count": 0,
        "store_get_site_count": 3,
        "store_set_site_count": 3,
        "store_remove_site_count": 0,
        "schema_unset_site_count": 0,
        "ethereum_call_site_count": 2,
        "call_indirect_count": 1,
        "abort_call_site_count": 52,
        "unreachable_instruction_count": 54,
        "unreachable_function_count": 37,
        "handler_body_sha256": "b382bc2861ff2c3664692b7364b0307f86670000116a7b771a5753790f4eed30",
        "handler_normalized_body_sha256": "cfb066d5e3b68fb43f8dfa9893cd3e49e8ad293caf82e03a6038b8c959ff7e0c",
        "handler_instruction_shape_sha256": "480de435dc3a3822d34fb7420c51900ddd5c9f4ca1bb6f5a1515f9c951d43576",
        "handler_call_sequence_sha256": "db5e28e7566de1faa53f4f2cb212761bee3865423d81b7a7a42ba8b70c2c9c4c",
        "handler_normalized_call_sequence_sha256": "db5e28e7566de1faa53f4f2cb212761bee3865423d81b7a7a42ba8b70c2c9c4c",
        "handler_call_count": 29,
        "handler_function_index": 80,
        "handler_start_line": 5956,
    },
    "QmUk7jc3c8joQBrrcTz2ZEVDKcg1P12G2nFtuNqiikDQLJ": {
        "same_as": "QmYWR79pUmVbQ42JkvB24D6AKCGtdo4UG78ZSewmFxwQdR",
        "bytes": 20_876,
        "raw_sha256": "e25dad1c3b6f1892eee2a8f51da62bb57268286deb9a135d6a689bdca1ad0034",
        "wat_sha256": "4370c99e82c40e311a7a3d9c23ff0a61ed0dfd04feb9d737727308400ce03d12",
        "function_count": 106,
        "direct_call_count": 398,
        "direct_target_count": 117,
        "handler_body_sha256": "c9d181187f5b83a513da91c18606f30a1fa81c47a48e8153f67529e61badcec0",
        "handler_normalized_body_sha256": "c9d181187f5b83a513da91c18606f30a1fa81c47a48e8153f67529e61badcec0",
        "handler_instruction_shape_sha256": "c9d181187f5b83a513da91c18606f30a1fa81c47a48e8153f67529e61badcec0",
        "handler_call_sequence_sha256": "f555bdcebbd34c5024e9d550365e3f41aae2e07bde9205521017336775fc6451",
        "handler_normalized_call_sequence_sha256": "f555bdcebbd34c5024e9d550365e3f41aae2e07bde9205521017336775fc6451",
        "handler_call_count": 24,
        "handler_function_index": 125,
        "handler_start_line": 4218,
    },
    "QmPjhEuGqknJJ2LfJCi6XTLFLtiymYfZAtjTLfkmJJGMEj": {
        "same_as": "QmWxG1yzdQmp4pRDiqKvTZyRrrrZPRUTza6xznjR1wu1sD",
        "bytes": 48_657,
        "raw_sha256": "6338f6b3b2071d0599b8381c948070ca138827bd61b6e5e05eb0d112177b0c91",
        "wat_sha256": "2ca2b971161bb406b60ddf8d0d486ee02c3599dedb72c3c9c9dad9f6e63dd8ca",
        "handler_body_sha256": "3b5e8f8936dc36d47fcc2154607e6dada0cd247c40fcd301a32b3c55f10a9efa",
        "handler_call_sequence_sha256": "91badc7fd7c32598fa4015755729568b07c570f41db00876d02311c98521dacd",
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

PROFILE_EXPECTATIONS = {
    "mainnet-root-correct-collect": {
        "handler_fee_setter_keys": ["collectedFeesToken0", "collectedFeesToken1"],
        "handler_token_read_count": 2,
        "handler_token_read_model": "two generated Token.load calls",
        "handler_amount_source_model": "event amount0 with token0 decimals, then event amount1 with token1 decimals",
        "token_missing_policy": "a missing required legacy Token pointer reaches a fatal dereference path",
        "handler_fee_setter_count": 2,
    },
    "mainnet-second-fee0-overwrite": {
        "handler_fee_setter_keys": ["collectedFeesToken0", "collectedFeesToken0"],
        "handler_token_read_count": 2,
        "handler_token_read_model": "two generated Token.load calls",
        "handler_amount_source_model": "event amount0 with token0 decimals, then event amount1 with token1 decimals; the second receiver key is still collectedFeesToken0",
        "token_missing_policy": "a missing required legacy Token pointer reaches a fatal dereference path",
        "handler_fee_setter_count": 2,
    },
    "mainnet-no-collect-amounts": {
        "handler_fee_setter_keys": [],
        "handler_token_read_count": 0,
        "handler_token_read_model": "no handler Token read",
        "handler_amount_source_model": "no handler collected-fee amount setter source edge",
        "token_missing_policy": "no handler Token dereference branch",
        "handler_fee_setter_count": 0,
    },
    "base-root-amount0-to-both": {
        "handler_fee_setter_keys": ["collectedFeesToken0", "collectedFeesToken1"],
        "handler_token_read_count": 1,
        "handler_token_read_model": "one generated Token.load call for Position.token0",
        "handler_amount_source_model": "the event amount0/token0 conversion call-chain result reaches both field setter paths",
        "token_missing_policy": "a missing required legacy Token pointer reaches a fatal dereference path",
        "handler_fee_setter_count": 2,
    },
    "current-amount0-to-both": {
        "handler_fee_setter_keys": ["collectedFeesToken0", "collectedFeesToken1"],
        "handler_token_read_count": 1,
        "handler_token_read_model": "one direct Token store.get for Position.token0",
        "handler_amount_source_model": "inside the token-non-null branch, the event amount0/token0 conversion call-chain result reaches both field setter paths",
        "token_missing_policy": "a null Token store result skips both collected-fee setters and continues to fee refresh and saves",
        "handler_fee_setter_count": 2,
    },
}

LEGACY_HELPER_EXPECTATIONS = {
    "get_position": {
        "body_sha256": "ca21e83d64e1e9337c4a8dbfaba2c90683cda096f12f34f7cb30d871c0fac105",
        "normalized_body_sha256": "796a2cd63de1a819920d45284810b0a4da76123ba0493c5a5a7329818ed60e71",
        "instruction_shape_sha256": "796a2cd63de1a819920d45284810b0a4da76123ba0493c5a5a7329818ed60e71",
        "call_count": 43,
        "call_sequence_sha256": "326a7dc4dfd347bf0595fe8120663e397b89acdbc530de19d189ae3fc18dad19",
        "normalized_call_sequence_sha256": "326a7dc4dfd347bf0595fe8120663e397b89acdbc530de19d189ae3fc18dad19",
    },
    "update_fee_vars": {
        "body_sha256": "bd2603c92b5f65cd290962538fc6e895bf3f32772690ee64df49b7cb9e4c0415",
        "normalized_body_sha256": "bd2603c92b5f65cd290962538fc6e895bf3f32772690ee64df49b7cb9e4c0415",
        "instruction_shape_sha256": "bd2603c92b5f65cd290962538fc6e895bf3f32772690ee64df49b7cb9e4c0415",
        "call_count": 7,
        "call_sequence_sha256": "0af7fbf53729471c952b929c83de083e17968eaee99b547977c6c0de69151658",
        "normalized_call_sequence_sha256": "0af7fbf53729471c952b929c83de083e17968eaee99b547977c6c0de69151658",
    },
    "snapshot": {
        "body_sha256": "d3c853504a1c4e65be0e64636d5a93036c246d08dbef85d90ddad76bfd4ab2a7",
        "normalized_body_sha256": "ff3460062942ca25fede4425d8c0452981cb86cf8ac29a1fed29d6f4537b72cf",
        "instruction_shape_sha256": "ff3460062942ca25fede4425d8c0452981cb86cf8ac29a1fed29d6f4537b72cf",
        "call_count": 39,
        "call_sequence_sha256": "6e029b5e3b1c2d570da1807336be3b1755f393ee674f8ef791da8a20cb822ded",
        "normalized_call_sequence_sha256": "6e029b5e3b1c2d570da1807336be3b1755f393ee674f8ef791da8a20cb822ded",
    },
    "load_transaction": {
        "body_sha256": "216ac48e01b294d936f1ddc43d42cb53ccfef3262fbf5c5340a51046dd95d06a",
        "normalized_body_sha256": "962b9bc21076ff3b5e3994ba6cfc4122d84645403e49991a9e67011d3c3afe06",
        "instruction_shape_sha256": "962b9bc21076ff3b5e3994ba6cfc4122d84645403e49991a9e67011d3c3afe06",
        "call_count": 11,
        "call_sequence_sha256": "414659960ad44644821817d5fe61cb325b3cab9576724ae802dbc065bfd3bfc0",
        "normalized_call_sequence_sha256": "414659960ad44644821817d5fe61cb325b3cab9576724ae802dbc065bfd3bfc0",
    },
    "try_positions": {
        "body_sha256": "31b639721f8d9a57b6e6f0ed6459024bbe584345e7aa98bc58ee8fd6503eaa4e",
        "normalized_body_sha256": "443a92a90d9709386beb839e29f862e7cb910ce3e93813cd3e1c1cd34ed84143",
        "instruction_shape_sha256": "3acc9be9a7f03e050d226fcc2492260f3bf672aa914d16347290de36ff90ff90",
        "call_count": 36,
        "call_sequence_sha256": "daaaa9872e259cc35853901f28c7f326ec7b4f7b84e306f63d582bd6046d67d8",
        "normalized_call_sequence_sha256": "daaaa9872e259cc35853901f28c7f326ec7b4f7b84e306f63d582bd6046d67d8",
    },
    "factory_get_pool": {
        "body_sha256": "36a77a25d4949abe1829887dc30fd6b40fa54151c58ce1299646bdff9ed8baad",
        "normalized_body_sha256": "36a77a25d4949abe1829887dc30fd6b40fa54151c58ce1299646bdff9ed8baad",
        "instruction_shape_sha256": "de1da68d42459956d036a18aab0ffd5ab8066344458b27c465520377ec5ded2a",
        "call_count": 11,
        "call_sequence_sha256": "ae34ea9be68ba2ae6b22e99e91d196804d606d9e081abe00951200cc976705fb",
        "normalized_call_sequence_sha256": "ae34ea9be68ba2ae6b22e99e91d196804d606d9e081abe00951200cc976705fb",
    },
}

CURRENT_COMMON_HELPER_EXPECTATIONS = {
    "try_positions": {
        "body_sha256": "745339fa0288b24addf8fd26a923561eded199859cea480ad1ec483a1a15e5b5",
        "normalized_body_sha256": "e333ec926a61a6fc0f3523490f0933b5202b8aa3470514b5729123c5ebd5270f",
        "instruction_shape_sha256": "93837a7483968826a1be75495e8ab766cfc90dcfd0a7d8543c140668936a7ff1",
        "call_count": 36,
        "call_sequence_sha256": "15be255c554294477cb670fd14a22b4de62edb77c15dc92c11d594108bb20b41",
        "normalized_call_sequence_sha256": "15be255c554294477cb670fd14a22b4de62edb77c15dc92c11d594108bb20b41",
    },
}

CURRENT_HELPER_OVERRIDES = {
    "QmWxG1yzdQmp4pRDiqKvTZyRrrrZPRUTza6xznjR1wu1sD": {
        "get_position": ("e1acbc13b7d35318b4bdccdfbe065eee5a6c1357e009af9e8062638745a63bca", "989364d871dc0ee90a9d9d0692f99a4b030d31a9cc23b024d586fbef5b9a89fb", "9e33dbfc5d1b50eddad196079f2828be5d36d436f104db131cedfdcee5858ebf", 70, "e84c157d0b2f50828e5caa94bec277dfa00b07b470199efac2121b8beb177200", "e84c157d0b2f50828e5caa94bec277dfa00b07b470199efac2121b8beb177200"),
        "update_fee_vars": ("1d1beb0f174c09c05d634a0ec6d5f12a110e9495e5e8e9e39a09aab55b1882a0", "2da23657cbdb3c7fe556c7c9b7e0d1eb34aa0458178ea4a1b5a13ca0c5c98daa", "f843ba96f8205e5681a54dc93748e8e4dd891f6003ed0c6b5372e532d0a72788", 9, "c3de7f20d60b7660be236ca8981846ba67727e25013828567fb55d479c5a705b", "c3de7f20d60b7660be236ca8981846ba67727e25013828567fb55d479c5a705b"),
        "snapshot": ("5eda90c80ea4fb75dc8b7821090bb4e5f6b17b9d76e2f4c74e8c34994f51ca23", "4e3dc40b11f08b1abaaf9a44ddabffd462c5b787fc122f0dea4b1d7b898d0afa", "562347928668f7f1762fd18402b76b3a32bb4d06ccefb36c8249260d866389e3", 66, "83eca54df4cb4da52ddccd8c2057312d3b401593c25ed4193937a74cac1e5d9e", "83eca54df4cb4da52ddccd8c2057312d3b401593c25ed4193937a74cac1e5d9e"),
        "load_transaction": ("7cea60cc3d7d1e567a06910f74e7164bdcc678e8ce5c3790c49d184f041c956b", "2bf605574f04555d61570f6cbf304429d0aa2d11c62081b1fd28ffefc10ba45c", "46f08ce57c44c9db94124e476bd890466ac3a885a0e0f856221bf1609e5ab7b2", 24, "3571e6dcf7a1625b7b448fe811c04dedadedd731a55f54d895907139cf7c609a", "3571e6dcf7a1625b7b448fe811c04dedadedd731a55f54d895907139cf7c609a"),
    },
    "QmPjhEuGqknJJ2LfJCi6XTLFLtiymYfZAtjTLfkmJJGMEj": {
        "get_position": ("a8b0bc2c6a931ea087131e2ce993ddf63fd1a3228e428f788ac2b227c86a4fbe", "989364d871dc0ee90a9d9d0692f99a4b030d31a9cc23b024d586fbef5b9a89fb", "9e33dbfc5d1b50eddad196079f2828be5d36d436f104db131cedfdcee5858ebf", 70, "a9f947689811cb81b3c1c5ea7e4bb16b6430f2dcf00e119f59443f8679287e32", "e84c157d0b2f50828e5caa94bec277dfa00b07b470199efac2121b8beb177200"),
        "update_fee_vars": ("1e28c7b6c81d0f75c913358d17f73b2651bf005b3d3960b532361cb99bc0481e", "2da23657cbdb3c7fe556c7c9b7e0d1eb34aa0458178ea4a1b5a13ca0c5c98daa", "f843ba96f8205e5681a54dc93748e8e4dd891f6003ed0c6b5372e532d0a72788", 9, "c3de7f20d60b7660be236ca8981846ba67727e25013828567fb55d479c5a705b", "c3de7f20d60b7660be236ca8981846ba67727e25013828567fb55d479c5a705b"),
        "snapshot": ("517acde56e848b34d5325df505f22516462bb689d54756599017c837edb89713", "7e8097f8a9a7c94c79623c3f154c0c849faa0974e90e7d90b278283badfd5724", "ffe042dae55866c68d45ca9a653ed5d0679ee724a79e31c67a3d8db9ac35042b", 66, "48013324eb1382de115834b4b62cbe4a33f9c340e1c04f9a69e32b485521925d", "83eca54df4cb4da52ddccd8c2057312d3b401593c25ed4193937a74cac1e5d9e"),
        "load_transaction": ("544a7956e83ed3bbec726d5f90dcbd3d217697593d2b7b42acad214b73aa9714", "2e4e8bde17a88431c67ef407d2abfb5b4d645670682cf47f157fcc73a8e76b58", "46f08ce57c44c9db94124e476bd890466ac3a885a0e0f856221bf1609e5ab7b2", 24, "3571e6dcf7a1625b7b448fe811c04dedadedd731a55f54d895907139cf7c609a", "3571e6dcf7a1625b7b448fe811c04dedadedd731a55f54d895907139cf7c609a"),
    },
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
TRANSACTION_COMMON_HIT_OR_MISS_FIELDS = TRANSACTION_FIELDS[1:]
CLASSIFIED_FIELDS = {
    *(('Position', field) for field in POSITION_FIELDS),
    *(('PositionSnapshot', field) for field in SNAPSHOT_FIELDS),
    *(('Transaction', field) for field in TRANSACTION_FIELDS),
}
RELATION_FIELDS = {
    ("Position", "pool"), ("Position", "token0"), ("Position", "token1"),
    ("Position", "tickLower"), ("Position", "tickUpper"), ("Position", "transaction"),
    ("PositionSnapshot", "pool"), ("PositionSnapshot", "position"),
    ("PositionSnapshot", "transaction"),
}
REQUIRED_ABSENT_ENTITIES = {"Collect", "Flash", "TickHourData"}

CATEGORY_CLASSIFIED = "classified_stored_target_with_path_qualified_schema_setter_authority"
CATEGORY_SAVED_NO_SETTER = "saved_target_stored_field_without_reachable_setter"
CATEGORY_DERIVED = "derived_query_field_without_direct_store_transition"
CATEGORY_OUTSIDE = "stored_field_outside_npm_collect_store_target_closure"

TRUE_FLAGS = (
    "exact_direct_roots_digest_bound_and_recomputed",
    "exact_six_retained_npm_wasms_regenerated_with_wabt_1_0_35",
    "all_eight_segment_bindings_resolved",
    "all_reachable_direct_calls_and_function_bodies_bound",
    "all_reachable_memory_writes_bound",
    "all_generic_named_constructor_unset_and_store_sites_accounted",
    "closed_call_indirect_table_target_proven",
    "all_three_store_targets_and_profile_specific_store_read_sites_bound",
    "accepted_existing_new_revert_fatal_excluded_token_null_and_trap_path_order_bound",
    "all_six_load_transaction_hit_miss_control_boundaries_bound",
    "all_thirty_eight_distinct_stored_targets_classified",
    "all_nine_relation_and_transaction_field_receiver_key_source_paths_bound",
    "all_eight_segments_have_299_outcomes",
    "all_264_required_absent_outcomes_present",
    "all_twenty_eight_recursive_segment_diffs_present",
    "path_qualified_complete_static_npm_collect_contract",
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
    "shared_transaction_intra_handler_visibility_complete",
    "collect_numeric_accumulation_semantics_complete",
    "event_ordinal_order_complete",
    "interleaved_handler_composition_complete",
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
    "uniswap_v3_segment_field_semantics_v2_for_npm_collect_v2",
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


def helper_expectations(cid: str) -> dict[str, dict[str, Any]]:
    fields = (
        "body_sha256",
        "normalized_body_sha256",
        "instruction_shape_sha256",
        "call_count",
        "call_sequence_sha256",
        "normalized_call_sequence_sha256",
    )
    if cid in CURRENT_HELPER_OVERRIDES:
        result = {key: dict(value) for key, value in CURRENT_COMMON_HELPER_EXPECTATIONS.items()}
        result.update(
            {
                key: dict(zip(fields, values))
                for key, values in CURRENT_HELPER_OVERRIDES[cid].items()
            }
        )
        return result
    result = {key: dict(value) for key, value in LEGACY_HELPER_EXPECTATIONS.items()}
    if cid == "QmYwxHm2GNNcukX9oe4owucCLNoAk2rYrbMFuMFtWfKLn2":
        result["snapshot"] = {
            "body_sha256": "529a852ba41aa5e920e2e956dd9146b7f9f0c5feeef7a8625d6b1eef43fbb986",
            "normalized_body_sha256": "07fdcc381766afd1f9e92c6597e8c6eebecfeb11c559ba655031d9c89a3e9d29",
            "instruction_shape_sha256": "07fdcc381766afd1f9e92c6597e8c6eebecfeb11c559ba655031d9c89a3e9d29",
            "call_count": 41,
            "call_sequence_sha256": "25a0a17968d54ce98dc76ede5bdb3417d715f0fe6dc0d690904cbac18bd445cb",
            "normalized_call_sequence_sha256": "25a0a17968d54ce98dc76ede5bdb3417d715f0fe6dc0d690904cbac18bd445cb",
        }
    return result


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


def _load_transaction_branch_record(
    cid: str,
    function: Any,
    memory: bytearray,
    generation: str,
) -> dict[str, Any]:
    """Bind the store-miss-only ID effect separately from common refresh writes."""

    call_sites = [
        (index, _normalized_call_target(target))
        for index, target in WRITER.function_call_sites(function)
    ]
    store_get_sites = [index for index, target in call_sites if target.endswith("/store.get")]
    require(len(store_get_sites) == 1, f"{cid} loadTransaction store.get count drift")
    store_get_site = store_get_sites[0]
    require(
        store_get_site + 3 < len(function.lines)
        and function.lines[store_get_site + 1].strip().startswith("local.tee ")
        and function.lines[store_get_site + 2].strip() == "i32.eqz"
        and function.lines[store_get_site + 3].strip().startswith("if "),
        f"{cid} loadTransaction store.get result is not bound to the null branch",
    )
    miss_branch_start = store_get_site + 3
    miss_branch_end = WRITER.matching_end(
        function.lines,
        miss_branch_start,
        f"{cid} loadTransaction store-miss branch",
    )

    constructor_sites = [
        (index, target)
        for index, target in call_sites
        if target.endswith("#constructor")
    ]
    require(len(constructor_sites) == 1, f"{cid} loadTransaction constructor count drift")
    constructor_site, constructor_call = constructor_sites[0]
    require(
        miss_branch_start < constructor_site < miss_branch_end,
        f"{cid} loadTransaction constructor escaped the store-miss branch",
    )

    map_accesses = [
        (index, target)
        for index, target in call_sites
        if "TypedMap<" in target and target.endswith(("#get", "#set"))
    ]

    def generic_setter_site(field: str) -> int:
        candidates: list[int] = []
        for literal_site in WRITER.decoded_constant_sites(function, memory, field):
            following = next(
                ((index, target) for index, target in map_accesses if index > literal_site),
                None,
            )
            if following is not None and following[1].endswith("#set"):
                candidates.append(following[0])
        require(len(candidates) == 1, f"{cid} loadTransaction {field} generic setter drift")
        return candidates[0]

    legacy = generation.startswith("legacy")
    field_setter_sites: dict[str, int] = {}
    if legacy:
        for field in ("blockNumber", "timestamp"):
            sites = [
                index
                for index, target in call_sites
                if target.endswith(f"/Transaction#set:{field}")
            ]
            require(len(sites) == 1, f"{cid} loadTransaction {field} named setter drift")
            field_setter_sites[field] = sites[0]
        for field in ("gasUsed", "gasPrice"):
            field_setter_sites[field] = generic_setter_site(field)
        id_setter_site = constructor_site
        id_effect_class = "constructor_carried"
    else:
        for field in TRANSACTION_FIELDS:
            field_setter_sites[field] = generic_setter_site(field)
        id_setter_site = field_setter_sites["id"]
        id_effect_class = "explicit_generic_id_set"

    require(
        miss_branch_start < id_setter_site < miss_branch_end,
        f"{cid} loadTransaction ID effect escaped the store-miss branch",
    )
    common_sites = [field_setter_sites[field] for field in TRANSACTION_COMMON_HIT_OR_MISS_FIELDS]
    require(
        common_sites == sorted(common_sites)
        and all(index > miss_branch_end for index in common_sites),
        f"{cid} loadTransaction common setter order or branch placement drift",
    )

    save_sites = [
        index
        for index, target in call_sites
        if (
            target.endswith("/Transaction#save")
            if legacy
            else target.endswith("/store.set")
        )
    ]
    require(len(save_sites) == 1, f"{cid} loadTransaction Transaction save count drift")
    save_site = save_sites[0]
    require(
        save_site > common_sites[-1] > miss_branch_end,
        f"{cid} loadTransaction Transaction save is not common to hit and miss",
    )
    require(
        not any(
            miss_branch_start < field_setter_sites[field] < miss_branch_end
            for field in TRANSACTION_COMMON_HIT_OR_MISS_FIELDS
        ),
        f"{cid} loadTransaction common setter entered the store-miss-only branch",
    )

    hit_ledger = [f"Transaction.{field}" for field in TRANSACTION_COMMON_HIT_OR_MISS_FIELDS]
    miss_ledger = ["Transaction.id", *hit_ledger]
    return {
        "function": function.name,
        "body_sha256": hashlib.sha256(function.payload).hexdigest(),
        "generation": generation,
        "store_get_wat_line": function.start_line + store_get_site,
        "store_get_result_to_eqz_to_if_machine_checked": True,
        "store_miss_branch_wat_lines": [
            function.start_line + miss_branch_start,
            function.start_line + miss_branch_end,
        ],
        "id_effect_class": id_effect_class,
        "id_initializer_physical_call": constructor_call,
        "id_effect_wat_line": function.start_line + id_setter_site,
        "miss_only_field_effect_order": ["Transaction.id"],
        "hit_or_miss_field_setter_order": hit_ledger,
        "field_setter_wat_lines": {
            field: function.start_line + site
            for field, site in field_setter_sites.items()
        },
        "transaction_save_wat_line": function.start_line + save_site,
        "transaction_save_after_common_setters_on_hit_or_miss": True,
        "successful_hit_effect_ledger": [*hit_ledger, "Transaction.save"],
        "successful_miss_effect_ledger": [*miss_ledger, "Transaction.save"],
        "successful_hit_field_effect_count": 4,
        "successful_miss_field_effect_count": 5,
        "only_id_effect_is_store_miss_conditional": True,
        "common_setters_and_save_are_outside_store_miss_branch": True,
        "store_read_contents_complete": False,
        "graph_store_persistence_proven": False,
    }


def _semantic_functions(
    cid: str,
    functions: dict[str, Any],
    closure: set[str],
    memory: bytearray,
    generation: str,
) -> dict[str, Any]:
    names = {
        "handler": "src/mappings/position-manager/handleCollect",
        "get_position": "src/mappings/position-manager/getPosition",
        "update_fee_vars": "src/mappings/position-manager/updateFeeVars",
        "save_snapshot": "src/mappings/position-manager/savePositionSnapshot",
        "load_transaction": "src/utils/index/loadTransaction",
    }
    suffixes = {
        "try_positions": "#try_positions",
        "factory_get_pool": "/Factory#getPool",
    }
    result: dict[str, Any] = {}
    for key, name in names.items():
        require(name in functions, f"semantic function missing: {name}")
        function = functions[name]
        result[key] = {
            **WRITER.handler_record(function, memory),
            "direct_calls": WRITER.function_calls(function),
            "static_strings": WRITER.function_static_strings(function, memory),
        }
    expected_helpers = helper_expectations(cid)
    for key, suffix in suffixes.items():
        matches = [function for name, function in functions.items() if name.endswith(suffix)]
        expected_count = 1 if key in expected_helpers else 0
        require(len(matches) == expected_count, f"{cid} {key} helper count drift")
        if matches:
            function = matches[0]
            result[key] = {
                **WRITER.handler_record(function, memory),
                "direct_calls": WRITER.function_calls(function),
                "static_strings": WRITER.function_static_strings(function, memory),
            }
    helper_key_to_result = {
        "get_position": "get_position",
        "update_fee_vars": "update_fee_vars",
        "snapshot": "save_snapshot",
        "load_transaction": "load_transaction",
        "try_positions": "try_positions",
        "factory_get_pool": "factory_get_pool",
    }
    for expected_key, expected in expected_helpers.items():
        observed = result[helper_key_to_result[expected_key]]
        for field, value in expected.items():
            require(observed[field] == value, f"{cid} {expected_key} {field} drift")

    profile = PROFILE_EXPECTATIONS[PROFILE_BY_CID[cid]]
    handler = functions[names["handler"]]
    handler_calls = WRITER.function_calls(handler)
    if generation.startswith("legacy"):
        fee_keys = [
            match.group(1)
            for call in handler_calls
            if (match := re.fullmatch(r"src/types/schema/Position#set:(collectedFeesToken[01])", call))
        ]
        token_reads = sum(call.endswith("schema/Token.load") for call in handler_calls)
    else:
        fee_keys = [
            value for value in WRITER.function_static_strings(handler, memory)
            if value in {"collectedFeesToken0", "collectedFeesToken1"}
        ]
        token_reads = sum(call.endswith("/store.get") for call in handler_calls)
    require(fee_keys == profile["handler_fee_setter_keys"], f"{cid} handler fee setter-key order drift")
    require(token_reads == profile["handler_token_read_count"], f"{cid} handler Token-read count drift")
    require(WRITER.historical_guard_proof(handler) is None, f"{cid} invented Collect block guard")
    require(
        any(
            "0x8fe8d9bb8eeba3ed688069c3d6b556c9ca258248"
            in WRITER.function_static_strings(functions[name], memory)
            for name in closure
        ),
        f"{cid} excluded-pool literal drift",
    )
    get_position_index = next(i for i, call in enumerate(handler_calls) if call.endswith("/getPosition"))
    equals_index = next(i for i, call in enumerate(handler_calls) if call.endswith("ByteArray#equals"))
    update_index = next(i for i, call in enumerate(handler_calls) if call.endswith("/updateFeeVars"))
    position_save_index = next(i for i, call in enumerate(handler_calls) if call.endswith("schema/Position#save"))
    snapshot_index = next(i for i, call in enumerate(handler_calls) if call.endswith("/savePositionSnapshot"))
    require(get_position_index < equals_index < update_index < position_save_index < snapshot_index, f"{cid} Collect prefix order drift")
    require(not any(call.endswith("schema/Collect#save") for call in handler_calls), f"{cid} invented Collect save")

    update = functions[names["update_fee_vars"]]
    update_calls = WRITER.function_calls(update)
    require(any(call.endswith("#try_positions") for call in update_calls), f"{cid} update try_positions drift")
    if generation.startswith("legacy"):
        update_keys = [
            match.group(1)
            for call in update_calls
            if (match := re.fullmatch(r"src/types/schema/Position#set:(feeGrowthInside[01]LastX128)", call))
        ]
    else:
        update_keys = [
            value for value in WRITER.function_static_strings(update, memory)
            if value in {"feeGrowthInside0LastX128", "feeGrowthInside1LastX128"}
        ]
    require(update_keys == ["feeGrowthInside0LastX128", "feeGrowthInside1LastX128"], f"{cid} update fee-growth order drift")

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
    load_transaction_branch = _load_transaction_branch_record(
        cid,
        functions[names["load_transaction"]],
        memory,
        generation,
    )
    return {
        "functions": result,
        "profile": profile,
        "handler_fee_setter_keys": fee_keys,
        "handler_fee_setter_count": len(fee_keys),
        "lexical_semantic_field_invocation_count": 40 + len(fee_keys),
        "distinct_semantic_field_count": 38,
        "maximum_expanded_new_position_field_invocation_count": 45 + len(fee_keys),
        "maximum_expanded_existing_position_field_invocation_count": 23 + len(fee_keys),
        "position_constructor_setter_order": list(POSITION_FIELDS),
        "snapshot_constructor_setter_order": list(SNAPSHOT_FIELDS),
        "load_transaction_hit_or_miss_control_boundary": load_transaction_branch,
        "transaction_miss_constructor_setter_order": list(TRANSACTION_FIELDS),
        "fee_refresh_setter_order": ["feeGrowthInside0LastX128", "feeGrowthInside1LastX128"],
        "handler_prefix_call_indexes": {
            "get_position": get_position_index,
            "excluded_pool_equals": equals_index,
            "update_fee_vars": update_index,
            "position_save": position_save_index,
            "save_snapshot": snapshot_index,
        },
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


def _path_contract(profile_id: str, generation: str, api_version: str) -> dict[str, Any]:
    legacy = generation.startswith("legacy")
    profile = PROFILE_EXPECTATIONS[profile_id]
    handler_effects = int(profile["handler_fee_setter_count"])
    normal_reads = {
        "mainnet-root-correct-collect": (4, 5),
        "mainnet-second-fee0-overwrite": (4, 5),
        "mainnet-no-collect-amounts": (2, 3),
        "base-root-amount0-to-both": (3, 4),
        "current-amount0-to-both": (3, 4),
    }[profile_id]
    gas_used_source = (
        "event.transaction.gasLimit getter result passed to the gasUsed field setter"
        if api_version == "0.0.4"
        else "result of BigInt.fromI32 with literal zero passed to the gasUsed field setter"
    )
    return {
        "accepted_existing_position": {
            "guard": "Position store.get returns a non-null entity pointer",
            "contract_call_count": 1,
            "expanded_store_get_count": normal_reads[0],
            "field_effect_counts": {
                "fee_refresh_success_transaction_hit": handler_effects + 22,
                "fee_refresh_success_transaction_miss": handler_effects + 23,
                "fee_refresh_revert_transaction_hit": handler_effects + 20,
                "fee_refresh_revert_transaction_miss": handler_effects + 21,
            },
            "store_set_orders": [
                ["Position", "Transaction", "PositionSnapshot"],
            ],
            "field_effect_order": [
                "profile-specific zero-or-two collected-fee setter edges",
                "updateFeeVars zero-or-two fee-growth setter edges",
                "Position save",
                "PositionSnapshot first thirteen-field constructor/setter ledger through collectedFeesToken1",
                "Transaction loadTransaction ledger: four common setters on a hit, or miss-only ID followed by the same four common setters, then Transaction save on both",
                "PositionSnapshot final transaction and two fee-growth setter edges",
                "PositionSnapshot save",
            ],
            "position_fields_without_setter_are_preserved_or_unchanged": False,
        },
        "accepted_new_position": {
            "guard": "Position store.get is null, try_positions is not reverted, and non-try Factory getPool returns",
            "contract_call_count": 3,
            "expanded_store_get_count": normal_reads[1],
            "field_effect_counts": {
                "fee_refresh_success_zero_transaction_misses": 43 + handler_effects,
                "fee_refresh_success_one_transaction_miss": 44 + handler_effects,
                "fee_refresh_success_two_transaction_misses": 45 + handler_effects,
                "fee_refresh_revert_zero_transaction_misses": 41 + handler_effects,
                "fee_refresh_revert_one_transaction_miss": 42 + handler_effects,
                "fee_refresh_revert_two_transaction_misses": 43 + handler_effects,
            },
            "store_set_orders": [
                ["Transaction", "Position", "Transaction", "PositionSnapshot"],
            ],
            "field_effect_order": [
                "Position first fourteen-field getPosition construction ledger through collectedFeesToken1",
                "first Transaction loadTransaction ledger: four common setters on a hit, or miss-only ID followed by the same four common setters, then Transaction save on both",
                "Position final transaction and two fee-growth setter edges",
                "profile-specific zero-or-two collected-fee setter edges",
                "updateFeeVars zero-or-two fee-growth setter edges",
                "Position save",
                "PositionSnapshot first thirteen-field constructor/setter ledger through collectedFeesToken1",
                "second Transaction loadTransaction ledger: independently classified hit or miss, four common setters on either, miss-only ID, then Transaction save on both",
                "PositionSnapshot final transaction and two fee-growth setter edges",
                "PositionSnapshot save",
            ],
        },
        "try_positions_revert": {
            "guard": "Position store.get is null and generated try_positions reports reverted",
            "normal_return": True,
            "contract_call_count": 1,
            "schema_field_invocation_count": 0,
            "store_set_count": 0,
        },
        "factory_get_pool_fatal": {
            "guard": "Position store.get is null, try_positions succeeds, and non-try Factory getPool has no returned value",
            "fatal_before_any_schema_constructor_setter_or_store_set": True,
            "contract_call_count_before_fatal": 2,
            "schema_field_invocation_count_before_fatal": 0,
            "store_set_count_before_fatal": 0,
            "post_fatal_execution_modeled": False,
        },
        "excluded_pool_guard": {
            "literal": "0x8fe8d9bb8eeba3ed688069c3d6b556c9ca258248",
            "existing_path_contract_call_count": 0,
            "existing_path_field_effect_count": 0,
            "existing_path_store_orders": [[]],
            "new_path_contract_call_count": 2,
            "new_path_field_effect_counts": {
                "transaction_hit": 21,
                "transaction_miss": 22,
            },
            "new_path_store_orders": {
                "transaction_hit": ["Transaction"],
                "transaction_miss": ["Transaction"],
            },
            "guard_precedes_handler_amount_update_position_save_and_snapshot": True,
        },
        "token_branch": {
            **profile,
            "legacy_missing_token_fatal_before_handler_fee_update_position_and_snapshot_saves": legacy and handler_effects > 0,
            "legacy_missing_token_prefix_field_effect_counts": (
                {"existing": 0, "new_transaction_hit": 21, "new_transaction_miss": 22}
                if legacy and handler_effects > 0 else {}
            ),
            "legacy_missing_token_prefix_store_orders": (
                {"existing": [], "new_transaction_hit": ["Transaction"], "new_transaction_miss": ["Transaction"]}
                if legacy and handler_effects > 0 else {}
            ),
            "current_null_token_continues_with_zero_handler_fee_setters": not legacy,
            "current_null_token_fee_refresh_success_field_effect_counts_existing": (
                {"transaction_hit": 22, "transaction_miss": 23} if not legacy else {}
            ),
            "current_null_token_fee_refresh_success_field_effect_counts_new": (
                {"zero_transaction_misses": 43, "one_transaction_miss": 44, "two_transaction_misses": 45}
                if not legacy else {}
            ),
            "current_null_token_store_set_order_existing": (
                ["Position", "Transaction", "PositionSnapshot"] if not legacy else []
            ),
            "current_null_token_store_set_order_new": (
                ["Transaction", "Position", "Transaction", "PositionSnapshot"] if not legacy else []
            ),
        },
        "update_fee_vars_revert": {
            "setter_count": 0,
            "caller_continues_to_position_save_and_snapshot": True,
            "store_orders_unchanged_from_corresponding_accepted_path": True,
        },
        "trap_prefixes": {
            "position_save_trap": {
                "existing_prior_completed_store_order": [],
                "new_prior_completed_store_order": ["Transaction"],
                "new_prefix_has_transaction_save_on_hit_and_miss": True,
                "position_or_snapshot_store_completed": False,
            },
            "snapshot_pre_transaction_required_getter_trap": {
                "existing_prior_completed_store_order": ["Position"],
                "new_prior_completed_store_order": ["Transaction", "Position"],
                "snapshot_transaction_or_snapshot_store_completed": False,
            },
            "snapshot_post_transaction_required_getter_or_save_trap": {
                "existing_prior_completed_store_order": ["Position", "Transaction"],
                "new_prior_completed_store_order": ["Transaction", "Position", "Transaction"],
                "second_transaction_save_precedes_final_snapshot_fields_on_hit_and_miss": True,
                "snapshot_store_completed": False,
            },
            "load_transaction_incomplete_invocation_trap": {
                "id_initialization_trap_path": "store miss only",
                "common_setter_or_save_trap_paths": ["store hit", "store miss"],
                "incomplete_invocation_adds_completed_transaction_store": False,
                "get_position_prior_completed_store_order": [],
                "snapshot_existing_prior_completed_store_order": ["Position"],
                "snapshot_new_prior_completed_store_order": ["Transaction", "Position"],
            },
            "physical_abort_and_unreachable_sites_are_not_achievable_path_counts": True,
            "post_fatal_execution_modeled": False,
        },
        "ordered_nested_helper_field_ledgers": {
            "new_position_get_position": {
                "before_load_transaction": list(POSITION_FIELDS[:14]),
                "load_transaction_hit": list(TRANSACTION_COMMON_HIT_OR_MISS_FIELDS),
                "load_transaction_miss": list(TRANSACTION_FIELDS),
                "transaction_save_on_hit_or_miss": True,
                "after_load_transaction": list(POSITION_FIELDS[14:]),
            },
            "position_snapshot": {
                "before_load_transaction": list(SNAPSHOT_FIELDS[:13]),
                "load_transaction_hit": list(TRANSACTION_COMMON_HIT_OR_MISS_FIELDS),
                "load_transaction_miss": list(TRANSACTION_FIELDS),
                "transaction_save_on_hit_or_miss": True,
                "after_load_transaction": list(SNAPSHOT_FIELDS[13:]),
                "position_snapshot_save_after_final_fields": True,
            },
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
        "collect_excluded_pool_guard_bound": True,
        "collect_historical_block_guard_present": False,
        "global_absence_of_exclusion_literals_claimed": False,
        "transaction_store_get_visibility_between_the_two_new_path_calls_proven": False,
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
        {
            "entity": "Position",
            "field": "transaction",
            "path": "new-position only",
            "source_chain": "loadTransaction(event) then Transaction.id getter result reaches Position.transaction",
            "receiver_and_key_authority_bound": True,
            "shared_transaction_last_writer_complete": False,
        },
        {
            "entity": "PositionSnapshot",
            "field": "position",
            "path": "both accepted paths",
            "source_chain": "input Position.id getter result reaches PositionSnapshot.position",
            "receiver_and_key_authority_bound": True,
            "store_read_or_alias_value_semantics_complete": False,
        },
        {
            "entity": "PositionSnapshot",
            "field": "transaction",
            "path": "both accepted paths",
            "source_chain": "snapshot-side loadTransaction(event) then Transaction.id getter result reaches PositionSnapshot.transaction",
            "receiver_and_key_authority_bound": True,
            "shared_transaction_last_writer_complete": False,
        },
    ]


def _shared_transaction_contract() -> dict[str, Any]:
    return {
        "key_source": "event transaction hash reaches the bytes-to-hex call chain used for Transaction store.get and ID construction",
        "load_transaction_hit": "classifies blockNumber, timestamp, gasUsed and gasPrice, then reaches Transaction save unless a common-path pre-save trap occurs",
        "load_transaction_miss": "first classifies ID inside the null branch, then classifies the same four common fields and reaches the same Transaction save unless a pre-save trap occurs",
        "successful_hit_field_effect_count": 4,
        "successful_miss_field_effect_count": 5,
        "successful_invocation_transaction_store_set_count_on_hit_or_miss": 1,
        "only_id_effect_is_store_miss_conditional": True,
        "new_position_invocation_count": 2,
        "existing_position_invocation_count": 1,
        "intra_handler_visibility_between_store_set_and_later_store_get_proven": False,
        "store_read_contents_complete": False,
        "shared_transaction_last_writer_complete": False,
        "complete_transaction_history": False,
    }


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
    abort_call_sites = [item for item in direct_calls if item["target"].endswith("/abort")]
    indirect_sites = []
    unreachable_sites = []
    for name in sorted(closure):
        function = functions[name]
        for index, line in enumerate(function.lines):
            if "call_indirect" in line:
                indirect_sites.append({**_site(function, index), "instruction": line.strip()})
            if line.strip() == "unreachable":
                unreachable_sites.append({**_site(function, index), "instruction": "unreachable"})

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
        "store_remove_site_count": len(store_remove_sites),
        "schema_unset_site_count": len(unset_sites),
        "ethereum_call_site_count": len(ethereum_call_sites),
        "call_indirect_count": len(indirect_sites),
        "abort_call_site_count": len(abort_call_sites),
        "unreachable_instruction_count": len(unreachable_sites),
        "unreachable_function_count": len({item["function"] for item in unreachable_sites}),
    }
    for field, value in observed.items():
        require(value == expected[field], f"{cid} {field} drift: {value} != {expected[field]}")
    require(len(store_remove_sites) == 0 and len(unset_sites) == 0, f"{cid} remove/unset closure drift")
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
        "instruction_shape_sha256": expected["handler_instruction_shape_sha256"],
        "call_sequence_sha256": expected["handler_call_sequence_sha256"],
        "normalized_call_sequence_sha256": expected["handler_normalized_call_sequence_sha256"],
        "call_count": expected["handler_call_count"],
        "wat_function_index": expected["handler_function_index"],
        "wat_start_line": expected["handler_start_line"],
    }
    for field, value in handler_expected.items():
        require(handler_record[field] == value, f"{cid} handler {field} drift")

    generation = expected["generation"]
    api_version = "0.0.4" if generation.startswith("legacy") else "0.0.7"
    semantic = _semantic_functions(cid, functions, closure, memory, generation)
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
            "abort_calls": abort_call_sites,
            "unreachable_instructions": unreachable_sites,
            "store_set_targets": store_targets,
            "call_indirect_sites": indirect_sites,
            "declared_table_initializers": analysis["call_indirect_table_targets"],
            "executable_call_indirect_targets": executable_indirect_targets,
        },
        "semantic_invocation_contract": semantic,
        "path_contract": _path_contract(PROFILE_BY_CID[cid], generation, api_version),
        "relation_field_authority": _relation_authority(),
        "shared_transaction_contract": _shared_transaction_contract(),
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
    require(not classified or record["storage"] == "stored", f"classified field is not stored: {identity}")
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
            paths.append("accepted_new_position:getPosition-constructor-or-setter")
            handler_keys = proof["semantic_invocation_contract"]["handler_fee_setter_keys"]
            if record["field"] in handler_keys:
                paths.append("accepted_existing_position:profile-handler-token-branch-setter")
            if record["field"] in {"feeGrowthInside0LastX128", "feeGrowthInside1LastX128"}:
                paths.append("accepted_existing_position:updateFeeVars-non-reverted-setter")
        elif record["entity"] == "PositionSnapshot":
            paths.extend(("accepted_existing_position:snapshot-setter", "accepted_new_position:snapshot-setter"))
        elif record["entity"] == "Transaction":
            qualifier = "store-miss-id" if record["field"] == "id" else "hit-or-miss-common-setter"
            paths.extend(
                (
                    f"accepted_existing_position:loadTransaction-{qualifier}",
                    f"accepted_new_position:either-loadTransaction-{qualifier}",
                )
            )
    require(bool(paths) == classified, f"classified setter-path equivalence drift: {identity}")
    require(not paths or not (derived or outside), f"nonclassified field gained setter path: {identity}")
    if record["entity"] == "Transaction":
        require(
            bool(paths) == (record["field"] in TRANSACTION_FIELDS),
            f"Transaction stored/derived setter-path boundary drift: {identity}",
        )
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
        "outside_npm_collect_store_target_closure": outside,
        "setter_before_matching_save_paths": paths,
        "no_setter_path_is_not_a_preservation_claim": classified,
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
        require(sum(item["required_absent_overlay"] for item in outcomes) == 33, f"{segment_id} required absence drift")
        require(
            sum(bool(item["setter_before_matching_save_paths"]) for item in outcomes) == 38
            and all(
                bool(item["setter_before_matching_save_paths"]) == item["classified_stored_target"]
                for item in outcomes
            ),
            f"{segment_id} classified setter-path population drift",
        )
        require(
            all(
                not item["setter_before_matching_save_paths"]
                for item in outcomes
                if item["derived_query_field"] or item["outside_npm_collect_store_target_closure"]
            ),
            f"{segment_id} nonclassified setter-path leakage",
        )
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
            "shared_transaction_contract": proof["shared_transaction_contract"],
            "field_outcome_summary": {
                "field_outcome_count": 299,
                "classified_stored_target_count": counts[CATEGORY_CLASSIFIED],
                "saved_target_stored_no_setter_count": counts[CATEGORY_SAVED_NO_SETTER],
                "derived_query_field_count": counts[CATEGORY_DERIVED],
                "outside_store_target_closure_count": counts[CATEGORY_OUTSIDE],
                "required_absent_overlay_count": sum(item["required_absent_overlay"] for item in outcomes),
                "setter_path_bearing_outcome_count": sum(
                    bool(item["setter_before_matching_save_paths"]) for item in outcomes
                ),
                "nonclassified_setter_path_outcome_count": sum(
                    bool(item["setter_before_matching_save_paths"])
                    and not item["classified_stored_target"]
                    for item in outcomes
                ),
            },
            "field_outcomes": outcomes,
            "complete_path_qualified_static_collect_contract": True,
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
    require(recompute_wat, "NPM Collect v2 requires direct retained-WAT recomputation")
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
        "store_remove_site_count",
        "schema_unset_site_count",
        "ethereum_call_site_count",
        "call_indirect_count",
        "abort_call_site_count",
        "unreachable_instruction_count",
        "unreachable_function_count",
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
    unique_lexical = sum(item["semantic_invocation_contract"]["lexical_semantic_field_invocation_count"] for item in proofs)
    unique_max_expanded = sum(item["semantic_invocation_contract"]["maximum_expanded_new_position_field_invocation_count"] for item in proofs)
    weighted_lexical = sum(item["semantic_invocation_contract"]["lexical_semantic_field_invocation_count"] for item in weighted_proofs)
    weighted_max_expanded = sum(item["semantic_invocation_contract"]["maximum_expanded_new_position_field_invocation_count"] for item in weighted_proofs)
    require((unique_lexical, unique_max_expanded, weighted_lexical, weighted_max_expanded) == (250, 280, 330, 370), "semantic invocation aggregate drift")
    require(all(len(item["relation_field_authority"]) == 9 for item in proofs), "nine-field relation authority drift")
    control_boundaries = [
        item["semantic_invocation_contract"]["load_transaction_hit_or_miss_control_boundary"]
        for item in proofs
    ]
    require(
        all(
            boundary["only_id_effect_is_store_miss_conditional"]
            and boundary["common_setters_and_save_are_outside_store_miss_branch"]
            for boundary in control_boundaries
        ),
        "six-WASM loadTransaction control-boundary drift",
    )
    field_outcomes = [
        outcome
        for segment in segments
        for outcome in segment["semantic_surface"]["field_outcomes"]
    ]
    setter_path_bearing = sum(
        bool(item["setter_before_matching_save_paths"]) for item in field_outcomes
    )
    nonclassified_setter_paths = sum(
        bool(item["setter_before_matching_save_paths"])
        and not item["classified_stored_target"]
        for item in field_outcomes
    )
    derived_transaction_setter_paths = sum(
        bool(item["setter_before_matching_save_paths"])
        and item["entity"] == "Transaction"
        and item["derived_query_field"]
        for item in field_outcomes
    )
    require(
        (setter_path_bearing, nonclassified_setter_paths, derived_transaction_setter_paths)
        == (304, 0, 0),
        "aggregate classified setter-path equivalence drift",
    )
    require(
        unique == {
            "function_count": 539,
            "direct_call_count": 2424,
            "direct_target_count": 600,
            "memory_write_count": 1312,
            "generic_setter_site_count": 172,
            "named_setter_invocation_count": 126,
            "store_get_site_count": 17,
            "store_set_site_count": 18,
            "store_remove_site_count": 0,
            "schema_unset_site_count": 0,
            "ethereum_call_site_count": 12,
            "call_indirect_count": 2,
            "abort_call_site_count": 220,
            "unreachable_instruction_count": 259,
            "unreachable_function_count": 197,
        },
        "unique-six aggregate closure drift",
    )
    require(
        weighted == {
            "function_count": 725,
            "direct_call_count": 3128,
            "direct_target_count": 798,
            "memory_write_count": 1658,
            "generic_setter_site_count": 216,
            "named_setter_invocation_count": 186,
            "store_get_site_count": 21,
            "store_set_site_count": 24,
            "store_remove_site_count": 0,
            "schema_unset_site_count": 0,
            "ethereum_call_site_count": 16,
            "call_indirect_count": 2,
            "abort_call_site_count": 278,
            "unreachable_instruction_count": 333,
            "unreachable_function_count": 257,
        },
        "eight-binding aggregate closure drift",
    )
    return {
        "unique_six_mapping_physical_totals": unique,
        "eight_binding_weighted_physical_totals": weighted,
        "unique_six_lexical_semantic_field_invocation_count": unique_lexical,
        "unique_six_maximum_expanded_new_path_field_invocation_count": unique_max_expanded,
        "unique_six_physical_store_set_site_count": 18,
        "unique_six_maximum_expanded_new_path_store_set_count": 24,
        "eight_binding_lexical_semantic_field_invocation_count": weighted_lexical,
        "eight_binding_maximum_expanded_new_path_field_invocation_count": weighted_max_expanded,
        "eight_binding_physical_store_set_site_count": 24,
        "eight_binding_maximum_expanded_new_path_store_set_count": 32,
        "field_outcome_count": 2392,
        "classified_stored_target_outcome_count": 304,
        "saved_target_stored_no_setter_outcome_count": 0,
        "derived_query_field_outcome_count": 104,
        "outside_store_target_closure_outcome_count": 1984,
        "required_absent_overlay_outcome_count": 264,
        "setter_path_bearing_outcome_count": setter_path_bearing,
        "nonclassified_setter_path_outcome_count": nonclassified_setter_paths,
        "derived_transaction_setter_path_outcome_count": derived_transaction_setter_paths,
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
        "mode": "complete-path-qualified-static-npm-collect-schema-api-effect-matrix",
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
            "setter_path_bearing_outcome_count": 304,
            "nonclassified_setter_path_outcome_count": 0,
            "pairwise_recursive_diff_count": 28,
            "issue_acceptance_checkbox_completed": False,
            "claim": "complete path-qualified retained-WAT schema-API effect contract for NonfungiblePositionManager.handleCollect across eight segment bindings and six unique WASMs; it binds receiver, key, setter, constructor, store and branch order without promoting imported values, store persistence, histories, runtime parity, backfill or readiness",
        },
        "authority_contract": {
            "implementation_base_commit": IMPLEMENTATION_BASE_COMMIT,
            "implementation_base_tree": IMPLEMENTATION_BASE_TREE,
            "retained_authority_commit": RETAINED_AUTHORITY_COMMIT,
            "retained_authority_tree": RETAINED_AUTHORITY_TREE,
            "semantic_authority": "exact retained deployed NonfungiblePositionManager mapping WASM regenerated with WABT 1.0.35",
            "schema_authority": "three exact retained GraphQL schema artifacts independently match the recomputed 299-field v2 catalog",
            "transfer_v2_role": "the preceding local Transfer v2 slice supplies repository layout and CI ordering only; no Transfer verifier, contract, output, or semantic claim is loaded as Collect authority",
            "physical_vs_semantic_boundary": "physical symbols and sites are enumerated independently from profile-specific 40 or 42 lexical semantic invocations, 38 distinct field authorities, and 45 or 47 maximum expanded new-path invocations",
            "no_setter_boundary": "every Position path records only the setters it reaches before Position.save; no missing setter is described as preserved, unchanged, value-stable, or persisted",
            "setter_path_population_boundary": "a field outcome has a setter-before-save path if and only if it is one of the 38 classified stored targets; all derived and outside-closure fields have no path",
            "fatal_boundary": "non-try Factory getPool failure is bound only through the pre-fatal prefix; post-fatal execution and rollback are not modeled",
            "transaction_visibility_boundary": "the two new-path loadTransaction reads are independently classified hit or miss; both successful outcomes execute the common four setters and Transaction save, while visibility of the earlier store.set to the later store.get is unproved",
            "composition_boundary": "NPM Collect-only static provenance does not complete NPM runtime observation work in issue 37 or the full multi-handler writer-provenance acceptance in issue 38",
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
                "Position fields without a path-local setter before save are deliberately not described as preserved, unchanged, value-stable, or persisted",
                "the two new-path Transaction helper reads have independent hit/miss field-effect ledgers because intra-handler store visibility is unproved; their successful save order is fixed",
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
        require(path.is_file(), f"NPM Collect v2 contract missing: {CONTRACT_PATH}")
        actual = load_json(path)
        require(path.read_text() == render(actual), "NPM Collect v2 contract byte rendering drift")
    require(canonical_bytes(actual) == canonical_bytes(expected), "NPM Collect v2 contract differs from generated proof")
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
        print(f"NPM Collect v2 verification failed: {error}", file=sys.stderr)
        return 1
    print(
        "verified Uniswap V3 NPM Collect v2: "
        f"{result['scope']['segment_binding_count']} bindings, "
        f"{result['scope']['unique_npm_wasm_count']} WASMs, "
        f"{result['scope']['field_outcome_count']} outcomes, "
        f"{len(result['segment_diffs'])} diffs; no issue checkbox completed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
