# Mapping-host per-block delta rollback

The producer previously deep-copied every live entity at the start of every
block, including empty blocks, to support fatal-error rollback. It also scanned
every live key at block end to report counts. Both costs grew with historical
live state even when the block changed little or nothing.

## Implementation and invariants

`MemoryStore::apply_recording` records the first old value or absence for each
distinct key modified by handlers in the current block. Later handlers and
dynamic-source waves cannot replace that original. Inserts, overwrites,
removals, and remove/reinsert sequences use the same path.

On a successful block the undo map is discarded. On a fatal block, only those
keys are restored or removed. The runner still clears the LFU cache and then
applies Graph Node's PoI modifications separately, after rollback. This changes
storage bookkeeping, not handler order, error policy, operation dispositions,
VID generation, dynamic-host scheduling, or PoI folding. Non-deterministic
process errors retain the existing behavior; this is not a new retry mechanism.

Live rows and per-type counts share one write lock. Inserting an absent key
increments its type count; replacing an existing key does not. Removing a
present key decrements the count and removes zero-count types. Rollback uses
the same operation. Explicit checkpoint restore rebuilds counts once from the
restored rows and replaces both together.

For N live rows, W modifications in a block, D distinct modified keys, and T
entity types, retained rollback state scales with D old entities, not N. It
still pays BTreeMap lookup costs and clones those entities' actual payloads;
there is no constant byte-size assumption. Per-block count reporting copies T
entries rather than scanning N keys. An empty modification list records no
undo entries. This is an algorithmic improvement, not a measured full-history
throughput claim.

## Verification

The focused store tests cover repeated updates across handler batches,
overwrite/remove/reinsert, originally absent keys, successful-block boundaries,
10,000 unrelated rows with zero or one touched key, and 500 deterministic
mutations checked against independently recomputed counts. Snapshot restore
and fatal rollback must preserve exact row content and original VIDs.

**Graph Node's `Entity::PartialEq` deliberately ignores VID.** The rollback
tests therefore compare `vid()` explicitly in addition to entity equality.
Never use a plain entity-map equality assertion as evidence of VID preservation.

The existing locked mapping-host suite additionally checks committed replay
goldens, fatal-block discarded modifications, PoI, store dumps and checkpoint
continuation. Do not regenerate goldens to validate this optimization. The
opt-in `source_chunks::real_300` test compares a real retained 300-block corpus
against the previously pinned BCF digest and a 200+100 restart, including all
semantic checkpoint fields. That test requires clean committed source and
retains the source and binary identities when an evidence directory is supplied.

## Remaining full-history work

The entity store is still in memory. Full-store checkpoint/export snapshots,
checkpoint restoration, LFU cache, active runtime hosts and cassette storage
remain separate scaling concerns. This does not establish all-segment/graft
parity, sustained Mainnet throughput, an independent Graph Node comparison,
database load authorization, or production readiness.

No runtime pins, checkpoint/wire formats, release allowlists, Kubernetes
resources, or credentials change here. A newly published source-built runtime
is a distinct execution successor; it must be audited and deliberately selected
before use. Existing pilot pins are not automatically upgraded.
