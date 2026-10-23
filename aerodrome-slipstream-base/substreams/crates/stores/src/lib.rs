use aerodrome_extractor_core::carry::{registry_ops, StoreOp};
use aerodrome_extractor_pb::internal::PoolsCreated;
use substreams::{
    pb::substreams::Clock,
    store::{StoreNew, StoreSetIfNotExists, StoreSetIfNotExistsRaw},
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
