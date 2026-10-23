//! The two pricing helpers called by Initialize, transcribed from Pool.wasm.
//! There is no stablecoin shortcut. Comparisons are strict, and counterpart
//! derivedETH comes from store.load, never the other unsaved handler object.
use super::*;
use crate::entity::{Pool, Token};
use graph_numerics::GraphDecimal as D;
fn threshold() -> D {
    D::host_from_string("0.01").expect("deployed constant")
}
pub(super) fn eth_price<B: EntityBackend>(journal: &mut HandlerJournal<'_, B>) -> MappingResult<D> {
    Ok(match journal.load::<Pool>(ETH_USD_POOL)? {
        Some(pool) => {
            if decimal_compare(&pool.total_value_locked_token0, &threshold())?.is_gt() {
                pool.token1_price
            } else {
                D::zero()
            }
        }
        _ => D::zero(),
    })
}
pub(super) fn derived_eth<B: EntityBackend>(
    journal: &mut HandlerJournal<'_, B>,
    token: &Token,
    other: &Token,
) -> MappingResult<D> {
    if token.id == WETH {
        return Ok(D::one());
    }
    let mut largest = D::zero();
    let mut price = D::zero();
    for pool_id in &token.whitelist_pools {
        let pool: Pool = required(journal, pool_id, "src/utils/pricing.ts:73:16")?;
        if pool.liquidity <= BigInt::from(0) {
            continue;
        }
        if pool.token0 == token.id
            && !(pool.token1 == other.id && WHITELIST.contains(&pool.token0.as_str()))
        {
            let counterpart: Token = required(journal, &pool.token1, "src/utils/pricing.ts:77:22")?;
            let locked = numeric(
                pool.total_value_locked_token1
                    .times(&counterpart.derived_eth),
            )?;
            if decimal_compare(&locked, &largest)?.is_gt()
                && decimal_compare(&locked, &threshold())?.is_gt()
            {
                price = numeric(pool.token1_price.times(&counterpart.derived_eth))?;
                largest = locked;
            }
        }
        if pool.token1 == token.id
            && !(pool.token0 == other.id && WHITELIST.contains(&pool.token1.as_str()))
        {
            let counterpart: Token = required(journal, &pool.token0, "src/utils/pricing.ts:87:22")?;
            let locked = numeric(
                pool.total_value_locked_token0
                    .times(&counterpart.derived_eth),
            )?;
            if decimal_compare(&locked, &largest)?.is_gt()
                && decimal_compare(&locked, &threshold())?.is_gt()
            {
                price = numeric(pool.token0_price.times(&counterpart.derived_eth))?;
                largest = locked;
            }
        }
    }
    Ok(price)
}
