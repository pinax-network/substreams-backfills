use super::*;
use crate::{
    calls::token_metadata,
    entity::{Bundle, Factory, Pool, Presence, Token},
    hosts::FACTORY_EXCLUDED_POOL,
};
use graph_numerics::GraphDecimal as D;

pub(super) fn pool_created<B: EntityBackend>(
    handler: &SupportedHandler<'_>,
    journal: &mut HandlerJournal<'_, B>,
) -> MappingResult<Option<Address>> {
    let pool_address = handler.address("pool")?;
    // Deployed hotfix returns before any store access, metadata calls or source.
    if hex::encode(pool_address) == FACTORY_EXCLUDED_POOL {
        return Ok(None);
    }
    let pool_id = id(&pool_address);
    let mut factory = match journal.load::<Factory>(FACTORY)? {
        Some(factory) => factory,
        None => {
            journal.save(&Bundle {
                id: "1".into(),
                eth_price_usd: D::zero(),
            })?;
            Factory {
                id: FACTORY.into(),
                owner: "0x0000000000000000000000000000000000000000".into(),
                pool_count: 0.into(),
                tx_count: 0.into(),
                total_fees_eth: D::zero(),
                total_fees_usd: D::zero(),
                total_value_locked_eth: D::zero(),
                total_value_locked_eth_untracked: D::zero(),
                total_value_locked_usd: D::zero(),
                total_value_locked_usd_untracked: D::zero(),
                total_volume_eth: D::zero(),
                total_volume_usd: D::zero(),
                untracked_volume_usd: D::zero(),
            }
        }
    };
    factory.pool_count = increment(&factory.pool_count)?;
    let a = handler.address("token0")?;
    let b = handler.address("token1")?;
    // Both loads precede either construction/save in the deployed mapping.
    let token0 = journal.load::<Token>(&id(&a))?;
    let token1 = journal.load::<Token>(&id(&b))?;
    let mut token0 = match token0 {
        Some(t) => t,
        None => new_token(handler, &a)?,
    };
    let mut token1 = match token1 {
        Some(t) => t,
        None => new_token(handler, &b)?,
    };
    if WHITELIST.contains(&token0.id.as_str()) {
        token1.whitelist_pools.push(pool_id.clone());
    }
    if WHITELIST.contains(&token1.id.as_str()) {
        token0.whitelist_pools.push(pool_id.clone());
    }
    let spacing = mapping_i32(&handler.integer("tickSpacing")?)?;
    let fee = match spacing {
        1 => 100,
        50 | 100 => 500,
        200 => 3000,
        _ => 10000,
    };
    let block = handler.input.block();
    let pool = Pool {
        id: pool_id,
        token0: token0.id.clone(),
        token1: token1.id.clone(),
        fee_tier: fee.into(),
        created_at_timestamp: block.timestamp.into(),
        created_at_block_number: block.number.into(),
        liquidity: 0.into(),
        sqrt_price: 0.into(),
        tick: Presence::Absent,
        fee_growth_global0_x128: 0.into(),
        fee_growth_global1_x128: 0.into(),
        observation_index: 0.into(),
        liquidity_provider_count: 0.into(),
        tx_count: 0.into(),
        token0_price: D::zero(),
        token1_price: D::zero(),
        volume_token0: D::zero(),
        volume_token1: D::zero(),
        volume_usd: D::zero(),
        untracked_volume_usd: D::zero(),
        fees_usd: D::zero(),
        collected_fees_token0: D::zero(),
        collected_fees_token1: D::zero(),
        collected_fees_usd: D::zero(),
        total_value_locked_token0: D::zero(),
        total_value_locked_token1: D::zero(),
        total_value_locked_eth: D::zero(),
        total_value_locked_usd: D::zero(),
        total_value_locked_usd_untracked: D::zero(),
    };
    journal.save(&pool)?;
    let created = journal.create_pool_source(pool_address)?;
    journal.save(&token0)?;
    journal.save(&token1)?;
    journal.save(&factory)?;
    Ok(created.then_some(pool_address))
}
fn new_token(handler: &SupportedHandler<'_>, address: &Address) -> MappingResult<Token> {
    let metadata = token_metadata(handler.input.calls().erc20(address)?)?;
    Ok(Token {
        id: id(address),
        symbol: metadata.symbol,
        name: metadata.name,
        total_supply: metadata.total_supply,
        decimals: metadata.decimals.into(),
        derived_eth: D::zero(),
        fees_usd: D::zero(),
        pool_count: 0.into(),
        tx_count: 0.into(),
        total_value_locked: D::zero(),
        total_value_locked_usd: D::zero(),
        total_value_locked_usd_untracked: D::zero(),
        untracked_volume_usd: D::zero(),
        version: Presence::Absent,
        volume: D::zero(),
        volume_usd: D::zero(),
        whitelist_pools: vec![],
    })
}
