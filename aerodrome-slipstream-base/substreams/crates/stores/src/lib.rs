use aerodrome_extractor_core::carry::{self, registry_ops, StoreOp};
use aerodrome_extractor_pb::{
    internal::{PoolsCreated, StorageDeltas},
    v1::ExtractorBlock,
};
use substreams::{
    pb::substreams::Clock,
    store::{
        StoreDelete, StoreNew, StoreSet, StoreSetIfNotExists, StoreSetIfNotExistsRaw,
        StoreSetInt64, StoreSetRaw,
    },
};
#[substreams::handlers::store]
pub fn store_pools(created: PoolsCreated, clock: Clock, store: StoreSetIfNotExistsRaw) {
    for op in registry_ops(&created, clock.number).expect("validated registry records") {
        match op {
            StoreOp::Set {
                key,
                value,
                ordinal,
            } => store.set_if_not_exists(ordinal, key, &value),
            StoreOp::Delete { .. } => unreachable!("registry never deletes"),
        }
    }
}

fn apply(ops: Vec<StoreOp>, store: &StoreSetRaw) {
    // Store host functions use signed ordinals. Validate all operations before
    // the first host write, rather than silently wrapping a malformed ordinal.
    assert!(
        ops.iter().all(|op| i64::try_from(op.ordinal()).is_ok()),
        "storage ordinal exceeds i64"
    );
    for op in ops {
        match op {
            StoreOp::Set {
                key,
                value,
                ordinal,
            } => store.set(ordinal, key, &value),
            StoreOp::Delete { key, ordinal } => store.delete_prefix(ordinal as i64, &key),
        }
    }
}

#[substreams::handlers::store]
pub fn store_pool_slots(deltas: StorageDeltas, clock: Clock, store: StoreSetRaw) {
    apply(
        carry::pool_slot_ops(&deltas, clock.number).expect("valid pool deltas"),
        &store,
    );
}

#[substreams::handlers::store]
pub fn store_pool_last_tick(block: ExtractorBlock, store: StoreSetInt64) {
    let ops = carry::last_tick_ops(&block).expect("valid candidate ticks");
    assert!(
        ops.iter()
            .all(|(_, _, ordinal)| i64::try_from(*ordinal).is_ok()),
        "tick ordinal exceeds i64"
    );
    for (key, tick, ordinal) in ops {
        store.set(ordinal, key, &tick);
    }
}

macro_rules! shard_store {
    ($name:ident, $ops:ident, $shard:expr) => {
        #[substreams::handlers::store]
        pub fn $name(deltas: StorageDeltas, clock: Clock, store: StoreSetRaw) {
            apply(
                carry::$ops(&deltas, clock.number, $shard).expect("valid sharded deltas"),
                &store,
            );
        }
    };
}
shard_store!(store_tick_slots_00, tick_slot_ops, 0);
shard_store!(store_tick_slots_01, tick_slot_ops, 1);
shard_store!(store_tick_slots_02, tick_slot_ops, 2);
shard_store!(store_tick_slots_03, tick_slot_ops, 3);
shard_store!(store_tick_slots_04, tick_slot_ops, 4);
shard_store!(store_tick_slots_05, tick_slot_ops, 5);
shard_store!(store_tick_slots_06, tick_slot_ops, 6);
shard_store!(store_tick_slots_07, tick_slot_ops, 7);
shard_store!(store_position_slots_00, position_slot_ops, 0);
shard_store!(store_position_slots_01, position_slot_ops, 1);
shard_store!(store_position_slots_02, position_slot_ops, 2);
shard_store!(store_position_slots_03, position_slot_ops, 3);
shard_store!(store_position_slots_04, position_slot_ops, 4);
shard_store!(store_position_slots_05, position_slot_ops, 5);
shard_store!(store_position_slots_06, position_slot_ops, 6);
shard_store!(store_position_slots_07, position_slot_ops, 7);
shard_store!(store_position_slots_08, position_slot_ops, 8);
shard_store!(store_position_slots_09, position_slot_ops, 9);
shard_store!(store_position_slots_10, position_slot_ops, 10);
shard_store!(store_position_slots_11, position_slot_ops, 11);
shard_store!(store_position_slots_12, position_slot_ops, 12);
shard_store!(store_position_slots_13, position_slot_ops, 13);
shard_store!(store_position_slots_14, position_slot_ops, 14);
shard_store!(store_position_slots_15, position_slot_ops, 15);
