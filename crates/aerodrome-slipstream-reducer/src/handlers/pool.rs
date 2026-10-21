//! Mint/Burn preserve the deployed operation order, including interval reloads.
use super::*;
use crate::entity::{Bundle, Burn, Factory, Mint, Pool, Presence, Tick, Token};
use graph_numerics::{mapping, GraphDecimal as D};
use std::cell::RefCell;

thread_local! {
    // Pure arithmetic memoization. It contains no mapping/entity state.
    static TICK_POW: RefCell<mapping::TickPowTable> = RefCell::new(mapping::TickPowTable::default());
}

fn decimal_delta(a: &D, b: &D, mint: bool) -> MappingResult<D> {
    numeric(if mint { a.plus(b) } else { a.minus(b) })
}
fn integer_delta(a: &BigInt, b: &BigInt, mint: bool) -> MappingResult<BigInt> {
    numeric(if mint {
        bigint::plus(a, b)
    } else {
        bigint::minus(a, b)
    })
}

pub(super) fn liquidity<B: EntityBackend>(
    handler: &SupportedHandler<'_>,
    journal: &mut HandlerJournal<'_, B>,
    mint: bool,
) -> MappingResult<()> {
    let sites = if mint {
        [52, 54, 55, 57, 58]
    } else {
        [171, 173, 174, 176, 177]
    };
    let bundle: Bundle = required(
        journal,
        "1",
        &format!("src/mappings/core.ts:{}:16", sites[0]),
    )?;
    let pool_id = id(&crate::address(&handler.candidate().address)?);
    let mut pool: Pool = required(
        journal,
        &pool_id,
        &format!("src/mappings/core.ts:{}:14", sites[1]),
    )?;
    let mut factory: Factory = required(
        journal,
        FACTORY,
        &format!("src/mappings/core.ts:{}:17", sites[2]),
    )?;
    let mut token0: Token = required(
        journal,
        &pool.token0,
        &format!("src/mappings/core.ts:{}:16", sites[3]),
    )?;
    let mut token1: Token = required(
        journal,
        &pool.token1,
        &format!("src/mappings/core.ts:{}:16", sites[4]),
    )?;
    let amount0 = numeric(mapping::convert_token_to_decimal(
        &handler.integer("amount0")?,
        &token0.decimals,
    ))?;
    let amount1 = numeric(mapping::convert_token_to_decimal(
        &handler.integer("amount1")?,
        &token1.decimals,
    ))?;
    let amount_usd = numeric(
        numeric(amount0.times(&numeric(token0.derived_eth.times(&bundle.eth_price_usd))?))?.plus(
            &numeric(amount1.times(&numeric(token1.derived_eth.times(&bundle.eth_price_usd))?))?,
        ),
    )?;
    factory.total_value_locked_eth = numeric(
        factory
            .total_value_locked_eth
            .minus(&pool.total_value_locked_eth),
    )?;
    factory.tx_count = increment(&factory.tx_count)?;
    for (token, amount) in [(&mut token0, &amount0), (&mut token1, &amount1)] {
        token.tx_count = increment(&token.tx_count)?;
        token.total_value_locked = decimal_delta(&token.total_value_locked, amount, mint)?;
        token.total_value_locked_usd = numeric(
            token
                .total_value_locked
                .times(&numeric(token.derived_eth.times(&bundle.eth_price_usd))?),
        )?;
    }
    pool.tx_count = increment(&pool.tx_count)?;
    let amount = handler.integer("amount")?;
    // Preserve short-circuit conversions: a missing tick skips both bounds.
    if let Presence::Set(tick) = &pool.tick {
        if BigInt::from(mapping_i32(&handler.integer("tickLower")?)?) <= *tick
            && BigInt::from(mapping_i32(&handler.integer("tickUpper")?)?) > *tick
        {
            pool.liquidity = integer_delta(&pool.liquidity, &amount, mint)?;
        }
    }
    pool.total_value_locked_token0 =
        decimal_delta(&pool.total_value_locked_token0, &amount0, mint)?;
    pool.total_value_locked_token1 =
        decimal_delta(&pool.total_value_locked_token1, &amount1, mint)?;
    pool.total_value_locked_eth = numeric(
        numeric(pool.total_value_locked_token0.times(&token0.derived_eth))?.plus(&numeric(
            pool.total_value_locked_token1.times(&token1.derived_eth),
        )?),
    )?;
    pool.total_value_locked_usd =
        numeric(pool.total_value_locked_eth.times(&bundle.eth_price_usd))?;
    factory.total_value_locked_eth = numeric(
        factory
            .total_value_locked_eth
            .plus(&pool.total_value_locked_eth),
    )?;
    factory.total_value_locked_usd =
        numeric(factory.total_value_locked_eth.times(&bundle.eth_price_usd))?;
    let tx = transaction::load(handler, journal)?;
    let lower = mapping_i32(&handler.integer("tickLower")?)?;
    let upper = mapping_i32(&handler.integer("tickUpper")?)?;
    let event_id = format!("{}#{}", tx.id, pool.tx_count);
    let origin = handler.input.block().transactions[handler.candidate().tx as usize]
        .from
        .clone();
    let owner = handler.address("owner")?.to_vec();
    let mint_row = if mint {
        Some(Mint {
            id: event_id.clone(),
            transaction: tx.id.clone(),
            timestamp: tx.timestamp.clone(),
            pool: pool.id.clone(),
            token0: pool.token0.clone(),
            token1: pool.token1.clone(),
            owner: owner.clone(),
            sender: Presence::Set(handler.address("sender")?.to_vec()),
            origin: origin.clone(),
            amount: amount.clone(),
            amount0: amount0.clone(),
            amount1: amount1.clone(),
            amount_usd: Presence::Set(amount_usd.clone()),
            tick_lower: lower.into(),
            tick_upper: upper.into(),
            log_index: Presence::Set(handler.candidate().log_index.into()),
        })
    } else {
        None
    };
    let burn_row = if mint {
        None
    } else {
        Some(Burn {
            id: event_id,
            transaction: tx.id,
            timestamp: tx.timestamp,
            pool: pool.id.clone(),
            token0: pool.token0.clone(),
            token1: pool.token1.clone(),
            owner: Presence::Set(owner),
            origin,
            amount: amount.clone(),
            amount0,
            amount1,
            amount_usd: Presence::Set(amount_usd),
            tick_lower: lower.into(),
            tick_upper: upper.into(),
            log_index: Presence::Set(handler.candidate().log_index.into()),
        })
    };
    let lower_id = format!("{pool_id}#{lower}");
    let upper_id = format!("{pool_id}#{upper}");
    let (mut lo, mut hi) = if mint {
        // Both loads precede either construction.
        let lo = journal.load::<Tick>(&lower_id)?;
        let hi = journal.load::<Tick>(&upper_id)?;
        (
            match lo {
                Some(t) => t,
                None => create_tick(handler, lower_id, lower, &pool_id)?,
            },
            match hi {
                Some(t) => t,
                None => create_tick(handler, upper_id, upper, &pool_id)?,
            },
        )
    } else {
        (
            required::<_, Tick>(journal, &lower_id, "src/mappings/core.ts:245:19")?,
            required::<_, Tick>(journal, &upper_id, "src/mappings/core.ts:246:19")?,
        )
    };
    lo.liquidity_gross = integer_delta(&lo.liquidity_gross, &amount, mint)?;
    lo.liquidity_net = integer_delta(&lo.liquidity_net, &amount, mint)?;
    hi.liquidity_gross = integer_delta(&hi.liquidity_gross, &amount, mint)?;
    hi.liquidity_net = integer_delta(&hi.liquidity_net, &amount, !mint)?;
    let timestamp = mapping_i32(&handler.input.block().timestamp.into())?;
    interval::uniswap_day(journal, timestamp)?;
    interval::pool_day(journal, &pool_id, timestamp)?;
    interval::pool_hour(journal, &pool_id, timestamp)?;
    interval::token_day(journal, &token0, timestamp)?;
    interval::token_day(journal, &token1, timestamp)?;
    interval::token_hour(journal, &token0, timestamp)?;
    interval::token_hour(journal, &token1, timestamp)?;
    if !mint {
        update_tick(handler, journal, &mut lo)?;
        update_tick(handler, journal, &mut hi)?;
    }
    journal.save(&token0)?;
    journal.save(&token1)?;
    journal.save(&pool)?;
    journal.save(&factory)?;
    if let Some(row) = mint_row {
        journal.save(&row)?;
    }
    if let Some(row) = burn_row {
        journal.save(&row)?;
    }
    if mint {
        update_tick(handler, journal, &mut lo)?;
        update_tick(handler, journal, &mut hi)?;
    }
    Ok(())
}

fn create_tick(
    handler: &SupportedHandler<'_>,
    id: String,
    tick: i32,
    pool: &str,
) -> MappingResult<Tick> {
    let price0 = TICK_POW.with(|pow| numeric(pow.borrow_mut().price(tick)))?;
    let price1 = numeric(mapping::safe_div(&D::one(), &price0))?;
    Ok(Tick {
        id,
        tick_idx: tick.into(),
        pool: pool.into(),
        pool_address: if pool.is_empty() {
            Presence::Null
        } else {
            Presence::Set(pool.into())
        },
        created_at_block_number: handler.input.block().number.into(),
        created_at_timestamp: handler.input.block().timestamp.into(),
        liquidity_gross: 0.into(),
        liquidity_net: 0.into(),
        liquidity_provider_count: 0.into(),
        price0,
        price1,
        volume_token0: D::zero(),
        volume_token1: D::zero(),
        volume_usd: D::zero(),
        fees_usd: D::zero(),
        untracked_volume_usd: D::zero(),
        collected_fees_token0: D::zero(),
        collected_fees_token1: D::zero(),
        collected_fees_usd: D::zero(),
        fee_growth_outside0_x128: 0.into(),
        fee_growth_outside1_x128: 0.into(),
    })
}

fn update_tick<B: EntityBackend>(
    handler: &SupportedHandler<'_>,
    journal: &mut HandlerJournal<'_, B>,
    tick: &mut Tick,
) -> MappingResult<()> {
    let answer = handler.input.calls().tick(
        &crate::address(&handler.candidate().address)?,
        mapping_i32(&tick.tick_idx)?,
    )?;
    // The deployed Pool ABI indexes are intentionally mismatched to Slipstream.
    tick.fee_growth_outside0_x128 = BigInt::from_signed_bytes_be(&answer.staked_liquidity_net);
    let mut positive = vec![0];
    positive.extend_from_slice(&answer.fee_growth_outside0_x128);
    tick.fee_growth_outside1_x128 = BigInt::from_signed_bytes_be(&positive);
    journal.save(tick)?;
    interval::tick_day(
        journal,
        tick,
        mapping_i32(&handler.input.block().timestamp.into())?,
    )
}
