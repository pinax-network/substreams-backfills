use super::*;
use crate::entity::{Bundle, Pool, PoolDayData, PoolHourData, Presence, Token};
use graph_numerics::GraphDecimal as D;

pub(super) fn initialize<B: EntityBackend>(
    handler: &SupportedHandler<'_>,
    journal: &mut HandlerJournal<'_, B>,
) -> MappingResult<()> {
    let pool_id = id(&crate::address(&handler.candidate().address)?);
    let mut pool: Pool = required(journal, &pool_id, "src/mappings/core.ts:27:14")?;
    pool.sqrt_price = handler.integer("sqrtPriceX96")?;
    pool.tick = Presence::Set(mapping_i32(&handler.integer("tick")?)?.into());
    journal.save(&pool)?;
    let mut token0: Token = required(journal, &pool.token0, "src/mappings/core.ts:33:16")?;
    let mut token1: Token = required(journal, &pool.token1, "src/mappings/core.ts:34:16")?;
    let mut bundle: Bundle = required(journal, "1", "src/mappings/core.ts:37:16")?;
    bundle.eth_price_usd = pricing::eth_price(journal)?;
    journal.save(&bundle)?;
    let timestamp = mapping_i32(&handler.input.block().timestamp.into())?;
    update_day(journal, &pool_id, timestamp)?;
    update_hour(journal, &pool_id, timestamp)?;
    token0.derived_eth = pricing::derived_eth(journal, &token0, &token1)?;
    token1.derived_eth = pricing::derived_eth(journal, &token1, &token0)?;
    journal.save(&token0)?;
    journal.save(&token1)?;
    Ok(())
}
fn copied_tick(tick: &Presence<BigInt>) -> Presence<BigInt> {
    match tick {
        Presence::Set(v) => Presence::Set(v.clone()),
        _ => Presence::Null,
    }
}
fn update_day<B: EntityBackend>(
    journal: &mut HandlerJournal<'_, B>,
    pool_id: &str,
    timestamp: i32,
) -> MappingResult<()> {
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
    Ok(())
}
fn update_hour<B: EntityBackend>(
    journal: &mut HandlerJournal<'_, B>,
    pool_id: &str,
    timestamp: i32,
) -> MappingResult<()> {
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
    Ok(())
}
