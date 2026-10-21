// The Substreams 0.7 handler macro exposes ABI raw pointers.
#![allow(clippy::not_unsafe_ptr_arg_deref)]
use aerodrome_extractor_core::{
    candidates::{self, EventDecoder, PoolRegistry},
    config::Config,
    Address,
};
use aerodrome_extractor_pb::{eth, internal as i, v1 as p};
use prost::Message;
use substreams::store::{StoreGet, StoreGetRaw};
use substreams_ethereum::Event;
substreams_ethereum::init!();
#[allow(clippy::all)]
mod factory {
    include!(concat!(env!("OUT_DIR"), "/factory.rs"));
}
#[allow(clippy::all)]
mod pool {
    include!(concat!(env!("OUT_DIR"), "/pool.rs"));
}
#[allow(clippy::all)]
mod npm {
    include!(concat!(env!("OUT_DIR"), "/npm.rs"));
}
/// The generated ABI TOPIC_IDs are the single event signature source.
pub struct Decoder;
fn log(l: &eth::Log) -> substreams_ethereum::pb::eth::v2::Log {
    substreams_ethereum::pb::eth::v2::Log {
        address: l.address.clone(),
        topics: l.topics.clone(),
        data: l.data.clone(),
        index: l.index,
        block_index: l.block_index,
        ordinal: l.ordinal,
    }
}
impl EventDecoder for Decoder {
    fn matches(&self, source: p::DataSourceKind, l: &eth::Log) -> bool {
        let Some(topic) = l.topics.first() else {
            return false;
        };
        let topics: &[&[u8]] = match source {
            p::DataSourceKind::Factory => &[&factory::events::PoolCreated::TOPIC_ID],
            p::DataSourceKind::PositionManager => &[
                &npm::events::IncreaseLiquidity::TOPIC_ID,
                &npm::events::DecreaseLiquidity::TOPIC_ID,
                &npm::events::Collect::TOPIC_ID,
                &npm::events::Transfer::TOPIC_ID,
            ],
            p::DataSourceKind::Pool => &[
                &pool::events::Initialize::TOPIC_ID,
                &pool::events::Swap::TOPIC_ID,
                &pool::events::Mint::TOPIC_ID,
                &pool::events::Burn::TOPIC_ID,
                &pool::events::Flash::TOPIC_ID,
            ],
            _ => &[],
        };
        topics.contains(&topic.as_slice())
    }
    fn decoded(&self, source: p::DataSourceKind, l: &eth::Log) -> bool {
        let l = log(l);
        match source {
            p::DataSourceKind::Factory => {
                factory::events::PoolCreated::match_and_decode(&l).is_some()
            }
            p::DataSourceKind::PositionManager => {
                npm::events::IncreaseLiquidity::match_and_decode(&l).is_some()
                    || npm::events::DecreaseLiquidity::match_and_decode(&l).is_some()
                    || npm::events::Collect::match_and_decode(&l).is_some()
                    || npm::events::Transfer::match_and_decode(&l).is_some()
            }
            p::DataSourceKind::Pool => {
                pool::events::Initialize::match_and_decode(&l).is_some()
                    || pool::events::Swap::match_and_decode(&l).is_some()
                    || pool::events::Mint::match_and_decode(&l).is_some()
                    || pool::events::Burn::match_and_decode(&l).is_some()
                    || pool::events::Flash::match_and_decode(&l).is_some()
            }
            _ => false,
        }
    }
    fn pool_created(&self, l: &eth::Log) -> Option<i::PoolCreatedRecord> {
        let event = factory::events::PoolCreated::match_and_decode(log(l))?;
        Some(i::PoolCreatedRecord {
            pool: event.pool,
            token0: event.token0,
            token1: event.token1,
            tick_spacing: event.tick_spacing.to_string().parse().ok()?,
            ..Default::default()
        })
    }
}
struct Registry(StoreGetRaw);
impl PoolRegistry for Registry {
    fn pool(&self, address: &Address) -> Result<Option<i::PoolRecord>, String> {
        self.0
            .get_last(format!("p:{};", substreams::Hex(address)))
            .map(|v| {
                i::PoolRecord::decode(v.as_slice())
                    .map_err(|e| format!("corrupt pool registry: {e}"))
            })
            .transpose()
    }
}
#[substreams::handlers::map]
pub fn map_pools_created(
    params: String,
    block: eth::Block,
) -> Result<i::PoolsCreated, substreams::errors::Error> {
    let cfg = Config::parse(&params)?;
    Ok(candidates::pools_created(&cfg, &block, &Decoder))
}
#[substreams::handlers::map]
pub fn map_candidates(
    params: String,
    block: eth::Block,
    pools: StoreGetRaw,
) -> Result<p::ExtractorBlock, substreams::errors::Error> {
    let cfg = Config::parse(&params)?;
    candidates::build_candidates(&cfg, &block, &Registry(pools), &Decoder)
        .map_err(substreams::errors::Error::msg)
}

#[substreams::handlers::map]
pub fn map_storage_deltas(
    params: String,
    block: eth::Block,
    pools: StoreGetRaw,
) -> Result<i::StorageDeltas, substreams::errors::Error> {
    let cfg = Config::parse(&params)?;
    aerodrome_extractor_core::storage::storage_deltas(&cfg, &block, &Registry(pools))
        .map_err(substreams::errors::Error::msg)
}
