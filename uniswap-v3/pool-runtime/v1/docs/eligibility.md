# Eligibility boundary

This v1 supplement certifies structural runtime facts for all eight retained
Pool mappings: two modern profiles and six legacy profiles in four exact legacy
digest groups.

For every profile it certifies the complete four-part artifact tuple, the
candidate shared-runtime bytes actually executed, the generation-appropriate
public collection capsule, complete module-state inventory, and initialized
data below the exact allocator floor.

The public capsules also bind exact function declarations independently from
body digests: function names and type uses, ordered parameter names/types,
result declarations, and every leading named local declaration. Recomputing a
body digest after swapping parameter or local labels cannot preserve a runtime
claim.

At the public context boundary, fixed per-profile all-defined-function
declaration digests additionally cover all 123 modern or 225 legacy function
definitions. This is declaration authority only, not a semantic promotion of
unselected helpers.

The modern certificate remains the same exported-initializer proof: 77-line
`TypedMap#set`, getter/index/equality dependencies, Entity constructor type
IDs, allocator identities, capacity commits, `_start -> ~start`, eight critical
mutable globals and all writers, and no initializer direct-memory write.

The legacy certificate is a separate native-start proof. Across all six exact
artifacts it binds:

- `(start $start)`, no `_start` export, 17 exact imports, and 11 exact exports;
- the sole one-entry `$null` table, no `call_indirect`, no internal
  `memory.reset` call, and no handler closure reaching `memory.reset`;
- complete global definitions and writers, including no-writer static globals;
- exact native-start/constants, arena/ArrayBuffer, EventParam, Value,
  String/compare, TypedMap, and entry-array paths; and
- the misleading `ethereum.SmartContract#constructor` symbol as the exact
  8-byte TypedMap entry constructor required by the setter append path.

The scope count is complete only at the runtime layer:

| Pool runtime profiles | Count |
|---|---:|
| Total retained profiles | 8 |
| Modern profiles closed | 2 |
| Legacy profiles closed | 6 |
| Runtime profiles residual | 0 |

No handler semantics are added. In particular, Initialize remains false here
even though a separate handler-level supplement exists; this runtime capsule
does not import or promote that independent claim.

The following remain strict JSON `false` values:

- Burn, Mint, Initialize, Swap, and Flash handler semantics;
- all-manifest handler semantics and complete Pool entity history;
- actual historic event population;
- arbitrary-linear-memory safety and other semantics of imported hosts;
- freshly rederived general semantics for legacy `memcpy`, `memmove`, and
  `memset` beyond their exact bodies and checked operand call sites;
- host-unreachability of exported legacy `memory.reset` and cross-handler
  allocator freshness;
- general aggregate-helper memory safety beyond exact body boundaries;
- boundary state continuity and Graph oracle completeness;
- logical, physical, proof-of-indexing, or checkpoint authority;
- backfill readiness, production readiness, and overall readiness.

Legacy allocator freshness is deliberately narrower: it holds within one
handler invocation only if imported hosts do not reenter exported
`memory.reset`. Handler closures do not reach reset internally, but the host
can call the export, so neither host-unreachability nor cross-handler
continuity is promoted.

The compile-valid WAT mutation suite covers all four legacy digest groups and
rejects module start/export/import/table/reset, global inventory, data-floor,
start/constants, allocator/ArrayBuffer, EventParam, Value, String,
TypedMap/entry-constructor, entry-array, and low-level primitive drift. When a
test targets a deeper structural rule, only the deliberately changed
top-level body authority is refreshed. It separately rejects parameter-order,
parameter/local-identity, type-use/result, and local-type declaration drift
after that refresh. A self-rehashed JSON contract cannot
promote any residual gate because verification recomputes the complete
deterministic projection.

This supplement completes no handler, backfill, or production acceptance
checkbox.
