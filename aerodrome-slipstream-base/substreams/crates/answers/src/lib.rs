#![allow(clippy::not_unsafe_ptr_arg_deref)]
// Each shard is a separate Substreams ABI argument, including in the generated wrapper.
#![allow(clippy::too_many_arguments)]
use aerodrome_extractor_core::{
    answers::{self, Store, StoreRead},
    Address,
};
use aerodrome_extractor_pb::{internal as i, v1 as p};
use substreams::store::{StoreGet, StoreGetInt64, StoreGetRaw};

#[derive(Default)]
struct View<'a> {
    pools: Option<&'a StoreGetRaw>,
    slots: Option<&'a StoreGetRaw>,
    ticks: &'a [StoreGetRaw],
    positions: &'a [StoreGetRaw],
    first: Option<&'a StoreGetInt64>,
}
impl StoreRead for View<'_> {
    fn get(&self, store: Store, key: &str) -> Result<Option<Vec<u8>>, String> {
        let source = match store {
            Store::Pools => self.pools,
            Store::PoolSlots => self.slots,
            Store::Tick(shard) => self.ticks.get(usize::from(shard)),
            Store::Position(shard) => self.positions.get(usize::from(shard)),
        }
        .ok_or_else(|| format!("module is missing store {store:?}"))?;
        Ok(source.get_last(key))
    }
    fn first_tick(&self, pool: &Address) -> Result<Option<i64>, String> {
        Ok(self
            .first
            .ok_or("module is missing prior tick store")?
            .get_first(format!("t:{};", substreams::Hex(pool))))
    }
}

#[allow(clippy::too_many_arguments)]
#[substreams::handlers::map]
pub fn map_tick_answers(
    block: p::ExtractorBlock,
    pools: StoreGetRaw,
    previous: StoreGetInt64,
    tick_00: StoreGetRaw,
    tick_01: StoreGetRaw,
    tick_02: StoreGetRaw,
    tick_03: StoreGetRaw,
    tick_04: StoreGetRaw,
    tick_05: StoreGetRaw,
    tick_06: StoreGetRaw,
    tick_07: StoreGetRaw,
) -> Result<i::TickAnswers, substreams::errors::Error> {
    let ticks = [
        tick_00, tick_01, tick_02, tick_03, tick_04, tick_05, tick_06, tick_07,
    ];
    answers::tick_answers(
        &block,
        &View {
            pools: Some(&pools),
            ticks: &ticks,
            first: Some(&previous),
            ..Default::default()
        },
    )
    .map_err(substreams::errors::Error::msg)
}

#[allow(clippy::too_many_arguments)]
#[substreams::handlers::map]
pub fn map_position_answers(
    block: p::ExtractorBlock,
    pools: StoreGetRaw,
    slots: StoreGetRaw,
    position_00: StoreGetRaw,
    position_01: StoreGetRaw,
    position_02: StoreGetRaw,
    position_03: StoreGetRaw,
    position_04: StoreGetRaw,
    position_05: StoreGetRaw,
    position_06: StoreGetRaw,
    position_07: StoreGetRaw,
    position_08: StoreGetRaw,
    position_09: StoreGetRaw,
    position_10: StoreGetRaw,
    position_11: StoreGetRaw,
    position_12: StoreGetRaw,
    position_13: StoreGetRaw,
    position_14: StoreGetRaw,
    position_15: StoreGetRaw,
) -> Result<i::PositionAnswers, substreams::errors::Error> {
    let positions = [
        position_00,
        position_01,
        position_02,
        position_03,
        position_04,
        position_05,
        position_06,
        position_07,
        position_08,
        position_09,
        position_10,
        position_11,
        position_12,
        position_13,
        position_14,
        position_15,
    ];
    answers::position_answers(
        &block,
        &View {
            pools: Some(&pools),
            slots: Some(&slots),
            positions: &positions,
            ..Default::default()
        },
    )
    .map_err(substreams::errors::Error::msg)
}

#[substreams::handlers::map]
pub fn map_extractor_block(
    block: p::ExtractorBlock,
    deltas: i::StorageDeltas,
    pools: StoreGetRaw,
    slots: StoreGetRaw,
    ticks: i::TickAnswers,
    positions: i::PositionAnswers,
    metadata: i::TokenMetadataAnswers,
) -> Result<p::ExtractorBlock, substreams::errors::Error> {
    answers::assemble(
        block,
        deltas,
        ticks,
        positions,
        metadata,
        &View {
            pools: Some(&pools),
            slots: Some(&slots),
            ..Default::default()
        },
    )
    .map_err(substreams::errors::Error::msg)
}
