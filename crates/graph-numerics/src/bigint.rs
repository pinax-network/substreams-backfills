//! Graph Node integer operations, observed after the next WASM crossing.
//!
//! Graph Node checks `magnitude.bits() + 1 <= 435412`, including one sign bit.
//! Its arithmetic internally constructs unchecked results; the next host call
//! or store crosses the checked constructor. We return that refusal explicitly.

use crate::{BigInt, NumericError};
use backfill_common::pb::pinax::graph::backfill::v1::BigIntValue;
use num_traits::{Pow, ToPrimitive, Zero};

pub const MAX_BITS: usize = 435_412;

pub fn check_bits(value: &BigInt) -> Result<(), NumericError> {
    let bits = value.bits() + 1;
    if bits > MAX_BITS {
        Err(NumericError::IntegerTooBig(bits))
    } else {
        Ok(())
    }
}

pub fn parse(value: &str) -> Result<BigInt, NumericError> {
    let value = value
        .parse::<BigInt>()
        .map_err(|_| NumericError::InvalidInteger(value.into()))?;
    checked(value)
}

fn checked(value: BigInt) -> Result<BigInt, NumericError> {
    check_bits(&value)?;
    Ok(value)
}

fn operands(a: &BigInt, b: &BigInt) -> Result<(), NumericError> {
    check_bits(a)?;
    check_bits(b)
}

macro_rules! binary {
    ($name:ident, $operator:tt) => {
        pub fn $name(a: &BigInt, b: &BigInt) -> Result<BigInt, NumericError> {
            operands(a, b)?;
            checked(a $operator b)
        }
    };
}
binary!(plus, +);
binary!(minus, -);
binary!(times, *);
binary!(bit_and, &);
binary!(bit_or, |);

pub fn divided_by(a: &BigInt, b: &BigInt) -> Result<BigInt, NumericError> {
    operands(a, b)?;
    if b.is_zero() {
        return Err(NumericError::IntegerDivideByZero(a.to_string()));
    }
    checked(a / b)
}

pub fn modulo(a: &BigInt, b: &BigInt) -> Result<BigInt, NumericError> {
    operands(a, b)?;
    if b.is_zero() {
        return Err(NumericError::IntegerRemainderByZero(a.to_string()));
    }
    checked(a % b)
}

pub fn pow(a: &BigInt, exponent: u8) -> Result<BigInt, NumericError> {
    check_bits(a)?;
    checked(a.pow(u32::from(exponent)))
}

pub fn left_shift(a: &BigInt, bits: u8) -> Result<BigInt, NumericError> {
    check_bits(a)?;
    checked(a << usize::from(bits))
}

pub fn right_shift(a: &BigInt, bits: u8) -> Result<BigInt, NumericError> {
    check_bits(a)?;
    checked(a >> usize::from(bits))
}

pub fn to_i32_checked(value: &BigInt) -> Result<i32, NumericError> {
    check_bits(value)?;
    value
        .to_i32()
        .ok_or_else(|| NumericError::I32Overflow(value.to_string()))
}

pub fn signed_bytes(value: &BigInt) -> Vec<u8> {
    if value.is_zero() {
        Vec::new()
    } else {
        value.to_signed_bytes_be()
    }
}

pub fn to_wire(value: &BigInt) -> Result<BigIntValue, NumericError> {
    check_bits(value)?;
    Ok(BigIntValue {
        signed_be: signed_bytes(value),
    })
}

pub fn from_wire(value: &BigIntValue) -> Result<BigInt, NumericError> {
    let int = BigInt::from_signed_bytes_be(&value.signed_be);
    if signed_bytes(&int) != value.signed_be {
        return Err(NumericError::NonCanonicalWire);
    }
    checked(int)
}
