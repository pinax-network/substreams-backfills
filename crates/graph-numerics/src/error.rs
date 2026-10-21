use std::{error::Error, fmt};

/// Deterministic refusals; no division, conversion, or exponent error panics.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum NumericError {
    InvalidDecimal(String),
    InvalidInteger(String),
    DecimalDivideByZero(String),
    IntegerDivideByZero(String),
    IntegerRemainderByZero(String),
    ExponentOutOfRange(i64),
    ScaleOverflow,
    IntegerTooBig(usize),
    I32Overflow(String),
    NonIntegerDecimal(String),
    NonCanonicalWire,
    NonFixedPoint,
    TokenDecimalsOutOfRange,
    TickOutOfRange(i32),
}

impl NumericError {
    /// Stable category for the cross-implementation oracle corpus.
    pub fn kind(&self) -> &'static str {
        match self {
            Self::InvalidDecimal(_) => "invalid_decimal",
            Self::InvalidInteger(_) => "invalid_integer",
            Self::DecimalDivideByZero(_) => "decimal_divide_by_zero",
            Self::IntegerDivideByZero(_) => "integer_divide_by_zero",
            Self::IntegerRemainderByZero(_) => "integer_remainder_by_zero",
            Self::ExponentOutOfRange(_) => "exponent_out_of_range",
            Self::ScaleOverflow => "scale_overflow",
            Self::IntegerTooBig(_) => "integer_too_big",
            Self::I32Overflow(_) => "i32_overflow",
            Self::NonIntegerDecimal(_) => "non_integer_decimal",
            Self::NonCanonicalWire => "non_canonical_wire",
            Self::NonFixedPoint => "non_fixed_point",
            Self::TokenDecimalsOutOfRange => "token_decimals_out_of_range",
            Self::TickOutOfRange(_) => "tick_out_of_range",
        }
    }
}

impl fmt::Display for NumericError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidDecimal(s) => write!(f, "string is not a BigDecimal: '{s}'"),
            Self::InvalidInteger(s) => write!(f, "string is not a BigInt: `{s}`"),
            Self::DecimalDivideByZero(x) => {
                write!(f, "attempted to divide BigDecimal `{x}` by zero")
            }
            Self::IntegerDivideByZero(x) => write!(f, "attempted to divide BigInt `{x}` by zero"),
            Self::IntegerRemainderByZero(x) => write!(
                f,
                "attempted to calculate the remainder of `{x}` with a divisor of zero"
            ),
            Self::ExponentOutOfRange(exp) => write!(
                f,
                "big decimal exponent `{exp}` is outside the `-6143` to `6144` range"
            ),
            Self::ScaleOverflow => write!(f, "BigDecimal scale arithmetic overflows i64"),
            Self::IntegerTooBig(bits) => {
                write!(f, "BigInt is too big, total bits {bits} (max 435412)")
            }
            Self::I32Overflow(x) => write!(f, "overflow converting {x} to i32"),
            Self::NonIntegerDecimal(x) => {
                write!(f, "Cannot convert non-integer BigDecimal to BigInt: {x}")
            }
            Self::NonCanonicalWire => write!(f, "non-canonical numeric wire representation"),
            Self::NonFixedPoint => write!(
                f,
                "BlockChanges v1 refuses a decimal that normalization changes"
            ),
            Self::TokenDecimalsOutOfRange => write!(f, "token decimals must be in 0..=255"),
            Self::TickOutOfRange(tick) => write!(f, "tick {tick} is outside -887272..=887272"),
        }
    }
}

impl Error for NumericError {}
