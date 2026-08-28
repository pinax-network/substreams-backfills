# Uniswap V3 graft ancestry contract

`v1/contract.json` is the fail-closed, machine-readable history contract for
the Uniswap V3 mainnet and Base deployments. It retains the exact raw IPFS
manifest bytes for every ancestor through a graft-free root and every schema,
ABI, and mapping WASM directly referenced by those manifests. The 38 retained
objects are stored without normalization under `v1/artifacts/<CID>`.

## Ordered writer ownership

At a graft boundary, the base deployment owns state **through and including**
the graft block. The child writer starts at the next block.

| Network | Writer deployment | Inclusive block interval |
|---|---|---:|
| mainnet | `Qme66ZNMxSdCQKzaDuvS381whCVYCQjf637sGZCqJHAWHB` | 12,369,621–13,450,880 |
| mainnet | `QmRvEgUpbjVV326W2zPvxWimzQwcDREfjejUdFn2L92qry` | 13,450,881–13,498,328 |
| mainnet | `QmS13421u6qsbVdBCrZhdRaZw2wH67drwF3urmueJvvJ5P` | 13,498,329–13,591,197 |
| mainnet | `QmSLHXCZBNKVtJRrWiEAF1yRQNPqAFptBsAcLdXQPsubSX` | 13,591,198–13,605,860 |
| mainnet | `QmZeCuoZeadgHkGwLwMeguyqUKz1WPWQYKcKyMCeQqGhsF` | 13,605,861–19,470,000 |
| mainnet | `QmTZ8ejXJxRo7vDBS4uwqBeGoxLSWbhaA7oXa1RvxunLy7` | 19,470,001–head |
| Base | `QmPWDTWRfS8XewMJhxXoQiZX6RkrUMYH7BFnnB846v6wzR` | 1,371,679–19,852,000 |
| Base | `Qmb4VUcAY9LsVgeCuCCMs7X1XrkbRcaiuAbSK8SqhmsAfP` | 19,852,001–head |

The verifier rejects a missing ancestor, a cycle or wrong parent, a gap or
overlap, a child starting on the graft block, and any segment selector that
does not resolve to exactly one writer.

## Artifact, handler, and writer evidence

Every artifact record contains its CIDv0, raw byte length, SHA-256, media type,
path, and all manifest references. Verification recomputes the canonical
single-chunk UnixFS CIDv0 offline, checks regular-file and path containment,
parses raw manifests with duplicate-key rejection, checks WebAssembly handler
exports, and requires exact reference closure. No gateway or live service is
used by CI.

The three retained schemas each declare the same 20 entities. Manual offline
review of every retained mapping's constant `index.store.set` targets observed
writer targets for 17 entities. No constant target for `Collect`, `Flash`, or
`TickHourData` was observed anywhere in either complete ancestry. These are
static observations, not runtime-population or required-absence certification.
The contract records all schema fields and marks field-level value, condition,
and ordering semantics as pending where they have not been proved.

Every mapping record retains the exact SHA-256 of the complete textual output
from `WABT wasm2wat 1.0.35 --generate-names`. This makes the review reproducible
against the exact mapping CID while keeping WABT out of the hermetic CI path.
CI validates the retained observations and their artifact bindings; it does not
independently rerun or certify the WAT analysis.

The deployment-specific observations include the historical position-manager
changes rather than projecting the current mappings backward:

- mainnet root Collect updates fee0 with amount0 and fee1 with amount1;
- the next mainnet epoch computes fee1 + amount1 but writes that result to fee0
  again, leaving fee1 unchanged;
- the following three mainnet epochs do not accumulate collected fees at all;
- the current mainnet and both Base position-manager mappings use the deployed
  amount0-to-both-fields behavior; the block 14,317,993 guard exists in current
  mainnet and both Base epochs, but not in the older mainnet epochs;
- mainnet block 14,317,993 belongs to the older unguarded `QmZe`/`QmYwx`
  interval, so replaying current `QmWx` code from origin would be wrong;
- every Pool epoch refreshes the two fee-growth fields on Flash and saves Pool,
  but does not write a `Flash` entity.

These are retained static WAT observations bound to exact mapping CIDs and
SHA-256 digests. They are not a complete field writer audit or runtime oracle.

## Verify or regenerate

With `requirements-ci.txt` installed, run:

```bash
python3 scripts/verify-uniswap-v3-graft-ancestry.py
python3 -m unittest scripts/tests/test_uniswap_v3_graft_ancestry.py
```

`--write-contract` deterministically regenerates `v1/contract.json` from the
retained artifacts and hard-pinned ancestry/static-review evidence. Generation
fails if an artifact no longer matches its CID or if manifest reference closure
changes.

## Truth boundary

This contract completes the immutable artifact closure, ordered ancestry,
manifest/handler inventory, and schema inventory. It retains independently
reviewed constant writer-target observations but deliberately leaves that
inventory's certification flag false. Every segment's execution model remains
undecided and `backfill_allowed=false`.

The complete field writer audit, boundary-state oracle samples, logical parity,
physical history, proof of indexing, and production package gates remain false.
Current mainnet code must not be replayed before block 19,470,001, and current
Base code must not be replayed before block 19,852,001, unless an independently
certified boundary seed supplies the inherited state.
