//! Mapping-level helpers with the deployed Aerodrome operation order.
//! They are separate from the family-neutral numeric operations.
use crate::{bigint, BigInt, GraphDecimal, NumericError};
use num_traits::{ToPrimitive, Zero};

pub fn exponent_to_big_decimal(decimals: &BigInt) -> Result<GraphDecimal, NumericError> {
    let decimals = decimals
        .to_u8()
        .ok_or(NumericError::TokenDecimalsOutOfRange)?;
    // Multiplication by 10 is exact under each normalization; this is the same
    // chain as exponentToBigDecimal without its redundant loop.
    GraphDecimal::from_asc_parts(BigInt::from(1), i64::from(decimals))
}

pub fn convert_token_to_decimal(
    amount: &BigInt,
    decimals: &BigInt,
) -> Result<GraphDecimal, NumericError> {
    let divisor = exponent_to_big_decimal(decimals)?;
    let amount = GraphDecimal::from_bigint(amount)?;
    if decimals.is_zero() {
        Ok(amount) // Exactly one normalization, including non-fixed points.
    } else {
        amount.divided_by(&divisor)
    }
}

pub fn safe_div(a: &GraphDecimal, b: &GraphDecimal) -> Result<GraphDecimal, NumericError> {
    if b.is_zero() {
        Ok(GraphDecimal::zero())
    } else {
        a.divided_by(b)
    }
}

pub fn sqrt_price_x96_to_token_prices(
    sqrt: &BigInt,
    decimals0: &BigInt,
    decimals1: &BigInt,
) -> Result<(GraphDecimal, GraphDecimal), NumericError> {
    let squared = bigint::times(sqrt, sqrt)?;
    let q192 = bigint::pow(&BigInt::from(2), 192)?;
    let price1 = GraphDecimal::from_bigint(&squared)?
        .divided_by(&GraphDecimal::from_bigint(&q192)?)?
        .times(&exponent_to_big_decimal(decimals0)?)?
        .divided_by(&exponent_to_big_decimal(decimals1)?)?;
    let price0 = safe_div(&GraphDecimal::one(), &price1)?;
    Ok((price0, price1))
}

/// Every 1024th value of the exact iterative `1.0001` multiplication chain.
/// Exponentiation by squaring is NOT equivalent because every multiply rounds.
#[derive(Debug)]
pub struct TickPowTable {
    checkpoints: Vec<GraphDecimal>,
    base: GraphDecimal,
}

impl Default for TickPowTable {
    fn default() -> Self {
        Self {
            checkpoints: vec![GraphDecimal::one()],
            base: GraphDecimal::host_from_string("1.0001").expect("mapping constant"),
        }
    }
}

impl TickPowTable {
    pub const MAX_TICK: i32 = 887_272;
    pub const STRIDE: u32 = 1_024;

    pub fn positive_power(&mut self, power: u32) -> Result<GraphDecimal, NumericError> {
        if power > Self::MAX_TICK as u32 {
            return Err(NumericError::TickOutOfRange(
                i32::try_from(power).unwrap_or(i32::MAX),
            ));
        }
        let checkpoint = (power / Self::STRIDE) as usize;
        while self.checkpoints.len() <= checkpoint {
            let mut value = self.checkpoints.last().expect("b0").clone();
            for _ in 0..Self::STRIDE {
                value = value.times(&self.base)?;
            }
            self.checkpoints.push(value);
        }
        let mut value = self.checkpoints[checkpoint].clone();
        for _ in 0..power % Self::STRIDE {
            value = value.times(&self.base)?;
        }
        Ok(value)
    }

    pub fn price(&mut self, tick: i32) -> Result<GraphDecimal, NumericError> {
        if !(-Self::MAX_TICK..=Self::MAX_TICK).contains(&tick) {
            return Err(NumericError::TickOutOfRange(tick));
        }
        let power = self.positive_power(tick.unsigned_abs())?;
        if tick < 0 {
            safe_div(&GraphDecimal::one(), &power)
        } else {
            Ok(power)
        }
    }
}
