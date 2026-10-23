use super::*;
use crate::entity::{Bundle, Pool, Presence, Token};

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
    interval::pool_day(journal, &pool_id, timestamp)?;
    interval::pool_hour(journal, &pool_id, timestamp)?;
    token0.derived_eth = pricing::derived_eth(journal, &token0, &token1)?;
    token1.derived_eth = pricing::derived_eth(journal, &token1, &token0)?;
    journal.save(&token0)?;
    journal.save(&token1)?;
    Ok(())
}
