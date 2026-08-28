#!/usr/bin/env python3
"""Build or verify the offline Uniswap V3 writer-compatibility evidence."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
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


CONTRACT_VERSION = "uniswap-v3-writer-compatibility/v1"
CONTRACT_PATH = Path(
    "uniswap-v3/graft-ancestry/v1/writer-compatibility.json"
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
        "Ethereum log triggers are ordered by global log index",
    ),
)

ENTITIES = set(ANCESTRY.ENTITIES)
REQUIRED_ABSENT = ("Collect", "Flash", "TickHourData")
STORE_SET_CALL = "~lib/@graphprotocol/graph-ts/index/store.set"
ETHEREUM_CALL = "~lib/@graphprotocol/graph-ts/chain/ethereum/ethereum.call"
EXCLUDED_POOL = "0x8fe8d9bb8eeba3ed688069c3d6b556c9ca258248"
HISTORICAL_GUARD_BLOCK = 14_317_993

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
I32_CONST_RE = re.compile(r"^\s*i32\.const (-?\d+)$")
CALL_RE = re.compile(r"\bcall \$([^\s\)]+)")


def parse_wat(wat: str) -> tuple[bytearray, dict[str, WatFunction]]:
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
        functions[name] = WatFunction(name, start + 1, tuple(body))
    require(functions, "WAT contains no named functions")
    return memory, functions


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


def resolve_handler(functions: dict[str, WatFunction], handler: str) -> WatFunction:
    matches = [
        function
        for name, function in functions.items()
        if name == handler or name.endswith(f"/{handler}")
    ]
    require(len(matches) == 1, f"handler {handler} resolved to {len(matches)} functions")
    return matches[0]


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


def reachable_functions(
    functions: dict[str, WatFunction], root: WatFunction
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
    return seen


def handler_record(function: WatFunction, memory: bytearray) -> dict[str, object]:
    call_sequence = function_calls(function)
    normalized_calls = normalized_call_sequence(function)
    return {
        "function": function.name,
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
    memory, functions = parse_wat(wat)
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

    handlers: dict[str, object] = {}
    for handler in mapping["registered_handler_exports"]:
        function = resolve_handler(functions, handler)
        handlers[handler] = handler_record(function, memory)

    targets = sorted({str(item["target"]) for item in callsites})
    return (
        {
            "cid": cid,
            "component": mapping["component"],
            "bytes": artifact["bytes"],
            "sha256": artifact["sha256"],
            "wat_sha256": wat_sha256,
            "registered_handlers": handlers,
            "store_set_callsite_count": len(callsites),
            "store_set_import_count": store_import_count,
            "store_set_callsites": callsites,
            "fixed_store_set_targets": targets,
            "dynamic_store_set_target_count": 0,
            "indirect_store_set_reference_count": indirect_store_references,
            "call_indirect_instruction_count": wat.count("call_indirect"),
        },
        functions,
        memory,
    )


def critical_reachability(
    analysis: dict[str, object],
    functions: dict[str, WatFunction],
    handler_name: str,
) -> dict[str, object]:
    handler = resolve_handler(functions, handler_name)
    reachable = reachable_functions(functions, handler)
    sites = [
        item
        for item in analysis["store_set_callsites"]
        if item["function"] in reachable
    ]
    return {
        "handler": handler_name,
        "handler_function": handler.name,
        "reachable_function_count": len(reachable),
        "reachable_store_set_site_ids": [item["site_id"] for item in sites],
        "reachable_store_set_targets": sorted({item["target"] for item in sites}),
        "dynamic_reachable_store_set_target_count": sum(
            item["target"] is None for item in sites
        ),
    }


def observed_guard_handlers(
    mapping_cid: str,
    functions: dict[str, WatFunction],
) -> list[str]:
    del mapping_cid
    result = []
    for handler in NPM_HANDLERS:
        function = resolve_handler(functions, handler)
        if any(
            line.strip() == f"i32.const {HISTORICAL_GUARD_BLOCK}"
            for line in function.lines
        ):
            result.append(handler)
    return sorted(result)


def verify_npm_profile_evidence(
    cid: str,
    profile_id: str,
    analysis: dict[str, object],
    functions: dict[str, WatFunction],
    memory: bytearray,
) -> dict[str, object]:
    expected = PROFILE_DEFINITIONS[profile_id]
    guards = observed_guard_handlers(cid, functions)
    require(guards == expected["block_guard_handlers"], f"{cid} block guard profile drift")
    pool_guards = []
    for handler in NPM_HANDLERS:
        handler_function = resolve_handler(functions, handler)
        reachable = reachable_functions(functions, handler_function)
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
            for call in function_calls(resolve_handler(functions, handler))
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
            for call in function_calls(resolve_handler(functions, handler))
        )
    ]
    require(
        snapshot_handlers == list(NPM_HANDLERS),
        f"{cid} snapshot handler inventory drift",
    )
    transfer_calls = function_calls(resolve_handler(functions, "handleTransfer"))
    require(
        (
            any(call.endswith("schema/Position#set:owner") for call in transfer_calls)
            or "owner"
            in function_static_strings(
                resolve_handler(functions, "handleTransfer"), memory
            )
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


def verify_flash_evidence(
    cid: str,
    analysis: dict[str, object],
    functions: dict[str, WatFunction],
    memory: bytearray,
) -> dict[str, object]:
    handler = resolve_handler(functions, "handleFlash")
    calls = function_calls(handler)
    static_strings = function_static_strings(handler, memory)
    old_wrapper_model = any(call.endswith("#feeGrowthGlobal0X128") for call in calls)
    if old_wrapper_model:
        expected_suffixes = (
            "#feeGrowthGlobal0X128",
            "#feeGrowthGlobal1X128",
            "schema/Pool#save",
        )
        positions = [
            next(index for index, call in enumerate(calls) if call.endswith(suffix))
            for suffix in expected_suffixes
        ]
        require(positions == sorted(positions), f"{cid} Flash call order drift")
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
        require(
            "feeGrowthGlobal0X128" in static_strings
            and "feeGrowthGlobal1X128" in static_strings,
            f"{cid} Flash method identity drift",
        )
        require(any(call.endswith("schema/Pool#save") for call in calls), f"{cid} Flash Pool save drift")
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
        "call_order": [
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
        "evidence_kind": "machine-checked non-try call, call ordering, handler reachability, and digest-bound WAT identity",
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

    pool_cids = sorted(
        cid for cid, mapping in mappings.items() if mapping["component"] == "Pool"
    )
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
            npm_component = component_record(segment, "NonfungiblePositionManager")
            pool_component = component_record(segment, "Pool")
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
                    "npm_mapping_cid": npm_cid,
                    "pool_mapping_cid": pool_cid,
                    "npm_profile_id": profile_id,
                    "npm_event_handlers_in_manifest_order": list(
                        npm_component["mapping"]["handlers"]
                    ),
                    "pool_flash_event_handler": flash_handlers[0],
                    "trigger_order_source_model": (
                        "Graph Node v0.44.0 orders Ethereum log triggers by ascending "
                        "global log index; contract calls still read block-level post-state"
                    ),
                    "manifest_features": features,
                    "historical_guard": {
                        "block": HISTORICAL_GUARD_BLOCK,
                        "present_in_mapping": guard_present,
                        "block_in_segment": block_in_segment,
                        "effective_in_segment": guard_present and block_in_segment,
                    },
                    "deterministic_handler_error_policy_under_source_model": (
                        "discard the failing handler's data-source and entity-cache changes, "
                        "continue other successful handlers, and write a deterministic proof-of-indexing error"
                        if nonfatal
                        else "nonFatalErrors is absent; a deterministic handler error fails the deployment at that block"
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
    return {
        "format_version": 1,
        "contract_version": CONTRACT_VERSION,
        "ancestry_contract": {
            "path": ANCESTRY.CONTRACT_PATH.as_posix(),
            "sha256": sha256_bytes(ancestry_contract_path.read_bytes()),
            "contract_version": ancestry["contract_version"],
            "artifact_count": len(ancestry["artifacts"]),
            "mapping_count": len(ancestry["mapping_writer_inventories"]),
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
        "pool_flash_evidence": flash_evidence,
        "segments": segments,
        "required_absence_certifications": absence,
        "truth_boundary": {
            "wabt_analysis_ci_recomputed": True,
            "global_store_set_callsite_closure_complete": True,
            "constant_store_set_target_inventory_complete": True,
            "npm_collect_and_pool_flash_reachability_complete": True,
            "required_absence_static_certified": True,
            "field_writer_audit_complete": False,
            "full_handler_semantics_complete": False,
            "runtime_population_complete": False,
            "boundary_state_continuity_complete": False,
            "logical_oracle_complete": False,
            "physical_parity_complete": False,
            "poi_parity_complete": False,
            "target_graph_node_runtime_identity_bound": False,
            "segment_execution_models_decided": False,
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
    "pool_flash_evidence",
    "segments",
    "required_absence_certifications",
    "truth_boundary",
}


def validate_internal_contract(contract: object) -> dict[str, object]:
    contract = ANCESTRY.exact_keys(contract, TOP_LEVEL_KEYS, "writer contract")
    require(contract["format_version"] == 1, "writer format version drift")
    require(contract["contract_version"] == CONTRACT_VERSION, "writer contract version drift")
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
    for mapping in mappings:
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
            reachability = evidence["collect_reachability"]
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
    require(
        len(contract["pool_flash_evidence"]) == 8,
        "writer Pool Flash evidence count drift",
    )
    for evidence in contract["pool_flash_evidence"]:
        reachability = evidence["reachable_writers"]
        require(
            reachability["reachable_store_set_targets"] == ["Pool"],
            "writer Flash reachability drift",
        )
        require(
            reachability["dynamic_reachable_store_set_target_count"] == 0,
            "writer Flash dynamic reachability drift",
        )
        require(evidence["flash_entity_write"] is False, "writer Flash write drift")
        require(
            evidence["complete_pool_field_writer_semantics"] is False,
            "writer Pool field-semantics overclaim",
        )
    effective_guards: list[tuple[str, str]] = []
    nonfatal_deployments: list[str] = []
    for segment in contract["segments"]:
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
        require(
            guard["effective_in_segment"]
            is (guard["present_in_mapping"] and guard["block_in_segment"]),
            "writer guard effectiveness drift",
        )
        if guard["effective_in_segment"]:
            effective_guards.append((segment["network"], segment["deployment"]))
        if "nonFatalErrors" in segment["manifest_features"]:
            nonfatal_deployments.append(segment["deployment"])
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

    truth = contract["truth_boundary"]
    for field in (
        "wabt_analysis_ci_recomputed",
        "global_store_set_callsite_closure_complete",
        "constant_store_set_target_inventory_complete",
        "npm_collect_and_pool_flash_reachability_complete",
        "required_absence_static_certified",
    ):
        require(truth.get(field) is True, f"writer proved evidence flag drift: {field}")
    for field in (
        "field_writer_audit_complete",
        "full_handler_semantics_complete",
        "runtime_population_complete",
        "boundary_state_continuity_complete",
        "logical_oracle_complete",
        "physical_parity_complete",
        "poi_parity_complete",
        "target_graph_node_runtime_identity_bound",
        "segment_execution_models_decided",
        "production_ready",
    ):
        require(truth.get(field) is False, f"unproved writer promotion claim: {field}")
    return contract


def verify(
    root: Path,
    contract_path: Path | None = None,
    wasm2wat: Path | None = None,
) -> dict[str, object]:
    root = root.resolve()
    path = contract_path or root / CONTRACT_PATH
    actual = validate_internal_contract(ANCESTRY.load_json(path))
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
