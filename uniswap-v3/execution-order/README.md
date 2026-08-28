# Uniswap V3 Graph Node execution-order supplement v1

`v1/contract.json` is a fail-closed source-reference supplement for the retained
Uniswap V3 writer-v3 and segment-matrix-v1 contracts. It corrects one unsafe
shorthand in the earlier ancestry documentation: Graph Node's Ethereum trigger
comparator orders triggers **inside one execution stage**. It does not flatten
the initial pass and later dynamic-data-source passes into one raw global order.

The supplement binds the exact raw SHA-256 of both upstream contracts and 22
full Graph Node source files at tag `v0.44.0`, commit
`77823b5a7adc4eac4abf03202c8dd7cb00dea31d`, tree
`1f372b47e4de659ddbf503cdbc31ebe4d54df239`. The immutable URLs, line anchors,
file hashes, model, and discriminating fixtures are all part of the contract.
No live Graph Node binary or target deployment is identified by this evidence.

## Ordering model

The initial pass is trigger-major and host-minor: Graph Node walks the stage's
sorted/deduplicated raw triggers, then invokes matching hosts in insertion
order. Successfully instantiated nonduplicate initial hosts are encountered
from manifest data sources in manifest order followed by stored dynamic data
sources ordered by creation block and database `vid`.

Successful handlers queue newly created data sources. After the initial pass,
Graph Node drains the queue, instantiates nonduplicate hosts while preserving
encounter order, refetches and rematches the entire block for only those new
hosts, and repeats. That is breadth-first traversal. Each wave has its own
trigger sort. A dynamic data source is gated by `start_block`, which is its
creation block; there is no creation-log ordinal gate. A same-block Pool log
with a lower log index than the Factory's `PoolCreated` log can therefore run
in the later Pool-host wave.

The stage fixture makes every child match earlier than its creating log. Its
canonical log-index trace is `10, 20 | 3, 4 | 1, 1`, where bars separate
stages. A raw-global flattening or creation-ordinal gate produces a different
trace and is rejected.

## Deterministic errors, VID, and PoI

Graph Node buffers entity updates and newly created data sources for each
mapping handler. A deterministic trap discards those two buffers. This is not a
full rollback: the block-shared VID and auto-ID counters, PoI events,
write-capacity accounting, metrics, and cache reads are not rewound. VIDs use
`(block << 32) + sequence`, with sequences starting at 100. An
`EntityCache::set` that reaches the allocation point consumes a VID that
handler-buffer discard does not reclaim, even if later validation fails, so a
later write has a gap. Other deterministic validation or capacity errors can
fail before allocation.

`store.set` writes a PoI `SetEntity` before `EntityCache::set` allocates the
VID. On a deterministic error the attempted `SetEntity` events remain in the
PoI input. Graph Node appends `DeterministicError { redacted_events }`; the
counter is a semantic redaction marker, not physical deletion. Its boundary is
Graph Node's `start_handler` marker once per raw runnable-trigger group before
all matching hosts, not universally the beginning of the one failing mapping
handler. The included rollback fixture has one hosted mapping handler per raw
trigger so its `redacted_events=2` is unambiguous.

After the user handlers, Graph Node stores the PoI entity through the same
`EntityCache`, consuming the next VID. The fixture therefore persists
`A@100`, `D@103`, and `PoI@104` in nonfatal mode; fatal mode filters the entity
modifications to `PoI@104` only. This entity VID sequence is unrelated to the
Postgres metadata `vid` used to order already-stored dynamic data sources.

With `nonFatalErrors`, successful entity/data-source changes, the PoI, and the
error are submitted as the block transaction and the in-memory block pointer
advances; continuation is conditional because an unsynced deployment may still
hit Graph Node's fail-fast cancellation. This source model does not turn queue
acceptance into a physical database-commit claim. Without that
feature, Graph Node filters only entity modifications to the PoI entity; it
still passes persisted data sources and deterministic errors into the block
transaction, advances the failed block pointer, and then stops the deployment.
Pre-transaction mapping, decode, or dynamic-stage unknown errors return before
the block transaction. Later persistence or metrics failures may occur after a
transaction is accepted and the pointer advances; they are outside this bounded
failure fixture.

A chain reorg is a different boundary from handler discard: the relational
store removes entity versions created at or after the first reverted block and
unclamps prior versions closed there; replay then constructs a fresh
block-scoped sequence generator. This does not make a failed handler rewind the
generator inside its original execution.

## Truth boundary

This is source-bound reference truth, not a runtime implementation. The only
true gates are `graph_node_reference_source_bound` and
`dynamic_datasource_stage_reference_modeled`. Target runtime identity, a
combined handler-order implementation, runtime consumption, same-path machine
proof, physical parity, PoI parity, backfill permission, and production
readiness all remain false.

## Verification

```sh
python3 scripts/verify-uniswap-v3-execution-order.py
python3 -m unittest scripts.tests.test_uniswap_v3_execution_order
```

Use `--write-contract` only to reproduce the canonical JSON after deliberately
changing the pinned verifier constants. CI verifies exact rendering, source
bindings, reference-truth digest, adversarial counterexamples, and conservative
flags without network access.
