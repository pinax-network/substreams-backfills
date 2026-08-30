#!/usr/bin/env python3
"""Contract-I/O-free structural proofs for retained Uniswap V3 WAT runtimes.

This module deliberately knows nothing about repository paths, committed
contracts, eligibility, or release gates.  Callers supply artifact-specific
body hashes and their own ``require`` function, so a verifier can reuse these
algorithms without transferring any certification authority to this module.
"""

from __future__ import annotations

import hashlib
import re
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
class FunctionDeclarationSpec:
    """Exact function header and local declarations behind named-body proofs."""

    suffix: str
    declaration_lines: tuple[str, ...]


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
    function_declarations: Mapping[str, FunctionDeclarationSpec]


@dataclass(frozen=True)
class ModernPoolCollectionProfileSpec:
    """Profile-specific retained-body authority for a modern Pool module."""

    ensure_capacity_body_sha256: str
    event_param_get_body_sha256: str
    memory_fill_body_sha256: str
    memory_copy_body_sha256: str
    memcpy_body_sha256: str


@dataclass(frozen=True)
class ModernPoolCollectionSpec:
    """Distinct authority for the modern Pool inline-append collection layout."""

    typed_map_set_call: str
    typed_map_get_call: str
    event_param_get_call: str
    stub_new_call: str
    stub_alloc_body_sha256: str
    stub_new_body_sha256: str
    typed_map_set_body_sha256: str
    typed_map_get_body_sha256: str
    entity_constructor_body_sha256: str
    entity_constructor_type_ids: tuple[int, int, int]
    string_eq_body_sha256: str
    function_declarations: Mapping[str, FunctionDeclarationSpec]
    profiles: Mapping[str, ModernPoolCollectionProfileSpec]


@dataclass(frozen=True)
class LegacyModuleStateSpec:
    """Exact native-start, module-surface, global, and reset contract."""

    native_start_function: str
    expected_native_start_directives: tuple[str, ...]
    expected_export_inventory_sha256: str
    expected_import_inventory_sha256: str
    expected_global_definition_inventory_sha256: str
    expected_global_set_inventory: Mapping[str, Sequence[Sequence[Any]]]
    expected_global_set_inventory_sha256: str
    zero_initialized_globals: tuple[str, ...]
    no_writer_static_globals: Mapping[str, int]
    allocator_floor_global: str
    allocator_offset_global: str
    memory_reset_export: str
    memory_reset_function: str
    handler_exports: tuple[str, ...]
    expected_table_line: str
    expected_element_line: str


@dataclass(frozen=True)
class LegacyCollectionProfileSpec:
    """One of four real retained-body layouts shared by legacy Pool modules."""

    group_id: str
    start_body_sha256: str
    start_floor: int
    start_data_literal_pointer: int
    start_result_globals: tuple[str, str]
    array_constructor_body_sha256: str
    array_abort_source_pointer: int
    array_push_body_sha256: str
    string_allocate_body_sha256: str
    string_abort_source_pointer: int


@dataclass(frozen=True)
class LegacyCollectionSpec:
    """Artifact authority for the legacy arena/ArrayBuffer collection layout."""

    constants_start_body_sha256: str
    byte_array_from_i32_body_sha256: str
    factory_constructor_body_sha256: str
    native_math_pow_body_sha256: str
    arena_allocate_body_sha256: str
    compute_size_body_sha256: str
    allocate_unsafe_body_sha256: str
    reallocate_unsafe_body_sha256: str
    event_param_get_body_sha256: str
    value_constructor_body_sha256: str
    value_from_big_decimal_body_sha256: str
    typed_map_get_body_sha256: str
    typed_map_get_entry_body_sha256: str
    typed_map_set_body_sha256: str
    entry_constructor_body_sha256: str
    string_eq_body_sha256: str
    compare_unsafe_body_sha256: str
    memcpy_body_sha256: str
    memmove_body_sha256: str
    memset_body_sha256: str
    memory_allocate_body_sha256: str
    memory_reset_body_sha256: str
    function_declarations: Mapping[str, FunctionDeclarationSpec]
    profiles: Mapping[str, LegacyCollectionProfileSpec]


def _function_declaration_lines(function: Any, ops: WatRuntimeOps) -> list[str]:
    """Return the exact header plus every leading local declaration line."""

    lines = [ops.normalized(line) for line in function.lines]
    ops.require(
        bool(lines) and lines[0].startswith("(func $"),
        "missing WAT function header",
    )
    declarations = [lines[0]]
    for line in lines[1:]:
        if not line.startswith("(local "):
            break
        declarations.append(line)
    return declarations


def _prove_exact_function_declaration_inventory(
    context: dict[str, Any],
    ops: WatRuntimeOps,
    specs: Mapping[str, FunctionDeclarationSpec],
) -> dict[str, Any]:
    """Bind parameter/local names, order, types, results, and type uses exactly."""

    observed: dict[str, dict[str, Any]] = {}
    selected_functions: set[str] = set()
    for authority_id in sorted(specs):
        spec = specs[authority_id]
        function = ops.function_by_suffix(context, spec.suffix)
        declarations = _function_declaration_lines(function, ops)
        ops.require(
            declarations == list(spec.declaration_lines),
            f"{context['cid']} exact {authority_id} function declaration drift",
        )
        ops.require(
            function.name not in selected_functions,
            f"{context['cid']} duplicate function declaration authority: {function.name}",
        )
        selected_functions.add(function.name)
        observed[authority_id] = {
            "function": function.name,
            "declaration_lines": declarations,
            "declaration_sha256": hashlib.sha256(
                ("\n".join(declarations) + "\n").encode()
            ).hexdigest(),
        }
    ops.require(
        len(observed) == len(specs),
        f"{context['cid']} incomplete function declaration inventory",
    )
    return {
        "functions": observed,
        "function_count": len(observed),
        "parameter_local_and_result_declarations_exactly_bound": True,
    }


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


def _stripped_line_inventory(
    module_text: str, prefix: str
) -> tuple[list[str], str]:
    lines = [
        line.strip()
        for line in module_text.splitlines()
        if line.strip().startswith(prefix)
    ]
    digest = hashlib.sha256(("\n".join(lines) + "\n").encode()).hexdigest()
    return lines, digest


def prove_legacy_module_state_invariants(
    context: dict[str, Any],
    start_function: Any,
    spec: LegacyModuleStateSpec,
    ops: WatRuntimeOps,
    *,
    canonical_sha256: Callable[[Any], str],
) -> dict[str, Any]:
    """Fail closed on the legacy native-start surface and reset boundary."""

    cid = context["cid"]
    module_text = context.get("module_text")
    functions = context.get("functions")
    exports = context.get("exports")
    ops.require(isinstance(module_text, str), f"{cid} complete module WAT is required")
    ops.require(isinstance(functions, dict), f"{cid} function inventory is required")
    ops.require(isinstance(exports, dict), f"{cid} function export inventory is required")
    native_starts = native_start_directives(module_text)
    ops.require(
        native_starts == list(spec.expected_native_start_directives)
        and start_function.name == spec.native_start_function,
        f"{cid} legacy native start binding drift: {native_starts}",
    )
    ops.require("_start" not in exports, f"{cid} legacy module acquired _start export")

    export_lines, export_digest = _stripped_line_inventory(module_text, "(export ")
    import_lines, import_digest = _stripped_line_inventory(module_text, "(import ")
    global_lines, global_digest = _stripped_line_inventory(module_text, "(global ")
    ops.require(
        len(export_lines) == 11
        and export_digest == spec.expected_export_inventory_sha256,
        f"{cid} legacy complete export inventory drift",
    )
    ops.require(
        len(import_lines) == 17
        and import_digest == spec.expected_import_inventory_sha256,
        f"{cid} legacy exact ordered import inventory drift",
    )
    ops.require(
        global_digest == spec.expected_global_definition_inventory_sha256,
        f"{cid} legacy global definition inventory drift",
    )

    definition_by_name: dict[str, str] = {}
    for line in global_lines:
        match = re.match(r"^\(global (\$g\d+) ", line)
        ops.require(match is not None, f"{cid} unsupported legacy global definition")
        name = match.group(1)
        ops.require(name not in definition_by_name, f"{cid} duplicate legacy global {name}")
        definition_by_name[name] = line
    for name in spec.zero_initialized_globals:
        ops.require(
            definition_by_name.get(name)
            == f"(global {name} (mut i32) (i32.const 0))",
            f"{cid} legacy zero-initialized global drift: {name}",
        )
    for name, pointer in spec.no_writer_static_globals.items():
        ops.require(
            definition_by_name.get(name)
            == f"(global {name} (mut i32) (i32.const {pointer}))",
            f"{cid} legacy no-writer static global definition drift: {name}",
        )

    observed: dict[str, list[list[Any]]] = {
        name: [] for name in definition_by_name
    }
    for function_name, function in functions.items():
        for index, raw_line in enumerate(function.lines):
            match = re.fullmatch(
                r"global\.set (\$g\d+)\)?", ops.normalized(raw_line)
            )
            if match is not None:
                ops.require(
                    match.group(1) in observed,
                    f"{cid} writer targets an undefined legacy global",
                )
                observed[match.group(1)].append([function_name, index])
    expected = {
        name: [list(site) for site in sites]
        for name, sites in spec.expected_global_set_inventory.items()
    }
    ops.require(
        observed == expected
        and canonical_sha256(observed) == spec.expected_global_set_inventory_sha256,
        f"{cid} legacy complete global writer inventory drift: {observed}",
    )
    for name in spec.no_writer_static_globals:
        ops.require(observed[name] == [], f"{cid} legacy static global acquired writer: {name}")
    ops.require(
        observed[spec.allocator_floor_global] == [[spec.native_start_function, 2]],
        f"{cid} legacy allocator floor writer drift",
    )
    ops.require(
        observed[spec.allocator_offset_global]
        == [
            ["~lib/allocator/arena/__memory_allocate", 59],
            [spec.memory_reset_function, 2],
            [spec.native_start_function, 4],
        ],
        f"{cid} legacy allocator offset writer drift",
    )

    ops.require(
        exports.get(spec.memory_reset_export) == spec.memory_reset_function,
        f"{cid} legacy memory.reset export binding drift",
    )
    table_lines, _ = _stripped_line_inventory(module_text, "(table ")
    element_lines, _ = _stripped_line_inventory(module_text, "(elem ")
    ops.require(
        table_lines == [spec.expected_table_line]
        and element_lines == [spec.expected_element_line],
        f"{cid} legacy table/element closure drift",
    )
    indirect_sites = [
        [function_name, index]
        for function_name, function in functions.items()
        for index, line in enumerate(function.lines)
        if "call_indirect" in ops.normalized(line)
    ]
    ops.require(indirect_sites == [], f"{cid} legacy call_indirect acquired: {indirect_sites}")

    call_graph: dict[str, set[str]] = {name: set() for name in functions}
    reset_calls: list[list[Any]] = []
    for function_name, function in functions.items():
        for index, line in enumerate(function.lines):
            target = ops.call_name(line)
            if target == spec.memory_reset_function:
                reset_calls.append([function_name, index])
            if target in functions:
                call_graph[function_name].add(target)
    ops.require(reset_calls == [], f"{cid} legacy internal memory.reset callsite drift")

    handler_closures: dict[str, dict[str, Any]] = {}
    for export_name in spec.handler_exports:
        entry = exports.get(export_name)
        ops.require(entry in functions, f"{cid} legacy handler export drift: {export_name}")
        pending = [entry]
        reachable: set[str] = set()
        while pending:
            current = pending.pop()
            if current in reachable:
                continue
            reachable.add(current)
            pending.extend(call_graph[current] - reachable)
        ops.require(
            spec.memory_reset_function not in reachable,
            f"{cid} legacy handler reaches memory.reset: {export_name}",
        )
        handler_closures[export_name] = {
            "entry_function": entry,
            "reachable_defined_function_count": len(reachable),
            "reachable_function_inventory_sha256": canonical_sha256(sorted(reachable)),
            "memory_reset_reachable": False,
        }
    return {
        "native_start": {
            "function": spec.native_start_function,
            "directive": native_starts[0],
            "underscore_start_export_present": False,
        },
        "complete_module_surface": {
            "export_count": len(export_lines),
            "export_inventory_sha256": export_digest,
            "import_count": len(import_lines),
            "ordered_import_inventory_sha256": import_digest,
            "imported_host_semantics_rederived": False,
        },
        "complete_global_state": {
            "global_definition_count": len(global_lines),
            "global_definition_inventory_sha256": global_digest,
            "complete_global_set_inventory": observed,
            "complete_global_set_inventory_sha256": canonical_sha256(observed),
            "zero_initialized_globals": list(spec.zero_initialized_globals),
            "no_writer_static_globals": dict(spec.no_writer_static_globals),
        },
        "table_and_reset_reachability": {
            "table": table_lines[0],
            "element": element_lines[0],
            "call_indirect_sites": indirect_sites,
            "internal_memory_reset_callsites": reset_calls,
            "handler_closures": handler_closures,
            "memory_reset_is_host_exported": True,
            "allocator_freshness_scope": "within one handler invocation only, assuming imported hosts do not reenter memory.reset",
        },
        "legacy_native_start_module_state_structurally_closed": True,
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
    context: dict[str, Any],
    ops: WatRuntimeOps,
    spec: ModernCollectionSpec | ModernPoolCollectionSpec,
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
    new_digest = hashlib.sha256(new.payload).hexdigest()
    if isinstance(spec, ModernPoolCollectionSpec):
        ops.require(
            new_digest == spec.stub_new_body_sha256,
            f"{context['cid']} fixed retained stub/__new body drift",
        )
    return {
        "stub_alloc_body_sha256": alloc_digest,
        "stub_new_body_sha256": new_digest,
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


def _prove_modern_pool_mutation_dependencies(
    context: dict[str, Any], ops: WatRuntimeOps, spec: ModernPoolCollectionSpec
) -> dict[str, Any]:
    """Bind the Pool 77-line inline-append mutation dependency chain."""

    allocator = _prove_modern_allocator_dependency(context, ops, spec)
    profile = context["profile"]["profile_id"]
    ops.require(
        profile in spec.profiles,
        f"{context['cid']} no retained Pool runtime authority for profile {profile}",
    )
    profile_spec = spec.profiles[profile]

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
        f"{context['cid']} Pool ensureCapacity committed capacity/backing behavior drift",
    )
    ensure_digest = hashlib.sha256(ensure.payload).hexdigest()
    ops.require(
        ensure_digest == profile_spec.ensure_capacity_body_sha256,
        f"{context['cid']} fixed retained Pool ensureCapacity body drift",
    )

    typed_set = ops.function_by_suffix(context, spec.typed_map_set_call)
    set_lines = [ops.normalized(line) for line in typed_set.lines]
    ops.require(
        len(set_lines) == 77
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
        and set_lines[33:77]
        == [
            "local.tee $l3", "if $I4", "local.get $l3", "local.get $p2",
            "i32.store offset=4", "else", "i32.const 8", "i32.const 28",
            set_lines[41], "local.tee $l3", "i32.const 0", "i32.store",
            "local.get $l3", "i32.const 0", "i32.store offset=4", "local.get $l3",
            "local.get $p1", "i32.store", "local.get $l3", "local.get $p2",
            "i32.store offset=4", "local.get $p0", "i32.load", "local.tee $p0",
            "i32.load offset=12", "local.tee $p1", "i32.const 1", "i32.add",
            "local.set $p2", "local.get $p0", "local.get $p2", set_lines[64],
            "local.get $p0", "i32.load offset=4", "local.get $p1", "i32.const 2",
            "i32.shl", "i32.add", "local.get $l3", "i32.store", "local.get $p0",
            "local.get $p2", "i32.store offset=12", "end)",
        ]
        and ops.call_name(typed_set.lines[41]) == spec.stub_new_call
        and (ops.call_name(typed_set.lines[64]) or "").endswith("array/ensureCapacity"),
        f"{context['cid']} Pool TypedMap#set key/value/inline-append operand drift",
    )
    set_digest = hashlib.sha256(typed_set.payload).hexdigest()
    ops.require(
        set_digest == spec.typed_map_set_body_sha256,
        f"{context['cid']} fixed retained Pool TypedMap#set body drift",
    )

    entity = ops.function_by_suffix(context, "common/collections/Entity#constructor")
    entity_lines = [ops.normalized(line) for line in entity.lines]
    receiver_type, fallback_type, array_type = spec.entity_constructor_type_ids
    ops.require(
        len(entity_lines) == 58
        and entity_lines[2:18]
        == [
            "local.get $p0", "i32.eqz", "if $I0", "i32.const 4",
            f"i32.const {receiver_type}", entity_lines[7], "local.set $p0", "end",
            "local.get $p0", "i32.eqz", "if $I1", "i32.const 4",
            f"i32.const {fallback_type}", entity_lines[15], "local.set $p0", "end",
        ]
        and ops.call_name(entity.lines[7]) == spec.stub_new_call
        and ops.call_name(entity.lines[15]) == spec.stub_new_call
        and entity_lines[18:58]
        == [
            "local.get $p0", "i32.const 0", "i32.store", "i32.const 16",
            f"i32.const {array_type}", entity_lines[23], "local.tee $l1", "i32.const 0",
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
        f"{context['cid']} Pool Entity constructor type/backing/return drift",
    )
    entity_digest = hashlib.sha256(entity.payload).hexdigest()
    ops.require(
        entity_digest == spec.entity_constructor_body_sha256,
        f"{context['cid']} fixed retained Pool Entity constructor body drift",
    )

    primitive_authority = {
        "memory_fill": (
            "~lib/memory/memory.fill",
            profile_spec.memory_fill_body_sha256,
        ),
        "memory_copy": (
            "~lib/memory/memory.copy",
            profile_spec.memory_copy_body_sha256,
        ),
        "memcpy": ("~lib/util/memory/memcpy", profile_spec.memcpy_body_sha256),
    }
    fixed_bodies: dict[str, dict[str, Any]] = {}
    for key, (suffix, expected_digest) in primitive_authority.items():
        primitive = ops.function_by_suffix(context, suffix)
        digest = hashlib.sha256(primitive.payload).hexdigest()
        ops.require(
            digest == expected_digest,
            f"{context['cid']} fixed retained Pool {suffix} body drift",
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
            "body_sha256": set_digest,
            "same_key_and_value_update_or_new_entry_structurally_proven": True,
            "same_new_entry_appended_inline_to_same_receiver": True,
            "old_length_slot_and_exact_new_length_committed": True,
        },
        "entity_map_constructor": {
            "function": entity.name,
            "body_sha256": entity_digest,
            "type_ids": list(spec.entity_constructor_type_ids),
            "fresh_array_backing_and_same_entity_receiver_structurally_proven": True,
        },
        "fixed_low_level_memory_primitives": fixed_bodies,
        "_collection_mutation_dependencies_structurally_bound": True,
    }


def _prove_modern_indexed_access_dependencies(
    context: dict[str, Any],
    ops: WatRuntimeOps,
    spec: ModernCollectionSpec | ModernPoolCollectionSpec,
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


def _prove_modern_pool_indexed_access_dependencies(
    context: dict[str, Any], ops: WatRuntimeOps, spec: ModernPoolCollectionSpec
) -> dict[str, Any]:
    """Add exact Pool getter bodies to the shared indexed-access structure."""

    profile = context["profile"]["profile_id"]
    ops.require(
        profile in spec.profiles,
        f"{context['cid']} no retained Pool indexed authority for profile {profile}",
    )
    event_get = ops.function_by_suffix(context, spec.event_param_get_call)
    event_lines = [ops.normalized(line) for line in event_get.lines]
    ops.require(
        len(event_lines) == 31
        and event_lines[1:6]
        == ["local.get $p0", "i32.load offset=12", "local.get $p1", "i32.le_u", "if $I0"]
        and (ops.call_name(event_get.lines[10]) or "").endswith("builtins/abort")
        and event_lines[13:21]
        == [
            "local.get $p0", "i32.load offset=4", "local.get $p1", "i32.const 2",
            "i32.shl", "i32.add", "i32.load", "local.tee $p0",
        ]
        and event_lines[21:23] == ["i32.eqz", "if $I1"]
        and (ops.call_name(event_get.lines[27]) or "").endswith("builtins/abort")
        and event_lines[28:31] == ["unreachable", "end", "local.get $p0)"],
        f"{context['cid']} Pool EventParam Array#get bounds/index/value drift",
    )
    event_get_digest = hashlib.sha256(event_get.payload).hexdigest()
    ops.require(
        event_get_digest == spec.profiles[profile].event_param_get_body_sha256,
        f"{context['cid']} fixed retained Pool EventParam Array#get body drift",
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
        f"{context['cid']} Pool TypedMap#get receiver/key/ordered-result drift",
    )
    typed_get_digest = hashlib.sha256(typed_get.payload).hexdigest()
    ops.require(
        typed_get_digest == spec.typed_map_get_body_sha256,
        f"{context['cid']} fixed retained Pool TypedMap#get body drift",
    )
    return {
        "event_param_array_get": {
            "function": event_get.name,
            "body_sha256": event_get_digest,
            "same_receiver_index_and_non_null_result_structurally_proven": True,
        },
        "typed_map_get": {
            "function": typed_get.name,
            "body_sha256": typed_get_digest,
            "same_receiver_key_loop_and_value_result_structurally_proven": True,
        },
    }


def _legacy_function(
    context: dict[str, Any],
    ops: WatRuntimeOps,
    suffix: str,
    expected_sha256: str,
    expected_lines: int,
) -> tuple[Any, list[str], str]:
    function = ops.function_by_suffix(context, suffix)
    lines = [ops.normalized(line) for line in function.lines]
    digest = hashlib.sha256(function.payload).hexdigest()
    ops.require(
        len(lines) == expected_lines and digest == expected_sha256,
        f"{context['cid']} fixed retained legacy {suffix} body drift",
    )
    return function, lines, digest


def _prove_legacy_start_dependencies(
    context: dict[str, Any], ops: WatRuntimeOps, spec: LegacyCollectionSpec
) -> dict[str, Any]:
    """Bind the native initializer and exact constant-construction dependency."""

    profile_id = context["profile"]["profile_id"]
    ops.require(profile_id in spec.profiles, f"{context['cid']} legacy profile authority missing")
    profile = spec.profiles[profile_id]
    start, lines, digest = _legacy_function(
        context, ops, "start", profile.start_body_sha256, 11
    )
    first_result, second_result = profile.start_result_globals
    ops.require(
        lines[1:11]
        == [
            f"i32.const {profile.start_floor}",
            "global.set $g0",
            "global.get $g0",
            "global.set $g1",
            "call $start:src/utils/constants",
            f"i32.const {profile.start_data_literal_pointer}",
            "call $~lib/@graphprotocol/graph-ts/index/bigDecimal.fromString",
            f"global.set {first_result}",
            "call $~lib/math/NativeMath.pow",
            f"global.set {second_result})",
        ],
        f"{context['cid']} legacy native start floor/constants/result flow drift",
    )
    constants, constant_lines, constants_digest = _legacy_function(
        context,
        ops,
        "start:src/utils/constants",
        spec.constants_start_body_sha256,
        21,
    )
    ops.require(
        constant_lines[1:21]
        == [
            "i32.const 0",
            "call $~lib/@graphprotocol/graph-ts/index/ByteArray.fromI32",
            "global.set $g2",
            "i32.const 1",
            "call $~lib/@graphprotocol/graph-ts/index/ByteArray.fromI32",
            "global.set $g3",
            "i32.const 312",
            "call $~lib/@graphprotocol/graph-ts/index/bigDecimal.fromString",
            "global.set $g4",
            "i32.const 320",
            "call $~lib/@graphprotocol/graph-ts/index/bigDecimal.fromString",
            "global.set $g5",
            "i32.const 18",
            "call $~lib/@graphprotocol/graph-ts/index/ByteArray.fromI32",
            "global.set $g6",
            "i32.const 328",
            "i32.const 96",
            "call $~lib/@graphprotocol/graph-ts/index/typeConversion.stringToH160",
            "call $src/types/templates/Pool/Factory/Factory#constructor",
            "global.set $g7)",
        ],
        f"{context['cid']} legacy constants construction/global flow drift",
    )
    dependencies: dict[str, dict[str, Any]] = {}
    for key, suffix, body_hash, line_count in (
        (
            "byte_array_from_i32",
            "index/ByteArray.fromI32",
            spec.byte_array_from_i32_body_sha256,
            33,
        ),
        (
            "factory_constructor",
            "templates/Pool/Factory/Factory#constructor",
            spec.factory_constructor_body_sha256,
            6,
        ),
        (
            "native_math_pow",
            "~lib/math/NativeMath.pow",
            spec.native_math_pow_body_sha256,
            228,
        ),
    ):
        function, _body, body_digest = _legacy_function(
            context, ops, suffix, body_hash, line_count
        )
        dependencies[key] = {
            "function": function.name,
            "body_sha256": body_digest,
            "proof_boundary": "exact retained dependency body",
        }
    factory = dependencies["factory_constructor"]
    factory_function = ops.function_by_suffix(
        context, "templates/Pool/Factory/Factory#constructor"
    )
    factory_lines = [ops.normalized(line) for line in factory_function.lines]
    ops.require(
        factory_lines[1:6]
        == [
            "i32.const 8",
            "call $~lib/allocator/arena/__memory_allocate",
            "local.get $p0",
            "local.get $p1",
            "call $~lib/@graphprotocol/graph-ts/chain/ethereum/ethereum.SmartContract#constructor)",
        ],
        f"{context['cid']} legacy Factory constant constructor operand drift",
    )
    factory["allocation_and_constructor_operands_structurally_proven"] = True
    return {
        "native_start_function": start.name,
        "native_start_body_sha256": digest,
        "allocator_floor": profile.start_floor,
        "constants_function": constants.name,
        "constants_body_sha256": constants_digest,
        "dependencies": dependencies,
        "floor_constants_and_result_globals_structurally_proven": True,
    }


def _prove_legacy_allocator_dependencies(
    context: dict[str, Any], ops: WatRuntimeOps, spec: LegacyCollectionSpec
) -> dict[str, Any]:
    """Bind arena identity and the ArrayBuffer allocate/reallocate chain."""

    compute, compute_lines, compute_digest = _legacy_function(
        context, ops, "internal/arraybuffer/computeSize", spec.compute_size_body_sha256, 9
    )
    ops.require(
        compute_lines[1:9]
        == [
            "i32.const 1", "i32.const 32", "local.get $p0", "i32.const 7",
            "i32.add", "i32.clz", "i32.sub", "i32.shl)",
        ],
        f"{context['cid']} legacy ArrayBuffer computeSize alignment drift",
    )
    arena, arena_lines, arena_digest = _legacy_function(
        context,
        ops,
        "allocator/arena/__memory_allocate",
        spec.arena_allocate_body_sha256,
        61,
    )
    ops.require(
        arena_lines[2:23]
        == [
            "local.get $p0", "i32.const 1073741824", "i32.gt_u", "if $I0",
            "unreachable", "end", "local.get $p0", "i32.const 1",
            "local.tee $l1", "local.get $p0", "local.get $l1", "i32.gt_u",
            "select", "global.get $g1", "local.tee $p0", "i32.add",
            "i32.const 7", "i32.add", "i32.const -8", "i32.and",
            "local.tee $l1",
        ]
        and arena_lines[23:58]
        == [
            "memory.size", "local.tee $l2", "i32.const 16", "i32.shl",
            "i32.gt_u", "if $I1", "local.get $l2", "local.get $l1",
            "local.get $p0", "i32.sub", "i32.const 65535", "i32.add",
            "i32.const -65536", "i32.and", "i32.const 16", "i32.shr_u",
            "local.tee $l3", "local.tee $l4", "local.get $l2",
            "local.get $l4", "i32.gt_s", "select", "memory.grow",
            "i32.const 0", "i32.lt_s", "if $I2", "local.get $l3",
            "memory.grow", "i32.const 0", "i32.lt_s", "if $I3",
            "unreachable", "end", "end", "end",
        ]
        and arena_lines[58:61]
        == ["local.get $l1", "global.set $g1", "local.get $p0)"],
        f"{context['cid']} legacy arena bounds/alignment/grow/commit/return drift",
    )
    allocate, allocate_lines, allocate_digest = _legacy_function(
        context,
        ops,
        "internal/arraybuffer/allocateUnsafe",
        spec.allocate_unsafe_body_sha256,
        20,
    )
    ops.require(
        allocate_lines[2:20]
        == [
            "local.get $p0", "i32.const 1073741816", "i32.gt_u", "if $I0",
            "i32.const 0", "i32.const 248", "i32.const 26", "i32.const 2",
            "call $~lib/env/abort", "unreachable", "end", "local.get $p0",
            "call $~lib/internal/arraybuffer/computeSize",
            "call $~lib/allocator/arena/__memory_allocate", "local.tee $l1",
            "local.get $p0", "i32.store", "local.get $l1)",
        ],
        f"{context['cid']} legacy allocateUnsafe header/return identity drift",
    )
    reallocate, reallocate_lines, reallocate_digest = _legacy_function(
        context,
        ops,
        "internal/arraybuffer/reallocateUnsafe",
        spec.reallocate_unsafe_body_sha256,
        74,
    )
    ops.require(
        reallocate_lines[2:30]
        == [
            "local.get $p1", "local.get $p0", "i32.load", "local.tee $l2",
            "i32.gt_s", "if $I0", "local.get $p1", "i32.const 1073741816",
            "i32.gt_s", "if $I1", "i32.const 0", "i32.const 248",
            "i32.const 40", "i32.const 4", "call $~lib/env/abort", "unreachable",
            "end", "local.get $p1", "local.get $l2",
            "call $~lib/internal/arraybuffer/computeSize", "i32.const 8",
            "i32.sub", "i32.le_s", "if $I2", "local.get $p0",
            "local.get $p1", "i32.store", "else",
        ]
        and reallocate_lines[30:52]
        == [
            "local.get $p1", "call $~lib/internal/arraybuffer/allocateUnsafe",
            "local.tee $l3", "i32.const 8", "i32.add", "local.get $p0",
            "i32.const 8", "i32.add", "local.get $l2",
            "call $~lib/internal/memory/memmove", "local.get $l3",
            "local.set $p0", "end", "local.get $p0", "i32.const 8",
            "i32.add", "local.get $l2", "i32.add", "local.get $p1",
            "local.get $l2", "i32.sub", "call $~lib/internal/memory/memset",
        ]
        and reallocate_lines[52:74]
        == [
            "else", "local.get $p1", "local.get $l2", "i32.lt_s", "if $I3",
            "local.get $p1", "i32.const 0", "i32.lt_s", "if $I4",
            "i32.const 0", "i32.const 248", "i32.const 62", "i32.const 4",
            "call $~lib/env/abort", "unreachable", "end", "local.get $p0",
            "local.get $p1", "i32.store", "end", "end", "local.get $p0)",
        ],
        f"{context['cid']} legacy reallocate grow/copy/zero/shrink/return drift",
    )
    primitives: dict[str, dict[str, Any]] = {}
    for key, suffix, body_hash, line_count in (
        ("memcpy", "internal/memory/memcpy", spec.memcpy_body_sha256, 859),
        ("memmove", "internal/memory/memmove", spec.memmove_body_sha256, 195),
        ("memset", "internal/memory/memset", spec.memset_body_sha256, 225),
    ):
        function, body_lines, body_digest = _legacy_function(
            context, ops, suffix, body_hash, line_count
        )
        if key == "memmove":
            ops.require(
                body_lines[23:29]
                == [
                    "if $I2",
                    "local.get $p0",
                    "local.get $p1",
                    "local.get $p2",
                    "call $~lib/internal/memory/memcpy",
                    "return",
                ],
                f"{context['cid']} legacy memmove-to-memcpy operand identity drift",
            )
        primitives[key] = {
            "function": function.name,
            "body_sha256": body_digest,
            "proof_boundary": "exact retained low-level body; general semantics not rederived",
            "relevant_collection_operand_callsites_structurally_proven": True,
        }
    memory_allocate, memory_allocate_lines, memory_allocate_digest = _legacy_function(
        context,
        ops,
        "~lib/memory/memory.allocate",
        spec.memory_allocate_body_sha256,
        3,
    )
    ops.require(
        memory_allocate_lines[1:3]
        == [
            "local.get $p0",
            "call $~lib/allocator/arena/__memory_allocate)",
        ],
        f"{context['cid']} legacy exported memory.allocate identity drift",
    )
    memory_reset, memory_reset_lines, memory_reset_digest = _legacy_function(
        context, ops, "~lib/memory/memory.reset", spec.memory_reset_body_sha256, 3
    )
    ops.require(
        memory_reset_lines[1:3] == ["global.get $g0", "global.set $g1)"],
        f"{context['cid']} legacy memory.reset floor restoration drift",
    )
    return {
        "compute_size": {"function": compute.name, "body_sha256": compute_digest},
        "arena_allocator": {
            "function": arena.name,
            "body_sha256": arena_digest,
            "old_offset_return_and_aligned_end_commit_structurally_proven": True,
        },
        "arraybuffer_allocate": {
            "function": allocate.name,
            "body_sha256": allocate_digest,
            "requested_length_header_and_same_allocation_return_structurally_proven": True,
        },
        "arraybuffer_reallocate": {
            "function": reallocate.name,
            "body_sha256": reallocate_digest,
            "in_place_or_new_copy_zero_tail_and_length_commit_structurally_proven": True,
            "memmove_and_memset_operands_structurally_proven": True,
        },
        "fixed_low_level_primitives": primitives,
        "exported_memory_allocate": {
            "function": memory_allocate.name,
            "body_sha256": memory_allocate_digest,
        },
        "exported_memory_reset": {
            "function": memory_reset.name,
            "body_sha256": memory_reset_digest,
            "resets_offset_to_native_start_floor_global": True,
            "host_exported_reentrancy_boundary": True,
        },
    }


def _prove_legacy_indexed_and_value_dependencies(
    context: dict[str, Any], ops: WatRuntimeOps, spec: LegacyCollectionSpec
) -> dict[str, Any]:
    """Bind EventParam index semantics and legacy Value object identity."""

    event_get, event_lines, event_digest = _legacy_function(
        context,
        ops,
        "EventParam>#__get",
        spec.event_param_get_body_sha256,
        19,
    )
    ops.require(
        event_lines[1:19]
        == [
            "local.get $p1", "local.get $p0", "i32.load", "local.tee $p0",
            "i32.load", "i32.const 2", "i32.shr_u", "i32.lt_u",
            "if $I0 (result i32)", "local.get $p1", "i32.const 2", "i32.shl",
            "local.get $p0", "i32.add", "i32.load offset=8", "else",
            "unreachable", "end)",
        ],
        f"{context['cid']} legacy EventParam bounds/index/backing/value drift",
    )
    value, value_lines, value_digest = _legacy_function(
        context,
        ops,
        "index/Value#constructor",
        spec.value_constructor_body_sha256,
        11,
    )
    ops.require(
        value_lines[2:11]
        == [
            "i32.const 16", "call $~lib/allocator/arena/__memory_allocate",
            "local.tee $l0", "i32.const 0", "i32.store", "local.get $l0",
            "i64.const 0", "i64.store offset=8", "local.get $l0)",
        ],
        f"{context['cid']} legacy Value constructor allocation/tag/payload/return drift",
    )
    from_decimal, decimal_lines, decimal_digest = _legacy_function(
        context,
        ops,
        "index/Value.fromBigDecimal",
        spec.value_from_big_decimal_body_sha256,
        11,
    )
    ops.require(
        decimal_lines[2:11]
        == [
            "call $~lib/@graphprotocol/graph-ts/index/Value#constructor",
            "local.tee $l1", "i32.const 2", "i32.store", "local.get $l1",
            "local.get $p0", "i64.extend_i32_u", "i64.store offset=8",
            "local.get $l1)",
        ],
        f"{context['cid']} legacy Value.fromBigDecimal tag/payload/object identity drift",
    )
    return {
        "event_param_array_get": {
            "function": event_get.name,
            "body_sha256": event_digest,
            "logical_length_bounds_and_backing_plus_index_value_structurally_proven": True,
        },
        "value_constructor": {
            "function": value.name,
            "body_sha256": value_digest,
            "fresh_16_byte_zero_value_object_structurally_proven": True,
        },
        "value_from_big_decimal": {
            "function": from_decimal.name,
            "body_sha256": decimal_digest,
            "kind_2_unsigned_pointer_payload_same_object_structurally_proven": True,
        },
    }


def _prove_legacy_string_dependencies(
    context: dict[str, Any], ops: WatRuntimeOps, spec: LegacyCollectionSpec
) -> dict[str, Any]:
    """Bind String equality, its comparator, and group-specific allocation."""

    profile = spec.profiles[context["profile"]["profile_id"]]
    compare, compare_lines, compare_digest = _legacy_function(
        context,
        ops,
        "internal/string/compareUnsafe",
        spec.compare_unsafe_body_sha256,
        32,
    )
    ops.require(
        compare_lines[2:32]
        == [
            "loop $L0", "local.get $p2", "if $I1 (result i32)",
            "local.get $p0", "i32.load16_u offset=4", "local.get $p1",
            "i32.load16_u offset=4", "i32.sub", "local.tee $l3", "i32.eqz",
            "else", "local.get $p2", "end", "if $I2", "local.get $p2",
            "i32.const 1", "i32.sub", "local.set $p2", "local.get $p0",
            "i32.const 2", "i32.add", "local.set $p0", "local.get $p1",
            "i32.const 2", "i32.add", "local.set $p1", "br $L0", "end",
            "end", "local.get $l3)",
        ],
        f"{context['cid']} legacy compareUnsafe ordered code-unit comparison drift",
    )
    string_eq, eq_lines, eq_digest = _legacy_function(
        context, ops, "~lib/string/String.__eq", spec.string_eq_body_sha256, 37
    )
    ops.require(
        eq_lines[2:37]
        == [
            "local.get $p0", "local.get $p1", "i32.eq", "if $I0",
            "i32.const 1", "return", "end", "local.get $p0", "i32.eqz",
            "local.tee $l2", "if $I1 (result i32)", "local.get $l2", "else",
            "local.get $p1", "i32.eqz", "end", "if $I2", "i32.const 0",
            "return", "end", "local.get $p0", "i32.load", "local.tee $l2",
            "local.get $p1", "i32.load", "i32.ne", "if $I3", "i32.const 0",
            "return", "end", "local.get $p0", "local.get $p1",
            "local.get $l2", "call $~lib/internal/string/compareUnsafe", "i32.eqz)",
        ],
        f"{context['cid']} legacy String.__eq identity/null/length/comparison drift",
    )
    allocate, allocate_lines, allocate_digest = _legacy_function(
        context,
        ops,
        "internal/string/allocateUnsafe",
        profile.string_allocate_body_sha256,
        32,
    )
    ops.require(
        allocate_lines[2:32]
        == [
            "local.get $p0", "i32.const 0", "i32.gt_s", "local.tee $l1",
            "if $I0 (result i32)", "local.get $p0", "i32.const 536870910",
            "i32.le_s", "else", "local.get $l1", "end", "i32.eqz", "if $I1",
            "i32.const 0", f"i32.const {profile.string_abort_source_pointer}",
            "i32.const 14", "i32.const 2", "call $~lib/env/abort", "unreachable",
            "end", "local.get $p0", "i32.const 1", "i32.shl", "i32.const 4",
            "i32.add", "call $~lib/allocator/arena/__memory_allocate",
            "local.tee $l1", "local.get $p0", "i32.store", "local.get $l1)",
        ],
        f"{context['cid']} legacy String allocate bounds/size/header/return drift",
    )
    return {
        "compare_unsafe": {
            "function": compare.name,
            "body_sha256": compare_digest,
            "ordered_utf16_code_unit_comparison_structurally_proven": True,
        },
        "string_equality": {
            "function": string_eq.name,
            "body_sha256": eq_digest,
            "identity_null_length_and_compare_result_structurally_proven": True,
        },
        "string_allocate": {
            "function": allocate.name,
            "body_sha256": allocate_digest,
            "length_header_and_same_object_return_structurally_proven": True,
        },
    }


def _prove_legacy_array_dependencies(
    context: dict[str, Any], ops: WatRuntimeOps, spec: LegacyCollectionSpec
) -> dict[str, Any]:
    """Bind group-specific entry-array construction, growth, and append identity."""

    profile = spec.profiles[context["profile"]["profile_id"]]
    constructor, ctor_lines, ctor_digest = _legacy_function(
        context,
        ops,
        "TypedMapEntry<~lib/string/String_~lib/@graphprotocol/graph-ts/index/Value>>#constructor",
        profile.array_constructor_body_sha256,
        39,
    )
    ops.require(
        ctor_lines[2:39]
        == [
            "local.get $p0", "i32.const 268435454", "i32.gt_u", "if $I0",
            "i32.const 0", f"i32.const {profile.array_abort_source_pointer}",
            "i32.const 45", "i32.const 39", "call $~lib/env/abort", "unreachable",
            "end", "local.get $p0", "i32.const 2", "i32.shl", "local.tee $l3",
            "call $~lib/internal/arraybuffer/allocateUnsafe", "local.set $l2",
            "i32.const 8", "call $~lib/allocator/arena/__memory_allocate",
            "local.tee $l1", "i32.const 0", "i32.store", "local.get $l1",
            "i32.const 0", "i32.store offset=4", "local.get $l1", "local.get $l2",
            "i32.store", "local.get $l1", "local.get $p0", "i32.store offset=4",
            "local.get $l2", "i32.const 8", "i32.add", "local.get $l3",
            "call $~lib/internal/memory/memset", "local.get $l1)",
        ],
        f"{context['cid']} legacy entry-array constructor backing/length/capacity/zero/return drift",
    )
    push, push_lines, push_digest = _legacy_function(
        context,
        ops,
        "TypedMapEntry<~lib/string/String_~lib/@graphprotocol/graph-ts/index/Value>>#push",
        profile.array_push_body_sha256,
        47,
    )
    ops.require(
        push_lines[2:47]
        == [
            "local.get $p0", "i32.load offset=4", "local.tee $l2", "i32.const 1",
            "i32.add", "local.set $l4", "local.get $l2", "local.get $p0",
            "i32.load", "local.tee $l3", "i32.load", "i32.const 2", "i32.shr_u",
            "i32.ge_u", "if $I0", "local.get $l2", "i32.const 268435454",
            "i32.ge_u", "if $I1", "i32.const 0",
            f"i32.const {profile.array_abort_source_pointer}", "i32.const 182",
            "i32.const 42", "call $~lib/env/abort", "unreachable", "end",
            "local.get $p0", "local.get $l3", "local.get $l4", "i32.const 2",
            "i32.shl", "call $~lib/internal/arraybuffer/reallocateUnsafe",
            "local.tee $l3", "i32.store", "end", "local.get $p0",
            "local.get $l4", "i32.store offset=4", "local.get $l2", "i32.const 2",
            "i32.shl", "local.get $l3", "i32.add", "local.get $p1",
            "i32.store offset=8)",
        ],
        f"{context['cid']} legacy entry-array push capacity/old-index/new-length/operand drift",
    )
    return {
        "entry_array_constructor": {
            "function": constructor.name,
            "body_sha256": ctor_digest,
            "fresh_backing_length_capacity_and_zeroing_structurally_proven": True,
            "memset_callsite_operands_structurally_proven": True,
        },
        "entry_array_push": {
            "function": push.name,
            "body_sha256": push_digest,
            "capacity_growth_old_index_new_length_and_same_entry_structurally_proven": True,
        },
    }


def _prove_legacy_typed_map_dependencies(
    context: dict[str, Any], ops: WatRuntimeOps, spec: LegacyCollectionSpec
) -> dict[str, Any]:
    """Bind legacy get/getEntry/set and the misleading entry constructor symbol."""

    get_entry, entry_lines, entry_digest = _legacy_function(
        context,
        ops,
        "index/Value>#getEntry",
        spec.typed_map_get_entry_body_sha256,
        34,
    )
    get_value, get_lines, get_digest = _legacy_function(
        context, ops, "index/Value>#get", spec.typed_map_get_body_sha256, 35
    )
    common_prefix = [
        "loop $L0", "block $B1", "local.get $l2", "local.get $p0", "i32.load",
        "i32.load offset=4", "i32.ge_s", "br_if $B1", "local.get $p0",
        "i32.load", "local.get $l2",
        "call $~lib/array/Array<~lib/@graphprotocol/graph-ts/chain/ethereum/ethereum.EventParam>#__get",
        "i32.load", "local.get $p1", "call $~lib/string/String.__eq", "if $I2",
        "local.get $p0", "i32.load", "local.get $l2",
        "call $~lib/array/Array<~lib/@graphprotocol/graph-ts/chain/ethereum/ethereum.EventParam>#__get",
    ]
    ops.require(
        entry_lines[2:22] == common_prefix
        and entry_lines[22:34]
        == [
            "return", "else", "local.get $l2", "i32.const 1", "i32.add",
            "local.set $l2", "br $L0", "end", "unreachable", "end", "end",
            "i32.const 0)",
        ],
        f"{context['cid']} legacy TypedMap#getEntry receiver/key/entry/null drift",
    )
    ops.require(
        get_lines[2:22] == common_prefix
        and get_lines[22:35]
        == [
            "i32.load offset=4", "return", "else", "local.get $l2",
            "i32.const 1", "i32.add", "local.set $l2", "br $L0", "end",
            "unreachable", "end", "end", "i32.const 0)",
        ],
        f"{context['cid']} legacy TypedMap#get receiver/key/value-offset/null drift",
    )
    entry_constructor, constructor_lines, constructor_digest = _legacy_function(
        context,
        ops,
        "ethereum.SmartContract#constructor",
        spec.entry_constructor_body_sha256,
        21,
    )
    ops.require(
        constructor_lines[1:21]
        == [
            "local.get $p0", "i32.eqz", "if $I0", "i32.const 8",
            "call $~lib/allocator/arena/__memory_allocate", "local.set $p0", "end",
            "local.get $p0", "i32.const 0", "i32.store", "local.get $p0",
            "i32.const 0", "i32.store offset=4", "local.get $p0", "local.get $p1",
            "i32.store", "local.get $p0", "local.get $p2", "i32.store offset=4",
            "local.get $p0)",
        ],
        f"{context['cid']} legacy misleading 8-byte entry constructor key/value/return drift",
    )
    typed_set, set_lines, set_digest = _legacy_function(
        context, ops, "index/Value>#set", spec.typed_map_set_body_sha256, 21
    )
    ops.require(
        set_lines[2:21]
        == [
            "local.get $p0", "local.get $p1",
            "call $~lib/@graphprotocol/graph-ts/index/TypedMap<~lib/string/String_~lib/@graphprotocol/graph-ts/index/Value>#getEntry",
            "local.tee $l3", "if $I0", "local.get $l3", "local.get $p2",
            "i32.store offset=4", "else", "i32.const 0", "local.get $p1",
            "local.get $p2",
            "call $~lib/@graphprotocol/graph-ts/chain/ethereum/ethereum.SmartContract#constructor",
            "local.set $p1", "local.get $p0", "i32.load", "local.get $p1",
            "call $~lib/array/Array<~lib/@graphprotocol/graph-ts/index/TypedMapEntry<~lib/string/String_~lib/@graphprotocol/graph-ts/index/Value>>#push",
            "end)",
        ],
        f"{context['cid']} legacy TypedMap#set update/entry/key/value/push identity drift",
    )
    return {
        "typed_map_get_entry": {
            "function": get_entry.name,
            "body_sha256": entry_digest,
            "same_receiver_key_entry_or_exhaustion_null_structurally_proven": True,
        },
        "typed_map_get": {
            "function": get_value.name,
            "body_sha256": get_digest,
            "same_receiver_key_value_offset_4_or_exhaustion_null_structurally_proven": True,
        },
        "misleading_entry_constructor": {
            "function": entry_constructor.name,
            "body_sha256": constructor_digest,
            "semantic_role": "8-byte TypedMap entry constructor, despite retained SmartContract symbol",
            "receiver_zero_key_value_offsets_and_return_structurally_proven": True,
        },
        "typed_map_set": {
            "function": typed_set.name,
            "body_sha256": set_digest,
            "existing_value_offset_4_or_original_key_value_entry_append_structurally_proven": True,
        },
    }


def prove_legacy_collection_capsule(
    context: dict[str, Any], ops: WatRuntimeOps, spec: LegacyCollectionSpec
) -> dict[str, Any]:
    """Close the sole public legacy allocator, collection, Value, and string capsule."""

    declarations = _prove_exact_function_declaration_inventory(
        context, ops, spec.function_declarations
    )
    start = _prove_legacy_start_dependencies(context, ops, spec)
    allocator = _prove_legacy_allocator_dependencies(context, ops, spec)
    indexed_value = _prove_legacy_indexed_and_value_dependencies(context, ops, spec)
    strings = _prove_legacy_string_dependencies(context, ops, spec)
    arrays = _prove_legacy_array_dependencies(context, ops, spec)
    typed_map = _prove_legacy_typed_map_dependencies(context, ops, spec)
    return {
        "exact_function_declarations": declarations,
        "native_start_and_constants": start,
        "allocator_and_arraybuffer": allocator,
        "indexed_access_and_value": indexed_value,
        "string_runtime": strings,
        "entry_array_runtime": arrays,
        "typed_map_runtime": typed_map,
        "allocator_freshness_scope": "within one handler invocation under the explicit assumption that imported hosts do not reenter exported memory.reset",
        "low_level_memory_semantics_rederived": False,
        "imported_host_behavior_rederived": False,
        "legacy_collection_capsule_structurally_closed": True,
    }


def prove_modern_collection_capsule(
    context: dict[str, Any],
    ops: WatRuntimeOps,
    spec: ModernCollectionSpec | ModernPoolCollectionSpec,
) -> dict[str, Any]:
    """Close the public modern allocator, collection, and equality capsule.

    This is the sole public modern collection proof. The private dependency
    algorithms above intentionally cannot certify a consumer on their own.
    """

    declarations = _prove_exact_function_declaration_inventory(
        context, ops, spec.function_declarations
    )
    if isinstance(spec, ModernPoolCollectionSpec):
        collection = _prove_modern_pool_mutation_dependencies(context, ops, spec)
        indexed = _prove_modern_pool_indexed_access_dependencies(context, ops, spec)
    else:
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
        "exact_function_declarations": declarations,
        "typed_map_collection_runtime": collection,
        "indexed_collection": indexed,
        "string_equality": {
            "function": string_eq.name,
            "retained_body_sha256": string_eq_digest,
            "proof_boundary": "exact retained pure library primitive body",
        },
        "modern_collection_capsule_structurally_closed": True,
    }
