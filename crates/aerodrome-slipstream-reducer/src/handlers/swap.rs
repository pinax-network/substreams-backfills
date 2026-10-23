//! Deployed Swap order, including the first Pool save and repeated tick updates.
use super::*;
use crate::entity::{Bundle, Factory, Pool, Presence, Swap, Tick, Token};
use graph_numerics::{mapping, GraphDecimal as D};

fn constant(value: &str) -> D {
    D::host_from_string(value).expect("deployed decimal constant")
}
fn absolute(value: &D) -> MappingResult<D> {
    if decimal_compare(value, &D::zero())?.is_lt() {
        numeric(value.times(&constant("-1")))
    } else {
        Ok(value.clone())
    }
}
fn tracked_usd<B: EntityBackend>(
    journal: &mut HandlerJournal<'_, B>,
    amount0: &D,
    token0: &Token,
    amount1: &D,
    token1: &Token,
) -> MappingResult<D> {
    let bundle: Bundle = required(journal, "1", "src/utils/pricing.ts:113:16")?;
    // This multiplication order differs from untracked volume calculation.
    let price0 = numeric(token0.derived_eth.times(&bundle.eth_price_usd))?;
    let price1 = numeric(token1.derived_eth.times(&bundle.eth_price_usd))?;
    match (
        WHITELIST.contains(&token0.id.as_str()),
        WHITELIST.contains(&token1.id.as_str()),
    ) {
        (true, true) => {
            numeric(numeric(amount0.times(&price0))?.plus(&numeric(amount1.times(&price1))?))
        }
        (true, false) => numeric(numeric(amount0.times(&price0))?.times(&constant("2"))),
        (false, true) => numeric(numeric(amount1.times(&price1))?.times(&constant("2"))),
        (false, false) => Ok(D::zero()),
    }
}

pub(super) fn swap<B: EntityBackend>(
    handler: &SupportedHandler<'_>,
    journal: &mut HandlerJournal<'_, B>,
) -> MappingResult<()> {
    let mut bundle: Bundle = required(journal, "1", "src/mappings/core.ts:271:16")?;
    let mut factory: Factory = required(journal, FACTORY, "src/mappings/core.ts:272:17")?;
    let address = crate::address(&handler.candidate().address)?;
    let mut pool: Pool = required(journal, &id(&address), "src/mappings/core.ts:273:14")?;
    if pool.id == "0x9663f2ca0454accad3e094448ea6f774438804" {
        return Ok(());
    }
    let mut token0: Token = required(journal, &pool.token0, "src/mappings/core.ts:280:16")?;
    let mut token1: Token = required(journal, &pool.token1, "src/mappings/core.ts:281:16")?;
    for token in [&mut token0, &mut token1] {
        if matches!(
            token.version,
            Presence::Absent | Presence::Null | Presence::Set(0)
        ) {
            token.version = Presence::Set(2);
            // addMissingWhitelistedPools pushes into a discarded getter copy.
            // Its host calls still need complete extraction evidence. The
            // public mapping getter is represented by a checked address answer;
            // a missing answer remains fatal even though no push is persisted.
            let token_address = crate::address(
                &hex::decode(
                    token
                        .id
                        .strip_prefix("0x")
                        .ok_or_else(|| refuse("token ID lacks address prefix"))?,
                )
                .map_err(|_| refuse("invalid token address"))?,
            )?;
            let usdc = crate::address(&hex::decode(&USDC[2..]).expect("constant address"))?;
            if token_address != usdc {
                for spacing in [100, 500, 3000, 10000] {
                    handler.input.calls().pool(&usdc, &token_address, spacing)?;
                }
            }
        }
    }
    let old_tick = match &pool.tick {
        Presence::Set(tick) => tick.clone(),
        _ => {
            return Err(Step::Abort(Abort {
                message: "unexpected null at src/mappings/core.ts:297:17".into(),
            }))
        }
    };
    let amount0 = numeric(mapping::convert_token_to_decimal(
        &handler.integer("amount0")?,
        &token0.decimals,
    ))?;
    let amount1 = numeric(mapping::convert_token_to_decimal(
        &handler.integer("amount1")?,
        &token1.decimals,
    ))?;
    let abs0 = absolute(&amount0)?;
    let abs1 = absolute(&amount1)?;
    let eth0 = numeric(abs0.times(&token0.derived_eth))?;
    let eth1 = numeric(abs1.times(&token1.derived_eth))?;
    let usd0 = numeric(eth0.times(&bundle.eth_price_usd))?;
    let usd1 = numeric(eth1.times(&bundle.eth_price_usd))?;
    let tracked =
        numeric(tracked_usd(journal, &abs0, &token0, &abs1, &token1)?.divided_by(&constant("2")))?;
    let tracked_eth = if decimal_compare(&bundle.eth_price_usd, &D::zero())?.is_eq() {
        D::zero()
    } else {
        numeric(tracked.divided_by(&bundle.eth_price_usd))?
    };
    let untracked = numeric(numeric(usd0.plus(&usd1))?.divided_by(&constant("2")))?;
    let fee = numeric(D::from_bigint(&pool.fee_tier))?;
    let fees_eth = numeric(numeric(tracked_eth.times(&fee))?.divided_by(&constant("1000000")))?;
    let fees_usd = numeric(numeric(tracked.times(&fee))?.divided_by(&constant("1000000")))?;
    factory.tx_count = increment(&factory.tx_count)?;
    factory.total_volume_eth = numeric(factory.total_volume_eth.plus(&tracked_eth))?;
    factory.total_volume_usd = numeric(factory.total_volume_usd.plus(&tracked))?;
    factory.untracked_volume_usd = numeric(factory.untracked_volume_usd.plus(&untracked))?;
    factory.total_fees_eth = numeric(factory.total_fees_eth.plus(&fees_eth))?;
    factory.total_fees_usd = numeric(factory.total_fees_usd.plus(&fees_usd))?;
    factory.total_value_locked_eth = numeric(
        factory
            .total_value_locked_eth
            .minus(&pool.total_value_locked_eth),
    )?;
    pool.volume_token0 = numeric(pool.volume_token0.plus(&abs0))?;
    pool.volume_token1 = numeric(pool.volume_token1.plus(&abs1))?;
    pool.volume_usd = numeric(pool.volume_usd.plus(&tracked))?;
    pool.untracked_volume_usd = numeric(pool.untracked_volume_usd.plus(&untracked))?;
    pool.fees_usd = numeric(pool.fees_usd.plus(&fees_usd))?;
    pool.tx_count = increment(&pool.tx_count)?;
    pool.liquidity = handler.integer("liquidity")?;
    pool.tick = Presence::Set(mapping_i32(&handler.integer("tick")?)?.into());
    pool.sqrt_price = handler.integer("sqrtPriceX96")?;
    pool.total_value_locked_token0 = numeric(pool.total_value_locked_token0.plus(&amount0))?;
    pool.total_value_locked_token1 = numeric(pool.total_value_locked_token1.plus(&amount1))?;
    for (token, amount, absolute) in [
        (&mut token0, &amount0, &abs0),
        (&mut token1, &amount1, &abs1),
    ] {
        token.volume = numeric(token.volume.plus(absolute))?;
        token.total_value_locked = numeric(token.total_value_locked.plus(amount))?;
        token.volume_usd = numeric(token.volume_usd.plus(&tracked))?;
        token.untracked_volume_usd = numeric(token.untracked_volume_usd.plus(&untracked))?;
        token.fees_usd = numeric(token.fees_usd.plus(&fees_usd))?;
        token.tx_count = increment(&token.tx_count)?;
    }
    (pool.token0_price, pool.token1_price) = numeric(mapping::sqrt_price_x96_to_token_prices(
        &pool.sqrt_price,
        &token0.decimals,
        &token1.decimals,
    ))?;
    // The pricing and interval helpers reload this intermediate Pool image.
    journal.save(&pool)?;
    bundle.eth_price_usd = pricing::eth_price(journal)?;
    journal.save(&bundle)?;
    token0.derived_eth = pricing::derived_eth(journal, &token0, &token1)?;
    token1.derived_eth = pricing::derived_eth(journal, &token1, &token0)?;
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
    token0.total_value_locked_usd = numeric(
        numeric(token0.total_value_locked.times(&token0.derived_eth))?.times(&bundle.eth_price_usd),
    )?;
    token1.total_value_locked_usd = numeric(
        numeric(token1.total_value_locked.times(&token1.derived_eth))?.times(&bundle.eth_price_usd),
    )?;
    let tx = transaction::load(handler, journal)?;
    let swap = Swap {
        id: format!("{}#{}", tx.id, pool.tx_count),
        transaction: tx.id,
        timestamp: tx.timestamp,
        pool: pool.id.clone(),
        token0: pool.token0.clone(),
        token1: pool.token1.clone(),
        sender: handler.address("sender")?.to_vec(),
        recipient: handler.address("recipient")?.to_vec(),
        origin: handler.input.block().transactions[handler.candidate().tx as usize]
            .from
            .clone(),
        amount0,
        amount1,
        amount_usd: tracked.clone(),
        tick: mapping_i32(&handler.integer("tick")?)?.into(),
        sqrt_price_x96: handler.integer("sqrtPriceX96")?,
        log_index: Presence::Set(handler.candidate().log_index.into()),
    };
    let growth = handler.input.calls().fee_growth(&address)?;
    let positive = |bytes: &[u8]| {
        let mut sign = vec![0];
        sign.extend_from_slice(bytes);
        BigInt::from_signed_bytes_be(&sign)
    };
    pool.fee_growth_global0_x128 = positive(&growth.fee_growth_global0_x128);
    pool.fee_growth_global1_x128 = positive(&growth.fee_growth_global1_x128);
    let timestamp = mapping_i32(&handler.input.block().timestamp.into())?;
    let mut udd = interval::uniswap_day(journal, timestamp)?;
    let mut pdd = interval::pool_day(journal, &pool.id, timestamp)?;
    let mut phd = interval::pool_hour(journal, &pool.id, timestamp)?;
    let mut tdd0 = interval::token_day(journal, &token0, timestamp)?;
    let mut tdd1 = interval::token_day(journal, &token1, timestamp)?;
    let mut thd0 = interval::token_hour(journal, &token0, timestamp)?;
    let mut thd1 = interval::token_hour(journal, &token1, timestamp)?;
    udd.volume_eth = numeric(udd.volume_eth.plus(&tracked_eth))?;
    udd.volume_usd = numeric(udd.volume_usd.plus(&tracked))?;
    udd.fees_usd = numeric(udd.fees_usd.plus(&fees_usd))?;
    for (volume, vol0, vol1, fees) in [
        (
            &mut pdd.volume_usd,
            &mut pdd.volume_token0,
            &mut pdd.volume_token1,
            &mut pdd.fees_usd,
        ),
        (
            &mut phd.volume_usd,
            &mut phd.volume_token0,
            &mut phd.volume_token1,
            &mut phd.fees_usd,
        ),
    ] {
        *volume = numeric(volume.plus(&tracked))?;
        *vol0 = numeric(vol0.plus(&abs0))?;
        *vol1 = numeric(vol1.plus(&abs1))?;
        *fees = numeric(fees.plus(&fees_usd))?;
    }
    for (volume, volume_usd, untracked_usd, fees, amount) in [
        (
            &mut tdd0.volume,
            &mut tdd0.volume_usd,
            &mut tdd0.untracked_volume_usd,
            &mut tdd0.fees_usd,
            &abs0,
        ),
        (
            &mut thd0.volume,
            &mut thd0.volume_usd,
            &mut thd0.untracked_volume_usd,
            &mut thd0.fees_usd,
            &abs0,
        ),
        (
            &mut tdd1.volume,
            &mut tdd1.volume_usd,
            &mut tdd1.untracked_volume_usd,
            &mut tdd1.fees_usd,
            &abs1,
        ),
        (
            &mut thd1.volume,
            &mut thd1.volume_usd,
            &mut thd1.untracked_volume_usd,
            &mut thd1.fees_usd,
            &abs1,
        ),
    ] {
        *volume = numeric(volume.plus(amount))?;
        *volume_usd = numeric(volume_usd.plus(&tracked))?;
        // Deployed interval accounting uses tracked, unlike the Token entity.
        *untracked_usd = numeric(untracked_usd.plus(&tracked))?;
        *fees = numeric(fees.plus(&fees_usd))?;
    }
    journal.save(&swap)?;
    journal.save(&tdd0)?;
    journal.save(&tdd1)?;
    journal.save(&udd)?;
    journal.save(&pdd)?;
    journal.save(&thd0)?;
    journal.save(&thd1)?;
    journal.save(&phd)?;
    journal.save(&factory)?;
    journal.save(&pool)?;
    journal.save(&token0)?;
    journal.save(&token1)?;
    cross_ticks(handler, journal, &pool, &old_tick)
}

fn load_tick<B: EntityBackend>(
    handler: &SupportedHandler<'_>,
    journal: &mut HandlerJournal<'_, B>,
    pool_id: &str,
    tick: &BigInt,
) -> MappingResult<()> {
    let index = mapping_i32(tick)?;
    if let Some(mut tick) = journal.load::<Tick>(&format!("{pool_id}#{index}"))? {
        pool::update_tick(handler, journal, &mut tick)?;
    }
    Ok(())
}
fn cross_ticks<B: EntityBackend>(
    handler: &SupportedHandler<'_>,
    journal: &mut HandlerJournal<'_, B>,
    pool: &Pool,
    old: &BigInt,
) -> MappingResult<()> {
    let new = match &pool.tick {
        Presence::Set(tick) => tick,
        _ => {
            return Err(Step::Abort(Abort {
                message: "unexpected null at src/mappings/core.ts:480:17".into(),
            }))
        }
    };
    let spacing = if pool.fee_tier == BigInt::from(10000) {
        200
    } else if pool.fee_tier == BigInt::from(3000) {
        60
    } else if pool.fee_tier == BigInt::from(500) {
        10
    } else if pool.fee_tier == BigInt::from(100) {
        1
    } else {
        // Qualified against the deployed abort in the Swap oracle corpus.
        return Err(Step::Abort(Abort {
            message: "Mapping aborted at src/utils/tick.ts, line 57, column 3, with no message"
                .into(),
        }));
    };
    let spacing = BigInt::from(spacing);
    let modulo = numeric(bigint::modulo(new, &spacing))?;
    if modulo == BigInt::from(0) {
        load_tick(handler, journal, &pool.id, new)?;
    }
    let mut distance = numeric(bigint::minus(old, new))?;
    if distance < BigInt::from(0) {
        distance = numeric(bigint::minus(&BigInt::from(0), &distance))?;
    }
    if numeric(bigint::divided_by(&distance, &spacing))? <= BigInt::from(100) {
        if new > old {
            let mut index = numeric(bigint::plus(
                old,
                &numeric(bigint::minus(&spacing, &modulo))?,
            ))?;
            while index <= *new {
                load_tick(handler, journal, &pool.id, &index)?;
                index = numeric(bigint::plus(&index, &spacing))?;
            }
        } else if new < old {
            let mut index = numeric(bigint::minus(old, &modulo))?;
            while index >= *new {
                load_tick(handler, journal, &pool.id, &index)?;
                index = numeric(bigint::minus(&index, &spacing))?;
            }
        }
    }
    Ok(())
}
