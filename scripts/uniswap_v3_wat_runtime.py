#!/usr/bin/env python3
"""Contract-I/O-free structural proofs for retained Uniswap V3 WAT runtimes.

This module deliberately knows nothing about repository paths, committed
contracts, eligibility, or release gates.  Callers supply artifact-specific
body hashes and their own ``require`` function, so a verifier can reuse these
algorithms without transferring any certification authority to this module.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence


Require = Callable[[bool, str], None]
Normalize = Callable[[str], str]
CallName = Callable[[str], str | None]
FunctionBySuffix = Callable[[dict[str, Any], str], Any]


@dataclass(frozen=True)
class WatRuntimeOps:
    """Verifier-owned operations used by the contract-independent algorithms."""

    require: Require
    normalized: Normalize
    call_name: CallName
    function_by_suffix: FunctionBySuffix


@dataclass(frozen=True)
class ModuleStateSpec:
    """Exact initializer and mutable-global writer contract for one module family."""

    initializer_export: str
    initializer_function: str
    mutable_globals: tuple[str, ...]
    expected_global_set_inventory: Mapping[str, Sequence[Sequence[Any]]]


@dataclass(frozen=True)
class ModernCollectionSpec:
    """Artifact authority needed by the modern AssemblyScript collection proof."""

    typed_map_set_call: str
    typed_map_get_call: str
    event_param_get_call: str
    stub_new_call: str
    stub_alloc_body_sha256: str
    ensure_capacity_body_sha256: Mapping[str, str]
    memory_fill_body_sha256: str
    memory_copy_body_sha256: str
    memcpy_body_sha256: str
    string_eq_body_sha256: str


def native_start_directives(module_text: str) -> list[str]:
    """Return every native WebAssembly ``start`` directive in a text module."""

    return [
        line.strip()
        for line in module_text.splitlines()
        if line.strip().startswith("(start ")
    ]


def mutable_global_definitions(
    module_text: str, mutable_globals: Sequence[str]
) -> dict[str, list[str]]:
    """Inventory complete top-level definitions for the named globals."""

    module_lines = [line.strip() for line in module_text.splitlines()]
    return {
        name: [line for line in module_lines if line.startswith(f"(global {name} ")]
        for name in mutable_globals
    }


def mutable_global_set_inventory(
    functions: Mapping[str, Any],
    mutable_globals: Sequence[str],
    normalized: Normalize,
) -> dict[str, list[list[Any]]]:
    """Inventory every writer of each named global across the complete module."""

    observed: dict[str, list[list[Any]]] = {name: [] for name in mutable_globals}
    for function_name, function in functions.items():
        for index, raw_line in enumerate(function.lines):
            line = normalized(raw_line)
            for global_name in mutable_globals:
                if line == f"global.set {global_name}":
                    observed[global_name].append([function_name, index])
    return observed


def prove_module_state_invariants(
    context: dict[str, Any],
    start_function: Any,
    spec: ModuleStateSpec,
    *,
    require: Require,
    normalized: Normalize,
    canonical_sha256: Callable[[Any], str],
) -> dict[str, Any]:
    """Fail closed on initializer dispatch, initial state, and global writers."""

    cid = context["cid"]
    module_text = context.get("module_text")
    exports = context.get("exports")
    require(isinstance(module_text, str), f"{cid} complete module WAT is required")
    require(isinstance(exports, dict), f"{cid} module export inventory is required")
    require(
        exports.get(spec.initializer_export) == spec.initializer_function
        and start_function.name == spec.initializer_function,
        f"{cid} {spec.initializer_export} export binding drift",
    )
    native_starts = native_start_directives(module_text)
    require(
        native_starts == [],
        f"{cid} unexpected native WebAssembly start section: {native_starts}",
    )
    definitions = mutable_global_definitions(module_text, spec.mutable_globals)
    for name, observed_definitions in definitions.items():
        require(
            observed_definitions == [f"(global {name} (mut i32) (i32.const 0))"],
            f"{cid} {name} zero initializer drift: {observed_definitions}",
        )
    observed = mutable_global_set_inventory(
        context["functions"], spec.mutable_globals, normalized
    )
    expected = {
        name: [list(site) for site in sites]
        for name, sites in spec.expected_global_set_inventory.items()
    }
    require(
        observed == expected,
        f"{cid} critical mutable-global writer inventory drift: {observed}",
    )
    return {
        "initializer_dispatch": {
            "export": spec.initializer_export,
            "function": spec.initializer_function,
            "native_start_section_present": False,
            "started_global_initial_value": 0,
        },
        "zero_initialized_mutable_globals": list(spec.mutable_globals),
        "complete_global_set_inventory": observed,
        "complete_global_set_inventory_sha256": canonical_sha256(observed),
        "critical_global_initializers_and_all_writers_machine_proven": True,
    }


def is_direct_memory_write(raw_line: str, normalized: Normalize) -> bool:
    """Recognize retained-WAT opcodes that can directly alter linear memory."""

    line = normalized(raw_line)
    if not line:
        return False
    opcode = line.split(maxsplit=1)[0].rstrip(")")
    return (
        ".store" in opcode
        or ".atomic.rmw" in opcode
        or opcode
        in {"memory.copy", "memory.fill", "memory.init", "memory.discard"}
    )


def _prove_modern_allocator_dependency(
    context: dict[str, Any], ops: WatRuntimeOps, spec: ModernCollectionSpec
) -> dict[str, Any]:
    """Bind allocator dependencies for the public aggregate capsule."""

    alloc = ops.function_by_suffix(context, "~lib/rt/stub/__alloc")
    alloc_lines = [ops.normalized(line) for line in alloc.lines]
    ops.require(
        len(alloc_lines) == 73
        and alloc_lines[2:5]
        == ["local.get $p0", "i32.const 1073741820", "i32.gt_u"]
        and alloc_lines[13:28]
        == [
            "global.get $~lib/rt/stub/offset", "local.tee $l1", "i32.const 4",
            "i32.add", "local.tee $l2", "local.get $p0", "i32.const 19",
            "i32.add", "i32.const -16", "i32.and", "i32.const 4", "i32.sub",
            "local.tee $p0", "i32.add", "local.tee $l3",
        ]
        and alloc_lines[67:73]
        == [
            "local.get $l3", "global.set $~lib/rt/stub/offset", "local.get $l1",
            "local.get $p0", "i32.store", "local.get $l2)",
        ],
        f"{context['cid']} stub/__alloc aligned extent/header/return identity drift",
    )
    alloc_digest = hashlib.sha256(alloc.payload).hexdigest()
    ops.require(
        alloc_digest == spec.stub_alloc_body_sha256,
        f"{context['cid']} fixed retained stub/__alloc body drift",
    )

    new = ops.function_by_suffix(context, "~lib/rt/stub/__new")
    new_lines = [ops.normalized(line) for line in new.lines]
    ops.require(
        len(new_lines) == 35
        and new_lines[2:35]
        == [
            "local.get $p0", "i32.const 1073741804", "i32.gt_u", "if $I0",
            new_lines[6], new_lines[7], "i32.const 86", "i32.const 30", new_lines[10],
            "unreachable", "end", "local.get $p0", "i32.const 16", "i32.add",
            new_lines[16], "local.tee $l3", "i32.const 4", "i32.sub",
            "local.tee $l2", "i32.const 0", "i32.store offset=4", "local.get $l2",
            "i32.const 0", "i32.store offset=8", "local.get $l2", "local.get $p1",
            "i32.store offset=12", "local.get $l2", "local.get $p0",
            "i32.store offset=16", "local.get $l3", "i32.const 16", "i32.add)",
        ]
        and (ops.call_name(new.lines[10]) or "").endswith("builtins/abort")
        and ops.call_name(new.lines[16]) == "~lib/rt/stub/__alloc",
        f"{context['cid']} stub/__new allocation/header/return identity drift",
    )
    return {
        "stub_alloc_body_sha256": alloc_digest,
        "stub_new_body_sha256": hashlib.sha256(new.payload).hexdigest(),
        "alloc_returns_old_offset_plus_header_word": True,
        "new_returns_same_allocated_payload_plus_object_header": True,
        "allocator_return_identity_structurally_proven": True,
    }


def _prove_modern_typed_map_mutation_dependencies(
    context: dict[str, Any], ops: WatRuntimeOps, spec: ModernCollectionSpec
) -> dict[str, Any]:
    """Bind mutation dependencies without independently claiming closure."""

    allocator = _prove_modern_allocator_dependency(context, ops, spec)
    profile = context["profile"]["profile_id"]
    ops.require(
        profile in spec.ensure_capacity_body_sha256,
        f"{context['cid']} no retained ensureCapacity authority for profile {profile}",
    )

    ensure = ops.function_by_suffix(context, "~lib/array/ensureCapacity")
    ensure_lines = [ops.normalized(line) for line in ensure.lines]
    ops.require(
        len(ensure_lines) == 226
        and ensure_lines[2:10]
        == [
            "local.get $p0", "i32.load offset=8", "local.tee $l3", "i32.const 2",
            "i32.shr_u", "local.get $p1", "i32.lt_u", "if $I0",
        ]
        and ensure_lines[195:226]
        == [
            "local.get $p1", "i32.const 4", "i32.sub", "local.get $l6",
            "i32.store offset=16", "local.get $l3", "local.get $p1", "i32.const 16",
            "i32.add", "local.tee $p1", "i32.add", "end", "local.get $l5",
            "local.get $l3", "i32.sub", ensure_lines[210], "local.get $p1",
            "local.get $l4", "i32.ne", "if $I12", "local.get $p0", "local.get $p1",
            "i32.store", "local.get $p0", "local.get $p1", "i32.store offset=4",
            "end", "local.get $p0", "local.get $l5", "i32.store offset=8", "end)",
        ]
        and (ops.call_name(ensure.lines[175]) or "").endswith("stub/__alloc")
        and (ops.call_name(ensure.lines[179]) or "").endswith("memory.copy")
        and (ops.call_name(ensure.lines[210]) or "").endswith("memory.fill"),
        f"{context['cid']} ensureCapacity committed capacity/backing behavior drift",
    )
    ensure_digest = hashlib.sha256(ensure.payload).hexdigest()
    ops.require(
        ensure_digest == spec.ensure_capacity_body_sha256[profile],
        f"{context['cid']} fixed retained ensureCapacity body drift",
    )

    push_suffix = (
        "TypedMapEntry<~lib/string/String_~lib/@graphprotocol/graph-ts/common/value/"
        "Value>>#push"
    )
    push = ops.function_by_suffix(context, push_suffix)
    push_lines = [ops.normalized(line) for line in push.lines]
    ops.require(
        len(push_lines) == 21
        and push_lines[2:21]
        == [
            "local.get $p0", "local.get $p0", "i32.load offset=12", "local.tee $l2",
            "i32.const 1", "i32.add", "local.tee $l3", push_lines[9],
            "local.get $p0", "i32.load offset=4", "local.get $l2", "i32.const 2",
            "i32.shl", "i32.add", "local.get $p1", "i32.store", "local.get $p0",
            "local.get $l3", "i32.store offset=12)",
        ]
        and (ops.call_name(push.lines[9]) or "").endswith("array/ensureCapacity"),
        f"{context['cid']} Array<TypedMapEntry>#push receiver/length/appended-operand drift",
    )

    typed_set = ops.function_by_suffix(context, spec.typed_map_set_call)
    set_lines = [ops.normalized(line) for line in typed_set.lines]
    ops.require(
        len(set_lines) == 59
        and set_lines[2:33]
        == [
            "block $B0 (result i32)", "loop $L1", "local.get $p0", "i32.load",
            "i32.load offset=12", "local.get $l3", "i32.gt_s", "if $I2",
            "local.get $p0", "i32.load", "local.get $l3", set_lines[13], "i32.load",
            "local.get $p1", set_lines[16], "if $I3", "local.get $p0", "i32.load",
            "local.get $l3", set_lines[21], "br $B0", "end", "local.get $l3",
            "i32.const 1", "i32.add", "local.set $l3", "br $L1", "end", "end",
            "i32.const 0", "end",
        ]
        and ops.call_name(typed_set.lines[13]) == spec.event_param_get_call
        and ops.call_name(typed_set.lines[16]) == "~lib/string/String.__eq"
        and ops.call_name(typed_set.lines[21]) == spec.event_param_get_call
        and set_lines[33:59]
        == [
            "local.tee $l3", "if $I4", "local.get $l3", "local.get $p2",
            "i32.store offset=4", "else", "i32.const 8", "i32.const 29",
            set_lines[41], "local.tee $l3", "i32.const 0", "i32.store",
            "local.get $l3", "i32.const 0", "i32.store offset=4", "local.get $l3",
            "local.get $p1", "i32.store", "local.get $l3", "local.get $p2",
            "i32.store offset=4", "local.get $p0", "i32.load", "local.get $l3",
            set_lines[57], "end)",
        ]
        and ops.call_name(typed_set.lines[41]) == spec.stub_new_call
        and (ops.call_name(typed_set.lines[57]) or "").endswith(push_suffix),
        f"{context['cid']} TypedMap#set key/value/entry/push operand drift",
    )

    entity = ops.function_by_suffix(context, "common/collections/Entity#constructor")
    entity_lines = [ops.normalized(line) for line in entity.lines]
    ops.require(
        len(entity_lines) == 58
        and entity_lines[2:18]
        == [
            "local.get $p0", "i32.eqz", "if $I0", "i32.const 4", "i32.const 26",
            entity_lines[7], "local.set $p0", "end", "local.get $p0", "i32.eqz",
            "if $I1", "i32.const 4", "i32.const 28", entity_lines[15],
            "local.set $p0", "end",
        ]
        and ops.call_name(entity.lines[7]) == spec.stub_new_call
        and ops.call_name(entity.lines[15]) == spec.stub_new_call
        and entity_lines[18:58]
        == [
            "local.get $p0", "i32.const 0", "i32.store", "i32.const 16",
            "i32.const 30", entity_lines[23], "local.tee $l1", "i32.const 0",
            "i32.store", "local.get $l1", "i32.const 0", "i32.store offset=4",
            "local.get $l1", "i32.const 0", "i32.store offset=8", "local.get $l1",
            "i32.const 0", "i32.store offset=12", "i32.const 32", "i32.const 0",
            entity_lines[38], "local.tee $l2", "i32.const 32", entity_lines[41],
            "local.get $l1", "local.get $l2", "i32.store", "local.get $l1",
            "local.get $l2", "i32.store offset=4", "local.get $l1", "i32.const 32",
            "i32.store offset=8", "local.get $l1", "i32.const 0",
            "i32.store offset=12", "local.get $p0", "local.get $l1", "i32.store",
            "local.get $p0)",
        ]
        and ops.call_name(entity.lines[23]) == spec.stub_new_call
        and ops.call_name(entity.lines[38]) == spec.stub_new_call
        and (ops.call_name(entity.lines[41]) or "").endswith("memory.fill"),
        f"{context['cid']} Entity constructor TypedMap array/backing/return drift",
    )

    primitive_authority = {
        "memory_fill": ("~lib/memory/memory.fill", spec.memory_fill_body_sha256),
        "memory_copy": ("~lib/memory/memory.copy", spec.memory_copy_body_sha256),
        "memcpy": ("~lib/util/memory/memcpy", spec.memcpy_body_sha256),
    }
    fixed_bodies: dict[str, dict[str, Any]] = {}
    for key, (suffix, expected_digest) in primitive_authority.items():
        primitive = ops.function_by_suffix(context, suffix)
        digest = hashlib.sha256(primitive.payload).hexdigest()
        ops.require(
            digest == expected_digest,
            f"{context['cid']} fixed retained {suffix} body drift",
        )
        fixed_bodies[key] = {
            "function": primitive.name,
            "body_sha256": digest,
            "proof_boundary": "exact retained low-level memory primitive body",
        }
    return {
        "allocator": allocator,
        "ensure_capacity": {
            "function": ensure.name,
            "body_sha256": ensure_digest,
            "committed_capacity_and_backing_structurally_proven": True,
            "proof_boundary": "exact retained complex array-growth primitive body plus structural commit checks",
        },
        "typed_map_set": {
            "function": typed_set.name,
            "same_key_and_value_update_or_new_entry_structurally_proven": True,
            "same_new_entry_appended_to_same_receiver": True,
        },
        "typed_map_entry_push": {
            "function": push.name,
            "same_appended_operand_at_old_length_and_exact_new_length_committed": True,
        },
        "entity_map_constructor": {
            "function": entity.name,
            "fresh_array_backing_and_same_entity_receiver_structurally_proven": True,
        },
        "fixed_low_level_memory_primitives": fixed_bodies,
        "_collection_mutation_dependencies_structurally_bound": True,
    }


def _prove_modern_indexed_access_dependencies(
    context: dict[str, Any], ops: WatRuntimeOps, spec: ModernCollectionSpec
) -> dict[str, Any]:
    """Bind indexed-access dependencies without independently claiming closure."""

    array_get = ops.function_by_suffix(
        context,
        "Array<~lib/@graphprotocol/graph-ts/chain/ethereum/ethereum.EventParam>#__get",
    )
    get_lines = [ops.normalized(line) for line in array_get.lines]
    ops.require(
        len(get_lines) == 31
        and get_lines[1:6]
        == ["local.get $p0", "i32.load offset=12", "local.get $p1", "i32.le_u", "if $I0"]
        and (ops.call_name(array_get.lines[10]) or "").endswith("builtins/abort")
        and get_lines[13:21]
        == [
            "local.get $p0", "i32.load offset=4", "local.get $p1", "i32.const 2",
            "i32.shl", "i32.add", "i32.load", "local.tee $p0",
        ]
        and get_lines[21:23] == ["i32.eqz", "if $I1"]
        and (ops.call_name(array_get.lines[27]) or "").endswith("builtins/abort")
        and get_lines[28:31] == ["unreachable", "end", "local.get $p0)"],
        f"{context['cid']} type-erased Array#__get bounds/index/value drift",
    )

    array_set = ops.function_by_suffix(
        context, "Array<~lib/@graphprotocol/graph-ts/common/value/Value>#__set"
    )
    set_lines = [ops.normalized(line) for line in array_set.lines]
    ops.require(
        len(set_lines) == 36
        and set_lines[2:7]
        == ["local.get $p0", "i32.load offset=12", "local.get $p1", "i32.le_u", "if $I0"]
        and set_lines[18:27]
        == [
            "local.get $p0", "local.get $p1", "i32.const 1", "i32.add",
            "local.tee $l3", set_lines[23], "local.get $p0", "local.get $l3",
            "i32.store offset=12",
        ]
        and (ops.call_name(array_set.lines[23]) or "").endswith("array/ensureCapacity")
        and set_lines[28:36]
        == [
            "local.get $p0", "i32.load offset=4", "local.get $p1", "i32.const 2",
            "i32.shl", "i32.add", "local.get $p2", "i32.store)",
        ],
        f"{context['cid']} type-erased Array#__set receiver/index/value drift",
    )

    typed_get = ops.function_by_suffix(context, spec.typed_map_get_call)
    map_lines = [ops.normalized(line) for line in typed_get.lines]
    ops.require(
        len(map_lines) == 32
        and map_lines[2:32]
        == [
            "loop $L0", "local.get $p0", "i32.load", "i32.load offset=12",
            "local.get $l2", "i32.gt_s", "if $I1", "local.get $p0", "i32.load",
            "local.get $l2", map_lines[12], "i32.load", "local.get $p1", map_lines[15],
            "if $I2", "local.get $p0", "i32.load", "local.get $l2", map_lines[20],
            "i32.load offset=4", "return", "end", "local.get $l2", "i32.const 1",
            "i32.add", "local.set $l2", "br $L0", "end", "end", "i32.const 0)",
        ]
        and ops.call_name(typed_get.lines[12]) == spec.event_param_get_call
        and ops.call_name(typed_get.lines[15]) == "~lib/string/String.__eq"
        and ops.call_name(typed_get.lines[20]) == spec.event_param_get_call,
        f"{context['cid']} TypedMap#get receiver/key/ordered-result drift",
    )
    return {
        "type_erased_array_get_set": {
            "same_receiver_index_and_value_structurally_proven": True
        },
        "typed_map_get": {
            "same_receiver_key_loop_and_value_result_structurally_proven": True
        },
    }


def prove_modern_collection_capsule(
    context: dict[str, Any], ops: WatRuntimeOps, spec: ModernCollectionSpec
) -> dict[str, Any]:
    """Close the public modern allocator, collection, and equality capsule.

    This is the sole public modern collection proof. The private dependency
    algorithms above intentionally cannot certify a consumer on their own.
    """

    collection = _prove_modern_typed_map_mutation_dependencies(context, ops, spec)
    indexed = _prove_modern_indexed_access_dependencies(context, ops, spec)
    string_eq = ops.function_by_suffix(context, "~lib/string/String.__eq")
    string_eq_digest = hashlib.sha256(string_eq.payload).hexdigest()
    ops.require(
        string_eq_digest == spec.string_eq_body_sha256,
        f"{context['cid']} retained String.__eq primitive body drift",
    )
    ops.require(
        collection.pop("_collection_mutation_dependencies_structurally_bound", None)
        is True,
        f"{context['cid']} internal collection dependency proof drift",
    )
    collection["collection_mutation_chain_structurally_closed"] = True
    return {
        "typed_map_collection_runtime": collection,
        "indexed_collection": indexed,
        "string_equality": {
            "function": string_eq.name,
            "retained_body_sha256": string_eq_digest,
            "proof_boundary": "exact retained pure library primitive body",
        },
        "modern_collection_capsule_structurally_closed": True,
    }
