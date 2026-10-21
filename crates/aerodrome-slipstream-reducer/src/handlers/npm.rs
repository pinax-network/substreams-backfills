//! Deployed NPM order and guards. Position construction saves a Transaction but
//! does not save Position; snapshot saves Transaction again before Snapshot.
use super::*;
use crate::entity::{Position, PositionSnapshot, Token};
use crate::hosts::FACTORY_EXCLUDED_POOL;
use graph_numerics::{mapping::convert_token_to_decimal, GraphDecimal as D};

pub(super) fn run<B: EntityBackend>(
    handler: &SupportedHandler<'_>,
    journal: &mut HandlerJournal<'_, B>,
) -> MappingResult<()> {
    let name = handler.event.name.as_str();
    if matches!(name, "IncreaseLiquidity" | "DecreaseLiquidity")
        && handler.input.block().number == 14_317_993
    {
        return Ok(());
    }
    let token_id = handler.word_parameter("tokenId")?;
    let Some(mut position) = get_position(handler, journal, &token_id)? else {
        return Ok(());
    };
    if name == "Transfer" {
        // Transfer has neither the historical block guard nor the pool guard,
        // and does not refresh fee growth for an existing Position.
        position.owner = handler.address("to")?.to_vec();
    } else {
        let pool = hex::decode(
            position
                .pool
                .strip_prefix("0x")
                .ok_or_else(|| refuse("invalid Position.pool address"))?,
        )
        .map_err(|_| refuse("invalid Position.pool hex"))?;
        let pool = crate::address(&pool)?;
        if hex::encode(pool) == FACTORY_EXCLUDED_POOL {
            return Ok(());
        }
        let (site0, site1) = match name {
            "IncreaseLiquidity" => (
                "src/mappings/position-manager.ts:102:16",
                "src/mappings/position-manager.ts:103:16",
            ),
            "DecreaseLiquidity" => (
                "src/mappings/position-manager.ts:137:16",
                "src/mappings/position-manager.ts:138:16",
            ),
            "Collect" => (
                "src/mappings/position-manager.ts:164:16",
                "src/mappings/position-manager.ts:165:16",
            ),
            _ => unreachable!("matched NPM handler"),
        };
        let token0: Token = required(journal, &position.token0, site0)?;
        let token1: Token = required(journal, &position.token1, site1)?;
        let amount0 = numeric(convert_token_to_decimal(
            &handler.integer("amount0")?,
            &token0.decimals,
        ))?;
        let amount1 = numeric(convert_token_to_decimal(
            &handler.integer("amount1")?,
            &token1.decimals,
        ))?;
        match name {
            "IncreaseLiquidity" => {
                position.liquidity = numeric(bigint::plus(
                    &position.liquidity,
                    &handler.integer("liquidity")?,
                ))?;
                position.deposited_token0 = numeric(position.deposited_token0.plus(&amount0))?;
                position.deposited_token1 = numeric(position.deposited_token1.plus(&amount1))?;
            }
            "DecreaseLiquidity" => {
                position.liquidity = numeric(bigint::minus(
                    &position.liquidity,
                    &handler.integer("liquidity")?,
                ))?;
                position.withdrawn_token0 = numeric(position.withdrawn_token0.plus(&amount0))?;
                position.withdrawn_token1 = numeric(position.withdrawn_token1.plus(&amount1))?;
            }
            "Collect" => {
                position.collected_token0 = numeric(position.collected_token0.plus(&amount0))?;
                position.collected_token1 = numeric(position.collected_token1.plus(&amount1))?;
                position.collected_fees_token0 =
                    numeric(position.collected_token0.minus(&position.withdrawn_token0))?;
                position.collected_fees_token1 =
                    numeric(position.collected_token1.minus(&position.withdrawn_token1))?;
            }
            _ => unreachable!(),
        }
        if let Some(answer) = position_answer(handler, &token_id)? {
            position.fee_growth_inside0_last_x128 =
                unsigned_integer(&answer.fee_growth_inside0_last_x128);
            position.fee_growth_inside1_last_x128 =
                unsigned_integer(&answer.fee_growth_inside1_last_x128);
        }
    }
    journal.save(&position)?;
    snapshot(handler, journal, &position)
}
fn position_answer<'a>(
    handler: &'a SupportedHandler<'_>,
    token_id: &crate::Word,
) -> MappingResult<Option<&'a pb::PositionValue>> {
    Ok(
        match handler
            .input
            .calls()
            .position(token_id)?
            .result
            .as_ref()
            .expect("validated answer")
        {
            pb::position_answer::Result::Value(value) => Some(value),
            pb::position_answer::Result::Reverted(_) => None,
        },
    )
}
fn get_position<B: EntityBackend>(
    handler: &SupportedHandler<'_>,
    journal: &mut HandlerJournal<'_, B>,
    token_id: &crate::Word,
) -> MappingResult<Option<Position>> {
    let id = unsigned_integer(token_id).to_string();
    if let Some(position) = journal.load::<Position>(&id)? {
        return Ok(Some(position));
    }
    let Some(answer) = position_answer(handler, token_id)? else {
        return Ok(None);
    };
    let token0 = crate::address(&answer.token0)?;
    let token1 = crate::address(&answer.token1)?;
    let pool = handler
        .input
        .calls()
        .pool(&token0, &token1, answer.tick_spacing)?;
    let pool = id_address(&pool.pool)?;
    let tx = transaction::load(handler, journal)?;
    Ok(Some(Position {
        id,
        owner: vec![0; 20],
        pool: pool.clone(),
        token0: super::id(&token0),
        token1: super::id(&token1),
        tick_lower: format!("{pool}#{}", answer.tick_lower),
        tick_upper: format!("{pool}#{}", answer.tick_upper),
        liquidity: 0.into(),
        deposited_token0: D::zero(),
        deposited_token1: D::zero(),
        withdrawn_token0: D::zero(),
        withdrawn_token1: D::zero(),
        collected_token0: D::zero(),
        collected_token1: D::zero(),
        collected_fees_token0: D::zero(),
        collected_fees_token1: D::zero(),
        transaction: tx.id,
        fee_growth_inside0_last_x128: unsigned_integer(&answer.fee_growth_inside0_last_x128),
        fee_growth_inside1_last_x128: unsigned_integer(&answer.fee_growth_inside1_last_x128),
    }))
}
fn id_address(bytes: &[u8]) -> Result<String> {
    Ok(id(&crate::address(bytes)?))
}
fn snapshot<B: EntityBackend>(
    handler: &SupportedHandler<'_>,
    journal: &mut HandlerJournal<'_, B>,
    p: &Position,
) -> MappingResult<()> {
    let tx = transaction::load(handler, journal)?;
    journal.save(&PositionSnapshot {
        id: format!("{}#{}", p.id, handler.input.block().number),
        owner: p.owner.clone(),
        pool: p.pool.clone(),
        position: p.id.clone(),
        block_number: handler.input.block().number.into(),
        timestamp: handler.input.block().timestamp.into(),
        liquidity: p.liquidity.clone(),
        deposited_token0: p.deposited_token0.clone(),
        deposited_token1: p.deposited_token1.clone(),
        withdrawn_token0: p.withdrawn_token0.clone(),
        withdrawn_token1: p.withdrawn_token1.clone(),
        collected_fees_token0: p.collected_fees_token0.clone(),
        collected_fees_token1: p.collected_fees_token1.clone(),
        transaction: tx.id,
        fee_growth_inside0_last_x128: p.fee_growth_inside0_last_x128.clone(),
        fee_growth_inside1_last_x128: p.fee_growth_inside1_last_x128.clone(),
    })?;
    Ok(())
}
