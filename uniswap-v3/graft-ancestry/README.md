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
retained in `writer-compatibility.json`. Registered-handler evidence is rooted
at the exact WAT export target rather than a suffix-matched function name.

Six modern mappings contain one `call_indirect` instruction. For each, the
verifier rejects imported/exported tables and every table mutation opcode,
parses the complete element target inventory, and conservatively adds every
table target to any handler closure that can execute `call_indirect`. The only
target is the local `Value#displayData` callback, whose transitive closure has
no `store.set` callsite. A synthetic regression test proves that an indirect
target containing a writer is included in critical handler reachability.

That complete callsite closure certifies static writer absence for `Collect`,
`Flash`, and `TickHourData` across the retained mainnet and Base ancestry. It
does **not** certify that those tables are empty in a live store: runtime
population remains a separate oracle query. The conservative lexical call-graph
closure for `handleCollect` contains only `Transaction`, `Position`, and
`PositionSnapshot` writers, while the equivalent closure for `handleFlash`
contains only `Pool`. This over-approximation supports writer-target absence
checks; it is not a same-path execution proof.

The deployment-specific observations include the historical position-manager
changes rather than projecting the current mappings backward:

- mainnet root Collect updates fee0 with amount0 and fee1 with amount1;
- the next mainnet epoch computes fee1 + amount1 but writes that result to fee0
  again, leaving fee1 unchanged;
- the following three mainnet epochs do not accumulate collected fees at all;
- the current mainnet and both Base position-manager mappings use the deployed
  amount0-to-both-fields behavior; the block 14,317,993 guard exists in current
  mainnet and both Base epochs, but not in the older mainnet epochs. Guard
  presence requires the handler's opening instructions to load
  `event.block.number`, compare it for equality with 14,317,993, and return from
  the matching conditional branch;
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

## Factory and Pool writer profiles

Writer contract v2 closes the static Factory/Pool profile inventory across all
14 distinct mappings: six Factory mappings with one `handlePoolCreated` each,
and eight Pool mappings with five handlers each. The verifier binds every
profile to its retained mapping CID, artifact digest, handler-body digest,
reachable entity writers, and WAT locations. It rejects missing or duplicate
profile coverage.

Every Factory profile retains the reviewed `PoolCreated` order as Pool save,
dynamic Pool datasource creation, token0 save, token1 save, then Factory save.
The verifier checks that lexical callsite tail and binds it to the exact handler
digest, but it does not prove same-path reachability, template argument dataflow,
or token identity. The ignored-pool guard is likewise a digest-bound reviewed
observation: literal and equality-call presence are checked, but event.pool to
comparison to early-return control flow is not. No `PoolCreated` row or
`Pool.tick` writer exists in the complete static writer inventory. Factory
static-handler completeness therefore remains false.

Factory metadata has two code generations. Legacy mappings convert the
`CallResult` pointer/allocation rather than the returned ERC20 total supply.
Their static arrays are constructor-backed and may contain leading holes: Base
root contains six empty slots, while historic mainnet allocates six empty slots
and then appends six definitions. Modern mappings decode total supply and use
safe literal arrays: empty on Base and six populated entries on mainnet. The
verifier checks the relevant helper bodies, array construction model, slot and
entry counts, and profile selection.

The eight Pool profiles retain these independent reviewed axes: legacy/modern
control generation, tracked-amount threshold and pricing profile, optional
QmRv 22-token gate, stable shortcut, Initialize persistence, TickDay relation
mode, fee-tier spacing, and explicit hour re-saves. Control generation, pricing,
threshold, gate, and stable shortcut are digest-bound reviewed catalog values,
not complete machine-proven axes. QmWu is the only mapping that rewrites
`TickDayData.tick` on every update; the other seven assign the relation only
when the day row is created. The verifier requires `store.get` to feed an exact
`local.tee`, then `eqz` and the creation `if`, and requires the helper to be
reachable from the exact exported Swap handler. The decoded `tick` literal,
setter, and branch placement remain digest-bound lexical evidence: symbolic key
stack dataflow and therefore the relation semantics are not machine-proven.
Legacy fee-spacing helpers must be
reachable from that same export and require an exact comparison branch whose
returned value is the recorded spacing. Equality branches are direct; compare
branches must use `eqz`. Modern inlined branches remain digest-bound reviewed
observations with only comparison-count and numeric-inventory checks.

QmZPi, QmPZ, and QmSa all contain direct PoolHourData re-save callsites after
the Pool-hour helper. The retained evidence records one direct re-save for
QmZPi and two each for QmPZ and QmSa. The other five profiles contain none.
These are exact lexical callsite counts and ordering; full control-flow
reachability is not claimed.

Mint, Burn, and Swap remain the only Pool event rows. The reviewed Flash behavior
is two ordered non-try fee-growth calls and one Pool save, with no Flash row.
For inline codegen, the verifier proves distinct field-specific method/signature
calls and distinct result locals, then retains lexical setter/save shapes and
the exact handler digest. Wrapper codegen additionally has immediate local
setter operand checks. Neither model claims CFG dominance or same-path execution.
Initialize persistence is likewise a digest-bound reviewed observation backed
by a lexical Pool.save callsite inventory, not an executable-path proof. The
Pool contract
also records the digest-bound reviewed observations for the Swap-only ignored
pool, cumulative writer groups, Token day/hour untracked-volume quirk, and
handler-atomic deterministic failure source model. These observations do not
claim complete field-value semantics. This is static deployed-WASM evidence,
not a runtime-population or boundary-state oracle.

Four mappings have exact source-entry blob anchors: Base-root Factory and Pool,
and current mainnet Factory and Pool. These pin a repository commit, entry path,
and Git blob only; no reproducible source-to-WASM build correspondence is
claimed. Every other mapping is explicitly `none_found`; four historic source
commits are retained only as unassigned semantic anchors. The retained deployed
WASM remains authoritative in every case. Validation reconstructs every full
provenance tuple from the mapping analysis and pinned entry-anchor table;
self-consistent fabricated commit/path/blob tuples are rejected.

The contract generates one canonical writer record for each of the eight
segments and all 28 unordered pairwise diffs. Artifact and semantic differences
have separate hashes and JSON paths. Six adjacent-graft pairs additionally pin
the boundary block. Standalone validation first verifies the retained immutable
ancestry file and cross-checks its path, SHA-256, version, artifact count, and
mapping count. It then binds the top-level writer segments—not only their child
records—to the ancestry network, deployment, range, Factory/NPM/Pool CIDs,
manifest handlers/features, and range-derived historical-guard status. Child
records are independently derived from those anchored segments and selected
profile semantics before accepting canonical hashes. Each segment
still has `execution_model="undecided"` and `backfill_allowed=false`.

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
| `graph/src/blockchain/block_stream.rs` | `8e4004884534c18054cb7ccd30b9eb675cbc956a3f651041e546ccca31fb0933` |
| `core/src/subgraph/inputs.rs` | `22a2ee4a8ef0b7ef4cca52115b505c41ff5ee917621645fa48e0971e712ff278` |
| `core/src/subgraph/runner/mod.rs` | `bb5623ed45b51ad99c783069ea4344c08a69e826016951a8b6282f3685e4b026` |

The pinned Ethereum trigger comparator orders logs by global log index, and the
block-stream source proves that Graph Node actually invokes the sort before
execution. Contract calls receive the trigger block pointer and read block-level
post-state. The adapter uses an EIP-1898 block hash when supported and otherwise
falls back to the block number, which is not fork/hash-bound. This is
deliberately distinct from intra-block handler order.

The first five mainnet segments do not enable `nonFatalErrors`; current mainnet
and both Base segments do. Under the pinned source model, a deterministic trap
discards the failing handler's created data sources and entity-cache changes and
records a deterministic proof-of-indexing event. The feature-selection and
runner source locks prove that `nonFatalErrors` preserves other successful
entity modifications, while fatal mode retains only proof-of-indexing changes,
transacts, and stops the deployment. This is source compatibility evidence
only. The exact Graph Node binary/source identity used by each target deployment
is still unbound, so runtime behavior and PoI parity remain oracle gates.

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
inventory, critical Collect/Flash reachability, Factory/Pool static profile and
source-binding inventories, all segment writer records and pairwise diffs, and
static absence certification for Collect, Flash, and TickHourData. Every
segment's execution model remains undecided and `backfill_allowed=false`.

Factory/Pool profile-axis machine proof, Factory/Pool static writer provenance,
the complete field writer audit, complete handler semantics, runtime
population, target Graph Node runtime identity, boundary-state continuity,
logical parity, physical history, proof of indexing, execution-model decisions,
and production package gates remain false.
Current mainnet code must not be replayed before block 19,470,001, and current
Base code must not be replayed before block 19,852,001, unless an independently
certified boundary seed supplies the inherited state.
