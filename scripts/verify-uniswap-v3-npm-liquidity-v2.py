#!/usr/bin/env python3
"""Build or verify the paired retained-WAT NPM Liquidity v2 certificate."""

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
CONTRACT_PATH = Path("uniswap-v3/npm-liquidity/v2/contract.json")
CONTRACT_VERSION = "uniswap-v3-npm-liquidity/v2"
HANDLERS = {
    "increase": {
        "handler_id": "NonfungiblePositionManager.handleIncreaseLiquidity",
        "export": "handleIncreaseLiquidity",
        "function": "src/mappings/position-manager/handleIncreaseLiquidity",
        "field_keys": ["liquidity", "depositedToken0", "depositedToken1"],
        "numeric_call": "plus",
    },
    "decrease": {
        "handler_id": "NonfungiblePositionManager.handleDecreaseLiquidity",
        "export": "handleDecreaseLiquidity",
        "function": "src/mappings/position-manager/handleDecreaseLiquidity",
        "field_keys": ["liquidity", "withdrawnToken0", "withdrawnToken1"],
        "numeric_call": "minus",
    },
}

IMPLEMENTATION_BASE_COMMIT = "5ad75eca9857176e9a9ecdfa6aeff6dd2a763312"
IMPLEMENTATION_BASE_TREE = "78ae066e45d0175f9efd858969c1d8dd8c968ac3"
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

COUNT_FIELDS = (
    "function_count", "direct_call_count", "direct_target_count",
    "memory_write_count", "generic_setter_site_count",
    "named_setter_invocation_count", "store_get_site_count",
    "store_set_site_count", "store_remove_site_count",
    "schema_unset_site_count", "ethereum_call_site_count",
    "call_indirect_count", "abort_call_site_count",
    "unreachable_instruction_count", "unreachable_function_count",
)


def _counts(*values: int) -> dict[str, int]:
    return dict(zip(COUNT_FIELDS, values, strict=True))


def _handler_record(
    body: str,
    normalized: str,
    shape: str,
    call_sequence: str,
    normalized_call_sequence: str,
    call_count: int,
    function_index: int,
    start_line: int,
    closure_sha256: str,
) -> dict[str, Any]:
    return {
        "body_sha256": body,
        "normalized_body_sha256": normalized,
        "instruction_shape_sha256": shape,
        "call_sequence_sha256": call_sequence,
        "normalized_call_sequence_sha256": normalized_call_sequence,
        "call_count": call_count,
        "wat_function_index": function_index,
        "wat_start_line": start_line,
        "closure_sha256": closure_sha256,
    }


MAPPING_EXPECTATIONS = {
    "QmYWR79pUmVbQ42JkvB24D6AKCGtdo4UG78ZSewmFxwQdR": {
        "profile_id": "legacy-no-block-guard",
        "generation": "legacy-generated-setters",
        "bytes": 20_794,
        "raw_sha256": "3ad2abc957362fa5fa62ef8bb762ab3b38676d1139d1ca85ee0db2b25ade9fca",
        "wat_sha256": "93cf89c0ac5f8af930c4a4a1b273a6831dced3247104db4585b6d6284da789a2",
        "handlers": {
            "increase": {
                "counts": _counts(108, 414, 119, 177, 22, 33, 3, 3, 0, 0, 2, 0, 29, 38, 31),
                "record": _handler_record(
                    "fbe685f95d0c0f0264a8e79f8d81ad484e0523f9e285857f35156a02534d2231",
                    "fbe685f95d0c0f0264a8e79f8d81ad484e0523f9e285857f35156a02534d2231",
                    "fbe685f95d0c0f0264a8e79f8d81ad484e0523f9e285857f35156a02534d2231",
                    "606d9a4199615ea710751d003f1e5fd88ecc3dba5687a7269c35977cabf873b1",
                    "606d9a4199615ea710751d003f1e5fd88ecc3dba5687a7269c35977cabf873b1",
                    35, 122, 4049,
                    "b95d828bf5e35593e3354029147f7e51dfa19389bf0d3f8dfb16ec977d93cb3b",
                ),
            },
            "decrease": {
                "counts": _counts(108, 414, 120, 177, 22, 33, 3, 3, 0, 0, 2, 0, 29, 38, 31),
                "record": _handler_record(
                    "a06e7b47650a60d1890c670dad6b3147f5ddb9af6a61f44a6d517b211e04e11a",
                    "a06e7b47650a60d1890c670dad6b3147f5ddb9af6a61f44a6d517b211e04e11a",
                    "a06e7b47650a60d1890c670dad6b3147f5ddb9af6a61f44a6d517b211e04e11a",
                    "ebec064317c63502374b2d9f23d85fa4b0ca8dce71691d11e08c7302861a009e",
                    "ebec064317c63502374b2d9f23d85fa4b0ca8dce71691d11e08c7302861a009e",
                    35, 123, 4123,
                    "6fea58181e73e12bc1d6fd2dc9fa35c64a28ccb36c5f856ae8391e12b44c669b",
                ),
            },
        },
        "union_counts": _counts(109, 449, 120, 177, 22, 36, 3, 3, 0, 0, 2, 0, 29, 38, 31),
        "union_closure_sha256": "cb526a18e6120a483c2c8c151fd86a9e7b0a3cf8bd00ac0da10f5f16bf24dff6",
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
        "handlers": {
            "increase": {
                "counts": _counts(106, 412, 117, 177, 22, 33, 3, 3, 0, 0, 2, 0, 29, 38, 31),
                "record": _handler_record(
                    "fbe685f95d0c0f0264a8e79f8d81ad484e0523f9e285857f35156a02534d2231",
                    "fbe685f95d0c0f0264a8e79f8d81ad484e0523f9e285857f35156a02534d2231",
                    "fbe685f95d0c0f0264a8e79f8d81ad484e0523f9e285857f35156a02534d2231",
                    "606d9a4199615ea710751d003f1e5fd88ecc3dba5687a7269c35977cabf873b1",
                    "606d9a4199615ea710751d003f1e5fd88ecc3dba5687a7269c35977cabf873b1",
                    35, 120, 4043,
                    "84156b429aa86df7d0160ace192a8da5f6f819daa19ef1b61215c654ec4cb607",
                ),
            },
            "decrease": {
                "counts": _counts(106, 412, 118, 177, 22, 33, 3, 3, 0, 0, 2, 0, 29, 38, 31),
                "record": _handler_record(
                    "a06e7b47650a60d1890c670dad6b3147f5ddb9af6a61f44a6d517b211e04e11a",
                    "a06e7b47650a60d1890c670dad6b3147f5ddb9af6a61f44a6d517b211e04e11a",
                    "a06e7b47650a60d1890c670dad6b3147f5ddb9af6a61f44a6d517b211e04e11a",
                    "ebec064317c63502374b2d9f23d85fa4b0ca8dce71691d11e08c7302861a009e",
                    "ebec064317c63502374b2d9f23d85fa4b0ca8dce71691d11e08c7302861a009e",
                    35, 121, 4117,
                    "5ceafc6a163f14837008ab38ff9e58b33378fe0228e37c1528ec64242f059858",
                ),
            },
        },
        "union_counts": _counts(107, 447, 118, 177, 22, 36, 3, 3, 0, 0, 2, 0, 29, 38, 31),
        "union_closure_sha256": "5cf1eddf3fa1b4f617a0698cf48187a2d3d5d3647a6c92d5200927ee56c7e930",
    },
    "QmUk7jc3c8joQBrrcTz2ZEVDKcg1P12G2nFtuNqiikDQLJ": {
        "same_as": "QmYWR79pUmVbQ42JkvB24D6AKCGtdo4UG78ZSewmFxwQdR",
        "profile_id": "legacy-block-guard",
        "bytes": 20_876,
        "raw_sha256": "e25dad1c3b6f1892eee2a8f51da62bb57268286deb9a135d6a689bdca1ad0034",
        "wat_sha256": "4370c99e82c40e311a7a3d9c23ff0a61ed0dfd04feb9d737727308400ce03d12",
        "handlers": {
            "increase": {
                "counts": _counts(109, 417, 120, 177, 22, 33, 3, 3, 0, 0, 2, 0, 29, 38, 31),
                "record": _handler_record(
                    "52b16a98927cef810ebddf9b6073b7c9edb91f5b83b2d8459b7add631bbbb2bf",
                    "52b16a98927cef810ebddf9b6073b7c9edb91f5b83b2d8459b7add631bbbb2bf",
                    "07a262cc52294ccfae8365fb75cda73ac4c87839a712a526012034aba7a03d23",
                    "5a41083af0e76fbba8a1120b8496106a9ffa2e12c1826e184f0b8d0348216f25",
                    "5a41083af0e76fbba8a1120b8496106a9ffa2e12c1826e184f0b8d0348216f25",
                    37, 123, 4053,
                    "b7d91741532a2d46d95da3635115dfd36165a1f26507b629c53f51007b9f142c",
                ),
            },
            "decrease": {
                "counts": _counts(109, 417, 121, 177, 22, 33, 3, 3, 0, 0, 2, 0, 29, 38, 31),
                "record": _handler_record(
                    "8f64d93ce4f48aa9e045e3cd2c0cbff84cf1bdc659163f8aa00624fa788e2199",
                    "8f64d93ce4f48aa9e045e3cd2c0cbff84cf1bdc659163f8aa00624fa788e2199",
                    "18cce06be69f0d5dac04977a722fbce351a1e9a97a8cc140e914588338db9428",
                    "cafbf25516910befb20197c35b933e372b8e5a5ecade0e62789465f147279822",
                    "cafbf25516910befb20197c35b933e372b8e5a5ecade0e62789465f147279822",
                    37, 124, 4136,
                    "473ff740495daaa0973e77a624cfae849e2e56955b3c12be03d3b25c8dcbffa6",
                ),
            },
        },
        "union_counts": _counts(110, 454, 121, 177, 22, 36, 3, 3, 0, 0, 2, 0, 29, 38, 31),
        "union_closure_sha256": "a6ff74a96a1487c742212ba070077d4964aa4af67cd1f10a09fd9f4670cc42a9",
    },
    "QmWxG1yzdQmp4pRDiqKvTZyRrrrZPRUTza6xznjR1wu1sD": {
        "profile_id": "current-block-guard",
        "generation": "current-generic-setters",
        "bytes": 48_593,
        "raw_sha256": "34487685c81672436f34b79f3749f41e6b3c724b52dd8cb24b933e3cb5006124",
        "wat_sha256": "6febde6b56e441b694f1708821a5e507f766ddfac3056a8efbce026826a9dced",
        "handlers": {
            "increase": {
                "counts": _counts(64, 449, 75, 310, 43, 0, 4, 3, 0, 0, 2, 1, 53, 55, 38),
                "record": _handler_record(
                    "737ca670264596e7f5ea57dc5e0e617b5f44b57e0ffde705ebb865016feb8437",
                    "03a5f5526aa9785c2139d5b21090b4ceaf9605b43fc3b1646528658fa67c2da0",
                    "56829d1cc02530cba7b026ce6d1f14949c41d9edbd6604338a7acb15e0736893",
                    "c2900be5b860b628573e9e166c02ff1bad6c695150231a1088f2efc728b4b44c",
                    "c2900be5b860b628573e9e166c02ff1bad6c695150231a1088f2efc728b4b44c",
                    45, 78, 5551,
                    "6fc88cccc7098858041a806bbd0edb6c1e7a4ac54f083ff6a3531af0d81461d4",
                ),
            },
            "decrease": {
                "counts": _counts(64, 450, 76, 310, 43, 0, 4, 3, 0, 0, 2, 1, 54, 56, 39),
                "record": _handler_record(
                    "c4191373a33bd95ed8828191bc8078d7c6821b111fdc471f1bef47884b553e7e",
                    "039d0cb7f8b479740da29ccb153cf67380bc0f22e3097ae4376316dceed5d794",
                    "01341a5171f9cfc5282af0d88e805dd5b8654b445dd906e79f84479c8d1c5a5c",
                    "b2b1d89bdf97ab69888f3c7e8d3fd77e887336920e177be8d3e1dcfc6d0852c1",
                    "b2b1d89bdf97ab69888f3c7e8d3fd77e887336920e177be8d3e1dcfc6d0852c1",
                    46, 79, 5748,
                    "1bf938b93c083c2eb6200c7a4d6e321e1c65a89eea1a66f1c25bddd6ee2deb1c",
                ),
            },
        },
        "union_counts": _counts(65, 495, 76, 326, 46, 0, 6, 3, 0, 0, 2, 1, 54, 56, 39),
        "union_closure_sha256": "356f19118f615ddd35a4b6304ef57011420d82eb29a79ccdb45124acbd024466",
    },
    "QmPjhEuGqknJJ2LfJCi6XTLFLtiymYfZAtjTLfkmJJGMEj": {
        "same_as": "QmWxG1yzdQmp4pRDiqKvTZyRrrrZPRUTza6xznjR1wu1sD",
        "bytes": 48_657,
        "raw_sha256": "6338f6b3b2071d0599b8381c948070ca138827bd61b6e5e05eb0d112177b0c91",
        "wat_sha256": "2ca2b971161bb406b60ddf8d0d486ee02c3599dedb72c3c9c9dad9f6e63dd8ca",
        "handlers": {
            "increase": {
                "counts": _counts(64, 449, 75, 310, 43, 0, 4, 3, 0, 0, 2, 1, 53, 55, 38),
                "record": _handler_record(
                    "c3ff8aff1150b654139fb2dde3b6818314ec82b530cc401709723262d0ac7f22",
                    "03a5f5526aa9785c2139d5b21090b4ceaf9605b43fc3b1646528658fa67c2da0",
                    "56829d1cc02530cba7b026ce6d1f14949c41d9edbd6604338a7acb15e0736893",
                    "bcbbe430a090e99dccee8a3cd88c82349808a0fd764d94beb156904707d964f1",
                    "c2900be5b860b628573e9e166c02ff1bad6c695150231a1088f2efc728b4b44c",
                    45, 78, 5551,
                    "b09cb186fb880b87c55110f4ae6222e346559b05f06225ae6c1524b8198ab53a",
                ),
            },
            "decrease": {
                "counts": _counts(64, 450, 76, 310, 43, 0, 4, 3, 0, 0, 2, 1, 54, 56, 39),
                "record": _handler_record(
                    "e20fd0c3c22f1dabcfe6c8d052f4befa5b47b53a9383203ac8f48c09cdb19f05",
                    "039d0cb7f8b479740da29ccb153cf67380bc0f22e3097ae4376316dceed5d794",
                    "01341a5171f9cfc5282af0d88e805dd5b8654b445dd906e79f84479c8d1c5a5c",
                    "8461260742d271b913192c67f4dacaaf502e28907cf625f65c09391ca0ac05cd",
                    "b2b1d89bdf97ab69888f3c7e8d3fd77e887336920e177be8d3e1dcfc6d0852c1",
                    46, 79, 5748,
                    "480a0b600eb9ec8315a6d4a87bf311326aa8e3f3a9bced3b2bb3748b5c99d385",
                ),
            },
        },
        "union_counts": _counts(65, 495, 76, 326, 46, 0, 6, 3, 0, 0, 2, 1, 54, 56, 39),
        "union_closure_sha256": "1b7ea91101f719c56fdbefd6e8a6496b13783cadaa20afcf241e02a40b1c36e8",
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
CATEGORY_OUTSIDE = "stored_field_outside_npm_liquidity_store_target_closure"

TRUE_FLAGS = (
    "exact_direct_roots_digest_bound_and_recomputed",
    "exact_six_retained_npm_wasms_regenerated_with_wabt_1_0_35",
    "all_eight_segment_bindings_resolved",
    "all_reachable_direct_calls_and_function_bodies_bound",
    "all_reachable_memory_writes_bound",
    "all_generic_named_constructor_unset_and_store_sites_accounted",
    "closed_call_indirect_table_target_proven",
    "all_three_store_targets_and_profile_specific_store_read_sites_bound",
    "both_handlers_accepted_existing_new_revert_fatal_excluded_token_null_and_trap_path_order_bound",
    "all_thirty_eight_distinct_stored_targets_classified",
    "all_nine_relation_and_transaction_field_receiver_key_source_paths_bound",
    "each_handler_has_eight_independent_299_outcome_segments",
    "all_528_independent_required_absent_outcomes_present",
    "derived_paired_union_has_2392_outcomes_and_264_overlays",
    "all_twenty_eight_recursive_segment_diffs_present_for_each_handler_and_union",
    "all_eight_within_segment_handler_diffs_present",
    "path_qualified_complete_static_paired_npm_liquidity_contract",
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
    "increase_liquidity_arithmetic_semantics_complete",
    "decrease_liquidity_arithmetic_semantics_complete",
    "legacy_params_type_alias_semantics_complete",
    "paired_handler_event_order_complete",
    "paired_handler_sequential_composition_complete",
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
    "uniswap_v3_segment_field_semantics_v2_for_npm_liquidity_v2",
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


def _transaction_helper_contract(
    function: Any,
    memory: bytearray,
    generation: str,
    store_callsites: list[dict[str, Any]],
) -> dict[str, Any]:
    """Bind the loadTransaction store-null branch without importing another slice."""

    fields = list(TRANSACTION_FIELDS)
    field_set = set(fields)
    call_sites = WRITER.function_call_sites(function)
    store_get_call_sites = [
        (index, target)
        for index, target in call_sites
        if target.endswith("/store.get")
    ]
    require(
        [index for index, _target in store_get_call_sites] == [7],
        "loadTransaction store.get placement drift",
    )
    store_get_index, store_get_target = store_get_call_sites[0]
    require(
        store_get_target.endswith("/store.get"),
        "loadTransaction store.get target suffix drift",
    )
    branch_starts = [
        index
        for index in range(store_get_index + 1, len(function.lines))
        if function.lines[index].strip().startswith("if ")
    ]
    require(branch_starts, "loadTransaction store-null branch missing")
    branch_start = branch_starts[0]
    require(
        [line.strip() for line in function.lines[store_get_index + 1 : branch_start]]
        == ["local.tee $l1", "i32.eqz"],
        "loadTransaction store-null guard shape drift",
    )
    branch_end = WRITER.matching_end(
        function.lines,
        branch_start,
        "loadTransaction store-null branch",
    )

    decoded_key: tuple[str, int] | None = None
    field_sites: dict[str, list[dict[str, Any]]] = {field: [] for field in fields}
    constructor_sites: list[dict[str, Any]] = []
    generic_setter_suffix = "TypedMap<~lib/string/String_~lib/@graphprotocol/graph-ts/common/value/Value>#set"
    legacy_generic_setter_suffix = "TypedMap<~lib/string/String_~lib/@graphprotocol/graph-ts/index/Value>#set"
    for index, line in enumerate(function.lines):
        match = WRITER.I32_CONST_RE.fullmatch(line)
        if match is not None:
            value = WRITER.decode_assemblyscript_string(memory, int(match.group(1)))
            if value in field_set:
                decoded_key = (value, index)
        call_match = WRITER.CALL_RE.search(line)
        if call_match is None:
            continue
        target = call_match.group(1)
        if target.endswith("Position#constructor") or target.endswith("Entity#constructor"):
            constructor_sites.append({
                **_site(function, index, target),
                "inside_store_null_branch": branch_start < index < branch_end,
            })
        named = re.fullmatch(r"(?:src/types/schema|generated/schema)/Transaction#set:([^#]+)", target)
        if named is not None and named.group(1) in field_set:
            field_sites[named.group(1)].append({
                **_site(function, index, target),
                "decoded_key_line_index": None,
                "inside_store_null_branch": branch_start < index < branch_end,
            })
        elif target.endswith(generic_setter_suffix) or target.endswith(legacy_generic_setter_suffix):
            require(decoded_key is not None, "loadTransaction generic setter lacks a decoded field key")
            key, key_index = decoded_key
            field_sites[key].append({
                **_site(function, index, target),
                "decoded_key_line_index": key_index,
                "inside_store_null_branch": branch_start < index < branch_end,
            })
            decoded_key = None

    legacy = generation.startswith("legacy")
    require(len(constructor_sites) == 1, "loadTransaction constructor count drift")
    require(constructor_sites[0]["inside_store_null_branch"], "loadTransaction constructor escaped null branch")
    if legacy:
        require(not field_sites["id"], "legacy loadTransaction invented an explicit id setter")
        id_effect = {
            "field": "id",
            "effect_model": "constructor_carried",
            "site": constructor_sites[0],
            "inside_store_null_branch": True,
        }
    else:
        require(len(field_sites["id"]) == 1, "current loadTransaction id setter count drift")
        require(field_sites["id"][0]["inside_store_null_branch"], "current loadTransaction id setter escaped null branch")
        id_effect = {
            "field": "id",
            "effect_model": "explicit_generic_id_set",
            "site": field_sites["id"][0],
            "inside_store_null_branch": True,
        }

    unconditional_fields = fields[1:]
    for field in unconditional_fields:
        require(len(field_sites[field]) == 1, f"loadTransaction {field} setter count drift")
        require(
            field_sites[field][0]["function_line_index"] > branch_end
            and not field_sites[field][0]["inside_store_null_branch"],
            f"loadTransaction {field} setter became null-branch-only",
        )
    unconditional_sites = [field_sites[field][0] for field in unconditional_fields]
    require(
        [item["function_line_index"] for item in unconditional_sites]
        == sorted(item["function_line_index"] for item in unconditional_sites),
        "loadTransaction unconditional setter order drift",
    )

    if legacy:
        legacy_save_sites = [
            (index, target)
            for index, target in call_sites
            if target.endswith("schema/Transaction#save")
        ]
        require(len(legacy_save_sites) == 1, "legacy loadTransaction save count drift")
        store_line_index, store_call_target = legacy_save_sites[0]
        store_record = {
            "target": "Transaction",
            "site_id": f"{function.name}#Transaction.save",
            "wat_line": function.start_line + store_line_index,
            "call_target": store_call_target,
        }
    else:
        helper_stores = [
            item for item in store_callsites if item["function"] == function.name
        ]
        require(len(helper_stores) == 1, "current loadTransaction store.set count drift")
        require(helper_stores[0]["target"] == "Transaction", "loadTransaction store target drift")
        store_line_index = int(helper_stores[0]["wat_line"]) - int(function.start_line)
        store_record = helper_stores[0]
    require(store_line_index > branch_end, "loadTransaction store.set became null-branch-only")
    require(
        store_line_index > unconditional_sites[-1]["function_line_index"],
        "loadTransaction store.set moved before unconditional setters",
    )

    hit_fields = unconditional_fields
    miss_fields = fields
    return {
        "function": function.name,
        "store_get_site": _site(function, store_get_index, store_get_target),
        "store_null_branch": {
            "function_line_start": branch_start,
            "function_line_end": branch_end,
            "wat_line_start": function.start_line + branch_start,
            "wat_line_end": function.start_line + branch_end,
            "guarded_effect_fields": ["id"],
        },
        "constructor_site": constructor_sites[0],
        "id_effect": id_effect,
        "unconditional_field_effects": [
            {"field": field, "site": field_sites[field][0]}
            for field in unconditional_fields
        ],
        "unconditional_store_set": {
            "target": "Transaction",
            "site_id": store_record["site_id"],
            "wat_line": store_record["wat_line"],
            "call_target": store_record.get("call_target", "~lib/@graphprotocol/graph-ts/index/store.set"),
            "function_line_index": store_line_index,
            "outside_store_null_branch": True,
        },
        "store_hit": {
            "field_effects": hit_fields,
            "field_effect_count": len(hit_fields),
            "store_set_count": 1,
        },
        "store_miss": {
            "field_effects": miss_fields,
            "field_effect_count": len(miss_fields),
            "store_set_count": 1,
        },
        "hit_and_miss_both_reach_transaction_store_set_unless_a_pre_store_trap_occurs": True,
    }


def _semantic_functions(
    cid: str,
    handler_key: str,
    functions: dict[str, Any],
    closure: set[str],
    memory: bytearray,
    generation: str,
    profile_id: str,
    store_callsites: list[dict[str, Any]],
) -> dict[str, Any]:
    handler_spec = HANDLERS[handler_key]
    names = {
        "handler": handler_spec["function"],
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

    transaction_helper = _transaction_helper_contract(
        functions[names["load_transaction"]],
        memory,
        generation,
        store_callsites,
    )

    handler = functions[names["handler"]]
    handler_calls = WRITER.function_calls(handler)
    if generation.startswith("legacy"):
        handler_keys = [
            match.group(1)
            for call in handler_calls
            if (match := re.fullmatch(r"src/types/schema/Position#set:([^#]+)", call))
        ]
        token_reads = sum(call.endswith("schema/Token.load") for call in handler_calls)
    else:
        handler_keys = [
            value for value in WRITER.function_static_strings(handler, memory)
            if value in set(handler_spec["field_keys"])
        ]
        token_reads = sum(call.endswith("/store.get") for call in handler_calls)
    require(handler_keys == handler_spec["field_keys"], f"{cid} {handler_key} setter-key order drift")
    require(token_reads == 2, f"{cid} {handler_key} Token-read count drift")

    historical_guard = WRITER.historical_guard_proof(handler)
    if profile_id == "legacy-no-block-guard":
        require(historical_guard is None, f"{cid} {handler_key} invented historical block guard")
    else:
        require(historical_guard is not None, f"{cid} {handler_key} historical block guard missing")
        expected_model = (
            "old-codegen-byte-array-equality"
            if profile_id == "legacy-block-guard"
            else "modern-big-int-compare-equals-zero"
        )
        expected_prefix = (
            "31c442d1d8d775341c87e5d7df3927aaad6c43326b787165f86c347da396a35a"
            if profile_id == "legacy-block-guard"
            else "434bb4f48fa30b526ac96f35150d0a7f95d3c3eeff52e1da7979e6a89bfedfbd"
        )
        require(historical_guard["block"] == 14_317_993, f"{cid} {handler_key} historical block drift")
        require(historical_guard["comparison_model"] == expected_model, f"{cid} {handler_key} guard model drift")
        require(historical_guard["instruction_prefix_sha256"] == expected_prefix, f"{cid} {handler_key} guard prefix drift")
    require(
        any(
            "0x8fe8d9bb8eeba3ed688069c3d6b556c9ca258248"
            in WRITER.function_static_strings(functions[name], memory)
            for name in closure
        ),
        f"{cid} {handler_key} excluded-pool literal drift",
    )
    get_position_index = next(i for i, call in enumerate(handler_calls) if call.endswith("/getPosition"))
    equals_index = next(i for i, call in enumerate(handler_calls) if call.endswith("ByteArray#equals"))
    token_read_indexes = [
        i for i, call in enumerate(handler_calls)
        if call.endswith("schema/Token.load") or call.endswith("/store.get")
    ]
    numeric_index = next(
        i for i, call in enumerate(handler_calls)
        if call.endswith("BigInt#plus") or call.endswith("bigInt.minus")
    )
    handler_setter_indexes = []
    if generation.startswith("legacy"):
        handler_setter_indexes = [
            i for i, call in enumerate(handler_calls)
            if re.fullmatch(r"src/types/schema/Position#set:(?:liquidity|depositedToken[01]|withdrawnToken[01])", call)
        ]
    else:
        handler_setter_indexes = [
            i for i, call in enumerate(handler_calls)
            if call.endswith("TypedMap<~lib/string/String_~lib/@graphprotocol/graph-ts/common/value/Value>#set")
        ]
    update_index = next(i for i, call in enumerate(handler_calls) if call.endswith("/updateFeeVars"))
    position_save_index = next(i for i, call in enumerate(handler_calls) if call.endswith("schema/Position#save"))
    snapshot_index = next(i for i, call in enumerate(handler_calls) if call.endswith("/savePositionSnapshot"))
    require(len(token_read_indexes) == 2, f"{cid} {handler_key} Token read indexes drift")
    require(len(handler_setter_indexes) == 3, f"{cid} {handler_key} setter site count drift")
    require(
        get_position_index < equals_index < token_read_indexes[0] < token_read_indexes[1]
        < numeric_index < handler_setter_indexes[0] < handler_setter_indexes[1]
        < handler_setter_indexes[2] < update_index < position_save_index < snapshot_index,
        f"{cid} {handler_key} handler prefix order drift",
    )
    expected_numeric_suffix = "BigInt#plus" if handler_key == "increase" else "bigInt.minus"
    require(handler_calls[numeric_index].endswith(expected_numeric_suffix), f"{cid} {handler_key} numeric-call identity drift")
    abort_indexes = [i for i, call in enumerate(handler_calls) if call.endswith("/abort")]
    if generation.startswith("current") and handler_key == "decrease":
        require(abort_indexes == [28], f"{cid} current decrease null-liquidity abort drift")
        require(abort_indexes[0] < numeric_index, f"{cid} decrease abort order drift")
    else:
        require(not abort_indexes, f"{cid} {handler_key} invented handler abort")

    legacy_params = sorted({call for call in handler_calls if "Liquidity__Params" in call})
    if generation.startswith("legacy"):
        require(legacy_params and all("IncreaseLiquidity__Params" in call for call in legacy_params), f"{cid} legacy Params alias drift")
        require(not any("DecreaseLiquidity__Params" in call for call in handler_calls), f"{cid} legacy Decrease Params appeared")
    else:
        require(not legacy_params, f"{cid} current generated Params symbol drift")

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
    return {
        "functions": result,
        "handler_key": handler_key,
        "handler_id": handler_spec["handler_id"],
        "handler_setter_keys": handler_keys,
        "handler_setter_count": len(handler_keys),
        "lexical_semantic_field_invocation_count": 43,
        "distinct_semantic_field_count": 38,
        "maximum_expanded_new_position_field_invocation_count": 48,
        "maximum_expanded_existing_position_field_invocation_count": 26,
        "lexical_semantic_invocation_ledger": [
            {"function": names["get_position"], "field_invocation_count": 17, "multiplicity": "one only when Position is missing"},
            {"function": names["handler"], "field_invocation_count": 3, "multiplicity": "one on the accepted non-excluded non-null-token suffix"},
            {"function": names["update_fee_vars"], "field_invocation_count": 2, "multiplicity": "zero on try_positions revert, otherwise one each"},
            {"function": names["save_snapshot"], "field_invocation_count": 16, "multiplicity": "one after Position.save unless a prior fatal or trap stops the prefix"},
            {"function": names["load_transaction"], "field_invocation_count": 5, "multiplicity": "once on its store-miss branch; helper is invoked once for existing Position and twice for new Position"},
        ],
        "position_constructor_setter_order": list(POSITION_FIELDS),
        "snapshot_constructor_setter_order": list(SNAPSHOT_FIELDS),
        "transaction_miss_constructor_setter_order": list(TRANSACTION_FIELDS),
        "fee_refresh_setter_order": ["feeGrowthInside0LastX128", "feeGrowthInside1LastX128"],
        "handler_prefix_call_indexes": {
            "historical_guard_calls": [0, 1] if historical_guard else [],
            "get_position": get_position_index,
            "excluded_pool_equals": equals_index,
            "token_reads": token_read_indexes,
            "numeric_operator": numeric_index,
            "handler_setters": handler_setter_indexes,
            "null_liquidity_abort": abort_indexes,
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
        "historical_guard": historical_guard,
        "legacy_decrease_uses_increase_liquidity_params_symbols": generation.startswith("legacy") and handler_key == "decrease",
        "legacy_params_alias_meaning_complete": False,
        "numeric_operator_result_reaches_liquidity_setter": True,
        "numeric_operator_meaning_complete": False,
        "schema_unset_invocation_count": 0,
        "transaction_helper_contract": transaction_helper,
    }


def _path_contract(
    handler_key: str,
    profile_id: str,
    generation: str,
    api_version: str,
    transaction_helper: dict[str, Any],
) -> dict[str, Any]:
    legacy = generation.startswith("legacy")
    normal_reads = (4, 5) if legacy else (5, 6)
    transaction_hit = transaction_helper["store_hit"]["field_effect_count"]
    transaction_miss = transaction_helper["store_miss"]["field_effect_count"]
    require((transaction_hit, transaction_miss) == (4, 5), "loadTransaction path denominator drift")
    require(
        transaction_helper["store_hit"]["store_set_count"]
        == transaction_helper["store_miss"]["store_set_count"]
        == 1,
        "loadTransaction unconditional store denominator drift",
    )
    new_position_prefixes = [17 + transaction_hit, 17 + transaction_miss]
    decrease_null_present = handler_key == "decrease" and not legacy
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
                "fee_refresh_success_transaction_hit": 3 + 2 + 16 + transaction_hit,
                "fee_refresh_success_transaction_miss": 3 + 2 + 16 + transaction_miss,
                "fee_refresh_revert_transaction_hit": 3 + 16 + transaction_hit,
                "fee_refresh_revert_transaction_miss": 3 + 16 + transaction_miss,
            },
            "store_set_orders": [["Position", "Transaction", "PositionSnapshot"]],
            "field_effect_order": [
                "three handler-local Position setter edges in handler-specific field order",
                "updateFeeVars zero-or-two fee-growth setter edges",
                "Position save",
                "first thirteen PositionSnapshot constructor/setter edges through collectedFeesToken1",
                "Transaction four-field hit or five-field miss ledger followed by an unconditional Transaction save",
                "final PositionSnapshot transaction and two fee-growth setter edges",
                "PositionSnapshot save",
            ],
            "position_fields_without_setter_are_preserved_or_unchanged": False,
        },
        "accepted_new_position": {
            "guard": "Position store.get is null, try_positions is not reverted, and non-try Factory getPool returns",
            "contract_call_count": 3,
            "expanded_store_get_count": normal_reads[1],
            "field_effect_counts": {
                "fee_refresh_success_zero_transaction_misses": 17 + transaction_hit + 3 + 2 + 16 + transaction_hit,
                "fee_refresh_success_one_transaction_miss": 17 + transaction_hit + 3 + 2 + 16 + transaction_miss,
                "fee_refresh_success_two_transaction_misses": 17 + transaction_miss + 3 + 2 + 16 + transaction_miss,
                "fee_refresh_revert_zero_transaction_misses": 17 + transaction_hit + 3 + 16 + transaction_hit,
                "fee_refresh_revert_one_transaction_miss": 17 + transaction_hit + 3 + 16 + transaction_miss,
                "fee_refresh_revert_two_transaction_misses": 17 + transaction_miss + 3 + 16 + transaction_miss,
            },
            "store_set_orders": [["Transaction", "Position", "Transaction", "PositionSnapshot"]],
            "field_effect_order": [
                "first fourteen Position getPosition constructor/setter edges through collectedFeesToken1 including provisional owner",
                "first Transaction four-field hit or five-field miss ledger followed by an unconditional Transaction save",
                "final Position transaction and two fee-growth setter edges",
                "three handler-local Position setter edges in handler-specific field order",
                "updateFeeVars zero-or-two fee-growth setter edges",
                "Position save",
                "first thirteen PositionSnapshot constructor/setter edges through collectedFeesToken1",
                "second Transaction four-field hit or five-field miss ledger followed by an unconditional Transaction save",
                "final PositionSnapshot transaction and two fee-growth setter edges",
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
            "new_path_field_effect_counts": new_position_prefixes,
            "new_path_store_orders": [["Transaction"]],
            "guard_precedes_handler_amount_update_position_save_and_snapshot": True,
        },
        "token_branch": {
            "token_read_model": "two generated Token.load calls" if legacy else "two direct store.get calls decoded as Token",
            "either_token_missing_or_null_stops_before_all_handler_setters_update_position_save_and_snapshot": True,
            "legacy_missing_token_is_a_fatal_prefix": legacy,
            "current_null_token_is_a_normal_early_return_prefix": not legacy,
            "existing_position_schema_field_effect_count_before_stop": 0,
            "new_position_schema_field_effect_counts_before_stop": new_position_prefixes,
            "new_position_store_orders_before_stop": [["Transaction"]],
        },
        "decrease_null_liquidity_branch": {
            "present_as_explicit_abort_only_in_current_generation": decrease_null_present,
            "abort_precedes_minus_and_all_three_handler_setters": decrease_null_present,
            "existing_position_schema_field_effect_count_before_fatal": 0 if decrease_null_present else None,
            "new_position_schema_field_effect_counts_before_fatal": new_position_prefixes if decrease_null_present else [],
            "new_position_store_orders_before_fatal": [["Transaction"]] if decrease_null_present else [],
            "post_fatal_execution_modeled": False,
        },
        "update_fee_vars_revert": {
            "setter_count": 0,
            "caller_continues_to_position_save_and_snapshot": True,
            "store_orders_unchanged_from_corresponding_accepted_path": True,
        },
        "trap_prefixes": {
            "position_save_trap": "no Position or PositionSnapshot store; a completed new-position getPosition path already has one Transaction store on both helper hit and miss",
            "snapshot_required_getter_or_save_trap": "Position store already precedes the snapshot helper; the second Transaction store exists if either the hit or miss helper completed before a later snapshot trap",
            "load_transaction_hit_or_miss_pre_store_trap": "no Transaction store from the trapping invocation; on the snapshot invocation Position already precedes it, and a new-position path also retains the first completed Transaction store",
            "physical_abort_and_unreachable_sites_are_not_achievable_path_counts": True,
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
        "liquidity_excluded_pool_guard_bound": True,
        "historical_block_guard": {
            "present": profile_id != "legacy-no-block-guard",
            "block": 14_317_993 if profile_id != "legacy-no-block-guard" else None,
            "model": (
                "none" if profile_id == "legacy-no-block-guard" else
                "old-codegen-byte-array-equality" if profile_id == "legacy-block-guard" else
                "modern-big-int-compare-equals-zero"
            ),
            "early_return_has_zero_schema_store_or_contract_call_effects": True,
        },
        "handler_key": handler_key,
        "handler_setter_order": HANDLERS[handler_key]["field_keys"],
        "handler_numeric_operator_result_reaches_liquidity_setter": True,
        "handler_numeric_semantics_complete": False,
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


def _shared_transaction_contract(transaction_helper: dict[str, Any]) -> dict[str, Any]:
    return {
        "key_source": "event transaction hash reaches the bytes-to-hex call chain used for Transaction store.get and ID construction",
        "retained_wat_control_contract": transaction_helper,
        "load_transaction_hit": "classifies blockNumber, timestamp, gasUsed and gasPrice, then reaches Transaction store.set unless a pre-store trap occurs",
        "load_transaction_miss": "additionally classifies id inside the store-null constructor branch, then follows the same four setters and Transaction store.set unless a pre-store trap occurs",
        "hit_field_effect_count": transaction_helper["store_hit"]["field_effect_count"],
        "miss_field_effect_count": transaction_helper["store_miss"]["field_effect_count"],
        "hit_store_set_count": transaction_helper["store_hit"]["store_set_count"],
        "miss_store_set_count": transaction_helper["store_miss"]["store_set_count"],
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
    require(artifact["bytes"] == expected["bytes"], f"{cid} byte count drift")
    require(artifact["sha256"] == expected["raw_sha256"], f"{cid} artifact digest drift")
    require(analysis["wat_sha256"] == expected["wat_sha256"], f"{cid} WAT digest drift")
    generation = expected["generation"]
    api_version = "0.0.4" if generation.startswith("legacy") else "0.0.7"
    profile_id = expected["profile_id"]
    store_callsites = WRITER.extract_store_set_callsites(functions, memory)

    def closure_proof(closure: set[str], expected_counts: dict[str, int], label: str) -> dict[str, Any]:
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
        indirect_sites: list[dict[str, Any]] = []
        unreachable_sites: list[dict[str, Any]] = []
        for name in sorted(closure):
            function = functions[name]
            for index, line in enumerate(function.lines):
                if "call_indirect" in line:
                    indirect_sites.append({**_site(function, index), "instruction": line.strip()})
                if line.strip() == "unreachable":
                    unreachable_sites.append({**_site(function, index), "instruction": "unreachable"})
        observed = _counts(
            len(closure), len(direct_calls), len(set(normalized_calls)), len(writes),
            len(generic_sites), len(named_sites), len(store_get_sites), len(store_set_sites),
            len(store_remove_sites), len(unset_sites), len(ethereum_call_sites),
            len(indirect_sites), len(abort_call_sites), len(unreachable_sites),
            len({item["function"] for item in unreachable_sites}),
        )
        require(observed == expected_counts, f"{cid} {label} physical closure drift: {observed} != {expected_counts}")
        require(not store_remove_sites and not unset_sites, f"{cid} {label} remove/unset closure drift")
        store_targets = [
            {
                "function": item["function"],
                "target": item["target"],
                "site_id": item["site_id"],
                "wat_line": item["wat_line"],
            }
            for item in store_callsites if item["function"] in closure
        ]
        require({item["target"] for item in store_targets} == {"Position", "PositionSnapshot", "Transaction"}, f"{cid} {label} store targets drift")
        executable_indirect_targets = analysis["call_indirect_table_targets"] if indirect_sites else []
        require(
            executable_indirect_targets == ([] if not indirect_sites else ["~lib/@graphprotocol/graph-ts/common/value/Value#displayData~anonymous|0"]),
            f"{cid} {label} executable indirect target drift",
        )
        return {
            "reachable_closure_summary": {**observed, "physical_store_set_target_count": 3, "executable_call_indirect_target_count": len(executable_indirect_targets)},
            "reachable_function_set_sha256": hashlib.sha256(("\n".join(sorted(closure)) + "\n").encode()).hexdigest(),
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
        }

    handler_proofs: dict[str, Any] = {}
    closures: dict[str, set[str]] = {}
    for handler_key, handler_spec in HANDLERS.items():
        handler = WRITER.resolve_handler(
            functions,
            analysis["registered_handler_export_targets"],
            handler_spec["export"],
        )
        closure = WRITER.reachable_functions(functions, handler, analysis["call_indirect_table_targets"])
        closures[handler_key] = closure
        physical = closure_proof(closure, expected["handlers"][handler_key]["counts"], handler_key)
        record = WRITER.handler_record(handler, memory)
        record_expected = expected["handlers"][handler_key]["record"]
        for field, value in record_expected.items():
            if field != "closure_sha256":
                require(record[field] == value, f"{cid} {handler_key} handler {field} drift")
        require(
            physical["reachable_function_set_sha256"] == record_expected["closure_sha256"],
            f"{cid} {handler_key} closure digest drift: {physical['reachable_function_set_sha256']} != {record_expected['closure_sha256']}",
        )
        semantic = _semantic_functions(
            cid,
            handler_key,
            functions,
            closure,
            memory,
            generation,
            profile_id,
            store_callsites,
        )
        transaction_helper = semantic["transaction_helper_contract"]
        normalized_calls = [_normalized_call_target(item["target"]) for item in physical["direct_call_sites"]]
        for constructor in semantic["semantic_constructor_invocations"]:
            require(normalized_calls.count(constructor["physical_symbol"]) >= 1, f"{cid} {handler_key} semantic constructor missing")
        handler_proofs[handler_key] = {
            "handler_id": handler_spec["handler_id"],
            "handler_binding": record,
            **physical,
            "semantic_invocation_contract": semantic,
            "path_contract": _path_contract(
                handler_key,
                profile_id,
                generation,
                api_version,
                transaction_helper,
            ),
            "relation_field_authority": _relation_authority(),
            "shared_transaction_contract": _shared_transaction_contract(transaction_helper),
            "complete_static_schema_api_effect_contract": True,
            "field_value_semantics_complete": False,
            "graph_store_persistence_proven": False,
            "complete_entity_history": False,
        }

    union_closure = closures["increase"] | closures["decrease"]
    union_proof = closure_proof(union_closure, expected["union_counts"], "paired union")
    require(
        union_proof["reachable_function_set_sha256"] == expected["union_closure_sha256"],
        f"{cid} paired-union closure digest drift: {union_proof['reachable_function_set_sha256']} != {expected['union_closure_sha256']}",
    )
    require(
        analysis["call_indirect_imported_table_count"] == 0
        and analysis["call_indirect_exported_table_count"] == (0 if union_proof["schema_api_sites"]["call_indirect_sites"] else 1)
        and analysis["call_indirect_table_mutation_instruction_count"] == 0
        and analysis["unsupported_call_ref_instruction_count"] == 0,
        f"{cid} indirect table authority drift",
    )
    return {
        "mapping_cid": cid,
        "profile_id": profile_id,
        "generation": generation,
        "api_version": api_version,
        "retained_wasm": {
            "path": artifact["path"],
            "bytes": artifact["bytes"],
            "raw_sha256": artifact["sha256"],
            "wat_sha256": analysis["wat_sha256"],
        },
        "handler_proofs": handler_proofs,
        "paired_union_proof": {
            **union_proof,
            "handler_keys": ["increase", "decrease"],
            "lexical_site_edge_union_field_invocation_count": 46,
            "handler_attributed_lexical_field_invocation_count": 86,
            "sequential_composition_claimed": False,
            "event_order_claimed": False,
        },
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


def _field_outcome(
    record: dict[str, Any],
    proof: dict[str, Any],
    handler_keys: list[str],
    *,
    derived_union: bool,
) -> dict[str, Any]:
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
    if classified and record["entity"] == "Position":
        paths.append("accepted_new_position:getPosition-constructor-or-setter")
        for handler_key in handler_keys:
            if record["field"] in HANDLERS[handler_key]["field_keys"]:
                paths.append(f"{handler_key}:accepted_existing_position:handler-token-branch-setter")
        if record["field"] in {"feeGrowthInside0LastX128", "feeGrowthInside1LastX128"}:
            paths.append("accepted_existing_position:updateFeeVars-non-reverted-setter")
    elif classified and record["entity"] == "PositionSnapshot":
        paths.extend(("accepted_existing_position:snapshot-setter", "accepted_new_position:snapshot-setter"))
    elif classified and record["entity"] == "Transaction":
        qualifier = "store-miss-id-effect" if record["field"] == "id" else "store-hit-or-miss-unconditional-effect"
        paths.extend((
            f"accepted_existing_position:loadTransaction-{qualifier}-before-unconditional-store",
            f"accepted_new_position:either-loadTransaction-{qualifier}-before-unconditional-store",
        ))
    require(bool(paths) == classified, f"setter-path/category mismatch: {identity}")
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
        "outside_npm_liquidity_store_target_closure": outside,
        "setter_before_matching_save_paths": paths,
        "no_setter_path_is_not_a_preservation_claim": classified,
        "required_absent_overlay": required_absent,
        "relation_field_authority_bound": identity in RELATION_FIELDS,
        "field_value_semantics_complete": False,
        "field_value_unchanged_or_preserved_proven": False,
        "graph_store_persistence_proven": False,
        "complete_entity_history": False,
        "mapping_proof_sha256": canonical_sha256(proof),
        "handler_authority": handler_keys,
        "derived_paired_union_projection": derived_union,
        "handler_event_order_claimed": False,
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
        require(binding["api_version"] == proof["api_version"], f"{segment_id} API generation drift")
        boundary = {
            "segment_id": segment_id,
            "network": binding["network"],
            "deployment": binding["deployment"],
            "start_block_inclusive": binding["start_block_inclusive"],
            "end_block_inclusive": binding["end_block_inclusive"],
            "graft": binding["graft"],
        }
        handler_surfaces: dict[str, Any] = {}
        for handler_key in HANDLERS:
            handler_proof = proof["handler_proofs"][handler_key]
            outcomes = [
                _field_outcome(record, handler_proof, [handler_key], derived_union=False)
                for record in field_contract["field_catalog"]
            ]
            counts = Counter(item["path_qualified_category"] for item in outcomes)
            require(counts == Counter({CATEGORY_CLASSIFIED: 38, CATEGORY_SAVED_NO_SETTER: 0, CATEGORY_DERIVED: 13, CATEGORY_OUTSIDE: 248}), f"{segment_id} {handler_key} 299-outcome partition drift")
            overlay_count = sum(item["required_absent_overlay"] for item in outcomes)
            require(overlay_count == 33, f"{segment_id} {handler_key} required absence drift")
            semantic = {
                "handler_key": handler_key,
                "handler_id": HANDLERS[handler_key]["handler_id"],
                "segment_boundary": boundary,
                "mapping_cid": proof["mapping_cid"],
                "profile_id": proof["profile_id"],
                "parent_npm_field_profile_id": npm_profile["profile_id"],
                "generation": proof["generation"],
                "api_version": proof["api_version"],
                "path_contract": handler_proof["path_contract"],
                "relation_field_authority": handler_proof["relation_field_authority"],
                "shared_transaction_contract": handler_proof["shared_transaction_contract"],
                "field_outcome_summary": {
                    "field_outcome_count": 299,
                    "classified_stored_target_count": counts[CATEGORY_CLASSIFIED],
                    "saved_target_stored_no_setter_count": counts[CATEGORY_SAVED_NO_SETTER],
                    "derived_query_field_count": counts[CATEGORY_DERIVED],
                    "outside_store_target_closure_count": counts[CATEGORY_OUTSIDE],
                    "required_absent_overlay_count": overlay_count,
                },
                "field_outcomes": outcomes,
                "complete_path_qualified_static_handler_contract": True,
                "complete_entity_histories": False,
                "graph_store_persistence_proven": False,
            }
            provenance = {
                "handler_key": handler_key,
                "segment_boundary": boundary,
                "mapping_cid": proof["mapping_cid"],
                "profile_id": proof["profile_id"],
                "parent_npm_field_profile_id": npm_profile["profile_id"],
                "schema_cid": binding["schema_cid"],
                "api_version": binding["api_version"],
                "retained_wasm": proof["retained_wasm"],
                "handler_binding": handler_proof["handler_binding"],
                "handler_proof_sha256": canonical_sha256(handler_proof),
                "parent_field_semantic_sha256": parent["semantic_surface_sha256"],
                "parent_field_provenance_sha256": parent["provenance_surface_sha256"],
            }
            handler_surfaces[handler_key] = {
                "semantic_surface": semantic,
                "semantic_surface_sha256": canonical_sha256(semantic),
                "provenance_surface": provenance,
                "provenance_surface_sha256": canonical_sha256(provenance),
            }

        union_outcomes = [
            _field_outcome(record, proof["paired_union_proof"], ["increase", "decrease"], derived_union=True)
            for record in field_contract["field_catalog"]
        ]
        union_counts = Counter(item["path_qualified_category"] for item in union_outcomes)
        require(union_counts == Counter({CATEGORY_CLASSIFIED: 38, CATEGORY_SAVED_NO_SETTER: 0, CATEGORY_DERIVED: 13, CATEGORY_OUTSIDE: 248}), f"{segment_id} union partition drift")
        require(sum(item["required_absent_overlay"] for item in union_outcomes) == 33, f"{segment_id} union overlay drift")
        union_semantic = {
            "segment_boundary": boundary,
            "mapping_cid": proof["mapping_cid"],
            "profile_id": proof["profile_id"],
            "parent_npm_field_profile_id": npm_profile["profile_id"],
            "handler_keys": ["increase", "decrease"],
            "derivation": "set union of independently certified handler authorities; not sequential execution or event ordering",
            "field_outcome_summary": {
                "field_outcome_count": 299,
                "classified_stored_target_count": union_counts[CATEGORY_CLASSIFIED],
                "saved_target_stored_no_setter_count": union_counts[CATEGORY_SAVED_NO_SETTER],
                "derived_query_field_count": union_counts[CATEGORY_DERIVED],
                "outside_store_target_closure_count": union_counts[CATEGORY_OUTSIDE],
                "required_absent_overlay_count": 33,
            },
            "field_outcomes": union_outcomes,
            "handler_event_order_complete": False,
            "sequential_composition_complete": False,
            "graph_store_persistence_proven": False,
        }
        union_provenance = {
            "segment_boundary": boundary,
            "mapping_cid": proof["mapping_cid"],
            "schema_cid": binding["schema_cid"],
            "profile_id": proof["profile_id"],
            "parent_npm_field_profile_id": npm_profile["profile_id"],
            "handler_binding_sha256": {
                key: canonical_sha256(proof["handler_proofs"][key]["handler_binding"])
                for key in HANDLERS
            },
            "paired_union_proof_sha256": canonical_sha256(proof["paired_union_proof"]),
            "parent_field_semantic_sha256": parent["semantic_surface_sha256"],
            "parent_field_provenance_sha256": parent["provenance_surface_sha256"],
        }
        within_semantic = json_diff_paths(handler_surfaces["increase"]["semantic_surface"], handler_surfaces["decrease"]["semantic_surface"])
        within_provenance = json_diff_paths(handler_surfaces["increase"]["provenance_surface"], handler_surfaces["decrease"]["provenance_surface"])
        require(within_semantic and within_provenance, f"{segment_id} within-segment handler diff empty")
        results.append({
            **boundary,
            "handler_surfaces": handler_surfaces,
            "paired_union_surface": {
                "semantic_surface": union_semantic,
                "semantic_surface_sha256": canonical_sha256(union_semantic),
                "provenance_surface": union_provenance,
                "provenance_surface_sha256": canonical_sha256(union_provenance),
            },
            "within_segment_handler_diff": {
                "recursive_semantic_diff_paths": within_semantic,
                "recursive_provenance_diff_paths": within_provenance,
                "event_order_compared": False,
                "store_persistence_compared": False,
            },
            "execution_model": "undecided",
            "backfill_allowed": False,
        })
    require(len(results) == 8, "segment result count drift")
    require(sum(len(item["handler_surfaces"][key]["semantic_surface"]["field_outcomes"]) for item in results for key in HANDLERS) == 4784, "independent handler field outcome drift")
    require(sum(len(item["paired_union_surface"]["semantic_surface"]["field_outcomes"]) for item in results) == 2392, "derived union field outcome drift")
    return results


def build_segment_diffs(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
    for left, right in itertools.combinations(segments, 2):
        record: dict[str, Any] = {
            "left_segment_id": left["segment_id"],
            "right_segment_id": right["segment_id"],
            "handler_diffs": {},
            "complete_entity_histories_compared": False,
            "boundary_state_compared": False,
            "graph_oracle_compared": False,
        }
        for handler_key in HANDLERS:
            left_surface = left["handler_surfaces"][handler_key]
            right_surface = right["handler_surfaces"][handler_key]
            semantic_paths = json_diff_paths(left_surface["semantic_surface"], right_surface["semantic_surface"])
            provenance_paths = json_diff_paths(left_surface["provenance_surface"], right_surface["provenance_surface"])
            require(semantic_paths and provenance_paths, f"empty {handler_key} recursive segment diff")
            record["handler_diffs"][handler_key] = {
                "recursive_semantic_diff_paths": semantic_paths,
                "recursive_provenance_diff_paths": provenance_paths,
                "left_semantic_surface_sha256": left_surface["semantic_surface_sha256"],
                "right_semantic_surface_sha256": right_surface["semantic_surface_sha256"],
                "left_provenance_surface_sha256": left_surface["provenance_surface_sha256"],
                "right_provenance_surface_sha256": right_surface["provenance_surface_sha256"],
            }
        left_union = left["paired_union_surface"]
        right_union = right["paired_union_surface"]
        union_semantic_paths = json_diff_paths(left_union["semantic_surface"], right_union["semantic_surface"])
        union_provenance_paths = json_diff_paths(left_union["provenance_surface"], right_union["provenance_surface"])
        require(union_semantic_paths and union_provenance_paths, "empty union recursive segment diff")
        record["paired_union_diff"] = {
            "recursive_semantic_diff_paths": union_semantic_paths,
            "recursive_provenance_diff_paths": union_provenance_paths,
            "left_semantic_surface_sha256": left_union["semantic_surface_sha256"],
            "right_semantic_surface_sha256": right_union["semantic_surface_sha256"],
            "left_provenance_surface_sha256": left_union["provenance_surface_sha256"],
            "right_provenance_surface_sha256": right_union["provenance_surface_sha256"],
        }
        results.append(record)
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
    require(recompute_wat, "NPM Liquidity v2 requires direct retained-WAT recomputation")
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
    fields = COUNT_FIELDS
    proof_by_cid = {item["mapping_cid"]: item for item in proofs}
    weighted_proofs = [proof_by_cid[item["handler_surfaces"]["increase"]["semantic_surface"]["mapping_cid"]] for item in segments]
    expected_unique = {
        "increase": _counts(559, 2555, 625, 1328, 174, 132, 20, 18, 0, 0, 12, 2, 222, 262, 200),
        "decrease": _counts(559, 2557, 631, 1328, 174, 132, 20, 18, 0, 0, 12, 2, 224, 264, 202),
        "paired_union": _counts(565, 2789, 631, 1360, 180, 144, 24, 18, 0, 0, 12, 2, 224, 264, 202),
    }
    expected_weighted = {
        "increase": _counts(771, 3379, 859, 1682, 218, 198, 26, 24, 0, 0, 16, 2, 280, 338, 262),
        "decrease": _counts(771, 3381, 867, 1682, 218, 198, 26, 24, 0, 0, 16, 2, 282, 340, 264),
        "paired_union": _counts(779, 3683, 867, 1714, 224, 216, 30, 24, 0, 0, 16, 2, 282, 340, 264),
    }
    unique: dict[str, dict[str, int]] = {}
    weighted: dict[str, dict[str, int]] = {}
    for proof_key in ("increase", "decrease", "paired_union"):
        path = (
            (lambda item: item["paired_union_proof"])
            if proof_key == "paired_union"
            else (lambda item, key=proof_key: item["handler_proofs"][key])
        )
        unique[proof_key] = {field: sum(path(item)["reachable_closure_summary"][field] for item in proofs) for field in fields}
        weighted[proof_key] = {field: sum(path(item)["reachable_closure_summary"][field] for item in weighted_proofs) for field in fields}
        require(unique[proof_key] == expected_unique[proof_key], f"{proof_key} unique-six aggregate drift")
        require(weighted[proof_key] == expected_weighted[proof_key], f"{proof_key} eight-binding aggregate drift")
    require(all(len(item["handler_proofs"][key]["relation_field_authority"]) == 9 for item in proofs for key in HANDLERS), "nine-field relation authority drift")
    return {
        "unique_six_physical_totals": unique,
        "eight_binding_weighted_physical_totals": weighted,
        "per_handler_semantic_denominators": {
            "lexical_field_invocation_count_per_mapping": 43,
            "maximum_existing_path_field_invocation_count_per_mapping": 26,
            "maximum_new_path_field_invocation_count_per_mapping": 48,
            "unique_six_lexical_field_invocation_count": 258,
            "eight_binding_lexical_field_invocation_count": 344,
            "unique_six_maximum_existing_path_field_invocation_count": 156,
            "eight_binding_maximum_existing_path_field_invocation_count": 208,
            "unique_six_maximum_new_path_field_invocation_count": 288,
            "eight_binding_maximum_new_path_field_invocation_count": 384,
        },
        "paired_semantic_denominators": {
            "lexical_site_edge_union_count_per_mapping": 46,
            "handler_attributed_lexical_count_per_mapping": 86,
            "unique_six_lexical_site_edge_union_count": 276,
            "eight_binding_lexical_site_edge_union_count": 368,
            "unique_six_handler_attributed_lexical_count": 516,
            "eight_binding_handler_attributed_lexical_count": 688,
            "sequential_composition_claimed": False,
        },
        "independent_handler_outcomes": {
            "field_outcome_count": 4784,
            "classified_stored_target_outcome_count": 608,
            "saved_target_stored_no_setter_outcome_count": 0,
            "derived_query_field_outcome_count": 208,
            "outside_store_target_closure_outcome_count": 3968,
            "required_absent_overlay_outcome_count": 528,
        },
        "derived_paired_union_outcomes": {
            "field_outcome_count": 2392,
            "classified_stored_target_outcome_count": 304,
            "saved_target_stored_no_setter_outcome_count": 0,
            "derived_query_field_outcome_count": 104,
            "outside_store_target_closure_outcome_count": 1984,
            "required_absent_overlay_outcome_count": 264,
        },
    }


def expected_contract_from_sources(sources: dict[str, Any]) -> dict[str, Any]:
    proofs = sources["mapping_proofs"]
    field_contract = sources["field_contract"]
    ancestry = sources["direct"]["ancestry_v2"]
    segments = build_segments(field_contract, ancestry, proofs)
    diffs = build_segment_diffs(segments)
    within_segment_diffs = [
        {"segment_id": item["segment_id"], **item["within_segment_handler_diff"]}
        for item in segments
    ]
    require(len(within_segment_diffs) == 8, "within-segment handler diff count drift")
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
        "mode": "complete-path-qualified-static-paired-npm-liquidity-schema-api-effect-matrix",
        "scope": {
            "networks": ["mainnet", "base"],
            "segment_binding_count": 8,
            "unique_npm_wasm_count": 6,
            "handlers": [HANDLERS[key]["handler_id"] for key in HANDLERS],
            "schema_field_count_per_segment": 299,
            "independent_handler_field_outcome_count": 4784,
            "independent_handler_required_absent_overlay_count": 528,
            "derived_paired_union_field_outcome_count": 2392,
            "derived_paired_union_required_absent_overlay_count": 264,
            "classified_stored_target_count_per_segment": 38,
            "saved_target_stored_no_setter_count_per_segment": 0,
            "derived_query_field_count_per_segment": 13,
            "outside_store_target_closure_count_per_segment": 248,
            "required_absent_overlay_count_per_segment": 33,
            "pairwise_recursive_diff_count": 28,
            "within_segment_handler_diff_count": 8,
            "issue_acceptance_checkbox_completed": False,
            "claim": "complete path-qualified retained-WAT schema-API effect contracts for NonfungiblePositionManager.handleIncreaseLiquidity and handleDecreaseLiquidity across eight segment bindings and six unique WASMs, plus a derived set union that does not imply event ordering or sequential execution; it binds receiver, key, setter, constructor, store and branch-prefix order without promoting arithmetic meaning, imported values, store persistence, histories, runtime parity, backfill or readiness",
        },
        "authority_contract": {
            "implementation_base_commit": IMPLEMENTATION_BASE_COMMIT,
            "implementation_base_tree": IMPLEMENTATION_BASE_TREE,
            "retained_authority_commit": RETAINED_AUTHORITY_COMMIT,
            "retained_authority_tree": RETAINED_AUTHORITY_TREE,
            "semantic_authority": "exact retained deployed NonfungiblePositionManager mapping WASM regenerated with WABT 1.0.35",
            "schema_authority": "three exact retained GraphQL schema artifacts independently match the recomputed 299-field v2 catalog",
            "transfer_and_collect_v2_role": "the preceding Transfer and Collect v2 slices supply repository layout and CI ordering patterns only; neither verifier, contract, output, nor semantic claim is loaded as Liquidity authority",
            "physical_vs_semantic_boundary": "physical symbols and sites are enumerated independently for each handler and their closure union; each handler has 43 lexical field invocations, 38 distinct field authorities, 26 maximum expanded existing-path invocations and 48 maximum expanded new-path invocations",
            "paired_union_boundary": "the 46-site lexical and physical closure unions are derived set unions of two independent handler proofs; they do not assert event order, sequential composition, shared-store visibility, or aggregate maximum path execution",
            "no_setter_boundary": "every Position path records only the setters it reaches before Position.save; no missing setter is described as preserved, unchanged, value-stable, or persisted",
            "fatal_boundary": "non-try Factory getPool failure is bound only through the pre-fatal prefix; post-fatal execution and rollback are not modeled",
            "transaction_visibility_boundary": "the two new-path loadTransaction reads are independently classified hit or miss because visibility of an earlier store.set to a later store.get is unproved; either completed branch performs four common field setters and Transaction store.set, while a miss additionally supplies id",
            "legacy_alias_boundary": "legacy handleDecreaseLiquidity physically resolves only IncreaseLiquidity__Params symbols; this physical alias is bound without asserting source-language type intent or runtime value meaning",
            "composition_boundary": "paired NPM Liquidity static provenance does not complete NPM runtime observation work in issue 37 or the full multi-handler writer-provenance acceptance in issue 38",
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
        "within_segment_handler_diffs": within_segment_diffs,
        "residual_blockers": {
            "semantic": [
                "contract-call returned values, block-pointer timing, error classes, numeric meaning, string formatting, address conversion, and arbitrary aliases remain unproved",
                "store.get contents and event-ordinal visibility, persistence, rollback, post-fatal behavior, VID and PoI remain unproved",
                "Position fields without a path-local setter before save are deliberately not described as preserved, unchanged, value-stable, or persisted",
                "the two new-path Transaction helper reads have independent hit/miss id ledgers because intra-handler store visibility is unproved; both completed branches perform the four common setters and Transaction store.set",
                "shared Position, PositionSnapshot, and Transaction histories and last-writer behavior remain incomplete",
                "BigInt plus/minus and BigDecimal plus result flow is bound only to setter paths; arithmetic meaning is unproved",
                "no ordering or sequential composition is inferred between IncreaseLiquidity and DecreaseLiquidity events",
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
        require(path.is_file(), f"NPM Liquidity v2 contract missing: {CONTRACT_PATH}")
        actual = load_json(path)
        require(path.read_text() == render(actual), "NPM Liquidity v2 contract byte rendering drift")
    require(canonical_bytes(actual) == canonical_bytes(expected), "NPM Liquidity v2 contract differs from generated proof")
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
        print(f"NPM Liquidity v2 verification failed: {error}", file=sys.stderr)
        return 1
    print(
        "verified Uniswap V3 NPM Liquidity v2: "
        f"{result['scope']['segment_binding_count']} bindings, "
        f"{result['scope']['unique_npm_wasm_count']} WASMs, "
        f"{result['scope']['independent_handler_field_outcome_count']} independent outcomes, "
        f"{len(result['segment_diffs'])} diffs; no issue checkbox completed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
