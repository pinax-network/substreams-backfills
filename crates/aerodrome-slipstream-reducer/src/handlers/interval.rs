//! Deployed interval updates. Pool/Factory are reloaded; Tokens use owned handler values.
use super::*;
use crate::entity::{
    Bundle, Factory, Pool, PoolDayData, PoolHourData, Presence, Tick, TickDayData, Token,
    TokenDayData, TokenHourData, UniswapDayData,
};
use graph_numerics::GraphDecimal as D;

pub(super) fn uniswap_day<B: EntityBackend>(
    journal: &mut HandlerJournal<'_, B>,
    timestamp: i32,
) -> MappingResult<UniswapDayData> {
    let day = timestamp / 86400;
    let factory: Factory = required(journal, FACTORY, "src/utils/intervalUpdates.ts:24:17")?;
    let mut data = journal
        .load::<UniswapDayData>(&day.to_string())?
        .unwrap_or_else(|| UniswapDayData {
            id: day.to_string(),
            date: day.wrapping_mul(86400),
            volume_eth: D::zero(),
            volume_usd: D::zero(),
            volume_usd_untracked: D::zero(),
            fees_usd: D::zero(),
            tvl_usd: D::zero(),
            tx_count: 0.into(),
        });
    data.tvl_usd = factory.total_value_locked_usd;
    data.tx_count = factory.tx_count;
    journal.save(&data)?;
    Ok(data)
}

pub(super) fn token_day<B: EntityBackend>(
    journal: &mut HandlerJournal<'_, B>,
    token: &Token,
    timestamp: i32,
) -> MappingResult<TokenDayData> {
    let day = timestamp / 86400;
    let bundle: Bundle = required(journal, "1", "src/utils/intervalUpdates.ts:144:16")?;
    let price = numeric(token.derived_eth.times(&bundle.eth_price_usd))?;
    let id = format!("{}-{day}", token.id);
    let mut data = journal
        .load::<TokenDayData>(&id)?
        .unwrap_or_else(|| TokenDayData {
            id,
            date: day.wrapping_mul(86400),
            token: token.id.clone(),
            open: price.clone(),
            high: price.clone(),
            low: price.clone(),
            close: price.clone(),
            volume: D::zero(),
            volume_usd: D::zero(),
            untracked_volume_usd: D::zero(),
            fees_usd: D::zero(),
            price_usd: D::zero(),
            total_value_locked: D::zero(),
            total_value_locked_usd: D::zero(),
        });
    if decimal_compare(&price, &data.high)?.is_gt() {
        data.high = price.clone();
    }
    if decimal_compare(&price, &data.low)?.is_lt() {
        data.low = price.clone();
    }
    data.close = price;
    data.price_usd = numeric(token.derived_eth.times(&bundle.eth_price_usd))?;
    data.total_value_locked = token.total_value_locked.clone();
    data.total_value_locked_usd = token.total_value_locked_usd.clone();
    journal.save(&data)?;
    Ok(data)
}

pub(super) fn token_hour<B: EntityBackend>(
    journal: &mut HandlerJournal<'_, B>,
    token: &Token,
    timestamp: i32,
) -> MappingResult<TokenHourData> {
    let hour = timestamp / 3600;
    let bundle: Bundle = required(journal, "1", "src/utils/intervalUpdates.ts:187:16")?;
    let price = numeric(token.derived_eth.times(&bundle.eth_price_usd))?;
    let id = format!("{}-{hour}", token.id);
    let mut data = journal
        .load::<TokenHourData>(&id)?
        .unwrap_or_else(|| TokenHourData {
            id,
            period_start_unix: hour.wrapping_mul(3600),
            token: token.id.clone(),
            open: price.clone(),
            high: price.clone(),
            low: price.clone(),
            close: price.clone(),
            volume: D::zero(),
            volume_usd: D::zero(),
            untracked_volume_usd: D::zero(),
            fees_usd: D::zero(),
            price_usd: D::zero(),
            total_value_locked: D::zero(),
            total_value_locked_usd: D::zero(),
        });
    if decimal_compare(&price, &data.high)?.is_gt() {
        data.high = price.clone();
    }
    if decimal_compare(&price, &data.low)?.is_lt() {
        data.low = price.clone();
    }
    data.close = price;
    data.price_usd = numeric(token.derived_eth.times(&bundle.eth_price_usd))?;
    data.total_value_locked = token.total_value_locked.clone();
    data.total_value_locked_usd = token.total_value_locked_usd.clone();
    journal.save(&data)?;
    Ok(data)
}

pub(super) fn tick_day<B: EntityBackend>(
    journal: &mut HandlerJournal<'_, B>,
    tick: &Tick,
    timestamp: i32,
) -> MappingResult<()> {
    let day = timestamp / 86400;
    let id = format!("{}-{day}", tick.id);
    let mut data = journal
        .load::<TickDayData>(&id)?
        .unwrap_or_else(|| TickDayData {
            id,
            date: day.wrapping_mul(86400),
            pool: tick.pool.clone(),
            tick: tick.id.clone(),
            liquidity_gross: 0.into(),
            liquidity_net: 0.into(),
            fee_growth_outside0_x128: 0.into(),
            fee_growth_outside1_x128: 0.into(),
            volume_token0: D::zero(),
            volume_token1: D::zero(),
            volume_usd: D::zero(),
            fees_usd: D::zero(),
        });
    data.liquidity_gross = tick.liquidity_gross.clone();
    data.liquidity_net = tick.liquidity_net.clone();
    data.volume_token0 = tick.volume_token0.clone();
    // Deployed mapping copies token0 volume into both fields.
    data.volume_token1 = tick.volume_token0.clone();
    data.volume_usd = tick.volume_usd.clone();
    data.fees_usd = tick.fees_usd.clone();
    data.fee_growth_outside0_x128 = tick.fee_growth_outside0_x128.clone();
    data.fee_growth_outside1_x128 = tick.fee_growth_outside1_x128.clone();
    journal.save(&data)?;
    Ok(())
}

fn copied_tick(tick: &Presence<BigInt>) -> Presence<BigInt> {
    match tick {
        Presence::Set(v) => Presence::Set(v.clone()),
        _ => Presence::Null,
    }
}
pub(super) fn pool_day<B: EntityBackend>(
    journal: &mut HandlerJournal<'_, B>,
    pool_id: &str,
    timestamp: i32,
) -> MappingResult<PoolDayData> {
    let day = timestamp / 86400;
    let id = format!("{pool_id}-{day}");
    let pool: Pool = required(journal, pool_id, "src/utils/intervalUpdates.ts:51:14")?;
    let mut data = journal
        .load::<PoolDayData>(&id)?
        .unwrap_or_else(|| PoolDayData {
            id,
            date: day.wrapping_mul(86400),
            pool: pool.id.clone(),
            open: pool.token0_price.clone(),
            high: pool.token0_price.clone(),
            low: pool.token0_price.clone(),
            close: pool.token0_price.clone(),
            volume_token0: D::zero(),
            volume_token1: D::zero(),
            volume_usd: D::zero(),
            fees_usd: D::zero(),
            tx_count: 0.into(),
            fee_growth_global0_x128: 0.into(),
            fee_growth_global1_x128: 0.into(),
            liquidity: 0.into(),
            sqrt_price: 0.into(),
            tick: Presence::Absent,
            token0_price: D::zero(),
            token1_price: D::zero(),
            tvl_usd: D::zero(),
        });
    if decimal_compare(&pool.token0_price, &data.high)?.is_gt() {
        data.high = pool.token0_price.clone();
    }
    if decimal_compare(&pool.token0_price, &data.low)?.is_lt() {
        data.low = pool.token0_price.clone();
    }
    data.liquidity = pool.liquidity;
    data.sqrt_price = pool.sqrt_price;
    data.fee_growth_global0_x128 = pool.fee_growth_global0_x128;
    data.fee_growth_global1_x128 = pool.fee_growth_global1_x128;
    data.token0_price = pool.token0_price;
    data.token1_price = pool.token1_price;
    data.tick = copied_tick(&pool.tick);
    data.tvl_usd = pool.total_value_locked_usd;
    data.tx_count = increment(&data.tx_count)?;
    // Deployed day updater deliberately never refreshes close.
    journal.save(&data)?;
    Ok(data)
}
pub(super) fn pool_hour<B: EntityBackend>(
    journal: &mut HandlerJournal<'_, B>,
    pool_id: &str,
    timestamp: i32,
) -> MappingResult<PoolHourData> {
    let hour = timestamp / 3600;
    let id = format!("{pool_id}-{hour}");
    let pool: Pool = required(journal, pool_id, "src/utils/intervalUpdates.ts:100:14")?;
    let mut data = journal
        .load::<PoolHourData>(&id)?
        .unwrap_or_else(|| PoolHourData {
            id,
            period_start_unix: hour.wrapping_mul(3600),
            pool: pool.id.clone(),
            open: pool.token0_price.clone(),
            high: pool.token0_price.clone(),
            low: pool.token0_price.clone(),
            close: pool.token0_price.clone(),
            volume_token0: D::zero(),
            volume_token1: D::zero(),
            volume_usd: D::zero(),
            fees_usd: D::zero(),
            tx_count: 0.into(),
            fee_growth_global0_x128: 0.into(),
            fee_growth_global1_x128: 0.into(),
            liquidity: 0.into(),
            sqrt_price: 0.into(),
            tick: Presence::Absent,
            token0_price: D::zero(),
            token1_price: D::zero(),
            tvl_usd: D::zero(),
        });
    if decimal_compare(&pool.token0_price, &data.high)?.is_gt() {
        data.high = pool.token0_price.clone();
    }
    if decimal_compare(&pool.token0_price, &data.low)?.is_lt() {
        data.low = pool.token0_price.clone();
    }
    data.liquidity = pool.liquidity;
    data.sqrt_price = pool.sqrt_price;
    data.fee_growth_global0_x128 = pool.fee_growth_global0_x128;
    data.fee_growth_global1_x128 = pool.fee_growth_global1_x128;
    data.close = pool.token0_price.clone();
    data.token0_price = pool.token0_price;
    data.token1_price = pool.token1_price;
    data.tick = copied_tick(&pool.tick);
    data.tvl_usd = pool.total_value_locked_usd;
    data.tx_count = increment(&data.tx_count)?;
    journal.save(&data)?;
    Ok(data)
}
