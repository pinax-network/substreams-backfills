# Eligibility boundary

This v1 supplement certifies exactly two new upstream paths:

```text
$.complete_static_handler_contract for modern-base
$.complete_static_handler_contract for modern-mainnet
```

The cumulative Factory status is therefore:

- total upstream Factory proof paths: 18;
- previously closed: 12;
- newly closed here: 2;
- cumulative closed: 14; and
- residual: 4, all four legacy `complete_static_handler_contract` paths.

Each certified modern path contains exactly 60 stored-field contracts: 59
written transitions and the required absence of `Pool.tick`. Across the two
modern mapping segments, this is 120 field projections. The handler-local
inventory has exactly 76 `TypedMap#set` calls per mapping, with `Token.id`
separately owned by the bound constructor proof. Every handler setter is
machine-bound to its exact entity receiver, decoded field key, Value kind,
semantic payload producer, final Value operand, and exact map-set call; the
semantic-family coverage set is required to equal the complete 76-site
inventory.

That handler inventory is not the call-graph boundary. A direct plus
conservative-indirect reachability pass closes 56 functions on Base and 57 on
mainnet and requires exactly 77 reachable `TypedMap#set` sites: the 76 handler
sites plus the certified `Token#constructor` `id` write. Any setter introduced
into a reachable helper, including a `Pool.tick` write hidden in an ID getter,
invalidates the proof even if that helper's body authority is refreshed.

The event parameter remains the reaching definition of handler `$p0` at every
event and block read; its sole earlier assignment is on an abort-only display
path. The fee-tier copy index `$l2` has no assignment before its first loop
increment and therefore retains WebAssembly's initial zero. Structural
certificates cover the exact token-call receiver/selectors/arguments,
CallResult and Value decoders, collection index/value flows, whitelist members,
ID getters, static tuple construction and lookup, and the complete decimals
comparison. Exact retained helper digests are authority seals, not substitutes
for those dataflow checks.

The collection closure additionally proves the same key/value operands through
both `TypedMap#set` branches, the same new entry appended to the same receiver,
the old-length/new-length transition in `Array<TypedMapEntry>#push`, a fresh
Entity map backing, stub allocator return identity, and the backing/capacity
commits of `ensureCapacity`. The complete retained `ensureCapacity` body and
the lower-level `memory.fill`, `memory.copy`, and `memcpy` bodies remain exact
hash boundaries because their general memory semantics are not rederived.

The exported initializer is bound as `_start -> ~start`; no native start
section is admitted. The proof requires zero initial values and inventories
every writer of `~started`, the allocator offset, ZERO_BI, ONE_BI, and ZERO_BD.
The decoded whitelist object, backing buffer, members, allocator floor, and
the direct linear-memory writes/calls in `~start` are also bound, and those
initializer-local writes cannot reach the protected regions. Other reachable
helper bodies are covered by the aggregate exact-body authority, not by a
general proof that they cannot write protected memory. Imported host functions
are assumed not to write arbitrary linear memory; both are explicit proof
boundaries.

The complete normal-return effect traces are exactly:

| Factory state | Token decimals outcome | Handler-local effect trace |
|---|---|---|
| Pool already exists | not reached | empty |
| Factory exists | either token returns null | empty |
| Factory missing | either token returns null | `Bundle.save` |
| Factory exists | both decimals non-null | exact five-effect suffix |
| Factory missing | both decimals non-null | `Bundle.save` then exact five-effect suffix |

The exact five-effect suffix is Pool save, Pool dynamic data-source creation,
token0 save, token1 save, and Factory save. Retained WAT proves invocation and
ordering, not Graph Node transaction rollback after a later failure.

The global segment-field-semantics v2 counts deliberately do not move: 34
selected fields and 232 residual conditional fields remain before and after
this partial-profile closure. The same 60-field Factory contract is still
unproved for all four legacy mappings, so no field can yet be promoted across
all six mapping segments.

The proof treats token helper outcomes symbolically. It proves the exact
mapping from each profile-pinned try-call outcome to the stored value or early
return; it does not assert which outcome occurred at any historic block. In
particular, it does not supply runtime population evidence.

The following remain strict JSON `false` values:

- all-six and all-legacy complete-static Factory coverage;
- complete Factory entity histories across other handlers;
- actual historic contract-call outcomes and runtime population;
- Graph Node rollback and complete execution-trace semantics;
- complete writer diffs, integrated scheduling, or runtime consumption;
- target identity, boundary continuity, or checkpoint authority;
- logical, physical, proof-of-indexing, GraphQL, or oracle parity; and
- backfill or production readiness.

This bounded supplement does not complete any acceptance checkbox in tracking
issue #38.

Extracting its contract-I/O-free WAT runtime algorithms for later reuse does
not bind either modern Pool context and does not add any Pool runtime,
backfill, or production certification.
