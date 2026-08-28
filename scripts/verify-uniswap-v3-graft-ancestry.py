#!/usr/bin/env python3
"""Build or verify the hermetic Uniswap V3 graft-ancestry contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import struct
import sys
from pathlib import Path
from typing import Any

import yaml


CONTRACT_VERSION = "uniswap-v3-graft-ancestry/v1"
CONTRACT_PATH = Path("uniswap-v3/graft-ancestry/v1/contract.json")
ARTIFACT_DIRECTORY = Path("uniswap-v3/graft-ancestry/v1/artifacts")
CID_RE = re.compile(r"^Qm[1-9A-HJ-NP-Za-km-z]{44}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

ENTITIES = (
    "Bundle",
    "Burn",
    "Collect",
    "Factory",
    "Flash",
    "Mint",
    "Pool",
    "PoolDayData",
    "PoolHourData",
    "Position",
    "PositionSnapshot",
    "Swap",
    "Tick",
    "TickDayData",
    "TickHourData",
    "Token",
    "TokenDayData",
    "TokenHourData",
    "Transaction",
    "UniswapDayData",
)

FACTORY_WRITERS = ("Bundle", "Factory", "Pool", "Token")
POSITION_WRITERS = ("Position", "PositionSnapshot", "Transaction")
POOL_WRITERS = (
    "Bundle",
    "Burn",
    "Factory",
    "Mint",
    "Pool",
    "PoolDayData",
    "PoolHourData",
    "Swap",
    "Tick",
    "TickDayData",
    "Token",
    "TokenDayData",
    "TokenHourData",
    "Transaction",
    "UniswapDayData",
)

MAPPING_WRITERS = {
    # Factory mappings, ordered by CID for deterministic output.
    "QmT8CKmLDFFCgwYnubFhKXUsuer5rfJKPT4PrCsv9tTwjV": ("Factory", FACTORY_WRITERS),
    "QmUN4pxwjMTfNem7rf1sKNFNHDsfzpbcTP93RxPAczgkvj": ("Factory", FACTORY_WRITERS),
    "QmUu9rnGvUiBbF9pLnuJQab1wHXqjooo3bY5cZDVTyQQgr": ("Factory", FACTORY_WRITERS),
    "QmXFDgK3qLnmsLFcPWobXbdnqV9gESL9BvYY29si4vpTjr": ("Factory", FACTORY_WRITERS),
    "QmbJGLb6sXkN11djxLvKGb2zDk3s7ddgEsULwzC7TVyrEb": ("Factory", FACTORY_WRITERS),
    "QmcsaU3DrUqZHZLzrrWT9aW4EVQuS54wxNHynq8g1PvESL": ("Factory", FACTORY_WRITERS),
    # NonfungiblePositionManager mappings.
    "QmPjhEuGqknJJ2LfJCi6XTLFLtiymYfZAtjTLfkmJJGMEj": (
        "NonfungiblePositionManager",
        POSITION_WRITERS,
    ),
    "QmUk7jc3c8joQBrrcTz2ZEVDKcg1P12G2nFtuNqiikDQLJ": (
        "NonfungiblePositionManager",
        POSITION_WRITERS,
    ),
    "QmWxG1yzdQmp4pRDiqKvTZyRrrrZPRUTza6xznjR1wu1sD": (
        "NonfungiblePositionManager",
        POSITION_WRITERS,
    ),
    "QmYWR79pUmVbQ42JkvB24D6AKCGtdo4UG78ZSewmFxwQdR": (
        "NonfungiblePositionManager",
        POSITION_WRITERS,
    ),
    "QmYwxHm2GNNcukX9oe4owucCLNoAk2rYrbMFuMFtWfKLn2": (
        "NonfungiblePositionManager",
        POSITION_WRITERS,
    ),
    "Qmebr2EyxV7v1wLt9DSFKA7g8EhcVr9k1x7pwZr5eWEHT6": (
        "NonfungiblePositionManager",
        POSITION_WRITERS,
    ),
    # Dynamically instantiated Pool mappings.
    "QmPZCHE1URf4oviX7Tbrkw3aMENo1qAeEGa1AS2gMumG7P": ("Pool", POOL_WRITERS),
    "QmSaGgPnyhStviGQSGTokQYRgVqLFNvnGWfnv8tSfuvpWD": ("Pool", POOL_WRITERS),
    "QmWuomVAQCdEXdCRavcsmRz4BNqPx2nppqe8S6AXid66xw": ("Pool", POOL_WRITERS),
    "QmYQRHstsSS7mntgKNSot74qN2dpuyFEtd1DddPmnqWC65": ("Pool", POOL_WRITERS),
    "QmZPiDeH1j95mozzb5AjKCHn6zgpnhMu77kNAitPbi4Vt3": ("Pool", POOL_WRITERS),
    "QmadCQv7VPgNXhQTNkcDyzmiWZpWexynUH4XuuaMrsAbJY": ("Pool", POOL_WRITERS),
    "Qmaydei2ScE7JptBTPgSfkf6PFxEZpLn39gEXYqrBZhsv8": ("Pool", POOL_WRITERS),
    "QmeNbEMUnaaPpmpLaUVBJfFWRCN5SxG8xPG5eDNoXEGdbW": ("Pool", POOL_WRITERS),
}

# SHA-256 of the complete textual output from WABT 1.0.35
# `wasm2wat --generate-names <retained mapping>`. This ancestry verifier does
# not invoke WABT; the layered writer-compatibility verifier recomputes all of
# these locks and every callsite in CI with the checksum-pinned tool.
WAT_SHA256 = {
    "QmPZCHE1URf4oviX7Tbrkw3aMENo1qAeEGa1AS2gMumG7P": "bd42b64aeaaf677018c11fe779179ecb81d7c4125fa0b846134bb0e0a6059ad1",
    "QmPjhEuGqknJJ2LfJCi6XTLFLtiymYfZAtjTLfkmJJGMEj": "2ca2b971161bb406b60ddf8d0d486ee02c3599dedb72c3c9c9dad9f6e63dd8ca",
    "QmSaGgPnyhStviGQSGTokQYRgVqLFNvnGWfnv8tSfuvpWD": "8454917398ef7a3b8f965a7e40e5b7a1d8cf7879e898490aeabe15726c3d4281",
    "QmT8CKmLDFFCgwYnubFhKXUsuer5rfJKPT4PrCsv9tTwjV": "4263d51999d58769c06bef6da1aed4c24c1c846f4b0aaed9142bf3bd912ecf9b",
    "QmUN4pxwjMTfNem7rf1sKNFNHDsfzpbcTP93RxPAczgkvj": "c2e7425784b498481ee8a822be18b59edd7aa6dd27712d8d093696cf0b8b1684",
    "QmUk7jc3c8joQBrrcTz2ZEVDKcg1P12G2nFtuNqiikDQLJ": "4370c99e82c40e311a7a3d9c23ff0a61ed0dfd04feb9d737727308400ce03d12",
    "QmUu9rnGvUiBbF9pLnuJQab1wHXqjooo3bY5cZDVTyQQgr": "1fbcd7b7305dd0e0eb2e9de2e64ecb023e9aa5abe29f7562be4dad72bf561f4d",
    "QmWuomVAQCdEXdCRavcsmRz4BNqPx2nppqe8S6AXid66xw": "5e8f6e0c96992afee37669c053b8940355e09e18741e53089838fb1c11924666",
    "QmWxG1yzdQmp4pRDiqKvTZyRrrrZPRUTza6xznjR1wu1sD": "6febde6b56e441b694f1708821a5e507f766ddfac3056a8efbce026826a9dced",
    "QmXFDgK3qLnmsLFcPWobXbdnqV9gESL9BvYY29si4vpTjr": "ea8185d6d94ff68dbb041684f29d23d528c6784a3396542657f9708d73d70972",
    "QmYQRHstsSS7mntgKNSot74qN2dpuyFEtd1DddPmnqWC65": "84dc181907baec30b5770fe5f8cdc61062b002989eb09f218963fd1995209aae",
    "QmYWR79pUmVbQ42JkvB24D6AKCGtdo4UG78ZSewmFxwQdR": "93cf89c0ac5f8af930c4a4a1b273a6831dced3247104db4585b6d6284da789a2",
    "QmYwxHm2GNNcukX9oe4owucCLNoAk2rYrbMFuMFtWfKLn2": "c68a6ea285b643a301f7931ec8bebc3acd88c047a7c84b5773ffd2aa8570f9c3",
    "QmZPiDeH1j95mozzb5AjKCHn6zgpnhMu77kNAitPbi4Vt3": "7444416b1ac3e7a3c98f4a2d5d3f24d343b2a1af8238f159b4839a0b2adc0a02",
    "QmadCQv7VPgNXhQTNkcDyzmiWZpWexynUH4XuuaMrsAbJY": "3868d954fe13117081173408b79d72fb88c4b88bfeabfb7a6e93b5482b87e4ff",
    "Qmaydei2ScE7JptBTPgSfkf6PFxEZpLn39gEXYqrBZhsv8": "3e68ada1f22ed2a2b72f74ecbdebe2f084ad42e11068fdc6991947963f145cb5",
    "QmbJGLb6sXkN11djxLvKGb2zDk3s7ddgEsULwzC7TVyrEb": "84064b99fa818216ac5090dcf2a8f6b16acfe5f93edcc9819d0cb88d84526449",
    "QmcsaU3DrUqZHZLzrrWT9aW4EVQuS54wxNHynq8g1PvESL": "d44ed8c0bbd1bdf62635871b475fbe1a22c8d3a4b88e5d77e6827e3e61b70f81",
    "QmeNbEMUnaaPpmpLaUVBJfFWRCN5SxG8xPG5eDNoXEGdbW": "6fac410afa86a411137e3bfabf46550261785b79fbfc53a39b8ec59492061d36",
    "Qmebr2EyxV7v1wLt9DSFKA7g8EhcVr9k1x7pwZr5eWEHT6": "19d7511d0a1ba05caeb115d4d820c89c61210c373b9253682915bc40d0d38d5d",
}

MANIFEST_LOCKS = {
    "QmPWDTWRfS8XewMJhxXoQiZX6RkrUMYH7BFnnB846v6wzR": (
        4164,
        "ab8cd8401649ae4ff439c2ab95f54f4cfdd31d259f20e21bcbee7b1436c9b78b",
    ),
    "QmRvEgUpbjVV326W2zPvxWimzQwcDREfjejUdFn2L92qry": (
        4226,
        "5d39dce087a8e76d564972718cd95136a523cc8c06ea7fc58f8fa603afe18198",
    ),
    "QmS13421u6qsbVdBCrZhdRaZw2wH67drwF3urmueJvvJ5P": (
        4226,
        "aef82097c2c69afadb448a331c21b85afca5a4d0853e860e9f8e74431fc8fe32",
    ),
    "QmSLHXCZBNKVtJRrWiEAF1yRQNPqAFptBsAcLdXQPsubSX": (
        4226,
        "5811b920f213e6baed3b11fe549015a49e543508f01c284be0dd289c59d7ae53",
    ),
    "QmTZ8ejXJxRo7vDBS4uwqBeGoxLSWbhaA7oXa1RvxunLy7": (
        4268,
        "691ea53201c6e3c65de3959b76be1a8fd1d9c119e1aaf55ab4a521f8e8a06e16",
    ),
    "QmZeCuoZeadgHkGwLwMeguyqUKz1WPWQYKcKyMCeQqGhsF": (
        4226,
        "e85fcc1e89eb3553d0e76068a35733940df3579657c12b2099b3b06e401234ec",
    ),
    "Qmb4VUcAY9LsVgeCuCCMs7X1XrkbRcaiuAbSK8SqhmsAfP": (
        4257,
        "b4516b3e083985529c801b5071f804ab103ff307264bf82d18cda61b0ccc1085",
    ),
    "Qme66ZNMxSdCQKzaDuvS381whCVYCQjf637sGZCqJHAWHB": (
        4146,
        "8c4e9c93d1aa9ecb9549ffb547e0174272fef716fca94435c58148ee0aa3d137",
    ),
}

# Each chain is origin-to-tip. The base owns state through end_block_inclusive;
# the following child mapping starts at the next block.
CHAINS = {
    "mainnet": (
        ("Qme66ZNMxSdCQKzaDuvS381whCVYCQjf637sGZCqJHAWHB", 12_369_621, 13_450_880),
        ("QmRvEgUpbjVV326W2zPvxWimzQwcDREfjejUdFn2L92qry", 13_450_881, 13_498_328),
        ("QmS13421u6qsbVdBCrZhdRaZw2wH67drwF3urmueJvvJ5P", 13_498_329, 13_591_197),
        ("QmSLHXCZBNKVtJRrWiEAF1yRQNPqAFptBsAcLdXQPsubSX", 13_591_198, 13_605_860),
        ("QmZeCuoZeadgHkGwLwMeguyqUKz1WPWQYKcKyMCeQqGhsF", 13_605_861, 19_470_000),
        ("QmTZ8ejXJxRo7vDBS4uwqBeGoxLSWbhaA7oXa1RvxunLy7", 19_470_001, None),
    ),
    "base": (
        ("QmPWDTWRfS8XewMJhxXoQiZX6RkrUMYH7BFnnB846v6wzR", 1_371_679, 19_852_000),
        ("Qmb4VUcAY9LsVgeCuCCMs7X1XrkbRcaiuAbSK8SqhmsAfP", 19_852_001, None),
    ),
}

OBSERVATIONS_BY_DEPLOYMENT = {
    "Qme66ZNMxSdCQKzaDuvS381whCVYCQjf637sGZCqJHAWHB": {
        "Position": ("npm-mainnet-root-qmywr",),
        "PositionSnapshot": ("npm-mainnet-root-qmywr",),
        "Pool": ("pool-flash-all-epochs",),
        "Flash": ("pool-flash-all-epochs",),
    },
    "QmRvEgUpbjVV326W2zPvxWimzQwcDREfjejUdFn2L92qry": {
        "Position": ("npm-mainnet-qmrv-qmebr",),
        "PositionSnapshot": ("npm-mainnet-qmrv-qmebr",),
        "Pool": ("pool-flash-all-epochs",),
        "Flash": ("pool-flash-all-epochs",),
    },
    "QmS13421u6qsbVdBCrZhdRaZw2wH67drwF3urmueJvvJ5P": {
        "Position": ("npm-mainnet-qmywx-epochs",),
        "PositionSnapshot": ("npm-mainnet-qmywx-epochs",),
        "Pool": ("pool-flash-all-epochs",),
        "Flash": ("pool-flash-all-epochs",),
    },
    "QmSLHXCZBNKVtJRrWiEAF1yRQNPqAFptBsAcLdXQPsubSX": {
        "Position": ("npm-mainnet-qmywx-epochs",),
        "PositionSnapshot": ("npm-mainnet-qmywx-epochs",),
        "Pool": ("pool-flash-all-epochs",),
        "Flash": ("pool-flash-all-epochs",),
    },
    "QmZeCuoZeadgHkGwLwMeguyqUKz1WPWQYKcKyMCeQqGhsF": {
        "Position": ("npm-mainnet-qmywx-epochs", "mainnet-dead-current-guard"),
        "PositionSnapshot": ("npm-mainnet-qmywx-epochs", "mainnet-dead-current-guard"),
        "Pool": ("pool-flash-all-epochs",),
        "Flash": ("pool-flash-all-epochs",),
    },
    "QmTZ8ejXJxRo7vDBS4uwqBeGoxLSWbhaA7oXa1RvxunLy7": {
        "Position": ("npm-current-mainnet-base-pair", "mainnet-dead-current-guard"),
        "PositionSnapshot": ("npm-current-mainnet-base-pair", "mainnet-dead-current-guard"),
        "Pool": ("pool-flash-all-epochs",),
        "Flash": ("pool-flash-all-epochs",),
    },
    "QmPWDTWRfS8XewMJhxXoQiZX6RkrUMYH7BFnnB846v6wzR": {
        "Position": ("npm-base-root-qmuk",),
        "PositionSnapshot": ("npm-base-root-qmuk",),
        "Pool": ("pool-flash-all-epochs",),
        "Flash": ("pool-flash-all-epochs",),
    },
    "Qmb4VUcAY9LsVgeCuCCMs7X1XrkbRcaiuAbSK8SqhmsAfP": {
        "Position": ("npm-current-mainnet-base-pair", "npm-base-current-retains-root-semantics"),
        "PositionSnapshot": ("npm-current-mainnet-base-pair", "npm-base-current-retains-root-semantics"),
        "Pool": ("pool-flash-all-epochs",),
        "Flash": ("pool-flash-all-epochs",),
    },
}


class VerificationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def exact_keys(value: object, expected: set[str], field: str) -> dict[str, Any]:
    require(isinstance(value, dict), f"{field} must be an object")
    actual = set(value)
    require(actual == expected, f"{field} keys drift: {sorted(actual ^ expected)}")
    return value


class UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that also rejects duplicate mapping keys."""


def _construct_unique_mapping(
    loader: UniqueKeyLoader, node: yaml.nodes.MappingNode, deep: bool = False
) -> dict[object, object]:
    result: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        require(key not in result, f"duplicate YAML key: {key!r}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping
)


def load_yaml_bytes(payload: bytes, field: str) -> dict[str, Any]:
    try:
        value = yaml.load(payload.decode("utf-8"), Loader=UniqueKeyLoader)
    except (UnicodeDecodeError, yaml.YAMLError) as error:
        raise VerificationError(f"invalid UTF-8/YAML for {field}: {error}") from error
    require(isinstance(value, dict), f"{field} YAML root must be an object")
    return value


def load_json(path: Path) -> object:
    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            require(key not in result, f"duplicate JSON key in {path}: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> object:
        raise VerificationError(f"non-finite JSON number in {path}: {value}")

    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(
                handle,
                object_pairs_hook=unique,
                parse_constant=reject_constant,
            )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise VerificationError(f"invalid UTF-8/JSON in {path}: {error}") from error


def load_json_bytes(payload: bytes, field: str) -> object:
    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            require(key not in result, f"duplicate JSON key in {field}: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> object:
        raise VerificationError(f"non-finite JSON number in {field}: {value}")

    try:
        return json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=unique,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise VerificationError(f"invalid UTF-8/JSON in {field}: {error}") from error


def encode_varint(value: int) -> bytes:
    require(value >= 0, "negative varint")
    output = bytearray()
    while value > 0x7F:
        output.append((value & 0x7F) | 0x80)
        value >>= 7
    output.append(value)
    return bytes(output)


def base58btc(payload: bytes) -> str:
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    number = int.from_bytes(payload, "big")
    encoded = ""
    while number:
        number, remainder = divmod(number, 58)
        encoded = alphabet[remainder] + encoded
    leading_zeroes = len(payload) - len(payload.lstrip(b"\0"))
    return "1" * leading_zeroes + encoded


def unixfs_file_cidv0(payload: bytes) -> str:
    require(len(payload) <= 262_144, "artifact exceeds the single-chunk CID verifier")
    unixfs = b"\x08\x02\x12" + encode_varint(len(payload)) + payload
    unixfs += b"\x18" + encode_varint(len(payload))
    node = b"\x0a" + encode_varint(len(unixfs)) + unixfs
    return base58btc(b"\x12\x20" + hashlib.sha256(node).digest())


def read_leb(payload: bytes, offset: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while True:
        require(offset < len(payload), "truncated WebAssembly LEB128")
        byte = payload[offset]
        offset += 1
        result |= (byte & 0x7F) << shift
        if byte & 0x80 == 0:
            return result, offset
        shift += 7
        require(shift <= 35, "oversized WebAssembly LEB128")


def read_wasm_name(payload: bytes, offset: int) -> tuple[str, int]:
    size, offset = read_leb(payload, offset)
    end = offset + size
    require(end <= len(payload), "truncated WebAssembly name")
    try:
        return payload[offset:end].decode("utf-8"), end
    except UnicodeDecodeError as error:
        raise VerificationError("invalid UTF-8 WebAssembly name") from error


def wasm_function_exports(payload: bytes) -> set[str]:
    require(payload.startswith(b"\0asm\x01\0\0\0"), "mapping is not WebAssembly v1")
    offset = 8
    result: set[str] = set()
    while offset < len(payload):
        section_id = payload[offset]
        offset += 1
        size, offset = read_leb(payload, offset)
        end = offset + size
        require(end <= len(payload), "truncated WebAssembly section")
        if section_id == 7:
            count, cursor = read_leb(payload, offset)
            for _ in range(count):
                name, cursor = read_wasm_name(payload, cursor)
                require(cursor < end, "truncated WebAssembly export")
                kind = payload[cursor]
                cursor += 1
                _, cursor = read_leb(payload, cursor)
                if kind == 0:
                    result.add(name)
            require(cursor == end, "trailing WebAssembly export data")
        offset = end
    return result


def cid_from_file(value: object, field: str) -> str:
    mapping = exact_keys(value, {"/"}, field)
    location = mapping["/"]
    require(isinstance(location, str), f"{field} IPFS location must be a string")
    require(location.startswith("/ipfs/"), f"{field} is not an /ipfs reference")
    cid = location.removeprefix("/ipfs/")
    require(CID_RE.fullmatch(cid) is not None, f"{field} CID is malformed")
    return cid


def direct_ipfs_references(value: object) -> set[str]:
    result: set[str] = set()
    if isinstance(value, dict):
        if "/" in value:
            result.add(cid_from_file(value, "manifest reference"))
        for item in value.values():
            result.update(direct_ipfs_references(item))
    elif isinstance(value, list):
        for item in value:
            result.update(direct_ipfs_references(item))
    return result


def normalize_component(value: object, component_type: str, field: str) -> dict[str, object]:
    component = exact_keys(value, {"kind", "mapping", "name", "network", "source"}, field)
    mapping = exact_keys(
        component["mapping"],
        {"abis", "apiVersion", "entities", "eventHandlers", "file", "kind", "language"},
        f"{field}.mapping",
    )
    source_keys = {"abi"} if component_type == "template" else {"abi", "address", "startBlock"}
    source = exact_keys(component["source"], source_keys, f"{field}.source")
    require(component["kind"] == "ethereum/contract", f"{field} kind drift")
    require(isinstance(component["name"], str) and component["name"], f"{field} name malformed")
    require(isinstance(component["network"], str) and component["network"], f"{field} network malformed")
    require(isinstance(source["abi"], str) and source["abi"], f"{field} source ABI malformed")
    require(mapping["kind"] == "ethereum/events", f"{field} mapping kind drift")
    require(mapping["language"] == "wasm/assemblyscript", f"{field} language drift")
    require(isinstance(mapping["apiVersion"], str), f"{field} apiVersion malformed")
    require(isinstance(mapping["entities"], list), f"{field} declared entities malformed")
    require(all(isinstance(item, str) for item in mapping["entities"]), f"{field} entity malformed")

    if component_type == "data_source":
        require(isinstance(source["address"], str), f"{field} address malformed")
        require(type(source["startBlock"]) is int and source["startBlock"] >= 0, f"{field} start block malformed")

    abis: list[dict[str, str]] = []
    require(isinstance(mapping["abis"], list), f"{field} ABI inventory malformed")
    for index, raw_abi in enumerate(mapping["abis"]):
        abi = exact_keys(raw_abi, {"file", "name"}, f"{field}.abis[{index}]")
        require(isinstance(abi["name"], str) and abi["name"], f"{field} ABI name malformed")
        abis.append(
            {
                "name": abi["name"],
                "cid": cid_from_file(abi["file"], f"{field}.abis[{index}].file"),
            }
        )
    require(len({item["name"] for item in abis}) == len(abis), f"{field} ABI names repeat")

    handlers: list[dict[str, str]] = []
    require(isinstance(mapping["eventHandlers"], list), f"{field} handler inventory malformed")
    for index, raw_handler in enumerate(mapping["eventHandlers"]):
        handler = exact_keys(raw_handler, {"event", "handler"}, f"{field}.handlers[{index}]")
        require(isinstance(handler["event"], str) and handler["event"], f"{field} event malformed")
        require(isinstance(handler["handler"], str) and handler["handler"], f"{field} handler malformed")
        handlers.append({"event": handler["event"], "handler": handler["handler"]})
    require(
        len({(item["event"], item["handler"]) for item in handlers}) == len(handlers),
        f"{field} handlers repeat",
    )

    normalized_source: dict[str, object] = {"abi": source["abi"]}
    if component_type == "data_source":
        normalized_source.update(
            {"address": source["address"], "start_block": source["startBlock"]}
        )
    return {
        "component_type": component_type,
        "name": component["name"],
        "kind": component["kind"],
        "network": component["network"],
        "source": normalized_source,
        "mapping": {
            "kind": mapping["kind"],
            "api_version": mapping["apiVersion"],
            "language": mapping["language"],
            "wasm_cid": cid_from_file(mapping["file"], f"{field}.mapping.file"),
            "declared_entities": mapping["entities"],
            "abis": abis,
            "handlers": handlers,
        },
    }


def normalize_manifest(payload: bytes, deployment: str, network: str) -> dict[str, object]:
    raw = load_yaml_bytes(payload, deployment)
    required = {"dataSources", "description", "repository", "schema", "specVersion", "templates"}
    optional = {"features", "graft"}
    require(required <= set(raw) <= required | optional, f"{deployment} manifest keys drift")
    require(isinstance(raw["specVersion"], str), f"{deployment} specVersion malformed")
    features = raw.get("features", [])
    require(isinstance(features, list) and all(isinstance(item, str) for item in features), f"{deployment} features malformed")
    require(len(features) == len(set(features)), f"{deployment} features contain duplicates")

    data_sources = raw["dataSources"]
    templates = raw["templates"]
    require(isinstance(data_sources, list) and data_sources, f"{deployment} dataSources malformed")
    require(isinstance(templates, list) and templates, f"{deployment} templates malformed")
    components = [
        normalize_component(item, "data_source", f"{deployment}.dataSources[{index}]")
        for index, item in enumerate(data_sources)
    ]
    components.extend(
        normalize_component(item, "template", f"{deployment}.templates[{index}]")
        for index, item in enumerate(templates)
    )
    require(all(item["network"] == network for item in components), f"{deployment} network drift")

    graft: dict[str, object] | None = None
    if "graft" in raw:
        raw_graft = exact_keys(raw["graft"], {"base", "block"}, f"{deployment}.graft")
        require(CID_RE.fullmatch(raw_graft["base"]) is not None, f"{deployment} graft base malformed")
        require(type(raw_graft["block"]) is int and raw_graft["block"] >= 0, f"{deployment} graft block malformed")
        graft = {"base": raw_graft["base"], "block": raw_graft["block"]}

    schema = exact_keys(raw["schema"], {"file"}, f"{deployment}.schema")
    return {
        "spec_version": raw["specVersion"],
        "features": features,
        "schema_cid": cid_from_file(schema["file"], f"{deployment}.schema.file"),
        "graft": graft,
        "components": components,
    }


ENTITY_RE = re.compile(r"(?ms)^type\s+(\w+)\s+([^\{]*@entity[^\{]*)\{(.*?)^\}")
FIELD_RE = re.compile(r"^\s*(\w+)\s*:\s*([^\s#]+)(.*)$")


def schema_inventory(payload: bytes, cid: str) -> dict[str, object]:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise VerificationError(f"invalid UTF-8 schema {cid}") from error
    entities: list[dict[str, object]] = []
    for match in ENTITY_RE.finditer(text):
        fields: list[dict[str, object]] = []
        for line in match.group(3).splitlines():
            field_match = FIELD_RE.match(line)
            if not field_match:
                continue
            suffix = field_match.group(3).split("#", 1)[0].strip()
            fields.append(
                {
                    "name": field_match.group(1),
                    "type": field_match.group(2),
                    "directives": suffix,
                    "storage": "derived" if "@derivedFrom" in suffix else "stored",
                }
            )
        require(fields, f"schema {cid} entity {match.group(1)} has no fields")
        entities.append(
            {
                "name": match.group(1),
                "directives": match.group(2).strip(),
                "fields": fields,
            }
        )
    names = [item["name"] for item in entities]
    require(len(names) == len(set(names)), f"schema {cid} repeats an entity")
    require(set(names) == set(ENTITIES), f"schema {cid} entity inventory drift")
    return {"cid": cid, "entity_count": len(entities), "entities": entities}


def artifact_path(root: Path, cid: str) -> Path:
    return root / ARTIFACT_DIRECTORY / cid


def artifact_payload(root: Path, cid: str) -> bytes:
    require(CID_RE.fullmatch(cid) is not None, f"malformed artifact CID: {cid}")
    path = artifact_path(root, cid)
    require(path.exists(), f"missing artifact {cid}")
    require(not path.is_symlink(), f"artifact {cid} must not be a symlink")
    metadata = path.stat()
    require(stat.S_ISREG(metadata.st_mode), f"artifact {cid} must be a regular file")
    expected_parent = (root / ARTIFACT_DIRECTORY).resolve()
    require(path.resolve().parent == expected_parent, f"artifact {cid} escapes artifact directory")
    payload = path.read_bytes()
    require(unixfs_file_cidv0(payload) == cid, f"artifact CID drift for {cid}")
    return payload


def manifest_documents(root: Path) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for network, segments in CHAINS.items():
        for deployment, _, _ in segments:
            payload = artifact_payload(root, deployment)
            expected_bytes, expected_digest = MANIFEST_LOCKS[deployment]
            require(len(payload) == expected_bytes, f"manifest byte count drift for {deployment}")
            require(hashlib.sha256(payload).hexdigest() == expected_digest, f"manifest SHA-256 drift for {deployment}")
            result[deployment] = normalize_manifest(payload, deployment, network)
    require(set(result) == set(MANIFEST_LOCKS), "manifest ancestry inventory drift")
    return result


def artifact_roles(manifests: dict[str, dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    roles: dict[str, list[dict[str, object]]] = {
        deployment: [
            {
                "deployment": deployment,
                "component": None,
                "reference_kind": "manifest",
                "name": None,
            }
        ]
        for deployment in manifests
    }
    for deployment, manifest in manifests.items():
        schema_cid = manifest["schema_cid"]
        roles.setdefault(schema_cid, []).append(
            {
                "deployment": deployment,
                "component": None,
                "reference_kind": "schema",
                "name": None,
            }
        )
        for component in manifest["components"]:
            name = component["name"]
            mapping = component["mapping"]
            roles.setdefault(mapping["wasm_cid"], []).append(
                {
                    "deployment": deployment,
                    "component": name,
                    "reference_kind": "mapping_wasm",
                    "name": None,
                }
            )
            for abi in mapping["abis"]:
                roles.setdefault(abi["cid"], []).append(
                    {
                        "deployment": deployment,
                        "component": name,
                        "reference_kind": "abi",
                        "name": abi["name"],
                    }
                )
    return roles


def media_type_for(roles: list[dict[str, object]]) -> str:
    kinds = {item["reference_kind"] for item in roles}
    require(len(kinds) == 1, f"artifact is referenced as multiple media kinds: {sorted(kinds)}")
    return {
        "manifest": "application/yaml",
        "schema": "application/graphql",
        "mapping_wasm": "application/wasm",
        "abi": "application/json",
    }[next(iter(kinds))]


def mapping_inventories(
    root: Path, manifests: dict[str, dict[str, object]]
) -> list[dict[str, object]]:
    references: dict[str, dict[str, object]] = {}
    for deployment, manifest in manifests.items():
        for component in manifest["components"]:
            mapping = component["mapping"]
            cid = mapping["wasm_cid"]
            item = references.setdefault(
                cid,
                {
                    "component": component["name"],
                    "handlers": set(),
                    "deployments": set(),
                },
            )
            require(item["component"] == component["name"], f"mapping {cid} component drift")
            item["handlers"].update(handler["handler"] for handler in mapping["handlers"])
            item["deployments"].add(deployment)

    require(set(references) == set(MAPPING_WRITERS), "mapping writer evidence does not close over manifests")
    require(set(WAT_SHA256) == set(MAPPING_WRITERS), "WAT evidence inventory drift")
    result: list[dict[str, object]] = []
    for cid in sorted(references):
        payload = artifact_payload(root, cid)
        component, entities = MAPPING_WRITERS[cid]
        reference = references[cid]
        require(reference["component"] == component, f"mapping {cid} locked component drift")
        handlers = sorted(reference["handlers"])
        exports = wasm_function_exports(payload)
        require(set(handlers) <= exports, f"mapping {cid} is missing a registered handler export")
        result.append(
            {
                "cid": cid,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "component": component,
                "referenced_by_deployments": sorted(reference["deployments"]),
                "registered_handler_exports": handlers,
                "manual_wat_sha256": WAT_SHA256[cid],
                "observed_constant_store_set_targets": list(entities),
                "observed_constant_store_set_target_count": len(entities),
                "observed_dynamic_store_set_target_count": 0,
                "review_status": "independently_reviewed_static_observation_not_ci_recomputed",
            }
        )
    return result


def writer_matrix(
    deployment: str,
    manifest: dict[str, object],
    schemas: dict[str, dict[str, object]],
) -> list[dict[str, object]]:
    mapping_entities: dict[str, set[str]] = {}
    for component in manifest["components"]:
        cid = component["mapping"]["wasm_cid"]
        locked_component, entities = MAPPING_WRITERS[cid]
        require(locked_component == component["name"], f"mapping component drift for {cid}")
        for entity in entities:
            mapping_entities.setdefault(entity, set()).add(component["name"])

    schema = schemas[manifest["schema_cid"]]
    result: list[dict[str, object]] = []
    for entity in schema["entities"]:
        name = entity["name"]
        components = sorted(mapping_entities.get(name, set()))
        stored_fields: list[str] = []
        derived_fields: list[str] = []
        for field in entity["fields"]:
            if field["storage"] == "derived":
                derived_fields.append(field["name"])
            else:
                stored_fields.append(field["name"])
        if components:
            stored_status = "pending_field_semantics_audit"
        else:
            stored_status = "no_constant_entity_store_set_target_observed"
        observation_ids = list(
            OBSERVATIONS_BY_DEPLOYMENT.get(deployment, {}).get(name, ())
        )
        if name == "TickHourData":
            observation_ids.append("tick-hour-no-target-observed")
        result.append(
            {
                "entity": name,
                "schema_declared": True,
                "observed_constant_store_set_components": components,
                "observed_constant_store_set_target_present": bool(components),
                "runtime_population_status": "not_certified",
                "required_nonempty_status": "not_audited",
                "conditional_write_status": "not_audited",
                "required_absent_status": "not_certified",
                "contract_call_side_effects_status": "not_audited",
                "historical_exclusions_status": "not_audited",
                "ordering_status": "not_audited",
                "deployed_quirks_status": "not_audited",
                "field_writer_matrix": {
                    "stored_fields": stored_fields,
                    "stored_fields_status": stored_status,
                    "derived_fields": derived_fields,
                    "derived_fields_status": "derived_query_fields_not_stored",
                },
                "partial_semantic_observation_ids": observation_ids,
            }
        )
    return result


def build_contract(root: Path) -> dict[str, object]:
    root = root.resolve()
    manifests = manifest_documents(root)
    roles = artifact_roles(manifests)

    artifact_files = {path.name for path in (root / ARTIFACT_DIRECTORY).iterdir() if path.is_file() or path.is_symlink()}
    require(artifact_files == set(roles), f"artifact reference closure drift: {sorted(artifact_files ^ set(roles))}")

    artifacts: list[dict[str, object]] = []
    schema_cids: set[str] = set()
    for cid in sorted(roles):
        payload = artifact_payload(root, cid)
        media_type = media_type_for(roles[cid])
        if media_type == "application/json":
            abi = load_json_bytes(payload, f"ABI {cid}")
            require(isinstance(abi, list), f"ABI {cid} root must be a list")
        elif media_type == "application/wasm":
            wasm_function_exports(payload)
        elif media_type == "application/graphql":
            schema_cids.add(cid)
        elif media_type == "application/yaml":
            direct = direct_ipfs_references(load_yaml_bytes(payload, cid))
            require(direct <= set(roles), f"manifest {cid} has an unclosed artifact reference")
        artifacts.append(
            {
                "cid": cid,
                "path": (ARTIFACT_DIRECTORY / cid).as_posix(),
                "media_type": media_type,
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "references": sorted(
                    roles[cid],
                    key=lambda item: (
                        str(item["deployment"]),
                        str(item["component"]),
                        str(item["reference_kind"]),
                        str(item["name"]),
                    ),
                ),
            }
        )

    schemas = {
        cid: schema_inventory(artifact_payload(root, cid), cid) for cid in sorted(schema_cids)
    }
    mappings = mapping_inventories(root, manifests)

    networks: dict[str, object] = {}
    for network, chain in CHAINS.items():
        segments: list[dict[str, object]] = []
        boundaries: list[dict[str, object]] = []
        for index, (deployment, start, end) in enumerate(chain):
            manifest = manifests[deployment]
            expected_graft = None
            if index:
                expected_graft = {"base": chain[index - 1][0], "block": start - 1}
            require(manifest["graft"] == expected_graft, f"{deployment} graft identity drift")
            if index == 0:
                starts = [
                    component["source"]["start_block"]
                    for component in manifest["components"]
                    if component["component_type"] == "data_source"
                ]
                require(start == min(starts), f"{deployment} root start drift")
            segments.append(
                {
                    "deployment": deployment,
                    "manifest_cid": deployment,
                    "start_block_inclusive": start,
                    "end_block_inclusive": end,
                    "graft": expected_graft,
                    "graft_free_root": index == 0,
                    "manifest": manifest,
                    "writer_matrix": writer_matrix(deployment, manifest, schemas),
                    "execution_model": "undecided",
                    "backfill_allowed": False,
                }
            )
            if index:
                boundaries.append(
                    {
                        "graft_block": start - 1,
                        "base_deployment_at_graft_block": chain[index - 1][0],
                        "child_deployment_at_next_block": deployment,
                        "base_probe_block": start - 1,
                        "child_probe_block": start,
                        "state_continuity_evidence_status": "not_captured",
                    }
                )
        networks[network] = {
            "ordered_origin_to_tip": True,
            "tip": chain[-1][0],
            "segments": segments,
            "boundary_probes": boundaries,
        }

    return {
        "format_version": 1,
        "contract_version": CONTRACT_VERSION,
        "boundary_rule": "base owns state through and including the graft block; child writer starts at graft block + 1",
        "artifacts": artifacts,
        "schema_inventories": [schemas[cid] for cid in sorted(schemas)],
        "mapping_writer_inventories": mappings,
        "networks": networks,
        "deployment_specific_static_observations": [
            {
                "observation_id": "tick-hour-no-target-observed",
                "scope": "all eight retained Pool mapping artifacts",
                "mapping_cids": [
                    "QmWuomVAQCdEXdCRavcsmRz4BNqPx2nppqe8S6AXid66xw",
                    "QmYQRHstsSS7mntgKNSot74qN2dpuyFEtd1DddPmnqWC65",
                    "QmeNbEMUnaaPpmpLaUVBJfFWRCN5SxG8xPG5eDNoXEGdbW",
                    "Qmaydei2ScE7JptBTPgSfkf6PFxEZpLn39gEXYqrBZhsv8",
                    "QmadCQv7VPgNXhQTNkcDyzmiWZpWexynUH4XuuaMrsAbJY",
                    "QmSaGgPnyhStviGQSGTokQYRgVqLFNvnGWfnv8tSfuvpWD",
                    "QmZPiDeH1j95mozzb5AjKCHn6zgpnhMu77kNAitPbi4Vt3",
                    "QmPZCHE1URf4oviX7Tbrkw3aMENo1qAeEGa1AS2gMumG7P",
                ],
                "method": "complete WABT 1.0.35 WAT store.set target review bound to each retained Pool mapping CID and full-WAT SHA-256",
                "observations": [
                    "no constant TickHourData index.store.set target was observed in any retained Pool mapping"
                ],
                "runtime_oracle_status": "not_executed",
                "semantic_audit_complete": False,
            },
            {
                "observation_id": "npm-mainnet-root-qmywr",
                "scope": "mainnet root Qme66 NonfungiblePositionManager",
                "mapping_cids": ["QmYWR79pUmVbQ42JkvB24D6AKCGtdo4UG78ZSewmFxwQdR"],
                "method": "complete exported-handler WAT control/data-flow review bound to the retained mapping CID",
                "observations": [
                    "position liquidity and amount fields are updated cumulatively",
                    "Collect adds amount0 to collectedFeesToken0 and amount1 to collectedFeesToken1",
                    "IncreaseLiquidity and DecreaseLiquidity have no block 14317993 guard",
                ],
                "runtime_oracle_status": "not_executed",
                "semantic_audit_complete": False,
            },
            {
                "observation_id": "npm-mainnet-qmrv-qmebr",
                "scope": "mainnet QmRv NonfungiblePositionManager",
                "mapping_cids": ["Qmebr2EyxV7v1wLt9DSFKA7g8EhcVr9k1x7pwZr5eWEHT6"],
                "method": "complete exported-handler WAT control/data-flow review bound to the retained mapping CID",
                "observations": [
                    "position liquidity and amount fields are updated cumulatively",
                    "Collect computes old collectedFeesToken1 plus amount1 but writes that result to collectedFeesToken0 a second time",
                    "Collect therefore leaves collectedFeesToken1 unchanged",
                ],
                "runtime_oracle_status": "not_executed",
                "semantic_audit_complete": False,
            },
            {
                "observation_id": "npm-mainnet-qmywx-epochs",
                "scope": "mainnet QmS134, QmSL, and QmZe NonfungiblePositionManager epochs",
                "mapping_cids": ["QmYwxHm2GNNcukX9oe4owucCLNoAk2rYrbMFuMFtWfKLn2"],
                "method": "complete exported-handler WAT control/data-flow review bound to the retained mapping CID",
                "observations": [
                    "Collect performs no amount conversion or collected-fee accumulation",
                    "Collect only refreshes fee variables, saves Position, and saves PositionSnapshot",
                    "IncreaseLiquidity and DecreaseLiquidity have no block 14317993 guard",
                ],
                "runtime_oracle_status": "not_executed",
                "semantic_audit_complete": False,
            },
            {
                "observation_id": "npm-current-mainnet-base-pair",
                "scope": "current-mainnet-and-base-position-manager",
                "mapping_cids": [
                    "QmWxG1yzdQmp4pRDiqKvTZyRrrrZPRUTza6xznjR1wu1sD",
                    "QmPjhEuGqknJJ2LfJCi6XTLFLtiymYfZAtjTLfkmJJGMEj",
                ],
                "method": "complete exported-handler WAT control/data-flow comparison bound to both mapping CIDs",
                "observations": [
                    "IncreaseLiquidity and DecreaseLiquidity skip block 14317993",
                    "IncreaseLiquidity, DecreaseLiquidity, and Collect guard on a resolved Pool",
                    "position amounts are updated cumulatively",
                    "Collect adds amount0 to both collected-fee fields, preserving the deployed quirk",
                    "fee-growth values are refreshed and PositionSnapshot is saved",
                    "Transfer performs the deployed direct owner update behavior",
                ],
                "runtime_oracle_status": "not_executed",
                "semantic_audit_complete": False,
            },
            {
                "observation_id": "npm-base-root-qmuk",
                "scope": "Base root QmPW NonfungiblePositionManager",
                "mapping_cids": ["QmUk7jc3c8joQBrrcTz2ZEVDKcg1P12G2nFtuNqiikDQLJ"],
                "method": "complete exported-handler WAT control/data-flow review bound to the retained mapping CID",
                "observations": [
                    "IncreaseLiquidity and DecreaseLiquidity skip block 14317993",
                    "Collect adds amount0 to both collected-fee fields",
                ],
                "runtime_oracle_status": "not_executed",
                "semantic_audit_complete": False,
            },
            {
                "observation_id": "npm-base-current-retains-root-semantics",
                "scope": "Base current Qmb4 versus Base root QmPW NonfungiblePositionManager",
                "mapping_cids": [
                    "QmUk7jc3c8joQBrrcTz2ZEVDKcg1P12G2nFtuNqiikDQLJ",
                    "QmPjhEuGqknJJ2LfJCi6XTLFLtiymYfZAtjTLfkmJJGMEj",
                ],
                "method": "complete exported-handler WAT control/data-flow comparison bound to both retained mapping CIDs",
                "observations": [
                    "the current Base position-manager mapping retains the root Base block guard and amount0-to-both Collect behavior"
                ],
                "runtime_oracle_status": "not_executed",
                "semantic_audit_complete": False,
            },
            {
                "observation_id": "mainnet-dead-current-guard",
                "scope": "mainnet block 14317993 segment selection",
                "mapping_cids": [
                    "QmYwxHm2GNNcukX9oe4owucCLNoAk2rYrbMFuMFtWfKLn2",
                    "QmWxG1yzdQmp4pRDiqKvTZyRrrrZPRUTza6xznjR1wu1sD",
                ],
                "method": "ordered ancestry selection combined with mapping-specific WAT review",
                "observations": [
                    "mainnet block 14317993 belongs to QmZe and QmYwx, which has no block guard",
                    "the QmWx block guard is outside QmWx's authoritative mainnet interval",
                    "replaying QmWx from origin would incorrectly skip mainnet block 14317993",
                ],
                "runtime_oracle_status": "not_executed",
                "semantic_audit_complete": False,
            },
            {
                "observation_id": "pool-flash-all-epochs",
                "scope": "all mainnet and Base Pool mapping epochs",
                "mapping_cids": [
                    "QmWuomVAQCdEXdCRavcsmRz4BNqPx2nppqe8S6AXid66xw",
                    "QmYQRHstsSS7mntgKNSot74qN2dpuyFEtd1DddPmnqWC65",
                    "QmeNbEMUnaaPpmpLaUVBJfFWRCN5SxG8xPG5eDNoXEGdbW",
                    "Qmaydei2ScE7JptBTPgSfkf6PFxEZpLn39gEXYqrBZhsv8",
                    "QmadCQv7VPgNXhQTNkcDyzmiWZpWexynUH4XuuaMrsAbJY",
                    "QmSaGgPnyhStviGQSGTokQYRgVqLFNvnGWfnv8tSfuvpWD",
                    "QmZPiDeH1j95mozzb5AjKCHn6zgpnhMu77kNAitPbi4Vt3",
                    "QmPZCHE1URf4oviX7Tbrkw3aMENo1qAeEGa1AS2gMumG7P",
                ],
                "method": "complete handleFlash WAT control/data-flow comparison bound to every retained Pool mapping CID",
                "observations": [
                    "all pre-current handleFlash bodies are byte-for-byte identical",
                    "current mainnet and Base handleFlash bodies are behavior-identical to the pre-current body after code-generation differences",
                    "handleFlash makes both feeGrowthGlobal contract calls",
                    "handleFlash updates and saves Pool fee-growth fields",
                    "handleFlash does not write a Flash entity row",
                ],
                "runtime_oracle_status": "not_executed",
                "semantic_audit_complete": False,
            },
        ],
        "writer_inventory_method": {
            "method": "manual offline callsite review of every index.store.set target in each retained mapping",
            "tool_identity": "WABT wasm2wat 1.0.35 --generate-names",
            "scope": "constant entity-name targets only",
            "artifact_binding": "mapping CID, mapping SHA-256, and full textual WAT SHA-256",
            "all_registered_mapping_artifacts_reviewed": True,
            "ci_recomputes_wat_review": False,
            "inventory_certification_status": "independently_reviewed_static_observation",
            "field_value_semantics_reviewed": False,
            "handler_to_entity_control_flow_reviewed": False,
        },
        "truth_boundary": {
            "artifact_reference_closure_complete": True,
            "graft_ancestry_complete": True,
            "handler_inventory_complete": True,
            "schema_entity_inventory_complete": True,
            "static_store_set_target_observations_retained": True,
            "constant_store_set_target_inventory_complete": False,
            "field_writer_audit_complete": False,
            "logical_oracle_complete": False,
            "boundary_state_continuity_complete": False,
            "physical_parity_complete": False,
            "poi_parity_complete": False,
            "segment_execution_models_decided": False,
            "production_ready": False,
            "remaining_blockers": [
                "complete segment-specific entity and field writer semantics, conditions, exclusions, ordering, calls, and quirks",
                "choose emulation or an independently certified graft-boundary seed for every differing segment",
                "capture oracle samples on both sides of every graft and prove state continuity",
                "complete logical, physical, and proof-of-indexing parity gates",
            ],
        },
    }


TOP_LEVEL_KEYS = {
    "format_version",
    "contract_version",
    "boundary_rule",
    "artifacts",
    "schema_inventories",
    "mapping_writer_inventories",
    "networks",
    "deployment_specific_static_observations",
    "writer_inventory_method",
    "truth_boundary",
}


def select_segment(contract: dict[str, object], network: str, block: int) -> dict[str, object]:
    require(network in contract["networks"], f"unknown network selector: {network}")
    require(type(block) is int and block >= 0, "block selector must be a non-negative integer")
    matches = []
    for segment in contract["networks"][network]["segments"]:
        start = segment["start_block_inclusive"]
        end = segment["end_block_inclusive"]
        if block >= start and (end is None or block <= end):
            matches.append(segment)
    require(len(matches) == 1, f"segment selection for {network} block {block} matched {len(matches)} segments")
    return matches[0]


def validate_internal_contract(root: Path, contract: object) -> dict[str, object]:
    contract = exact_keys(contract, TOP_LEVEL_KEYS, "contract")
    require(contract["format_version"] == 1, "format version drift")
    require(contract["contract_version"] == CONTRACT_VERSION, "contract version drift")
    require(
        contract["boundary_rule"]
        == "base owns state through and including the graft block; child writer starts at graft block + 1",
        "boundary rule drift",
    )

    artifacts = contract["artifacts"]
    require(isinstance(artifacts, list), "artifacts must be a list")
    by_cid: dict[str, dict[str, object]] = {}
    for index, value in enumerate(artifacts):
        record = exact_keys(
            value,
            {"cid", "path", "media_type", "bytes", "sha256", "references"},
            f"artifacts[{index}]",
        )
        cid = record["cid"]
        require(isinstance(cid, str) and CID_RE.fullmatch(cid), f"artifacts[{index}] CID malformed")
        require(cid not in by_cid, f"duplicate artifact record {cid}")
        by_cid[cid] = record
        require(record["path"] == (ARTIFACT_DIRECTORY / cid).as_posix(), f"artifact path drift for {cid}")
        require(type(record["bytes"]) is int and record["bytes"] >= 0, f"artifact byte count malformed for {cid}")
        require(isinstance(record["sha256"], str) and SHA256_RE.fullmatch(record["sha256"]), f"artifact digest malformed for {cid}")
        payload = artifact_payload(root, cid)
        require(len(payload) == record["bytes"], f"artifact byte count drift for {cid}")
        require(hashlib.sha256(payload).hexdigest() == record["sha256"], f"artifact SHA-256 drift for {cid}")

    directory_entries = {item.name for item in (root / ARTIFACT_DIRECTORY).iterdir()}
    require(directory_entries == set(by_cid), f"artifact directory closure drift: {sorted(directory_entries ^ set(by_cid))}")

    networks = exact_keys(contract["networks"], {"mainnet", "base"}, "networks")
    seen: set[str] = set()
    manifest_cache: dict[str, dict[str, object]] = {}
    for network, value in networks.items():
        chain = exact_keys(value, {"ordered_origin_to_tip", "tip", "segments", "boundary_probes"}, network)
        require(chain["ordered_origin_to_tip"] is True, f"{network} order claim drift")
        segments = chain["segments"]
        require(isinstance(segments, list) and segments, f"{network} segments malformed")
        require(chain["tip"] == segments[-1]["deployment"], f"{network} tip drift")
        for index, raw_segment in enumerate(segments):
            segment = exact_keys(
                raw_segment,
                {
                    "deployment",
                    "manifest_cid",
                    "start_block_inclusive",
                    "end_block_inclusive",
                    "graft",
                    "graft_free_root",
                    "manifest",
                    "writer_matrix",
                    "execution_model",
                    "backfill_allowed",
                },
                f"{network}.segments[{index}]",
            )
            deployment = segment["deployment"]
            require(isinstance(deployment, str) and CID_RE.fullmatch(deployment), f"{network} deployment malformed")
            require(deployment not in seen, f"graft ancestry cycle or duplicate deployment: {deployment}")
            seen.add(deployment)
            require(segment["manifest_cid"] == deployment, f"{deployment} manifest identity drift")
            require(deployment in by_cid, f"missing ancestor artifact {deployment}")
            start = segment["start_block_inclusive"]
            end = segment["end_block_inclusive"]
            require(type(start) is int and start >= 0, f"{deployment} start boundary malformed")
            require(end is None or (type(end) is int and end >= start), f"{deployment} end boundary malformed")
            require(segment["execution_model"] == "undecided", f"{deployment} execution model is not approved")
            require(segment["backfill_allowed"] is False, f"{deployment} improperly allows backfill")
            if index == 0:
                require(segment["graft"] is None, f"{network} root must be graft-free")
                require(segment["graft_free_root"] is True, f"{network} root graft-free claim is unproven")
            else:
                previous = segments[index - 1]
                graft = exact_keys(segment["graft"], {"base", "block"}, f"{deployment}.graft")
                require(graft["base"] == previous["deployment"], f"{deployment} graft base creates a gap or cycle")
                require(graft["block"] == previous["end_block_inclusive"], f"{deployment} graft block does not match base end")
                require(start == graft["block"] + 1, f"{deployment} child writer must start at graft block + 1")
                require(segment["graft_free_root"] is False, f"{deployment} child claims graft-free")
            if index + 1 < len(segments):
                require(end is not None, f"{deployment} non-tip segment has no end")
                next_start = segments[index + 1]["start_block_inclusive"]
                require(end + 1 == next_start, f"{network} segment gap or overlap after {deployment}")
            else:
                require(end is None, f"{network} tip must be open-ended")

            payload = artifact_payload(root, deployment)
            normalized = normalize_manifest(payload, deployment, network)
            require(segment["manifest"] == normalized, f"{deployment} normalized manifest inventory drift")
            require(normalized["graft"] == segment["graft"], f"{deployment} raw graft identity drift")
            manifest_cache[deployment] = normalized

            writer_matrix_value = segment["writer_matrix"]
            require(isinstance(writer_matrix_value, list), f"{deployment} writer matrix malformed")
            matrix_names = [item.get("entity") for item in writer_matrix_value if isinstance(item, dict)]
            require(set(matrix_names) == set(ENTITIES) and len(matrix_names) == len(ENTITIES), f"{deployment} writer matrix does not cover schema entities")

        expected_boundaries = []
        for index, segment in enumerate(segments[1:], start=1):
            start = segment["start_block_inclusive"]
            expected_boundaries.append(
                {
                    "graft_block": start - 1,
                    "base_deployment_at_graft_block": segments[index - 1]["deployment"],
                    "child_deployment_at_next_block": segment["deployment"],
                    "base_probe_block": start - 1,
                    "child_probe_block": start,
                    "state_continuity_evidence_status": "not_captured",
                }
            )
            require(
                select_segment(contract, network, start - 1)["deployment"]
                == segments[index - 1]["deployment"],
                f"{network} graft-block segment mis-selection",
            )
            require(
                select_segment(contract, network, start)["deployment"] == segment["deployment"],
                f"{network} child-block segment mis-selection",
            )
        require(chain["boundary_probes"] == expected_boundaries, f"{network} boundary probes drift")

    require(seen == set(MANIFEST_LOCKS), f"missing ancestor or unexpected segment: {sorted(seen ^ set(MANIFEST_LOCKS))}")

    # Every direct manifest file reference must be retained, indexed, and typed.
    direct_references: set[str] = set(MANIFEST_LOCKS)
    for deployment in MANIFEST_LOCKS:
        raw = load_yaml_bytes(artifact_payload(root, deployment), deployment)
        direct_references.update(direct_ipfs_references(raw))
    require(direct_references == set(by_cid), f"artifact-reference closure drift: {sorted(direct_references ^ set(by_cid))}")

    truth = contract["truth_boundary"]
    require(isinstance(truth, dict), "truth boundary malformed")
    for field in (
        "constant_store_set_target_inventory_complete",
        "field_writer_audit_complete",
        "logical_oracle_complete",
        "boundary_state_continuity_complete",
        "physical_parity_complete",
        "poi_parity_complete",
        "segment_execution_models_decided",
        "production_ready",
    ):
        require(truth.get(field) is False, f"unproved promotion claim: {field}")
    return contract


def verify(root: Path, contract_path: Path | None = None) -> dict[str, object]:
    root = root.resolve()
    path = contract_path or root / CONTRACT_PATH
    actual = validate_internal_contract(root, load_json(path))
    expected = build_contract(root)
    require(actual == expected, "contract content drift from deterministic artifact-derived inventory")
    return actual


def render(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--write-contract", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        if args.write_contract:
            contract = build_contract(root)
            output = root / CONTRACT_PATH
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(render(contract), encoding="utf-8")
            print(f"wrote {output.relative_to(root)}")
        else:
            contract = verify(root)
            print(
                "verified Uniswap V3 graft ancestry: "
                f"{len(contract['networks']['mainnet']['segments'])} mainnet segments, "
                f"{len(contract['networks']['base']['segments'])} Base segments, "
                f"{len(contract['artifacts'])} content-addressed artifacts"
            )
        return 0
    except (OSError, VerificationError) as error:
        print(f"graft ancestry verification failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
