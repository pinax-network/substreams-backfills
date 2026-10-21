//! Mapping primitives for Factory, Initialize and pool liquidity changes.
//!
//! This is a handler primitive, not a complete block reducer. Match every
//! candidate against authoritative hosts; unsupported matched handlers are
//! errors, never silently skipped. The caller owns block/handler order and must
//! record a returned source only after the handler commits (or its failed
//! creation after abort), and persist hosts only after the block commits.
mod factory;
mod initialize;
mod interval;
mod pool;
mod pricing;
mod transaction;

use crate::{
    abi::DecodedEvent,
    entity::Entity,
    hosts::HostSet,
    input::BlockInput,
    pb, refuse,
    state::{Abort, EntityBackend, HandlerJournal, Step},
    Address, Result,
};
use alloy_dyn_abi::DynSolValue;
use graph_numerics::{bigint, BigInt, NumericError};

type MappingResult<T> = std::result::Result<T, Step>;
pub const FACTORY: &str = "0x5e7bb104d84c7cb9b682aac2f3d509f5f406809a";
pub const WETH: &str = "0x4200000000000000000000000000000000000006";
pub const USDC: &str = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913";
pub const AERO: &str = "0x940181a94a35a4569e4529a3cdfb74e38fd98631";
pub const ETH_USD_POOL: &str = "0xb2cc224c1c9fee385f8ad6a55b4d94e92359dc59";
const WHITELIST: [&str; 3] = [WETH, USDC, AERO];

/// A validated, host-matched trigger. Construction refuses every handler not
/// implemented by this checkpoint, including Swap and all NPM events.
pub struct SupportedHandler<'a> {
    input: &'a BlockInput,
    index: usize,
    event: &'a DecodedEvent,
}
impl<'a> SupportedHandler<'a> {
    pub fn match_candidate(
        input: &'a BlockInput,
        hosts: &HostSet,
        index: usize,
    ) -> Result<Option<Self>> {
        let Some(event) = hosts.match_candidate(input, index)? else {
            return Ok(None);
        };
        let source = input.block().candidates[index].source;
        if !matches!(
            (source, event.name.as_str()),
            (1, "PoolCreated") | (3, "Initialize" | "Mint" | "Burn")
        ) {
            return Err(refuse(format!("UnsupportedHandler: {}", event.name)));
        }
        Ok(Some(Self {
            input,
            index,
            event,
        }))
    }
    pub fn source_trigger_order(&self) -> u64 {
        self.candidate().source_trigger_order.into()
    }
    /// Invoke inside `BlockStore::run_handler`. A successful Factory invocation
    /// returns a newly created source; install it only after Committed status.
    pub fn run<B: EntityBackend>(
        &self,
        journal: &mut HandlerJournal<'_, B>,
    ) -> MappingResult<Option<Address>> {
        match self.event.name.as_str() {
            "PoolCreated" => factory::pool_created(self, journal),
            "Initialize" => initialize::initialize(self, journal).map(|()| None),
            "Mint" => pool::liquidity(self, journal, true).map(|()| None),
            "Burn" => pool::liquidity(self, journal, false).map(|()| None),
            _ => unreachable!("constructor matches the supported source and handler"),
        }
    }
    fn candidate(&self) -> &pb::CandidateLog {
        &self.input.block().candidates[self.index]
    }
    fn address(&self, name: &str) -> Result<Address> {
        match self.event.param(name) {
            Some(DynSolValue::Address(value)) => Ok(value.0 .0),
            _ => Err(refuse(format!("validated ABI lost address {name}"))),
        }
    }
    fn integer(&self, name: &str) -> Result<BigInt> {
        match self.event.param(name) {
            Some(DynSolValue::Int(value, _)) => {
                Ok(BigInt::from_signed_bytes_be(&value.to_be_bytes::<32>()))
            }
            Some(DynSolValue::Uint(value, _)) => {
                // A leading zero preserves the sign when bit 255 is set.
                let mut bytes = vec![0];
                bytes.extend_from_slice(&value.to_be_bytes::<32>());
                Ok(BigInt::from_signed_bytes_be(&bytes))
            }
            _ => Err(refuse(format!("validated ABI lost integer {name}"))),
        }
    }
}
fn id(address: &Address) -> String {
    format!("0x{}", hex::encode(address))
}
// Refuse unqualified host/native limits instead of manufacturing PoI errors.
fn numeric<T>(value: std::result::Result<T, NumericError>) -> MappingResult<T> {
    value.map_err(|e| Step::Fatal(refuse(format!("UnqualifiedNumericFailure: {e}"))))
}
// Only this overflow is proven to abort by both the deployed export and full
// handler oracle; its message is the original AssemblyScript abort message.
fn mapping_i32(value: &BigInt) -> MappingResult<i32> {
    match bigint::to_i32_mapping(value) {
        Ok(value) => Ok(value),
        Err(NumericError::I32Overflow(_)) => Err(Step::Abort(Abort {
            message: format!(
                "overflow converting 0x{} to i32",
                hex::encode(value.to_signed_bytes_le())
            ),
        })),
        Err(e) => numeric(Err(e)),
    }
}
// Pool.wasm compare calls host minus, then compares the signed digits to zero.
fn decimal_compare(
    a: &graph_numerics::GraphDecimal,
    b: &graph_numerics::GraphDecimal,
) -> MappingResult<std::cmp::Ordering> {
    Ok(numeric(a.minus(b))?
        .coefficient_and_scale()
        .0
        .cmp(&BigInt::from(0)))
}

fn increment(value: &BigInt) -> MappingResult<BigInt> {
    numeric(bigint::plus(value, &BigInt::from(1)))
}
fn required<B: EntityBackend, E: Entity>(
    journal: &mut HandlerJournal<'_, B>,
    id: &str,
    site: &str,
) -> MappingResult<E> {
    journal.load_required(
        id,
        Abort {
            message: format!("unexpected null at {site}"),
        },
    )
}
