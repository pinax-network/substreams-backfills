# Eligibility boundary

This v1 supplement certifies exactly these runtime facts for
`modern-base` and `modern-mainnet`:

- the exact two four-part artifact tuples are selected;
- the candidate shared-runtime source bytes equal the bytes actually executed;
- the public modern Pool collection capsule closes over the 77-line
  `TypedMap#set`, `TypedMap#get`, EventParam indexer, `String.__eq`, Entity
  constructor type IDs, allocator return identities, capacity commits, and
  exact low-level body boundaries;
- `_start` resolves only to `~start`, there is no native start section, all
  critical mutable globals begin at zero, and their complete writer
  inventories match; and
- the exact initializer contains no direct memory write and all initialized
  data ends below the installed allocator floor.

The eight critical mutable globals are `~started`, the stub allocator offset,
ZERO_BI, ONE_BI, ZERO_BD, ONE_BD, MINIMUM_ETH_LOCKED, and Q192. Their only
permitted writers are the exact profile initializer plus the bound allocator
and `ensureCapacity` offset writes recorded in `contract.json`.

The scope count is deliberately partial:

| Pool runtime profiles | Count |
|---|---:|
| Total retained profiles | 8 |
| Modern profiles closed here | 2 |
| Legacy profiles still residual | 6 |

No handler semantics are added. In particular, Initialize remains false here
even though a separate handler-level supplement exists; this runtime capsule
does not import or promote that independent claim.

The following remain strict JSON `false` values:

- all-eight and all-six-legacy Pool runtime coverage;
- Burn, Mint, Initialize, Swap, and Flash handler semantics;
- all-manifest handler semantics and complete Pool entity history;
- actual historic event population;
- arbitrary-linear-memory safety for imported host functions;
- general aggregate-helper memory safety beyond the exact body boundaries;
- boundary state continuity and Graph oracle completeness;
- logical, physical, proof-of-indexing, or checkpoint authority;
- backfill readiness, production readiness, and overall readiness.

The host boundary is explicit: imported host functions are assumed not to
write arbitrary linear memory. The aggregate boundary is also explicit:
`ensureCapacity` and the three low-level memory primitives are checksum-pinned
complete bodies with narrower structural checks, not a fresh general proof of
all reachable memory behavior.

The compile-valid WAT mutation suite rejects setter early return/no-op,
key/value exchange, inline append or length drift, getter/index/equality drift,
allocator return or reset drift, start/export/global/direct-memory drift, and
initialized data crossing the allocator floor. A self-rehashed JSON contract
cannot promote any residual gate because verification recomputes the complete
deterministic projection.

This supplement completes no backfill or production acceptance checkbox.
