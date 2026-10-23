// Boundary normalization follows graph-node graph/src/data/store/scalar/bigdecimal.rs
// and runtime/wasm/src/to_from/external.rs at GRAPH_NODE_COMMIT (Apache-2.0).
// Arithmetic itself is delegated to the pinned upstream dependencies.
use crate::{bigint, BigInt, NumericError};
use backfill_common::pb::pinax::graph::backfill::v1::BigDecimalValue;
use graph_bigdecimal::BigDecimal;
use graph_num_bigint::ToBigInt;
use num_traits::Zero;
use std::{cmp::Ordering, fmt, str::FromStr};

/// A normalized Graph Node value. Constructors state how many crossings they
/// model; no `FromStr`/Serde implementation hides a normalization on restore.
#[derive(Clone, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct GraphDecimal(BigDecimal);

impl GraphDecimal {
    pub const MAX_SIGNIFICANT_DIGITS: u64 = 34;
    pub const MIN_EXP: i64 = -6_143;
    pub const MAX_EXP: i64 = 6_144;

    pub fn zero() -> Self {
        Self(BigDecimal::from(0))
    }

    pub fn one() -> Self {
        Self(BigDecimal::from(1))
    }

    /// `BigInt.toBigDecimal()` constructed in WASM and crossing into the host
    /// once. May be a non-fixed point: do not normalize again to serialize it.
    pub fn from_bigint(value: &BigInt) -> Result<Self, NumericError> {
        Self::from_asc_parts(value.clone(), 0)
    }

    /// Raw WASM coefficient and power-of-ten exponent (the opposite of scale).
    pub fn from_asc_parts(coefficient: BigInt, exponent: i64) -> Result<Self, NumericError> {
        bigint::check_bits(&coefficient)?;
        let scale = exponent.checked_neg().ok_or(NumericError::ScaleOverflow)?;
        Self::normalized(BigDecimal::new(coefficient, scale))?.checked_range()
    }

    /// A host `BigDecimal.fromString` result observed at its next crossing.
    pub fn host_from_string(value: &str) -> Result<Self, NumericError> {
        let parsed = Self::parse_raw(value)?;
        Self::wasm_result(parsed)
    }

    /// Database text deserialization normalizes once. `cross()` models a later
    /// store.get result crossing back from WASM. For fixed points it is a no-op.
    /// This reducer primitive supports only the host's exponent domain.
    pub fn from_db_text(value: &str) -> Result<Self, NumericError> {
        Self::normalized(Self::parse_raw(value)?)?.checked_range()
    }

    /// One more explicit AssemblyScript-to-host boundary crossing.
    pub fn cross(&self) -> Result<Self, NumericError> {
        Self::normalized(self.0.clone())?.checked_range()
    }

    pub fn is_zero(&self) -> bool {
        self.0.is_zero()
    }

    pub fn compare(&self, other: &Self) -> Ordering {
        self.cmp(other)
    }

    pub fn coefficient_and_scale(&self) -> (BigInt, i64) {
        self.0.as_bigint_and_exponent()
    }

    /// Graph Node checks ONLY `-scale`, not digit count minus scale.
    pub fn exponent_in_range(&self) -> bool {
        let (_, scale) = self.coefficient_and_scale();
        (-Self::MAX_EXP..=-Self::MIN_EXP).contains(&scale)
    }

    fn checked_range(self) -> Result<Self, NumericError> {
        if self.exponent_in_range() {
            Ok(self)
        } else {
            let exp = self
                .coefficient_and_scale()
                .1
                .checked_neg()
                .ok_or(NumericError::ScaleOverflow)?;
            Err(NumericError::ExponentOutOfRange(exp))
        }
    }

    pub fn plus(&self, other: &Self) -> Result<Self, NumericError> {
        Self::wasm_result(&self.0 + &other.0)
    }

    pub fn minus(&self, other: &Self) -> Result<Self, NumericError> {
        Self::wasm_result(&self.0 - &other.0)
    }

    pub fn times(&self, other: &Self) -> Result<Self, NumericError> {
        Self::wasm_result(&self.0 * &other.0)
    }

    pub fn divided_by(&self, other: &Self) -> Result<Self, NumericError> {
        if other.is_zero() {
            return Err(NumericError::DecimalDivideByZero(self.to_string()));
        }
        Self::wasm_result(&self.0 / &other.0)
    }

    pub fn abs(&self) -> Result<Self, NumericError> {
        if self < &Self::zero() {
            Self::zero().minus(self)
        } else {
            Ok(self.clone())
        }
    }

    /// Exact integer conversion, as Graph Node's scalar conversion; no rounding.
    pub fn to_bigint(&self) -> Result<BigInt, NumericError> {
        if !self.0.is_integer() {
            return Err(NumericError::NonIntegerDecimal(self.to_string()));
        }
        let value = self.0.to_bigint().expect("upstream always returns Some");
        bigint::check_bits(&value)?;
        Ok(value)
    }

    pub fn is_fixed_point(&self) -> bool {
        Self::normalized(self.0.clone())
            .map(|next| next.coefficient_and_scale() == self.coefficient_and_scale())
            .unwrap_or(false)
    }

    /// Lossless checkpoint representation, INCLUDING once-normalized values.
    /// This is not permission to put a non-fixed point into BlockChanges v1.
    pub fn to_wire_exact(&self) -> BigDecimalValue {
        let (coefficient, scale) = self.coefficient_and_scale();
        BigDecimalValue {
            coefficient_signed_be: bigint::signed_bytes(&coefficient),
            scale,
        }
    }

    /// Restore the tuple without Graph Node's extra normalization. Rejects
    /// nonminimal bytes, trailing zeroes, noncanonical zero and values outside
    /// the image's coefficient/scale bounds. In particular, a 117-bit negative
    /// from one normalization round-trips exactly instead of being truncated.
    pub fn from_wire_exact(value: &BigDecimalValue) -> Result<Self, NumericError> {
        let coefficient = BigInt::from_signed_bytes_be(&value.coefficient_signed_be);
        if bigint::signed_bytes(&coefficient) != value.coefficient_signed_be {
            return Err(NumericError::NonCanonicalWire);
        }
        if coefficient.is_zero() {
            return if value.scale == 0 {
                Ok(Self::zero())
            } else {
                Err(NumericError::NonCanonicalWire)
            };
        }
        // n(x) has at most 34 positive or 35 negative decimal digits, including
        // the negative 117-bit values deliberately excluded from v1 frames.
        let digits = coefficient.to_str_radix(10);
        let bound = if digits.starts_with('-') { 36 } else { 34 };
        if digits.len() > bound || digits.ends_with('0') {
            return Err(NumericError::NonCanonicalWire);
        }
        Self(BigDecimal::new(coefficient, value.scale)).checked_range()
    }

    /// The strict v1 wire contract: fail closed, never silently change a value.
    pub fn to_block_changes_wire(&self) -> Result<BigDecimalValue, NumericError> {
        if !self.is_fixed_point() {
            return Err(NumericError::NonFixedPoint);
        }
        Ok(self.to_wire_exact())
    }

    pub fn from_block_changes_wire(value: &BigDecimalValue) -> Result<Self, NumericError> {
        let result = Self::from_wire_exact(value)?;
        result.to_block_changes_wire()?;
        Ok(result)
    }

    fn parse_raw(value: &str) -> Result<BigDecimal, NumericError> {
        // Upstream 0.1.2 subtracts the exponent with unchecked i64 arithmetic.
        // Check before invoking it, then let its parser own the grammar.
        let (base, exponent) = match value.find(['e', 'E']) {
            Some(index) => {
                let exp = value[index + 1..]
                    .parse::<i64>()
                    .map_err(|_| NumericError::InvalidDecimal(value.into()))?;
                (&value[..index], exp)
            }
            None => (value, 0),
        };
        let fractional = base.find('.').map_or(0, |index| base.len() - index - 1);
        let fractional = i64::try_from(fractional).map_err(|_| NumericError::ScaleOverflow)?;
        fractional
            .checked_sub(exponent)
            .ok_or(NumericError::ScaleOverflow)?;
        let parsed =
            BigDecimal::from_str(value).map_err(|_| NumericError::InvalidDecimal(value.into()))?;
        // Graph Node parses strings directly into BigDecimal, then normalizes.
        // The unrounded coefficient never crosses the checked BigInt boundary.
        Ok(parsed)
    }

    fn wasm_result(value: BigDecimal) -> Result<Self, NumericError> {
        Self::normalized(value)?.cross()
    }

    fn normalized(value: BigDecimal) -> Result<Self, NumericError> {
        if value.is_zero() {
            return Ok(Self::zero());
        }
        // Preserve the pinned crate's signed digit-count bug and rounding;
        // check its scale arithmetic first so malformed inputs cannot panic.
        let digits = value.digits();
        let (_, scale) = value.as_bigint_and_exponent();
        if digits > Self::MAX_SIGNIFICANT_DIGITS {
            scale.checked_sub((digits - Self::MAX_SIGNIFICANT_DIGITS) as i64)
        } else {
            scale.checked_add((Self::MAX_SIGNIFICANT_DIGITS - digits) as i64)
        }
        .ok_or(NumericError::ScaleOverflow)?;
        let rounded = value.with_prec(Self::MAX_SIGNIFICANT_DIGITS);
        let (coefficient, scale) = rounded.as_bigint_and_exponent();
        let (sign, mut digits) = coefficient.to_radix_be(10);
        let trailing = digits.iter().rev().take_while(|digit| **digit == 0).count();
        digits.truncate(digits.len() - trailing);
        let coefficient = BigInt::from_radix_be(sign, &digits, 10)
            .expect("a nonzero value retains a decimal digit");
        let scale = scale
            .checked_sub(trailing as i64)
            .ok_or(NumericError::ScaleOverflow)?;
        Ok(Self(BigDecimal::new(coefficient, scale)))
    }
}

impl Default for GraphDecimal {
    fn default() -> Self {
        Self::zero()
    }
}

impl fmt::Display for GraphDecimal {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(f)
    }
}

impl fmt::Debug for GraphDecimal {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "GraphDecimal({})", self.0)
    }
}
