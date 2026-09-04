# `mapping-host`

A hermetic Rust host that runs a **deployed** subgraph's mapping WASM under Graph
Node's own runtime crates, pinned to `graph-node` revision
`77823b5a7adc4eac4abf03202c8dd7cb00dea31d` (tag `v0.44.0`).

It is family-neutral. It knows about segment bundles, Firehose blocks, an
in-memory store, an `eth_call` cassette and Graph Node's wave scheduler; it knows
nothing about Uniswap. Uniswap V3 is simply the first family whose eight
deployments are bundled under `segments/`.

It runs the deployed mappings hermetically, records the **ordered per-save
operation stream**, and seals one canonical
`pinax.graph.backfill.v1.BlockChanges` frame per block. It makes no parity claim;
see [Evidence boundary](#evidence-boundary).

## Why a separate cargo workspace

`graph` has no feature flags. `diesel` with the `postgres` feature, `redis`,
`tonic`, `arrow` and two `stable-hash` git dependencies are all unconditional:
784 packages resolve, 577 compile, and the binary links `libpq`. Putting that in
the root workspace would add about ninety seconds to every `cargo test
--workspace` in `ci-core`.

So `mapping-host/` has its own `Cargo.toml` with a `[workspace]` table, its own
`Cargo.lock`, and its own `rust-toolchain.toml`; `"mapping-host"` is in the root
`Cargo.toml` `exclude` list, which is the only root change this directory makes.

Toolchain: **1.98.0**. graph-node pins 1.94.0, but that pin is only valid against
graph-node's own lockfile — a fresh downstream resolution picks `alloy 2.4.1`,
whose MSRV is 1.94.1, and fails at resolution time. Two lockfile pins are copied
from graph-node: `graphql-tools` at 0.5.1 (0.5.8 changes `Value::Object` from a
map to a slice of pairs and breaks `graph`'s schema module), and both
`stable-hash` git dependencies by **revision**, not branch, because the Legacy
PoI digest depends on them.

Building also needs `libpq` and `protoc`. `cmake` is not needed: rustls resolves
to `ring`, and wasmtime and cranelift are pure Rust.

## Architecture

```
segments/<cid>/            deployed artifacts, digest-locked  ─┐
uniswap-v3/fixtures/       Firehose sf.ethereum.type.v2.Block ─┤
$FIREHOSE_ENDPOINT         or the same blocks, streamed live  ─┤
fixtures/cassettes/        recorded eth_call answers          ─┤
                                                               ▼
  bundle.rs        FileLinkResolver + SubgraphManifest::resolve_from_raw
  block.rs         codec::Block -> BlockFinality; log -> EthereumTrigger::Log
  source.rs        BlockSource: committed fixtures, or a live Firehose range
  live.rs          streaming report, frame and BCF1 writers; stderr progress
  runner.rs        waves, hosts, handler groups; per-handler BlockState
  store.rs         in-memory ReadStore, persistent across blocks in a run
  calls.rs         RuntimeAdapter -> cassette-backed ethereum.call HostFn
  poi.rs           update_proof_of_indexing + ProofOfIndexingFinisher
  blockchanges.rs  the recorded save stream -> canonical frames
  descriptor.rs    per-segment compatibility descriptors
  report.rs        deterministic JSON
                                                               ▼
      fixtures/reports/<cid>.json   fixtures/block-changes/<cid>/<block>.pb
```

Roughly 4,700 lines of library and binary code, plus 1,800 lines of tests, on
top of the vendored runtime crate.

### Segment bundles

`segments/<deployment-cid>/` holds `manifest.yaml` byte-identical to the IPFS
object (so it still hashes to the deployment CID), `schema.graphql`,
`abis/<Name>.json`, `mappings/<mapping-cid>.wasm`, and `bundle.lock.json` listing
every file's IPFS CID, byte length and SHA-256. The loader verifies every digest
before use and refuses drift in both directions: a file whose bytes changed, and
a file present on disk that the lock does not cover.

The manifest keeps its original `/ipfs/<cid>` links. Resolution goes through
graph-node's own `FileLinkResolver`, seeded with an alias table mapping each CID
to its friendly path, so data sources, templates, ABIs and handlers all come out
of graph-node's parser rather than ours.

All eight Uniswap V3 deployments are bundled:

| Deployment | Blocks | Spec | API | Features |
|---|---|---|---|---|
| `Qme66ZNMxSdCQKzaDuvS381whCVYCQjf637sGZCqJHAWHB` | mainnet 12,369,621–13,450,880 | 0.0.2 | 0.0.4 | none |
| `QmRvEgUpbjVV326W2zPvxWimzQwcDREfjejUdFn2L92qry` | mainnet 13,450,881–13,498,328 | 0.0.2 | 0.0.4 | none |
| `QmS13421u6qsbVdBCrZhdRaZw2wH67drwF3urmueJvvJ5P` | mainnet 13,498,329–13,591,197 | 0.0.2 | 0.0.4 | none |
| `QmSLHXCZBNKVtJRrWiEAF1yRQNPqAFptBsAcLdXQPsubSX` | mainnet 13,591,198–13,605,860 | 0.0.2 | 0.0.4 | none |
| `QmZeCuoZeadgHkGwLwMeguyqUKz1WPWQYKcKyMCeQqGhsF` | mainnet 13,605,861–19,470,000 | 0.0.2 | 0.0.4 | none |
| `QmTZ8ejXJxRo7vDBS4uwqBeGoxLSWbhaA7oXa1RvxunLy7` | mainnet 19,470,001–head | 0.0.4 | 0.0.7 | nonFatalErrors, grafting |
| `QmPWDTWRfS8XewMJhxXoQiZX6RkrUMYH7BFnnB846v6wzR` | Base 1,371,679–19,852,000 | 0.0.4 | 0.0.4 | nonFatalErrors |
| `Qmb4VUcAY9LsVgeCuCCMs7X1XrkbRcaiuAbSK8SqhmsAfP` | Base 19,852,001–head | 0.0.4 | 0.0.7 | nonFatalErrors, grafting |

The first five declare no `features`, so their deterministic-error policy is
**fatal**: one deterministic error discards every other write in the block. The
last three are **non-fatal**. Getting that wrong is a silent correctness bug, so
it is read from the resolved manifest and reported per block.

Rebuild the bundles from a directory of IPFS objects with:

```sh
cargo run -- build-bundles --from <dir-of-cid-files> --out segments
cargo run -- verify-bundle --segment segments/<cid>
```

### Block input

A fixture is one bare `sf.ethereum.type.v2.Block` protobuf, converted by
graph-node's own `TryInto<BlockFinality>`.

**One block per file, enforced.** Release `block-fixtures-v1` shipped two
consecutive blocks per file, and handing such a file to `Block::decode` is
silently wrong rather than an error: prost merges the two messages, so scalar
fields come from the last block while `transaction_traces` is the union of both,
producing a block that claims to be `N+1` while carrying `N`'s logs as well.
Release `block-fixtures-v2` re-cut every file, and `cargo xtask fixtures check`
is now strict about it.

`block::load_block` does not take that on trust. It splits the stream at message
boundaries and refuses anything but a single message, naming the second block and
its offset in the error. `split_messages` remains only as the detector behind
that refusal: protobuf gives no framing, but this encoder emits top-level fields
in ascending tag order, so a tag lower than the previous one starts a new message
(a repeated field repeats its tag, so only a decrease counts), and the field that
opens a message must be `ver`. A stream that does not split cleanly is an error,
never a guess.

Trigger construction mirrors `parse_log_triggers`, which is `pub(crate)`. Note
what it does: once the log filter is non-empty it emits a trigger for **every**
log in the block and leaves address and topic matching to
`DataSource::match_and_decode`. The sort and dedup then come from
`BlockWithTriggers::new`, reused verbatim, because that is where Graph Node's
trigger determinism actually lives.

### The per-save operation stream, and the vendored runtime

`EntityCache` collapses writes into a `HashMap`, so the order in which a mapping
called `store.set` is not recoverable from `as_modifications` — nor is a repeat
upsert that changes nothing, nor a save inside a handler that later aborts. All
three matter to `BlockChanges`.

They *are* recoverable beside the proof-of-indexing writes in `HostExports`,
which already emit one event per store call, in call order, and which the PoI
itself hashes. `vendor/graph-runtime-wasm/` is graph-node's `runtime/wasm` copied
verbatim from the pinned revision plus an optional recorder invoked there:

  `src/op_recorder.rs`   new file, the `EntityOpRecorder` trait
  `src/lib.rs`           export it
  `src/host_exports.rs`  one optional field, one setter, three call sites
  `src/host.rs`          carry it from the builder into `HostExports`

The exact diff is `vendor/graph-runtime-wasm.patch`; everything else under
`src/` is byte-identical to upstream and the two licence files are copied
alongside. The default is `None`, so an unconfigured runtime behaves exactly as
upstream does, which is what makes the patch upstreamable. `Cargo.toml` wires it
with

```toml
[patch."https://github.com/graphprotocol/graph-node"]
graph-runtime-wasm = { path = "vendor/graph-runtime-wasm" }
```

so `graph` and `graph-chain-ethereum` still come from the git source and link
against one `graph`.

Why a threaded field rather than a process-global: `HostExports` is constructed
inside `graph_runtime_wasm::host`, a **private** module, so there is no public
seam to inject through — but `RuntimeHostBuilder` is public, `RuntimeHost::new`
already builds the `HostExports` it will share, and a `&mut` setter before the
`Arc` needs no interior mutability. That keeps the recorder per host rather than
per process, which a multi-segment run will need.

The runner drains the recorder after each handler returns, before that handler's
modifications reach the store. Exactly one handler runs at a time, so the drain
is that handler's saves in call order.

### The store, and why writes land between handlers

Graph Node uses one `BlockState`, and so one `EntityCache`, for every handler in a
block: a handler's `store.get` sees writes an earlier handler made, because
`EntityCache::get` layers `updates` over `current`.

To report *per-handler* modifications, each handler here gets its own
`BlockState`, and `as_modifications` is taken after it returns. Two things keep
reads observationally identical to the shared cache:

1. that handler's modifications are applied into the in-memory store, and
2. the `entity_lfu_cache` that `as_modifications` returns is threaded into the
   next handler's `BlockState` via `EntityCache::with_current`.

After `as_modifications`, `current` holds the post-write entity for every key the
handler touched and `updates` is empty, so the next handler's `get` reads exactly
what the shared cache would have produced. Step 1 keeps `current` and the store in
agreement, which also satisfies the `debug_assert!` in `EntityCache::get` that
compares them — that assertion is live in test builds.

Sequence numbers are *not* per handler: the `SeqGenerator` is cloned, and a clone
shares the same atomic counters, so VIDs stay dense and monotonic across the whole
block exactly as Graph Node's do.

Two differences remain, neither reachable by these mappings:

* A shared cache emits **no** modification when a handler changes an entity and a
  later handler changes it back; per-handler snapshots emit both. That is the
  difference we want — the report is a per-handler operation stream, not a
  coalesced block diff.
* `Remove` then `Set` on one key is a single `Overwrite` under a shared cache and
  a `Remove` followed by an `Insert` here. None of the twenty deployed Uniswap V3
  modules imports `store.remove`, so the case cannot arise.

### The `eth_call` cassette

Graph Node's own `graph_chain_ethereum::RuntimeAdapter` cannot be reused with a
cassette-backed `EthereumCallCache`: it resolves an `EthereumAdapter` with
`call_or_cheapest` *before* consulting the cache, so an adapter-less network
errors on every call. We implement the one-method `RuntimeAdapter` trait instead
and return our own `ethereum.call`, reproducing graph-node's `ethereum_call` and
`eth_call` step for step: charge `ETHEREUM_CALL` gas, read the
`SmartContractCall` out of WASM memory using the 0.0.4 layout when the mapping's
API version allows, find the named ABI and the function by name and signature,
ABI-encode, look up, ABI-decode.

The key is `(block hash, contract address, calldata)`. The value is graph-node's
own `Retval` shape: `Null` for a revert, or return data. That distinction matters:
AssemblyScript's generated `try_foo()` reads a null pointer as `reverted = true`,
while the non-`try` `foo()` asserts on it and aborts the handler with a
*deterministic* error. A decode failure is also a revert, exactly as
`contract_calls::decode` treats it.

```json
{
  "schema": "pinax.substreams-backfills.mapping-host.cassette/v1",
  "entries": [
    {
      "block_number": 12369739,
      "block_hash": "0x…",
      "address": "0x1f9840a85d5af5bf1d1762f925bdaddc4201f984",
      "calldata": "0x95d89b41",
      "contract": "ERC20",
      "function": "symbol()",
      "retval": { "kind": "value", "data": "0x…" }
    }
  ]
}
```

Rows are sorted by key, so the file is byte-stable.

**Replay is the default and fails closed**: a missing key is a hard error, never a
silent revert, because a silent revert would change the mapping's behaviour and
the PoI. Record mode needs both `--record` and `ETHEREUM_RPC_URL`; no endpoint is
compiled in, and no token appears in any file here. Recording pins the call to the
block hash with EIP-1898, stores an RPC revert as `Null`, and treats a transport
error as a hard failure — never as `HostExportError::PossibleReorg`, which in
Graph Node restarts the block stream and here would quietly mean "no answer".

The committed segment-1 cassette is 15 KB / 22 rows, recorded once against
`https://eth.rpc.pinax.network`:

| Contract | Function | Rows |
|---|---|---:|
| ERC20 | `symbol()`, `name()`, `decimals()`, `totalSupply()` | 3 each |
| Factory | `getPool(address,address,uint24)` | 3 |
| NonfungiblePositionManager | `positions(uint256)` | 3 |
| Pool | `ticks(int24)` | 4 |

Every answer is a value; no call reverted at these blocks.

### Proof of indexing

Two different things happen at the end of a block:

* `update_proof_of_indexing` pauses each causality region's event stream, mixing
  in that region's digest from the previous block, and writes the result as a
  `Poi$` entity. That is the value that chains. It is a private free function in
  graph-node, so `poi.rs` carries a documented copy.
* `ProofOfIndexingFinisher` combines the stored per-region digests with the block
  pointer, the deployment hash and an indexer address into what a gateway serves.
  We pass `indexer: None`, the public PoI.

Version rule: spec `>= 0.0.6` uses `Fast`, below uses `Legacy`. All eight Uniswap
V3 deployments are 0.0.2 or 0.0.4, so all eight are **Legacy**, which is why the
`stable-hash` revisions are pinned.

A block in which no handler ran produces no causality region, so no PoI entity is
written and the digest does not advance. The report says `poi: null` for such a
block. That is Graph Node's behaviour, not a simplification.

### Environment pinning

`graph::env::ENV_VARS` is a process-global `Lazy` read on first use, so a stray
`GRAPH_*` in the ambient environment could change a report or a digest.
`env_pin::pin()` runs before anything touches it, from `main` and from the test
entry point, and sets every variable below to graph-node v0.44.0's own default:

| Variable | Pinned to |
|---|---|
| `GRAPH_MAX_SPEC_VERSION` | `1.5.0` |
| `GRAPH_MAX_GAS_PER_HANDLER` | `1_000_000_000_000_000` |
| `GRAPH_LOG_POI_EVENTS` | `false` |
| `GRAPH_ENABLE_DIPS_METRICS` | `false` |
| `GRAPH_SUBGRAPH_MAX_DATA_SOURCES` | `1000000` |
| `GRAPH_MAX_API_VERSION` | `0.0.9` |
| `GRAPH_ENTITY_CACHE_SIZE` | `10000` |
| `GRAPH_WASM_OPT_LEVEL` | `speed` |
| `GRAPH_ALLOW_NON_DETERMINISTIC_IPFS` | `false` |
| `GRAPH_DISABLE_DECLARED_CALLS` | `false` |
| `GRAPH_STORE_ERRORS_ARE_NON_DETERMINISTIC` | `false` |
| `GRAPH_IPFS_REQUEST_LIMIT` | `100` |

Two are forced *absent*, because graph-node's default for them is unset and any
value changes behaviour: `GRAPH_MAPPING_HANDLER_TIMEOUT` (a timeout turns a slow
handler into a non-deterministic failure) and `GRAPH_RUNTIME_MAX_STACK_SIZE` (it
moves where a deep AssemblyScript recursion traps).

### BlockChanges v1 frames

Each block produces one `pinax.graph.backfill.v1.BlockChanges` message.

| Field | Source |
|---|---|
| `operation_index` | dense, zero-based, across the block |
| `handler_group_order` | one per `start_handler`, monotonic |
| `source_trigger_order` | the trigger's index within its wave |
| `handler_order` | the host's index within one trigger |
| `source_causality_region` | 0; Uniswap V3 is onchain-only |
| `poi_causality_region` | `ethereum/<network>` on every operation |
| `written_fields` | the schema-filtered entity exactly as hashed, `vid` excluded, sorted |
| `materialized` | the get-visible entity after that save |
| `store_disposition` | see below |
| `redacted_events` | PoI events since that group's `start_handler` |
| `compatibility_id` | SHA-256 of the segment descriptor |

`materialized` is computed with `backfill_common::CacheOperation`, whose
`accumulate` and `apply_to` are the canonical wrappers over
`apply_written_fields` and `NullMergeMode` — the exact items the validator uses.
No merge semantics are restated here, because two implementations of them is the
failure mode the contract exists to prevent.

Within a handler, saves to one key **accumulate** and the running effect is
projected onto the entity visible before the handler ran. Re-merging incrementally
instead would diverge: two saves where the second nulls a field the first set
leave a *retained* Null over an absent baseline under accumulation, and a
*removed* field if each save is merged in turn. Graph Node's `EntityCache::get`
layers accumulated `handler_updates` over `current`, so accumulation is the
faithful one.

Dispositions follow the manifest's policy. Under `fatal` (segments 1 to 5) one
deterministic error makes every operation in the block `BLOCK_DISCARDED`, except
the failing handler's own, which are `DISCARDED`. Under `non_fatal` only the
failing handler's operations are `DISCARDED`. A block may carry several errors:
Graph Node keeps processing triggers after one and only discards effects at
`transact_block_state`, so each failing group writes its own `DeterministicError`
event. Two errors in *one* group is the case Graph Node itself asserts against,
and this host refuses it too.

Every frame is validated with `backfill_common::validate_block_changes` and
round-tripped through `encode_canonical_block_changes` and
`decode_canonical_block_changes` before it is written, so nothing leaves here
that the engine's read side would refuse.

### Segment descriptors

`segments/<cid>/block-changes-descriptor.json` and its `.sha256` sidecar are
generated, not hand-written, by `graph-mapping-host build-descriptors`. The
descriptor's digest is the frame's `compatibility_id`, and it binds the
deployment CID, the CID and SHA-256 of the manifest, schema, every mapping module
and every ABI, the canonical proto and its prost binding, the Graph Node revision
and the PoI version it selects, the manifest features and the resolved schema's
entity types.

They are **not** fixture descriptors: `fixture_only` is absent, so the engine
replays them without `--allow-fixture-descriptor`. The sidecar is what
`--block-changes-descriptor` requires.

The bundle lock does not cover the descriptor or its sidecar: those are
repository-authored statements *about* the deployed artifacts, with their own
digest pin. Every other file in a bundle directory must be locked, and the loader
refuses an unlocked one.

## Running it

```sh
cargo run -- run \
  --segment segments/Qme66ZNMxSdCQKzaDuvS381whCVYCQjf637sGZCqJHAWHB \
  --blocks ../uniswap-v3/fixtures/blocks/mainnet/12369739.pb \
  --cassette fixtures/cassettes/Qme66ZNMxSdCQKzaDuvS381whCVYCQjf637sGZCqJHAWHB.json \
  --out report.json
```

Block fixtures are content-addressed release assets; hydrate them from the
repository root with
`cargo xtask evidence fetch --lock uniswap-v3/fixtures/blocks.lock.json`.

Every block in every `--blocks` file is replayed, in ascending order; `--only`
restricts that to named block numbers. `--record` plus `ETHEREUM_RPC_URL` appends
cassette misses instead of failing.

`--block-changes-out DIR` writes one canonical frame per block as `<number>.pb`
plus an `index.json` pinning each by SHA-256 and naming the descriptor they were
sealed against. `--bcf1-out FILE` additionally writes the whole run as one `BCF1`
clock-v1 stream, the envelope `cmd/substreams-native` produces and the engine's
`--input-format block-changes-v1-framed` reads:

```text
0  ..4    "BCF1"
4         version, 1
5  ..8    reserved, zero
8  ..16   block number, big-endian u64
16 ..48   block hash, 32 bytes
48 ..52   payload length, big-endian u32
52 ..     one canonical BlockChanges message
```

Golden frames live under `fixtures/block-changes/<cid>/`. Regenerate them with
`UPDATE_GOLDENS=1 cargo test --test block_changes_qme66zn`, which rewrites them
and then fails, so a regeneration is never mistaken for a passing check.

## Live mode: a contiguous range from Firehose

The four committed fixtures are four sampled points. A block range that would
exercise `handleSwap`, `handleBurn`, `handleFlash` and a *successful*
`handleCollect` has to be contiguous, and the parity window alone is roughly
1.2 GB of blocks — far too much to commit. So `--from N --to M` streams the
half-open range live at run time, and everything committed here stays a fixture.

```sh
export FIREHOSE_ENDPOINT=eth.firehose.pinax.network:443
export FIREHOSE_API_TOKEN=…            # or SUBSTREAMS_API_TOKEN

cargo run -- run \
  --segment segments/Qme66ZNMxSdCQKzaDuvS381whCVYCQjf637sGZCqJHAWHB \
  --from 12369739 --to 12369741 \
  --cassette fixtures/cassettes/Qme66ZNMxSdCQKzaDuvS381whCVYCQjf637sGZCqJHAWHB.json \
  --out live.jsonl \
  --block-changes-out live-frames \
  --bcf1-out live.bcf1
```

`--blocks` and `--from/--to` are the two block sources and cannot be combined.
Everything downstream of the source is unchanged: the same waves, the same PoI
chain, the same store, the same sealed frames. A live run over a fixture's block
produces a byte-identical frame; the smoke run below is exactly that check.

**No new dependency.** `graph` already builds the `sf.firehose.v2` protos and
ships a client, so `source.rs` uses `graph::firehose::FirehoseEndpoint` and
`stream_blocks` rather than generating a second copy of the protos. Nothing was
added to `Cargo.toml` or `Cargo.lock`. One thing does have to be done that
graph-node does in its own `main`: `rustls` 0.23 panics on the first handshake
unless a crypto provider is installed, because this dependency graph links both
`aws_lc_rs` and `ring`, so `FirehoseSource::connect` calls
`graph::tls::install_default_crypto_provider()`. A fixture run installs nothing.

### The endpoint, and the token

`$FIREHOSE_ENDPOINT` is a bare `host:port`, or the same with an explicit
`https://`. It is **credential-free by construction**: userinfo (`user:pass@`), a
query string, a fragment, a path, a plaintext scheme and whitespace are each
refused rather than stripped, so a token can only ever arrive through
`$FIREHOSE_API_TOKEN` or `$SUBSTREAMS_API_TOKEN`, in that order. The token is
validated for printable ASCII first, because `FirehoseEndpoint::new` *panics* on
one that is not, and it is never echoed, logged, or written into the report — the
report header records the endpoint's `host:port` and nothing else.

### Fail closed on a gap, a fork or a duplicate

The request sets `final_blocks_only`, so there is no undo stream to reconcile.
Every source is then wrapped in a `CheckedSource`, and a live range asks it for
`Ordering::Contiguous`, which refuses:

| Refusal | Why it matters |
|---|---|
| a gap (`expected 102, got 103`) | the store and the PoI chain would silently diverge |
| a repeat of a block already produced | the same effects would be applied twice |
| a decrease | out-of-order replay makes the store meaningless |
| a block outside `[from, to)` | the source answered a question that was not asked |
| a stream that ends before `to - 1` | a truncated range would look like a complete one |

The live source adds four checks of its own, before contiguity is even
considered: the response must be `STEP_FINAL`, must carry a block, must carry an
`sf.ethereum.type.v2.Block` and not something else, and must decode as **exactly
one** message whose number is the one that position in the range calls for. The
one-message check is `block::split_messages`, the same detector that guards the
committed fixtures — prost merges concatenated messages rather than rejecting
them, which is how release `block-fixtures-v1` shipped blocks that claimed to be
`N+1` while carrying `N`'s logs.

The range is also checked against the segment before the stream is opened.
`--from` below the segment's own first block is refused; that block comes from
the resolved manifest (the lowest `dataSources[].source.startBlock`, or the block
after the graft when the manifest grafts). There is no upper check for these
deployments, and the reason is worth stating plainly: a segment's *last* block is
a fact about the deployment succession, recorded in this README's bundle table,
not a fact the manifest carries. `endBlock` would be enforced if a manifest
declared one; none of the eight does.

### The cassette in live mode

Unchanged, and that is the point: `ethereum.call` replays from the committed
cassette and **fails closed on a miss**. A live run never silently reaches the
RPC. `--record-calls` (the same flag as `--record`) plus `ETHEREUM_RPC_URL`
appends misses instead, and because the rows live in a `BTreeMap` keyed by
`(block hash, address, calldata)` the file is rewritten in the same order every
time — a recording is a pure addition. Writes now go through a temporary file and
a rename, so a run that dies mid-write cannot leave a truncated cassette, and a
long recording run also saves on each progress tick rather than only at the end.

### Streaming output

A contiguous range cannot be held in memory, so every writer flushes per block.

| Artifact | Fixture run | Live run |
|---|---|---|
| `--out` | one pretty-printed `RunReport`, exactly as before | JSON Lines: one `report-stream/v1` header line, then one `BlockReport` per line |
| `--block-changes-out` | `<number>.pb` per block, `index.json` at the end | `<number>.pb` per block, `index.jsonl` appended per frame |
| `--bcf1-out` | one `BCF1` stream | the same bytes, flushed per frame |

The fixture report keeps its single-document form deliberately: it is what
`fixtures/reports/<cid>.json` pins, and a golden that is one parseable document
is worth more than uniformity between two modes with very different sizes. The
frames and the `BCF1` stream are byte-identical either way.

`--progress-secs` (default 10, `0` to silence) prints block number, blocks/second
and cumulative handler groups to **stderr**, so it never contaminates a report
streamed to stdout. Progress is constructed only on the live path, so the
hermetic tests emit nothing.

### `--resume` is refused, and why

`--resume` exists and always fails, with the reason. Three things carry across a
block boundary and none of them survives the process:

* **the in-memory store.** Nothing is persisted between blocks. There is no
  snapshot format, and the written `BlockChanges` frames are a per-save
  *operation stream*, not a store image.
* **the Legacy PoI chain.** Each block's causality-region digest mixes in the
  previous block's, and it lives in a `Poi$` entity that no mapping handler
  writes — the recorder never sees it, so no frame carries it.
* **the host set.** Dynamic data sources accumulate across blocks; only a replay
  from the segment's first block puts the same hosts in the same order.

Resuming from partial state would produce a different PoI and a different store
while looking like a success, which is the one failure this crate exists to
prevent. Re-run the whole range instead. Making `--resume` real means persisting
a store snapshot *and* the per-region PoI digests *and* the ordered host set, and
proving the reconstruction round-trips; that is a piece of work, not a flag.

### What CI runs, and what a real range costs

CI runs the **fixtures only**. Every test in this crate is hermetic:
`tests/block_source.rs` drives a fake source and hand-built Firehose responses,
`tests/live_cli.rs` asserts the CLI refusals with `FIREHOSE_ENDPOINT=127.0.0.1:1`
so a refusal that stopped short of the network would fail rather than pass
quietly, and the two segment tests are unchanged. No test opens a socket.

Scale, for planning a real run:

| Range | Blocks | Approximate block bytes |
|---|---:|---:|
| parity window, 12,369,621 → 12,370,674 | 1,053 | ~1.2 GB |
| segment 1, 12,369,621 → 13,450,880 | 1,081,260 | ~1.2 TB |

At the ~0.3 blocks/second the smoke run measured — dominated by WASM execution,
not by the network — the parity window is about an hour and the full segment is
not a single-run proposition.

### The live smoke run

One run has been done end to end, on 2026-09-04, against
`eth.firehose.pinax.network:443` over `--from 12369739 --to 12369741`, without
`--record-calls`:

* both blocks arrived, contiguous, `STEP_FINAL`, one message each;
* 12,369,739 produced **5 handler groups, 29 collapsed modifications, 34 saves,
  0 errors**, and its 32,328-byte frame is **byte-identical to the committed
  golden**, with public PoI `020f3009…1cd012cc` — the same value the fixture run
  reports;
* 12,369,740 triggered no handler, so it wrote a 114-byte frame and no PoI, which
  is what a block with no causality region is supposed to do;
* **no cassette miss**: 22 rows consulted, 22 rows after, file byte-unchanged.

A second, longer probe over `--from 12369739 --to 12369790` replayed 21
contiguous blocks and then stopped at 12,369,760 with

```text
cassette miss in replay mode: 0x6b175474e89094c44da98b954eedeac495271d0f 0x95d89b41 … (ERC20::symbol())
```

That is the second `PoolCreated` in this window, for DAI, whose `symbol()` the
committed cassette does not cover — the intended outcome, not a bug: the run
failed closed instead of reaching the RPC, the cassette was left byte-unchanged,
and the artifacts written before the failure are a consistent 21-block prefix.
The cassette was **not** extended here. Recording the calls a contiguous range
needs belongs to the parity-window run that will consume them, not to this
change.

## What the run shows

Segment 1 over the four committed fixture files, one block each. One host, one
store and one PoI chain across the run, so Pool template instances accumulate:
the hosts column climbs 2, 2, 3, 4.

| Block | Triggers per wave | Hosts per wave | Groups | Collapsed mods | Saves | Errors | Frame | Public PoI |
|---:|---|---|---:|---:|---:|---:|---:|---|
| 12,369,621 | 152 | 2 | 0 | 0 | 0 | 0 | 114 B | none |
| 12,369,739 | 199, 199 | 2, 1 | 5 | 29 | **34** | 0 | 32,328 B | `020f3009…1cd012cc` |
| 12,369,879 | 242, 242 | 3, 1 | 5 | 27 | **33** | 0 | 32,484 B | `aec119d6…0803bc47` |
| 12,370,523 | 401 | 4 | 2 | 0 | **2** | 2 | 1,262 B | `59996f37…e44e39ccd` |

The gap between "collapsed mods" and "saves" is what the recorder buys. At
12,369,739 the mapping performed 34 saves that `EntityCache` reported as 29
modifications; at 12,370,523 it performed 2 saves that `EntityCache` reported as
**none at all**, because both handlers aborted and the cache discarded their
work. The frames keep those two saves with `STORE_DISPOSITION_DISCARDED` beside
the `DeterministicError` that redacted them.

Four results are worth stating plainly.

**The wave model is real, and a flat log ordering is wrong.** In block 12,369,739
the Factory's `PoolCreated` (log 24) runs in wave 1 along with the position
manager's `Transfer` (30) and `IncreaseLiquidity` (31). The Pool template's
`Initialize` (log 25) and `Mint` (29) run in **wave 2**, at *lower* log indices,
because the data source that handles them did not exist when wave 1 was scheduled.
Both waves report 199 triggers because wave 2 rescans **the same block**, not
because the two waves see different logs. `parse_log_triggers` emits a trigger for
every log in the block as soon as the filter is non-empty, and wave 2's filter,
built from the newly created Pool data source, is non-empty. The two waves are
therefore offered an identical 199-trigger list; what differs is the host set each
list is matched against — two manifest hosts in wave 1, the one new Pool host in
wave 2 — which is what `hosts_per_stage` records as `2, 1`. Because each wave
indexes into its own list, `source_trigger_order` regresses from 31 to 25 between
handler groups.

**`Pool.save` precedes the `Mint` write in `handleMint`.** Phase 1 could not
check this: `as_modifications` gives an arbitrary `HashMap` order, so the report
sorted by key and said so. The recorded stream shows the real order, and a test
asserts it. The same stream shows `handleMint` saving one entity type more than
once, which a coalesced diff cannot represent at all.

**The legacy `totalSupply` quirk reproduces.** `handlePoolCreated` writes
`Token.totalSupply = 18776` for UNI, whose real supply is 10^27. The six legacy
mappings convert the ERC-20 `CallResult` with `ByteArray.fromI32`, yielding the
allocation pointer rather than the value. This is the executable form of the
`total_supply_model` claim in the segment survey.

**The fatal policy discards a block — from a fixture-gap error, not deployed
behaviour.** Block 12,370,523's position-manager events concern token id 33,
whose position lives in pool `0xdc7b403e2e967eaf6c97d79316d285b8a112fda7` with
token0 `0x956f47f50a910163d8bf957cf5846d573e7f87ca`. That pool was created
somewhere in 12,369,881 to 12,370,522, which this fixture set does not sample, so
no `Token` row for it exists in the run's store, `Token.load` returns null, and
the old-codegen dereference aborts both `handleDecreaseLiquidity` and
`handleCollect` with `Value is not a BigInt`. A contiguous replay would have the
row and both handlers would succeed. What the run does demonstrate is the host's
fatal-policy machinery: the store is restored to its pre-block state and only the
PoI survives. The test that covers this says so explicitly and asserts nothing
about the deployed mapping at this height.

## Cross-reference against the frozen Substreams port

The port's `graph_out` goldens live at
`uniswap-v3/fixtures/goldens/mainnet/<block>/graph_out.jsonl`. They are **not** a
gate here — they are a different producer with known divergences — but comparing
them is informative:

| Block | Port `graph_out` | This host | Why |
|---|---|---|---|
| 12,369,621 | creates `Bundle` and `Factory` | nothing | The deployed mapping creates both inside `handlePoolCreated`; there is no `PoolCreated` in this block. The port creates them at the module start block. |
| 12,369,739 | 16 entity types, 22 ops, including 2 `TickHourData` | 15 types, 29 ops, no `TickHourData` | The port emits `TickHourData`, which all twenty deployed modules certify as never written. Op counts differ because `graph_out` coalesces per entity per block while this report is per handler. |
| 12,369,879 | includes a `Swap` on pool `0xc2e9f25b…` | no `Swap` | That pool was created in a block the fixture set does not sample, so no Pool data source exists for it here. |
| 12,370,523 | includes a `Burn` | none | Same cause, plus the fatal-policy discard above. |

The last two rows are the sharpest limitation of this evidence: **the fixture set
is four sampled points, not a contiguous range**, so any handler whose data source
was created in an unsampled block cannot fire. `handleSwap`, `handleBurn`, a
successful `handleCollect` and `handleDecreaseLiquidity`, and `handleFlash` are
therefore unexercised. Exercising them needs a contiguous replay — the
`12,369,621 → 12,370,674` window that `uniswap-v3/fixtures/mainnet-chain-config-parity-v1.json`
already locks — which is what [live mode](#live-mode-a-contiguous-range-from-firehose)
streams. What it still needs is a cassette covering that window's `eth_call`s.

## What could not be reproduced through public API

| Wanted | Status | Why |
|---|---|---|
| Per-handler gas | still `null` | `RuntimeHost::process_mapping_trigger` discards the `Gas` that `WasmInstance::handle_trigger` returns (`runtime/wasm/src/host.rs:224`), and `WasmRequest` is `pub(crate)`. The vendored crate is now the obvious place to expose it, but `BlockChanges` v1 has no field for it, so nothing here needs it yet. |
| Per-`store.set` ordering | **resolved** by the vendored recorder | Still invisible in `fixtures/reports/`, whose per-handler `modifications` list stays sorted by `(entity, id)` because it comes from `as_modifications`. The BlockChanges frames carry the real order. |
| Redundant identical upserts | **resolved** by the vendored recorder | `as_modifications` emits nothing when a write does not change the entity, so the report still shows `Transaction` once for block 12,369,739. The frames show each handler's own upsert. |
| `parse_log_triggers`, `EthereumLogFilter` | reproduced | Both `pub(crate)`. |
| `SubgraphTriggerProcessor::process_trigger` | reproduced | Lives in `graph-core`, which is not a dependency. |
| `update_proof_of_indexing` | copied | A private free function. |
| `RuntimeHost`, `WasmRequest` types | reached indirectly | `graph_runtime_wasm::host` is a private module; both are reachable as associated types of the public `RuntimeHostBuilder`. |
| Stopping after a fatal error | deliberate difference | Graph Node fails the subgraph and stops. This host rolls the block back, records `block_discarded`, and continues, so one run can report every block it was given. |

## What is still open

* **The other seven segments.** All eight are bundled and all eight have
  descriptors, but only segment 1 has a cassette and golden frames. The rest need
  their own cassettes, and the Base pair needs Base block fixtures.
* **A contiguous block range, actually replayed.** The live source exists and
  works (see [Live mode](#live-mode-a-contiguous-range-from-firehose)), but no
  parity-window run has been done: the committed cassette covers the four fixture
  blocks only, so a contiguous range stops at the first `eth_call` it has not
  seen. Five handlers stay unexercised and `STORE_DISPOSITION_COMMITTED` after a
  deterministic error stays untested until that cassette is recorded.
* **`RemoveEntity`.** Implemented end to end, including the pre-key remove the
  proto models, but no Uniswap V3 module imports `store.remove`, so no fixture
  reaches it.
* **A live engine replay.** The frames are sealed with the same codec the engine
  decodes with, and the `BCF1` envelope is byte-checked against the engine's own
  frame layout, but no run of
  `state-replay --input-format block-changes-v1-framed` over these frames has
  happened here.

## Evidence boundary

This directory is an execution harness and a set of recorded observations. It

* makes **no parity claim** against the deployed subgraph: no PoI here has been
  compared with an indexer's, and the ancestor deployments are not queryable at
  all;
* makes **no parity claim** against the frozen Substreams port: the cross-
  reference above is informative only;
* changes **no readiness flag**. `runtime_population_complete`,
  `boundary_state_continuity_complete`, `physical_parity_complete` and
  `poi_parity_complete` in `uniswap-v3/writer-runtime/segment-profiles-v1.json`
  remain false;
* covers **one** of eight segments and four non-contiguous blocks.

What it does establish is that the deployed AssemblyScript modules execute
faithfully under our own host, with our own store and call provider, and that the
wave scheduler, the fatal-error policy and the Legacy PoI chain behave as the
segment survey described.
