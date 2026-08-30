#!/usr/bin/env python3
"""Verify the bounded runtime capsule for the two modern Uniswap V3 Pool WASMs."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[1]
CONTRACT_PATH = Path("uniswap-v3/pool-runtime/v1/contract.json")
CONTRACT_VERSION = "uniswap-v3-pool-runtime/v1"
BASE_COMMIT = "1df0c471c354fc3718dac88a973a34f5b149d9c3"
RUNTIME_SOURCE_PATH = Path("scripts/uniswap_v3_wat_runtime.py")
RUNTIME_PATH = REPOSITORY / RUNTIME_SOURCE_PATH
WABT_VERSION = "1.0.35"


class VerificationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


try:
    RUNTIME_SOURCE_BYTES = RUNTIME_PATH.read_bytes()
except OSError as error:
    raise RuntimeError(f"cannot read {RUNTIME_PATH}: {error}") from error
RUNTIME_IMPORT_SPEC = importlib.util.spec_from_file_location(
    "uniswap_v3_wat_runtime_for_pool_runtime", RUNTIME_PATH
)
if RUNTIME_IMPORT_SPEC is None or RUNTIME_IMPORT_SPEC.loader is None:
    raise RuntimeError(f"cannot import {RUNTIME_PATH}")
RUNTIME = importlib.util.module_from_spec(RUNTIME_IMPORT_SPEC)
sys.modules[RUNTIME_IMPORT_SPEC.name] = RUNTIME
exec(compile(RUNTIME_SOURCE_BYTES, str(RUNTIME_PATH), "exec"), RUNTIME.__dict__)


def raw_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()


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


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(), object_pairs_hook=reject_duplicate_keys)
    except (OSError, json.JSONDecodeError) as error:
        raise VerificationError(f"cannot load {path}: {error}") from error
    require(isinstance(value, dict), f"{path} must contain one JSON object")
    return value


def bind_candidate_runtime(root: Path) -> str:
    candidate = root.resolve() / RUNTIME_SOURCE_PATH
    try:
        candidate_bytes = candidate.read_bytes()
    except OSError as error:
        raise VerificationError(f"cannot read candidate shared runtime {candidate}: {error}") from error
    require(
        candidate_bytes == RUNTIME_SOURCE_BYTES,
        "candidate-root shared WAT runtime bytes differ from the exact imported runtime bytes",
    )
    return hashlib.sha256(candidate_bytes).hexdigest()


@dataclass(frozen=True)
class WatFunction:
    name: str
    start_line: int
    lines: tuple[str, ...]
    function_index: int

    @property
    def payload(self) -> bytes:
        return ("\n".join(self.lines) + "\n").encode()


@dataclass(frozen=True)
class PoolProfileSpec:
    profile_id: str
    cid: str
    wasm_bytes: int
    wasm_sha256: str
    wat_sha256: str
    start_line_count: int
    start_body_sha256: str
    allocator_floor: int
    initialized_data_end: int
    initialized_data_segment_count: int
    q192_writer_line: int
    ensure_capacity_body_sha256: str
    event_param_get_body_sha256: str


@dataclass(frozen=True)
class LegacyPoolProfileSpec:
    profile_id: str
    cid: str
    wasm_bytes: int
    wasm_sha256: str
    wat_sha256: str
    wat_line_count: int
    initialized_data_end: int
    initialized_data_segment_count: int
    initialized_data_inventory_sha256: str
    allocator_floor: int
    group_id: str


@dataclass(frozen=True)
class LegacyGroupSpec:
    group_id: str
    collection: Any
    expected_import_inventory_sha256: str
    expected_global_definition_inventory_sha256: str
    expected_global_set_inventory_sha256: str
    no_writer_static_globals: dict[str, int]


PROFILE_SPECS = (
    PoolProfileSpec(
        profile_id="modern-base",
        cid="QmPZCHE1URf4oviX7Tbrkw3aMENo1qAeEGa1AS2gMumG7P",
        wasm_bytes=76_545,
        wasm_sha256="e0050819429ca279916027512234119308ab26f4ff115939e6409aab676a501c",
        wat_sha256="bd42b64aeaaf677018c11fe779179ecb81d7c4125fa0b846134bb0e0a6059ad1",
        start_line_count=50,
        start_body_sha256="52a99f58e7904d3ed759bf0a0272101e9e998bdfdb0e2fe93a21aedd6c12d589",
        allocator_floor=20_940,
        initialized_data_end=20_902,
        initialized_data_segment_count=528,
        q192_writer_line=46,
        ensure_capacity_body_sha256="09e6f7222a5ada41dc343ffb5eb297342dd3ff167cd6532bcaeec772f9705578",
        event_param_get_body_sha256="dd7f14070e5643932f0dc9ba5d3e7f9966aa900dc9e171eb213b9aaf4cf6d0c8",
    ),
    PoolProfileSpec(
        profile_id="modern-mainnet",
        cid="QmSaGgPnyhStviGQSGTokQYRgVqLFNvnGWfnv8tSfuvpWD",
        wasm_bytes=78_047,
        wasm_sha256="f9a25426839d83f84679cd0d272582f2631c57117093ffd342351bc04aff8970",
        wat_sha256="8454917398ef7a3b8f965a7e40e5b7a1d8cf7879e898490aeabe15726c3d4281",
        start_line_count=49,
        start_body_sha256="785ca5348b08a12a9a90b79760beefb3ab8b71130bfc01ee9e48ddefa36c79d3",
        allocator_floor=22_700,
        initialized_data_end=22_662,
        initialized_data_segment_count=558,
        q192_writer_line=45,
        ensure_capacity_body_sha256="90f7a34c6ef281823ee2062d67f72c339ee27b748d82b578348b02c3300a7579",
        event_param_get_body_sha256="d7838efd2a3cd438b05d6d627df4c1ea8ef0a291c02921096b89198d8643de68",
    ),
)

PROFILE_BY_ID = {item.profile_id: item for item in PROFILE_SPECS}
PROFILE_BY_CID = {item.cid: item for item in PROFILE_SPECS}
MODERN_EXPECTED_ARTIFACT_TUPLES = {
    (item.profile_id, item.cid, item.wasm_sha256, item.wat_sha256)
    for item in PROFILE_SPECS
}

LEGACY_GROUP_SPECS = {
    "legacy-wuom": LegacyGroupSpec(
        group_id="legacy-wuom",
        collection=RUNTIME.LegacyCollectionProfileSpec(
            group_id="legacy-wuom",
            start_body_sha256="287ad43620693a8d7b56e4e279c70c20ddf418deee872113bea040240b6d6c37",
            start_floor=10_984,
            start_data_literal_pointer=2_336,
            start_result_globals=("$g9", "$g10"),
            array_constructor_body_sha256="49c2ef950af1df2183e8d9a554594508f9b0bf86ed4831a39a211468f3023428",
            array_abort_source_pointer=2_560,
            array_push_body_sha256="3ac2d877fec3008d9f13c8e95a1e20bc78c8a9bbe429630cc5e0a077604c3d5d",
            string_allocate_body_sha256="857aa72088e9ec6101a1c984f483b2321172f093d8acfb857acbf79b7f2432f1",
            string_abort_source_pointer=2_696,
        ),
        expected_import_inventory_sha256="9c6a135b698d1112402448fe57a65c99aaa1dff83651071eab5fc0f78a79063d",
        expected_global_definition_inventory_sha256="1d7c8731dca518f74fe9a5c027f3853d982e272286b5ebc1e034c9328943360a",
        expected_global_set_inventory_sha256="c845773db986aab170addee20811fb1bbb0a6d294177dee5e2ddf85f60efa50e",
        no_writer_static_globals={"$g8": 2_328},
    ),
    "legacy-yqr": LegacyGroupSpec(
        group_id="legacy-yqr",
        collection=RUNTIME.LegacyCollectionProfileSpec(
            group_id="legacy-yqr",
            start_body_sha256="7b4e87d1aac1cdab8bbf97f74860739b39d24e70561c5f5b658318720852e9c1",
            start_floor=11_072,
            start_data_literal_pointer=2_424,
            start_result_globals=("$g9", "$g10"),
            array_constructor_body_sha256="f70f06c137d5b20c51b88de9ef8ff2eda6f713b92a8ab2fe0515238823e9fa8d",
            array_abort_source_pointer=2_648,
            array_push_body_sha256="383337d49695eb70e6f113a5b5ee2bac214824350c788a996594a8d3104515d7",
            string_allocate_body_sha256="bac733ad2a46c0975cfeb8f37fd25464803ec78d52cb5b6262aad4386ea71e1b",
            string_abort_source_pointer=2_784,
        ),
        expected_import_inventory_sha256="9c6a135b698d1112402448fe57a65c99aaa1dff83651071eab5fc0f78a79063d",
        expected_global_definition_inventory_sha256="99e0ab1b8e3bafdea0512d073dc4e08a6624f61e485f16d686244dc696c91594",
        expected_global_set_inventory_sha256="c845773db986aab170addee20811fb1bbb0a6d294177dee5e2ddf85f60efa50e",
        no_writer_static_globals={"$g8": 2_416},
    ),
    "legacy-zpi": LegacyGroupSpec(
        group_id="legacy-zpi",
        collection=RUNTIME.LegacyCollectionProfileSpec(
            group_id="legacy-zpi",
            start_body_sha256="dfedcb96be9317aad4d57a7bb53c8df3bbc2cd661a90f94b30ec299b7045424a",
            start_floor=9_304,
            start_data_literal_pointer=320,
            start_result_globals=("$g10", "$g11"),
            array_constructor_body_sha256="3ceaf38d13058325c0d8929a6ecf48010e801860d9d11cb34b9f321f73eef486",
            array_abort_source_pointer=880,
            array_push_body_sha256="741170d740eafb130b2ca5ec98930f6e4d648ab781de35b8f0e193c4023ab4af",
            string_allocate_body_sha256="3775376af9346f6a9e5ab38c9721e024a9e481481189b1cc3cb2035fcf07f608",
            string_abort_source_pointer=1_016,
        ),
        expected_import_inventory_sha256="9007556738a86572d9edd0fa3c5ebb507def4948449090908dfd729e09074d14",
        expected_global_definition_inventory_sha256="f64d9bc88ea4db73fd7855858981a0f218186dca5b4cde33e7aed8b914247c0d",
        expected_global_set_inventory_sha256="48fe667f180e56e42afed6a1856be83ee4f2647cc03fe7547a1de4ba2e0efbca",
        no_writer_static_globals={"$g8": 632, "$g9": 656},
    ),
    "legacy-stable": LegacyGroupSpec(
        group_id="legacy-stable",
        collection=RUNTIME.LegacyCollectionProfileSpec(
            group_id="legacy-stable",
            start_body_sha256="e97cc12f2129907015f400de8d01332698f783916ea1eaaaaca46272ccd79b53",
            start_floor=11_112,
            start_data_literal_pointer=2_464,
            start_result_globals=("$g10", "$g11"),
            array_constructor_body_sha256="174c75441ee0095f6f7e05633ee7f7352c47019ed0140970d3f28560d5ea4d63",
            array_abort_source_pointer=2_688,
            array_push_body_sha256="830deee879384740601f635f04a329aa2a0e3688c5dc2bc8178e399308625665",
            string_allocate_body_sha256="098a5876f9394c48b20268aaecb58e3967f063baced1bfc0b5a42aafa036962b",
            string_abort_source_pointer=2_824,
        ),
        expected_import_inventory_sha256="9007556738a86572d9edd0fa3c5ebb507def4948449090908dfd729e09074d14",
        expected_global_definition_inventory_sha256="6b0969d826801b77ad412adb2295f1a0844dd58265b4c1cf161e6143549d8ea1",
        expected_global_set_inventory_sha256="48fe667f180e56e42afed6a1856be83ee4f2647cc03fe7547a1de4ba2e0efbca",
        no_writer_static_globals={"$g8": 2_328, "$g9": 2_456},
    ),
}

LEGACY_PROFILE_SPECS = (
    LegacyPoolProfileSpec(
        "legacy-mainnet-root", "QmWuomVAQCdEXdCRavcsmRz4BNqPx2nppqe8S6AXid66xw",
        40_813, "f2238dc4f98e2ab6e7caf1ebe2bf2574c0f47f50df17c466b492542f3e06e4e7",
        "5e8f6e0c96992afee37669c053b8940355e09e18741e53089838fb1c11924666", 8_842,
        10_981, 194, "f1da16a54377c5b25aed8b60d9adc51d87abedd906403ef85dbb49ff1cc91bd5",
        10_984, "legacy-wuom",
    ),
    LegacyPoolProfileSpec(
        "legacy-mainnet-qmrv", "QmYQRHstsSS7mntgKNSot74qN2dpuyFEtd1DddPmnqWC65",
        40_954, "ee35ffc861d04313370845e12d27de3a16d4f1f2d7137b81407c797d189fe94f",
        "84dc181907baec30b5770fe5f8cdc61062b002989eb09f218963fd1995209aae", 8_865,
        11_069, 195, "686512ac95f010c719799331d12bd3ffe9a1b1e6782cff634dd0dd5b240af7a6",
        11_072, "legacy-yqr",
    ),
    LegacyPoolProfileSpec(
        "legacy-base-root", "QmZPiDeH1j95mozzb5AjKCHn6zgpnhMu77kNAitPbi4Vt3",
        39_128, "daaf355098f0d962fe772cdf858a5135cf229c03224380a83ea1e5248b746a0c",
        "7444416b1ac3e7a3c98f4a2d5d3f24d343b2a1af8238f159b4839a0b2adc0a02", 8_859,
        9_301, 177, "efbba1f5eda3364f807941b0e7019878422028ef5500487ae41e7a5a8cebd495",
        9_304, "legacy-zpi",
    ),
    LegacyPoolProfileSpec(
        "legacy-mainnet-stable", "QmeNbEMUnaaPpmpLaUVBJfFWRCN5SxG8xPG5eDNoXEGdbW",
        40_971, "0cb47b9bc9352ff26fda2267967374dee8bd54b9627120c97e442de1692979c5",
        "6fac410afa86a411137e3bfabf46550261785b79fbfc53a39b8ec59492061d36", 8_862,
        11_109, 197, "f7ecfeb04dec522d8e56e2b0750fd302ff36a9e182692409817c1872bd499a0b",
        11_112, "legacy-stable",
    ),
    LegacyPoolProfileSpec(
        "legacy-mainnet-stable-fee-tier-1", "Qmaydei2ScE7JptBTPgSfkf6PFxEZpLn39gEXYqrBZhsv8",
        40_987, "5130b364eb6e67767f0f6890011095a40f603af96e3dab9b3207e474af7d9e3b",
        "3e68ada1f22ed2a2b72f74ecbdebe2f084ad42e11068fdc6991947963f145cb5", 8_871,
        11_109, 197, "f7ecfeb04dec522d8e56e2b0750fd302ff36a9e182692409817c1872bd499a0b",
        11_112, "legacy-stable",
    ),
    LegacyPoolProfileSpec(
        "legacy-mainnet-stable-fee-tier-100", "QmadCQv7VPgNXhQTNkcDyzmiWZpWexynUH4XuuaMrsAbJY",
        40_988, "6f795b4a38a805ff8fbff2b0c33f8c5e52da2cd342a5efea9cffe637ec8ff42b",
        "3868d954fe13117081173408b79d72fb88c4b88bfeabfb7a6e93b5482b87e4ff", 8_871,
        11_109, 197, "f7ecfeb04dec522d8e56e2b0750fd302ff36a9e182692409817c1872bd499a0b",
        11_112, "legacy-stable",
    ),
)
LEGACY_EXPECTED_ARTIFACT_TUPLES = {
    (item.profile_id, item.cid, item.wasm_sha256, item.wat_sha256)
    for item in LEGACY_PROFILE_SPECS
}
EXPECTED_ARTIFACT_TUPLES = MODERN_EXPECTED_ARTIFACT_TUPLES | LEGACY_EXPECTED_ARTIFACT_TUPLES

MODULE_FUNCTION_DECLARATIONS = {
    "modern-base": RUNTIME.AllDefinedFunctionDeclarationInventorySpec(
        expected_function_count=123,
        expected_inventory_sha256="4c288bb51f506dcad12d1985d772c388c5aa7fb31e83adb3777dc2a9c2a38d4e",
    ),
    "modern-mainnet": RUNTIME.AllDefinedFunctionDeclarationInventorySpec(
        expected_function_count=123,
        expected_inventory_sha256="5669d97cd2b172292c699775b477383cef35562cf3b576e6fb5235425f985fad",
    ),
    "legacy-mainnet-root": RUNTIME.AllDefinedFunctionDeclarationInventorySpec(
        expected_function_count=225,
        expected_inventory_sha256="49119dc2f85372f5c8975fcdb6c25b06d868cdca61b1fdc5a9448038ec421c4e",
    ),
    "legacy-mainnet-qmrv": RUNTIME.AllDefinedFunctionDeclarationInventorySpec(
        expected_function_count=225,
        expected_inventory_sha256="a91930ddbf086e37a5e240e8ff3b5a390373970c03f6f066678def94c0facbf4",
    ),
    "legacy-base-root": RUNTIME.AllDefinedFunctionDeclarationInventorySpec(
        expected_function_count=225,
        expected_inventory_sha256="9882a4927dfbca99f3197b45158a70a4103e9f52589ee11bc144c6f0eff1670e",
    ),
    "legacy-mainnet-stable": RUNTIME.AllDefinedFunctionDeclarationInventorySpec(
        expected_function_count=225,
        expected_inventory_sha256="68e17a52c7846777508cbd7da39e15db9482b9711c0966658f34e5999da8a8e2",
    ),
    "legacy-mainnet-stable-fee-tier-1": RUNTIME.AllDefinedFunctionDeclarationInventorySpec(
        expected_function_count=225,
        expected_inventory_sha256="68e17a52c7846777508cbd7da39e15db9482b9711c0966658f34e5999da8a8e2",
    ),
    "legacy-mainnet-stable-fee-tier-100": RUNTIME.AllDefinedFunctionDeclarationInventorySpec(
        expected_function_count=225,
        expected_inventory_sha256="68e17a52c7846777508cbd7da39e15db9482b9711c0966658f34e5999da8a8e2",
    ),
}

TYPED_MAP_SET_CALL = (
    "~lib/@graphprotocol/graph-ts/common/collections/"
    "TypedMap<~lib/string/String_~lib/@graphprotocol/graph-ts/common/value/Value>#set"
)
TYPED_MAP_GET_CALL = TYPED_MAP_SET_CALL.removesuffix("#set") + "#get"
EVENT_PARAM_GET_CALL = (
    "~lib/array/Array<~lib/@graphprotocol/graph-ts/chain/ethereum/"
    "ethereum.EventParam>#__get"
)
STUB_NEW_CALL = "~lib/rt/stub/__new"


def function_declaration(suffix: str, *lines: str) -> Any:
    return RUNTIME.FunctionDeclarationSpec(suffix, tuple(lines))


MODERN_POOL_FUNCTION_DECLARATIONS = {
    "stub_alloc": function_declaration(
        "~lib/rt/stub/__alloc",
        "(func $~lib/rt/stub/__alloc (type $t0) (param $p0 i32) (result i32)",
        "(local $l1 i32) (local $l2 i32) (local $l3 i32) (local $l4 i32) (local $l5 i32)",
    ),
    "stub_new": function_declaration(
        "~lib/rt/stub/__new",
        "(func $~lib/rt/stub/__new (type $t1) (param $p0 i32) (param $p1 i32) (result i32)",
        "(local $l2 i32) (local $l3 i32)",
    ),
    "ensure_capacity": function_declaration(
        "~lib/array/ensureCapacity",
        "(func $~lib/array/ensureCapacity (type $t3) (param $p0 i32) (param $p1 i32)",
        "(local $l2 i32) (local $l3 i32) (local $l4 i32) (local $l5 i32) (local $l6 i32) (local $l7 i32) (local $l8 i32) (local $l9 i32) (local $l10 i32)",
    ),
    "typed_map_set": function_declaration(
        TYPED_MAP_SET_CALL,
        f"(func ${TYPED_MAP_SET_CALL} (type $t4) (param $p0 i32) (param $p1 i32) (param $p2 i32)",
        "(local $l3 i32)",
    ),
    "entity_constructor": function_declaration(
        "common/collections/Entity#constructor",
        "(func $~lib/@graphprotocol/graph-ts/common/collections/Entity#constructor (type $t0) (param $p0 i32) (result i32)",
        "(local $l1 i32) (local $l2 i32)",
    ),
    "memory_fill": function_declaration(
        "~lib/memory/memory.fill",
        "(func $~lib/memory/memory.fill (type $t3) (param $p0 i32) (param $p1 i32)",
        "(local $l2 i32)",
    ),
    "memory_copy": function_declaration(
        "~lib/memory/memory.copy",
        "(func $~lib/memory/memory.copy (type $t4) (param $p0 i32) (param $p1 i32) (param $p2 i32)",
        "(local $l3 i32) (local $l4 i32)",
    ),
    "memcpy": function_declaration(
        "~lib/util/memory/memcpy",
        "(func $~lib/util/memory/memcpy (type $t4) (param $p0 i32) (param $p1 i32) (param $p2 i32)",
        "(local $l3 i32) (local $l4 i32) (local $l5 i32)",
    ),
    "event_param_get": function_declaration(
        EVENT_PARAM_GET_CALL,
        f"(func ${EVENT_PARAM_GET_CALL} (type $t1) (param $p0 i32) (param $p1 i32) (result i32)",
    ),
    "typed_map_get": function_declaration(
        TYPED_MAP_GET_CALL,
        f"(func ${TYPED_MAP_GET_CALL} (type $t1) (param $p0 i32) (param $p1 i32) (result i32)",
        "(local $l2 i32)",
    ),
    "string_eq": function_declaration(
        "~lib/string/String.__eq",
        "(func $~lib/string/String.__eq (type $t1) (param $p0 i32) (param $p1 i32) (result i32)",
        "(local $l2 i32) (local $l3 i32) (local $l4 i32) (local $l5 i32)",
    ),
}


LEGACY_FUNCTION_DECLARATIONS = {
    "native_start": function_declaration("start", "(func $start (type $t0)"),
    "constants_start": function_declaration(
        "start:src/utils/constants", "(func $start:src/utils/constants (type $t0)"
    ),
    "byte_array_from_i32": function_declaration(
        "index/ByteArray.fromI32",
        "(func $~lib/@graphprotocol/graph-ts/index/ByteArray.fromI32 (type $t1) (param $p0 i32) (result i32)",
        "(local $l1 i32)",
    ),
    "factory_constructor": function_declaration(
        "templates/Pool/Factory/Factory#constructor",
        "(func $src/types/templates/Pool/Factory/Factory#constructor (type $t2) (param $p0 i32) (param $p1 i32) (result i32)",
    ),
    "native_math_pow": function_declaration(
        "~lib/math/NativeMath.pow",
        "(func $~lib/math/NativeMath.pow (type $t15) (result f64)",
        "(local $l0 i32) (local $l1 i32) (local $l2 i32) (local $l3 i32) (local $l4 i64) (local $l5 f64) (local $l6 f64) (local $l7 f64) (local $l8 f64)",
    ),
    "arena_allocate": function_declaration(
        "allocator/arena/__memory_allocate",
        "(func $~lib/allocator/arena/__memory_allocate (type $t1) (param $p0 i32) (result i32)",
        "(local $l1 i32) (local $l2 i32) (local $l3 i32) (local $l4 i32)",
    ),
    "compute_size": function_declaration(
        "internal/arraybuffer/computeSize",
        "(func $~lib/internal/arraybuffer/computeSize (type $t1) (param $p0 i32) (result i32)",
    ),
    "allocate_unsafe": function_declaration(
        "internal/arraybuffer/allocateUnsafe",
        "(func $~lib/internal/arraybuffer/allocateUnsafe (type $t1) (param $p0 i32) (result i32)",
        "(local $l1 i32)",
    ),
    "reallocate_unsafe": function_declaration(
        "internal/arraybuffer/reallocateUnsafe",
        "(func $~lib/internal/arraybuffer/reallocateUnsafe (type $t2) (param $p0 i32) (param $p1 i32) (result i32)",
        "(local $l2 i32) (local $l3 i32)",
    ),
    "event_param_get": function_declaration(
        "EventParam>#__get",
        "(func $~lib/array/Array<~lib/@graphprotocol/graph-ts/chain/ethereum/ethereum.EventParam>#__get (type $t2) (param $p0 i32) (param $p1 i32) (result i32)",
    ),
    "value_constructor": function_declaration(
        "index/Value#constructor",
        "(func $~lib/@graphprotocol/graph-ts/index/Value#constructor (type $t10) (result i32)",
        "(local $l0 i32)",
    ),
    "value_from_big_decimal": function_declaration(
        "index/Value.fromBigDecimal",
        "(func $~lib/@graphprotocol/graph-ts/index/Value.fromBigDecimal (type $t1) (param $p0 i32) (result i32)",
        "(local $l1 i32)",
    ),
    "typed_map_get": function_declaration(
        "index/Value>#get",
        "(func $~lib/@graphprotocol/graph-ts/index/TypedMap<~lib/string/String_~lib/@graphprotocol/graph-ts/index/Value>#get (type $t2) (param $p0 i32) (param $p1 i32) (result i32)",
        "(local $l2 i32)",
    ),
    "typed_map_get_entry": function_declaration(
        "index/Value>#getEntry",
        "(func $~lib/@graphprotocol/graph-ts/index/TypedMap<~lib/string/String_~lib/@graphprotocol/graph-ts/index/Value>#getEntry (type $t2) (param $p0 i32) (param $p1 i32) (result i32)",
        "(local $l2 i32)",
    ),
    "typed_map_set": function_declaration(
        "index/Value>#set",
        "(func $~lib/@graphprotocol/graph-ts/index/TypedMap<~lib/string/String_~lib/@graphprotocol/graph-ts/index/Value>#set (type $t4) (param $p0 i32) (param $p1 i32) (param $p2 i32)",
        "(local $l3 i32)",
    ),
    "entry_constructor": function_declaration(
        "ethereum.SmartContract#constructor",
        "(func $~lib/@graphprotocol/graph-ts/chain/ethereum/ethereum.SmartContract#constructor (type $t5) (param $p0 i32) (param $p1 i32) (param $p2 i32) (result i32)",
    ),
    "string_eq": function_declaration(
        "~lib/string/String.__eq",
        "(func $~lib/string/String.__eq (type $t2) (param $p0 i32) (param $p1 i32) (result i32)",
        "(local $l2 i32)",
    ),
    "compare_unsafe": function_declaration(
        "internal/string/compareUnsafe",
        "(func $~lib/internal/string/compareUnsafe (type $t5) (param $p0 i32) (param $p1 i32) (param $p2 i32) (result i32)",
        "(local $l3 i32)",
    ),
    "memcpy": function_declaration(
        "internal/memory/memcpy",
        "(func $~lib/internal/memory/memcpy (type $t4) (param $p0 i32) (param $p1 i32) (param $p2 i32)",
        "(local $l3 i32) (local $l4 i32) (local $l5 i32)",
    ),
    "memmove": function_declaration(
        "internal/memory/memmove",
        "(func $~lib/internal/memory/memmove (type $t4) (param $p0 i32) (param $p1 i32) (param $p2 i32)",
        "(local $l3 i32)",
    ),
    "memset": function_declaration(
        "internal/memory/memset",
        "(func $~lib/internal/memory/memset (type $t8) (param $p0 i32) (param $p1 i32)",
        "(local $l2 i32)",
    ),
    "memory_allocate": function_declaration(
        "~lib/memory/memory.allocate",
        "(func $~lib/memory/memory.allocate (type $t1) (param $p0 i32) (result i32)",
    ),
    "memory_reset": function_declaration(
        "~lib/memory/memory.reset", "(func $~lib/memory/memory.reset (type $t0)"
    ),
    "array_constructor": function_declaration(
        "TypedMapEntry<~lib/string/String_~lib/@graphprotocol/graph-ts/index/Value>>#constructor",
        "(func $~lib/array/Array<~lib/@graphprotocol/graph-ts/index/TypedMapEntry<~lib/string/String_~lib/@graphprotocol/graph-ts/index/Value>>#constructor (type $t1) (param $p0 i32) (result i32)",
        "(local $l1 i32) (local $l2 i32) (local $l3 i32)",
    ),
    "array_push": function_declaration(
        "TypedMapEntry<~lib/string/String_~lib/@graphprotocol/graph-ts/index/Value>>#push",
        "(func $~lib/array/Array<~lib/@graphprotocol/graph-ts/index/TypedMapEntry<~lib/string/String_~lib/@graphprotocol/graph-ts/index/Value>>#push (type $t8) (param $p0 i32) (param $p1 i32)",
        "(local $l2 i32) (local $l3 i32) (local $l4 i32)",
    ),
    "string_allocate": function_declaration(
        "internal/string/allocateUnsafe",
        "(func $~lib/internal/string/allocateUnsafe (type $t1) (param $p0 i32) (result i32)",
        "(local $l1 i32)",
    ),
}

POOL_COLLECTION_SPEC = RUNTIME.ModernPoolCollectionSpec(
    typed_map_set_call=TYPED_MAP_SET_CALL,
    typed_map_get_call=TYPED_MAP_GET_CALL,
    event_param_get_call=EVENT_PARAM_GET_CALL,
    stub_new_call=STUB_NEW_CALL,
    stub_alloc_body_sha256="a03922d8f65cdc65e9d23c65bae22238c3783fed3294ec8847c2951f45a49c68",
    stub_new_body_sha256="dc15ae7bfd1ff6f9f27d365946a2de6d849b46ed9e08818b80d59c05f97918fa",
    typed_map_set_body_sha256="1e32ff9bb00d137e45c1023931fe103bbe71d7011e2955044d0fb772b88f008b",
    typed_map_get_body_sha256="672fd714a063fdaf09f51b8e3a25c5b01a2124f68f3e8f7fcb587cddeb5999cb",
    entity_constructor_body_sha256="df453669386fdd214d23b561c134fdc0b1fe4e8c9bb46a3b6bec63e22e51d032",
    entity_constructor_type_ids=(25, 27, 29),
    string_eq_body_sha256="f7967b738553ba98aba24f869e968d73e8013f99e83d02e106cad52306aa3c3f",
    function_declarations=MODERN_POOL_FUNCTION_DECLARATIONS,
    profiles={
        item.profile_id: RUNTIME.ModernPoolCollectionProfileSpec(
            ensure_capacity_body_sha256=item.ensure_capacity_body_sha256,
            event_param_get_body_sha256=item.event_param_get_body_sha256,
            memory_fill_body_sha256="3eb4dece783813845638f30ebde64f0ce5c2d10784a724c6b5bcd346e7771390",
            memory_copy_body_sha256="0128a0af41ee62c13df7a14de4648d2e7ac19f230786e447a8736179e36d74a6",
            memcpy_body_sha256="a201b34d93d9bb7e4813134f668fb9436014260ba637d2db39cf7af3dc84a97c",
        )
        for item in PROFILE_SPECS
    },
)

LEGACY_COLLECTION_SPEC = RUNTIME.LegacyCollectionSpec(
    constants_start_body_sha256="232c849ec7edb036ef054a9ef6da3da385a249ed1f09cfe1d5150fb0cdfae48c",
    byte_array_from_i32_body_sha256="3ef30704c311054beff2e7feaec737e977c9f55e3128f77007ef5a8d138c8f1f",
    factory_constructor_body_sha256="8bb102e04b4f08b651fd9cac8d22fa7929e827dd4724a95827637699838bf781",
    native_math_pow_body_sha256="70dd0798aa9bb6f1233f0ca0bd55e5efd91867cbc5a40f43c1683f4479923f0d",
    arena_allocate_body_sha256="a623541999e809e36b28e93c8f51c112db4522793a991befaf70302b2e8536d3",
    compute_size_body_sha256="1e18ac493de5e2cdb5602df7e2836274ead1cebc6b6d4f8109e2b330400aa27c",
    allocate_unsafe_body_sha256="e682646c4f45c8ead7d44af5369332c44fc80c348547bbec4a91a2cb6f0d2cf0",
    reallocate_unsafe_body_sha256="143cb92ce81c3e40c7403e38bca744cd74a5a3c38f737898e824d699d7d99b4f",
    event_param_get_body_sha256="fc0df8b86d252ba211dab70c151a7e02b70d6ffd6ed5020a5c03b107e62cd124",
    value_constructor_body_sha256="cf90529347bf394fa999326553e3e83db5f9df634a3cfa9e9dac70538a478422",
    value_from_big_decimal_body_sha256="c22dc4c0902b6c3aa5b53bf549c79ccb3b8b5175add4de32117b556c19e54741",
    typed_map_get_body_sha256="10c6b7fd4cd1bc0ba3d0f10aed3d6c935831228c31e7363ce4360e496517839a",
    typed_map_get_entry_body_sha256="7252de05e0d18971d8914753ca4f0d39b5984d81ef160014463b3c7212616c50",
    typed_map_set_body_sha256="5ab31969af87a734b8fb29f32ae0046b68dade3b74c24b320bab0fbdd4fde923",
    entry_constructor_body_sha256="77a5c0d652ef661a5abf6c119ff0aa3fb6ff18dce62e9afb86d540988856535c",
    string_eq_body_sha256="13098aa1b32179fca6ed0194087ebd6d83dc2c8f5eee03d97bcf6e2f7aa247a4",
    compare_unsafe_body_sha256="203ddf43add8c0f8f0bddde6136f4a67d1a6a04b331e87bd87d87e40fad1b14d",
    memcpy_body_sha256="b84e9b1f9c3394c4495fd02fa0c1445d46b6988ec8c6fb9799dcda5164617c67",
    memmove_body_sha256="c15a394bae33d7b2489e53bbabf806c9367a6bcf00dfa2e88ebcfec87b3906b6",
    memset_body_sha256="d501c434f3cb81a087c2da86432a0b4054083d8860eae61ac85841082675f940",
    memory_allocate_body_sha256="ae57abfa142d50c8539b89b63ec1790b25722d7ecdda61aee91a97026daf237d",
    memory_reset_body_sha256="9767c060a0ccee2ec358b573bf2c7334e08e0cca9e14f7618c01cffa39d50c1c",
    function_declarations=LEGACY_FUNCTION_DECLARATIONS,
    profiles={
        profile.profile_id: LEGACY_GROUP_SPECS[profile.group_id].collection
        for profile in LEGACY_PROFILE_SPECS
    },
)

MUTABLE_GLOBALS = (
    "$~started",
    "$~lib/rt/stub/offset",
    "$src/utils/constants/ZERO_BI",
    "$src/utils/constants/ONE_BI",
    "$src/utils/constants/ZERO_BD",
    "$src/utils/constants/ONE_BD",
    "$src/utils/pricing/MINIMUM_ETH_LOCKED",
    "$src/utils/pricing/Q192",
)

TRUE_FLAGS = {
    "all_eight_pool_runtime_capsules_proven",
    "six_legacy_pool_runtime_capsules_proven",
    "exact_six_legacy_pool_artifact_tuples_selected",
    "all_four_legacy_pool_digest_groups_bound",
    "six_legacy_pool_native_start_module_states_proven",
    "six_legacy_pool_public_collection_capsules_proven",
    "six_legacy_pool_allocator_data_floors_proven",
    "six_legacy_pool_complete_import_export_global_inventories_proven",
    "six_legacy_pool_no_indirect_table_and_handler_reset_reachability_proven",
    "six_legacy_pool_exact_function_declaration_inventories_proven",
    "six_legacy_pool_all_defined_function_declaration_inventories_proven",
    "exact_two_modern_pool_artifact_tuples_selected",
    "candidate_shared_runtime_bytes_equal_executed_bytes",
    "both_modern_pool_public_collection_capsules_proven",
    "both_modern_pool_77_line_typed_map_setters_proven",
    "both_modern_pool_entity_constructor_type_ids_proven",
    "both_modern_pool_getter_index_and_string_equality_dependencies_proven",
    "both_modern_pool_allocator_return_identities_proven",
    "both_modern_pool_exported_start_and_global_writer_inventories_proven",
    "both_modern_pool_allocator_floors_above_all_initialized_data_proven",
    "both_modern_pool_start_direct_memory_write_absence_proven",
    "both_modern_pool_exact_function_declaration_inventories_proven",
    "both_modern_pool_all_defined_function_declaration_inventories_proven",
}

FALSE_FLAGS = {
    "pool_initialize_handler_semantics_complete",
    "pool_mint_handler_semantics_complete",
    "pool_burn_handler_semantics_complete",
    "pool_swap_handler_semantics_complete",
    "pool_flash_handler_semantics_complete",
    "pool_complete_entity_history",
    "all_manifest_handler_semantics_complete",
    "actual_historic_event_population_proven",
    "host_functions_cannot_write_arbitrary_linear_memory",
    "aggregate_helper_memory_safety_rederived",
    "legacy_low_level_memory_primitive_semantics_rederived",
    "imported_host_semantics_rederived",
    "legacy_memory_reset_unreachable_from_host",
    "cross_handler_allocator_freshness_proven",
    "boundary_state_continuity_complete",
    "graph_oracle_complete",
    "logical_parity_complete",
    "physical_parity_complete",
    "poi_parity_complete",
    "checkpoint_authority",
    "backfill_ready",
    "production_ready",
    "readiness_complete",
}

DATA_RE = re.compile(r'^  \(data \$\S+ \(i32\.const (\d+)\) "(.*)"\)\)?$')
FUNCTION_RE = re.compile(r"^  \(func \$([^\s]+)")
FUNCTION_IMPORT_RE = re.compile(r'^  \(import "[^"]+" "[^"]+" \(func \$[^\s\)]+')
EXPORT_RE = re.compile(r'^  \(export "([^"]+)" \(func \$([^\s\)]+)\)\)$')
CALL_RE = re.compile(r"\bcall \$([^\s\)]+)")


def decode_wat_string(value: str) -> bytes:
    output = bytearray()
    index = 0
    escapes = {"n": 10, "r": 13, "t": 9, "\\": 92, '"': 34, "'": 39}
    while index < len(value):
        if value[index] != "\\":
            output.extend(value[index].encode())
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


def parse_wat(wat: str) -> tuple[dict[str, WatFunction], dict[str, str]]:
    lines = wat.splitlines()
    functions: dict[str, WatFunction] = {}
    function_import_count = sum(FUNCTION_IMPORT_RE.match(line) is not None for line in lines)
    defined_count = 0
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
        require(name not in functions, f"duplicate WAT function {name}")
        functions[name] = WatFunction(
            name=name,
            start_line=start + 1,
            lines=tuple(body),
            function_index=function_import_count + defined_count,
        )
        defined_count += 1
    require(functions, "WAT contains no named functions")

    exports: dict[str, str] = {}
    for line in lines:
        match = EXPORT_RE.fullmatch(line)
        if match is None:
            continue
        export, target = match.groups()
        require(export not in exports, f"duplicate WAT export {export}")
        require(target in functions, f"WAT export {export} target missing: {target}")
        exports[export] = target
    return functions, exports


def resolve_wasm2wat(candidate: Path | None) -> Path:
    if candidate is None:
        found = shutil.which("wasm2wat")
        require(found is not None, "wasm2wat is required")
        candidate = Path(found)
    require(candidate.is_file(), f"wasm2wat not found: {candidate}")
    version = subprocess.run(
        [str(candidate), "--version"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    require(
        version.returncode == 0 and version.stdout.strip() == WABT_VERSION,
        "wasm2wat version drift",
    )
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
    require(result.returncode == 0, f"wasm2wat failed for {artifact.name}")
    require(not result.stderr, f"wasm2wat emitted stderr for {artifact.name}")
    try:
        result.stdout.decode()
    except UnicodeDecodeError as error:
        raise VerificationError(f"wasm2wat emitted invalid UTF-8 for {artifact.name}") from error
    return result.stdout


def normalized(line: str) -> str:
    return line.strip().replace("generated/schema/", "src/types/schema/")


def call_name(line: str) -> str | None:
    match = CALL_RE.search(line)
    if match is None:
        return None
    return match.group(1).replace("generated/schema/", "src/types/schema/")


def function_by_suffix(context: dict[str, Any], suffix: str) -> WatFunction:
    if suffix == "~start":
        require("~start" in context["functions"], f"{context['cid']} module start missing")
        return context["functions"]["~start"]
    matches = [
        function
        for name, function in context["functions"].items()
        if name.replace("generated/schema/", "src/types/schema/").endswith(suffix)
    ]
    require(
        len(matches) == 1,
        f"{context['cid']} helper {suffix!r} count drift: {len(matches)}",
    )
    return matches[0]


def runtime_ops() -> Any:
    return RUNTIME.WatRuntimeOps(
        require=require,
        normalized=normalized,
        call_name=call_name,
        function_by_suffix=function_by_suffix,
    )


def initialized_data_inventory(wat: str) -> dict[str, Any]:
    segments: list[dict[str, Any]] = []
    for line in wat.splitlines():
        match = DATA_RE.fullmatch(line)
        if match is None:
            continue
        offset = int(match.group(1))
        payload = decode_wat_string(match.group(2))
        segments.append(
            {
                "offset": offset,
                "bytes": len(payload),
                "end_exclusive": offset + len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    require(segments, "WAT contains no initialized data segments")
    return {
        "segment_count": len(segments),
        "maximum_end_exclusive": max(item["end_exclusive"] for item in segments),
        "segment_inventory_sha256": canonical_sha256(segments),
    }


def load_context(
    root: Path, spec: PoolProfileSpec | LegacyPoolProfileSpec, executable: Path
) -> dict[str, Any]:
    artifact_path = (
        root.resolve() / "uniswap-v3/graft-ancestry/v1/artifacts" / spec.cid
    )
    require(artifact_path.is_file(), f"retained Pool artifact missing: {spec.cid}")
    require(artifact_path.stat().st_size == spec.wasm_bytes, f"Pool WASM byte count drift: {spec.cid}")
    require(raw_sha256(artifact_path) == spec.wasm_sha256, f"Pool WASM digest drift: {spec.cid}")
    wat_payload = run_wasm2wat(executable, artifact_path)
    require(
        hashlib.sha256(wat_payload).hexdigest() == spec.wat_sha256,
        f"Pool WAT digest drift: {spec.cid}",
    )
    wat = wat_payload.decode()
    functions, exports = parse_wat(wat)
    return {
        "cid": spec.cid,
        "profile": {"profile_id": spec.profile_id},
        "spec": spec,
        "artifact_path": str(artifact_path.relative_to(root.resolve())),
        "functions": functions,
        "exports": exports,
        "module_text": wat,
        "wat_line_count": len(wat.splitlines()),
        "initialized_data": initialized_data_inventory(wat),
    }


def expected_global_writers(spec: PoolProfileSpec) -> dict[str, list[list[Any]]]:
    return {
        "$~started": [["~start", 7]],
        "$~lib/rt/stub/offset": [
            ["~lib/rt/stub/__alloc", 68],
            ["~lib/array/ensureCapacity", 161],
            ["~lib/array/ensureCapacity", 189],
            ["~start", 9],
        ],
        "$src/utils/constants/ZERO_BI": [["~start", 15]],
        "$src/utils/constants/ONE_BI": [["~start", 18]],
        "$src/utils/constants/ZERO_BD": [["~start", 21]],
        "$src/utils/constants/ONE_BD": [["~start", 24]],
        "$src/utils/pricing/MINIMUM_ETH_LOCKED": [["~start", 40]],
        "$src/utils/pricing/Q192": [["~start", spec.q192_writer_line]],
    }


def prove_start_and_allocator_floor(context: dict[str, Any]) -> dict[str, Any]:
    spec: PoolProfileSpec = context["spec"]
    start = function_by_suffix(context, "~start")
    lines = [normalized(line) for line in start.lines]
    digest = hashlib.sha256(start.payload).hexdigest()
    require(
        len(lines) == spec.start_line_count and digest == spec.start_body_sha256,
        f"{context['cid']} exact Pool start body drift",
    )
    require(
        lines[2:10]
        == [
            "global.get $~started",
            "if $I0",
            "return",
            "end",
            "i32.const 1",
            "global.set $~started",
            f"i32.const {spec.allocator_floor}",
            "global.set $~lib/rt/stub/offset",
        ],
        f"{context['cid']} Pool start idempotence/allocator-floor prelude drift",
    )
    module_state_spec = RUNTIME.ModuleStateSpec(
        initializer_export="_start",
        initializer_function="~start",
        mutable_globals=MUTABLE_GLOBALS,
        expected_global_set_inventory=expected_global_writers(spec),
    )
    module_state = RUNTIME.prove_module_state_invariants(
        context,
        start,
        module_state_spec,
        require=require,
        normalized=normalized,
        canonical_sha256=canonical_sha256,
    )
    direct_writes = [
        index
        for index, line in enumerate(start.lines)
        if RUNTIME.is_direct_memory_write(line, normalized)
    ]
    require(
        direct_writes == [],
        f"{context['cid']} Pool start acquired a direct linear-memory write: {direct_writes}",
    )
    initialized = context["initialized_data"]
    require(
        initialized["segment_count"] == spec.initialized_data_segment_count
        and initialized["maximum_end_exclusive"] == spec.initialized_data_end,
        f"{context['cid']} initialized data inventory drift",
    )
    require(
        spec.initialized_data_end < spec.allocator_floor,
        f"{context['cid']} allocator floor overlaps initialized data",
    )
    return {
        "function": start.name,
        "body_sha256": digest,
        "line_count": len(lines),
        "module_state": module_state,
        "initialized_data": initialized,
        "allocator_floor": spec.allocator_floor,
        "allocator_floor_gap_bytes": spec.allocator_floor - spec.initialized_data_end,
        "direct_memory_write_sites": direct_writes,
        "all_initialized_data_below_allocator_floor_machine_proven": True,
        "start_has_no_direct_linear_memory_write_machine_proven": True,
        "non_start_allocator_writers_are_capsule_bound_but_general_memory_safety_is_not_rederived": True,
    }


def prove_pool_runtime_context(context: dict[str, Any]) -> dict[str, Any]:
    declarations = RUNTIME.prove_exact_function_declaration_inventory(
        context, runtime_ops(), MODERN_POOL_FUNCTION_DECLARATIONS
    )
    require(
        declarations["function_count"] == 11
        and declarations["parameter_local_and_result_declarations_exactly_bound"]
        is True,
        f"{context['cid']} modern Pool function declaration inventory did not close",
    )
    profile_id = context["profile"]["profile_id"]
    require(
        profile_id in MODULE_FUNCTION_DECLARATIONS,
        f"{context['cid']} all-defined-function declaration profile missing",
    )
    module_declarations = RUNTIME.prove_exact_all_defined_function_declaration_inventory(
        context, runtime_ops(), MODULE_FUNCTION_DECLARATIONS[profile_id]
    )
    start = prove_start_and_allocator_floor(context)
    capsule = RUNTIME.prove_modern_collection_capsule(
        context, runtime_ops(), POOL_COLLECTION_SPEC
    )
    require(
        capsule["modern_collection_capsule_structurally_closed"] is True
        and capsule["exact_function_declarations"] == declarations,
        f"{context['cid']} modern Pool collection capsule did not close",
    )
    spec: PoolProfileSpec = context["spec"]
    return {
        "profile_id": spec.profile_id,
        "mapping_cid": spec.cid,
        "artifact_selection_tuple": [
            spec.profile_id,
            spec.cid,
            spec.wasm_sha256,
            spec.wat_sha256,
        ],
        "retained_wasm": {
            "path": context["artifact_path"],
            "bytes": spec.wasm_bytes,
            "sha256": spec.wasm_sha256,
            "wat_sha256": spec.wat_sha256,
        },
        "defined_function_count": len(context["functions"]),
        "all_defined_function_declarations": module_declarations,
        "start_and_allocator_floor": start,
        "public_collection_capsule": capsule,
        "proof_boundaries": {
            "handler_semantics_proven": False,
            "historic_event_population_proven": False,
            "imported_host_functions_assumed_not_to_write_arbitrary_linear_memory": True,
            "complex_allocator_capacity_and_memory_primitive_bodies_are_exact_aggregate_boundaries": True,
            "general_reachable_helper_memory_safety_rederived": False,
        },
        "modern_pool_runtime_facts_only": True,
    }


def legacy_expected_global_writers(
    group: LegacyGroupSpec,
) -> dict[str, list[list[Any]]]:
    shifted = group.collection.start_result_globals == ("$g10", "$g11")
    result_first = 10 if shifted else 9
    scratch_first = 12 if shifted else 11
    inventory: dict[str, list[list[Any]]] = {
        "$g0": [["start", 2]],
        "$g1": [
            ["~lib/allocator/arena/__memory_allocate", 59],
            ["~lib/memory/memory.reset", 2],
            ["start", 4],
        ],
        "$g2": [["start:src/utils/constants", 3]],
        "$g3": [["start:src/utils/constants", 6]],
        "$g4": [["start:src/utils/constants", 9]],
        "$g5": [["start:src/utils/constants", 12]],
        "$g6": [["start:src/utils/constants", 15]],
        "$g7": [["start:src/utils/constants", 20]],
    }
    inventory.update({name: [] for name in group.no_writer_static_globals})
    inventory[f"$g{result_first}"] = [["start", 8]]
    inventory[f"$g{result_first + 1}"] = [["start", 10]]
    inventory[f"$g{scratch_first}"] = [["~lib/internal/number/dtoa_core", 63]]
    inventory[f"$g{scratch_first + 1}"] = [["~lib/internal/number/dtoa_core", 82]]
    inventory[f"$g{scratch_first + 2}"] = [["~lib/internal/number/dtoa_core", 84]]
    inventory[f"$g{scratch_first + 3}"] = [
        ["~lib/internal/number/genDigits", 191],
        ["~lib/internal/number/genDigits", 321],
        ["~lib/internal/number/dtoa_core", 110],
    ]
    inventory[f"$g{scratch_first + 4}"] = [["~lib/internal/number/dtoa_core", 121]]
    inventory[f"$g{scratch_first + 5}"] = [["~lib/internal/number/dtoa_core", 128]]
    return inventory


def legacy_module_state_spec(group: LegacyGroupSpec) -> Any:
    return RUNTIME.LegacyModuleStateSpec(
        native_start_function="start",
        expected_native_start_directives=("(start $start)",),
        expected_export_inventory_sha256="ec559f76cf848547649dc9d0306b7830b37536366c6eef5542002056125b0bf4",
        expected_import_inventory_sha256=group.expected_import_inventory_sha256,
        expected_global_definition_inventory_sha256=group.expected_global_definition_inventory_sha256,
        expected_global_set_inventory=legacy_expected_global_writers(group),
        expected_global_set_inventory_sha256=group.expected_global_set_inventory_sha256,
        zero_initialized_globals=tuple(f"$g{index}" for index in range(8)),
        no_writer_static_globals=group.no_writer_static_globals,
        allocator_floor_global="$g0",
        allocator_offset_global="$g1",
        memory_reset_export="memory.reset",
        memory_reset_function="~lib/memory/memory.reset",
        handler_exports=(
            "handleInitialize",
            "handleMint",
            "handleBurn",
            "handleSwap",
            "handleFlash",
        ),
        expected_table_line="(table $table 1 funcref)",
        expected_element_line="(elem $e0 (i32.const 0) func $null)",
    )


def prove_legacy_pool_runtime_context(context: dict[str, Any]) -> dict[str, Any]:
    spec: LegacyPoolProfileSpec = context["spec"]
    group = LEGACY_GROUP_SPECS[spec.group_id]
    require(
        context["wat_line_count"] == spec.wat_line_count,
        f"{spec.cid} legacy WAT line-count drift",
    )
    initialized = context["initialized_data"]
    require(
        initialized
        == {
            "segment_count": spec.initialized_data_segment_count,
            "maximum_end_exclusive": spec.initialized_data_end,
            "segment_inventory_sha256": spec.initialized_data_inventory_sha256,
        },
        f"{spec.cid} legacy initialized data inventory drift",
    )
    require(
        spec.allocator_floor == (spec.initialized_data_end + 7) & -8
        and group.collection.start_floor == spec.allocator_floor,
        f"{spec.cid} legacy allocator floor is not exact align8(data end)",
    )
    declarations = RUNTIME.prove_exact_function_declaration_inventory(
        context, runtime_ops(), LEGACY_FUNCTION_DECLARATIONS
    )
    require(
        declarations["function_count"] == 26
        and declarations["parameter_local_and_result_declarations_exactly_bound"]
        is True,
        f"{spec.cid} legacy Pool function declaration inventory did not close",
    )
    require(
        spec.profile_id in MODULE_FUNCTION_DECLARATIONS,
        f"{spec.cid} all-defined-function declaration profile missing",
    )
    module_declarations = RUNTIME.prove_exact_all_defined_function_declaration_inventory(
        context, runtime_ops(), MODULE_FUNCTION_DECLARATIONS[spec.profile_id]
    )
    start = function_by_suffix(context, "start")
    module_state = RUNTIME.prove_legacy_module_state_invariants(
        context,
        start,
        legacy_module_state_spec(group),
        runtime_ops(),
        canonical_sha256=canonical_sha256,
    )
    capsule = RUNTIME.prove_legacy_collection_capsule(
        context, runtime_ops(), LEGACY_COLLECTION_SPEC
    )
    require(
        capsule["legacy_collection_capsule_structurally_closed"] is True
        and capsule["exact_function_declarations"] == declarations,
        f"{spec.cid} legacy Pool collection capsule did not close",
    )
    return {
        "profile_id": spec.profile_id,
        "digest_group_id": group.group_id,
        "mapping_cid": spec.cid,
        "artifact_selection_tuple": [
            spec.profile_id,
            spec.cid,
            spec.wasm_sha256,
            spec.wat_sha256,
        ],
        "retained_wasm": {
            "path": context["artifact_path"],
            "bytes": spec.wasm_bytes,
            "sha256": spec.wasm_sha256,
            "wat_sha256": spec.wat_sha256,
            "wat_line_count": spec.wat_line_count,
        },
        "defined_function_count": len(context["functions"]),
        "all_defined_function_declarations": module_declarations,
        "initialized_data_and_floor": {
            "initialized_data": initialized,
            "allocator_floor": spec.allocator_floor,
            "allocator_floor_gap_bytes": spec.allocator_floor
            - spec.initialized_data_end,
            "allocator_floor_is_exact_align8_of_data_end": True,
        },
        "native_start_module_state": module_state,
        "public_collection_capsule": capsule,
        "proof_boundaries": {
            "handler_semantics_proven": False,
            "historic_event_population_proven": False,
            "imported_host_functions_assumed_not_to_reenter_memory_reset": True,
            "imported_host_behavior_rederived": False,
            "low_level_memory_primitives_are_exact_body_authority_with_operand_callsite_checks": True,
            "low_level_memory_primitive_general_semantics_rederived": False,
            "cross_handler_allocator_freshness_proven": False,
        },
        "legacy_pool_runtime_facts_only": True,
    }


def expected_contract(root: Path, wasm2wat: Path | None = None) -> dict[str, Any]:
    runtime_sha256 = bind_candidate_runtime(root)
    executable = resolve_wasm2wat(wasm2wat)
    modern_contexts = [load_context(root, spec, executable) for spec in PROFILE_SPECS]
    legacy_contexts = [
        load_context(root, spec, executable) for spec in LEGACY_PROFILE_SPECS
    ]
    modern_proofs = [prove_pool_runtime_context(context) for context in modern_contexts]
    legacy_proofs = [
        prove_legacy_pool_runtime_context(context) for context in legacy_contexts
    ]
    observed_tuples = {
        (
            proof["profile_id"],
            proof["mapping_cid"],
            proof["retained_wasm"]["sha256"],
            proof["retained_wasm"]["wat_sha256"],
        )
        for proof in modern_proofs + legacy_proofs
    }
    require(
        observed_tuples == EXPECTED_ARTIFACT_TUPLES
        and len(modern_proofs) == 2
        and len(legacy_proofs) == 6,
        f"Pool artifact tuple selection drift: {sorted(observed_tuples)}",
    )
    require(
        {proof["digest_group_id"] for proof in legacy_proofs}
        == set(LEGACY_GROUP_SPECS),
        "legacy Pool digest-group coverage drift",
    )
    require(
        all(
            proof["all_defined_function_declarations"]["defined_function_count"]
            == MODULE_FUNCTION_DECLARATIONS[
                proof["profile_id"]
            ].expected_function_count
            and proof["all_defined_function_declarations"][
                "all_defined_function_headers_type_uses_ordered_parameters_results_and_leading_locals_exactly_bound"
            ]
            is True
            for proof in modern_proofs + legacy_proofs
        ),
        "Pool all-defined-function declaration inventories did not close",
    )
    truth = {key: True for key in sorted(TRUE_FLAGS)} | {
        key: False for key in sorted(FALSE_FLAGS)
    }
    contract: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "authority_contract": {
            "semantic_authority": "exact retained WASM bytes and checksum-pinned WABT 1.0.35 --generate-names WAT for all eight retained Pool mappings",
            "proof_model": "exact artifact tuple selection plus separate modern exported-initializer and legacy native-start module-state proofs and generation-specific public collection capsules",
            "host_boundary": "imported host behavior is not rederived; modern hosts are assumed not to write arbitrary linear memory, and legacy hosts are additionally assumed not to reenter exported memory.reset during a handler",
            "aggregate_body_boundary": "modern capacity/memory bodies and legacy memcpy/memmove/memset remain exact retained-body authority with structural operand callsite checks rather than general memory-semantics proofs",
            "fail_closed_rule": "any candidate runtime, tuple, WAT, import/export, start, all-defined-function declaration inventory, selected function header or local declaration, global definition/writer, data floor, reset reachability, allocator, setter/getter/index/equality, Value/Entity/entry/array layout, or exact low-level body drift leaves every scoped runtime claim false",
        },
        "provenance": {
            "base_commit": BASE_COMMIT,
            "base_commit_verification": "recorded review provenance; Git ancestry is outside this verifier",
            "shared_wat_runtime": {
                "path": RUNTIME_SOURCE_PATH.as_posix(),
                "raw_sha256": runtime_sha256,
                "candidate_bytes_equal_exact_executed_source": True,
            },
            "wabt_version": WABT_VERSION,
            "wasm2wat_command": ["wasm2wat", "--generate-names", "<retained-pool-wasm>"],
        },
        "scope": {
            "pool_mapping_profile_count": 8,
            "closed_modern_runtime_profile_count": 2,
            "newly_closed_legacy_runtime_profile_count": 6,
            "closed_runtime_profile_count": 8,
            "residual_runtime_profile_count": 0,
            "legacy_digest_group_count": 4,
            "closed_profiles": [item.profile_id for item in PROFILE_SPECS]
            + [item.profile_id for item in LEGACY_PROFILE_SPECS],
            "closed_mapping_cids": [item.cid for item in PROFILE_SPECS]
            + [item.cid for item in LEGACY_PROFILE_SPECS],
            "handler_semantics_added": [],
        },
        "modern_pool_runtime_proofs": modern_proofs,
        "legacy_pool_runtime_proofs": legacy_proofs,
        "truth_boundary": truth,
        "residuals": [
            "Burn, Mint, Initialize, Swap, and Flash handler semantics are outside this runtime-only certificate",
            "complete Pool entity histories and actual historic event population remain unproved",
            "legacy allocator freshness is only intra-handler under the explicit non-reentrant-host assumption because memory.reset is exported",
            "imported host behavior and low-level primitive general semantics remain proof boundaries",
            "boundary continuity, parity, checkpoint, backfill, production, and readiness gates remain false",
        ],
    }
    contract["projection_sha256"] = canonical_sha256(contract)
    return contract


def verify_contract(
    root: Path,
    contract: dict[str, Any] | None = None,
    wasm2wat: Path | None = None,
) -> dict[str, Any]:
    expected = expected_contract(root, wasm2wat)
    committed = contract if contract is not None else load_json(root.resolve() / CONTRACT_PATH)
    require(
        committed == expected,
        "committed Pool runtime contract is not the deterministic retained-WAT projection",
    )
    truth = committed["truth_boundary"]
    require(all(type(value) is bool for value in truth.values()), "truth gates must be strict booleans")
    require({key for key, value in truth.items() if value} == TRUE_FLAGS, "true gate set drift")
    require({key for key, value in truth.items() if not value} == FALSE_FLAGS, "false gate set drift")
    projection = dict(committed)
    digest = projection.pop("projection_sha256")
    require(digest == canonical_sha256(projection), "Pool runtime projection digest drift")
    return committed


def write_contract(root: Path, wasm2wat: Path | None = None) -> dict[str, Any]:
    contract = expected_contract(root, wasm2wat)
    destination = root.resolve() / CONTRACT_PATH
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(render(contract))
    return contract


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=REPOSITORY)
    parser.add_argument("--wasm2wat", type=Path)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    try:
        contract = (
            write_contract(args.root, args.wasm2wat)
            if args.write
            else verify_contract(args.root, wasm2wat=args.wasm2wat)
        )
    except VerificationError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(
        f"verified {contract['contract_version']}: all eight Pool runtime capsules closed; handler and readiness gates remain false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
