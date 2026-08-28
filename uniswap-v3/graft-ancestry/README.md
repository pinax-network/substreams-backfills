# Uniswap V3 graft ancestry contract

`v1/contract.json` is the fail-closed, machine-readable history contract for
the Uniswap V3 mainnet and Base deployments. `v1/writer-compatibility.json`
adds a versioned writer-evidence layer over that immutable ancestry. They retain
the exact raw IPFS manifest bytes for every ancestor through a graft-free root
and every schema, ABI, and mapping WASM directly referenced by those manifests.
The 38 retained objects are stored without normalization under
`v1/artifacts/<CID>`.

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

The three retained schemas each declare the same 20 entities. The writer
verifier reruns checksum-pinned `WABT wasm2wat 1.0.35 --generate-names` over all
20 mapping WASMs in CI. It checks the complete WAT of every function, all 20
direct `store.set` imports, and all 162 direct callsites. Every callsite has the
same proved argument shape: a decoded constant entity literal, an ID converted
to string, and the entity value. The verifier finds 162 fixed known targets and
zero dynamic or indirect targets. The WAT output SHA-256, handler bodies,
normalized cross-chain bodies, call sequences, and callsite locations are
retained in `writer-compatibility.json`.

That complete callsite closure certifies static writer absence for `Collect`,
`Flash`, and `TickHourData` across the retained mainnet and Base ancestry. It
does **not** certify that those tables are empty in a live store: runtime
population remains a separate oracle query. `handleCollect` is also proved to
reach only `Transaction`, `Position`, and `PositionSnapshot` writers, while
`handleFlash` reaches only `Pool`.

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
SHA-256 digests. The verifier proves their mapping/profile selection, guard
effectiveness, handler reachability, and exact body identities. The
human-readable formula descriptions remain digest-bound, independently reviewed
observations; they are not a complete handler or field-writer audit and are not
a runtime oracle.

Five position-manager profiles are selected across the eight writer segments:

| Profile | Mapping epoch | Collect result |
|---|---|---|
| mainnet root | `QmYWR` | old fee0 + amount0; old fee1 + amount1 |
| mainnet second | `Qmebr` | writes fee0 twice; final fee0 is old fee1 + amount1 and fee1 is unchanged |
| mainnet middle | `QmYwx` | no collected-fee amount accumulation |
| Base root | `QmUk` | amount0 is added to both fee fields; block 14,317,993 guard is effective |
| current codegen | `QmWx`, `QmPjh` | amount0 is added to both fee fields when token0 exists; compiled guards are outside these segments |

The QmRv/Qmebr result is an absolute fee0 assignment computed from the
position's fee1 value at that event ordinal plus amount1. It is **not** an
additive update to fee0 and cannot be reproduced by the candidate's current
fee0 `StoreAdd` alone; an implementation must expose the ordinal-correct fee1
state and apply the deployed overwrite. This PR supplies evidence only and does
not satisfy that #37 runtime repair.

All four NPM handlers save a position snapshot. Increase, Decrease, and Collect
refresh fee-growth fields through generated `try_positions`; a reverted call
preserves the previous values. Transfer directly sets the owner from the NPM
event. Pool Flash uses generated non-try `SmartContract#call` for
`feeGrowthGlobal0X128` followed by `feeGrowthGlobal1X128`, updates Pool, and
saves it; a missing call result traps that handler.

## Trigger timing and failure source model

The source model is pinned to Graph Node `v0.44.0`, commit
[`77823b5`](https://github.com/graphprotocol/graph-node/commit/77823b5a7adc4eac4abf03202c8dd7cb00dea31d),
tree `1f372b47e4de659ddbf503cdbc31ebe4d54df239`. The contract retains immutable
blob URLs, relevant line anchors, and these full-file SHA-256 values:

| File | SHA-256 |
|---|---|
| `chain/ethereum/src/runtime/runtime_adapter.rs` | `b76b73c36b8f2fc57372b5d1847ac3877bee3bff64dffe8cf54ef984abe11bf6` |
| `chain/ethereum/src/ethereum_adapter.rs` | `e018e25a8ad480c0d436d4a046ce404b4e10dd7488231fd28ed58e1e9b1c49f0` |
| `runtime/wasm/src/module/instance.rs` | `5d259076417e59ef217d888b5bb8e711faa31e7431165ac8f5c2bbeac9accc86` |
| `graph/src/components/subgraph/instance.rs` | `e55bda1854ea60b10729b56b2e1b524bbc76aaa02a4d3256424b1631968de504` |
| `core/src/subgraph/trigger_processor.rs` | `5cdce1e42627e45d8520d5e8d938a1eb13f142c245d72d5bfb098d94e7cb2905` |
| `chain/ethereum/src/trigger.rs` | `6b31d65fa9c0289d76a5bb7d812965e51e26054bb4fad417aa641843c531700f` |

This source orders Ethereum log triggers by global log index, but contract
calls receive the trigger block pointer and read block-level post-state. The
adapter uses an EIP-1898 block hash when supported and otherwise falls back to
the block number, which is not fork/hash-bound. This is deliberately distinct
from intra-block handler order.

The first five mainnet segments do not enable `nonFatalErrors`; current mainnet
and both Base segments do. Under the pinned source model, a deterministic trap
discards the failing handler's created data sources and entity-cache changes and
records a deterministic proof-of-indexing event. With `nonFatalErrors`, other
successful handlers continue; without it, the deployment fails at that block.
This is source compatibility evidence only. The exact Graph Node binary/source
identity used by each target deployment is still unbound, so runtime behavior
and PoI parity remain oracle gates.

## Verify or regenerate

With `requirements-ci.txt` installed, run:

```bash
python3 scripts/verify-uniswap-v3-graft-ancestry.py
wasm2wat --version # must print 1.0.35
python3 scripts/verify-uniswap-v3-writer-semantics.py
python3 -m unittest scripts/tests/test_uniswap_v3_graft_ancestry.py
python3 -m unittest scripts/tests/test_uniswap_v3_writer_semantics.py
```

`--write-contract` deterministically regenerates `v1/contract.json` from the
retained artifacts and hard-pinned ancestry/static-review evidence. Generation
fails if an artifact no longer matches its CID or if manifest reference closure
changes. The writer verifier's same flag regenerates
`v1/writer-compatibility.json`, but only after every retained mapping reproduces
its WAT digest and every writer/profile invariant passes.

## Truth boundary

These contracts complete the immutable artifact closure, ordered ancestry,
manifest/handler inventory, schema inventory, exact constant writer-target
inventory, critical Collect/Flash reachability, and static absence certification
for Collect, Flash, and TickHourData. Every segment's execution model remains
undecided and `backfill_allowed=false`.

The complete field writer audit, complete handler semantics, runtime
population, target Graph Node runtime identity, boundary-state continuity,
logical parity, physical history, proof of indexing, execution-model decisions,
and production package gates remain false.
Current mainnet code must not be replayed before block 19,470,001, and current
Base code must not be replayed before block 19,852,001, unless an independently
certified boundary seed supplies the inherited state.
