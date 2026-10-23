//! Graph Node-compatible event decoding for state derivation. Abigen's
//! diagnostic flag is deliberately not an input to this decoder.
use crate::pb::v1::{CandidateLog, DataSourceKind};
use alloy_dyn_abi::{DynSolValue, EventExt};
use alloy_json_abi::JsonAbi;
use alloy_primitives::B256;
use std::sync::OnceLock;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Event {
    PoolCreated {
        pool: crate::Address,
        token0: crate::Address,
        token1: crate::Address,
        spacing: i32,
    },
    Initialize {
        tick: i32,
    },
    Swap {
        tick: i32,
    },
    Mint {
        lower: i32,
        upper: i32,
    },
    Burn {
        lower: i32,
        upper: i32,
    },
    Flash,
    Position {
        token_id: crate::Word,
    },
}

fn int24(value: Option<&DynSolValue>) -> Result<i32, &'static str> {
    let Some(DynSolValue::Int(value, 24)) = value else {
        return Err("locked event ABI int24 result drift");
    };
    let value: i64 = value
        .to_string()
        .parse()
        .map_err(|_| "decoded int24 exceeds i64")?;
    if !(-8_388_608..=8_388_607).contains(&value) {
        return Err("Graph Node accepted a tick outside the declared int24 domain");
    }
    Ok(value as i32)
}

pub fn decode(candidate: &CandidateLog) -> Result<Option<Event>, &'static str> {
    static FACTORY: OnceLock<JsonAbi> = OnceLock::new();
    static POOL: OnceLock<JsonAbi> = OnceLock::new();
    static NPM: OnceLock<JsonAbi> = OnceLock::new();
    let (abi, names): (&JsonAbi, &[&str]) = match candidate.source {
        x if x == DataSourceKind::Factory as i32 => (
            FACTORY.get_or_init(|| {
                serde_json::from_slice(include_bytes!("../../../../reference/abis/Factory.json"))
                    .expect("locked Factory ABI")
            }),
            &["PoolCreated"],
        ),
        x if x == DataSourceKind::Pool as i32 => (
            POOL.get_or_init(|| {
                serde_json::from_slice(include_bytes!("../../../../reference/abis/Pool.json"))
                    .expect("locked Pool ABI")
            }),
            &["Initialize", "Swap", "Mint", "Burn", "Flash"],
        ),
        x if x == DataSourceKind::PositionManager as i32 => (
            NPM.get_or_init(|| {
                serde_json::from_slice(include_bytes!(
                    "../../../../reference/abis/NonfungiblePositionManager.json"
                ))
                .expect("locked NPM ABI")
            }),
            &[
                "IncreaseLiquidity",
                "DecreaseLiquidity",
                "Collect",
                "Transfer",
            ],
        ),
        _ => return Ok(None),
    };
    let Some(topic) = candidate.topics.first() else {
        return Ok(None);
    };
    let Some(event) = names.iter().find_map(|name| {
        abi.events[*name]
            .iter()
            .find(|event| event.selector().as_slice() == topic)
    }) else {
        return Ok(None);
    };
    if candidate.address.len() != 20 {
        return Err("event address must be 20 bytes");
    }
    let topics = candidate
        .topics
        .iter()
        .map(|topic| <[u8; 32]>::try_from(topic.as_slice()).map(B256::from))
        .collect::<Result<Vec<_>, _>>();
    let Ok(topics) = topics else { return Ok(None) };
    let Ok(decoded) = event.decode_log_parts(topics, &candidate.data) else {
        return Ok(None);
    };
    Ok(Some(match event.name.as_str() {
        "PoolCreated" => {
            let address = |value: Option<&DynSolValue>| match value {
                Some(DynSolValue::Address(value)) => Ok(value.into_array()),
                _ => Err("locked Factory event ABI address result drift"),
            };
            Event::PoolCreated {
                pool: address(decoded.body.first())?,
                token0: address(decoded.indexed.first())?,
                token1: address(decoded.indexed.get(1))?,
                spacing: int24(decoded.indexed.get(2))?,
            }
        }
        "Initialize" => Event::Initialize {
            tick: int24(decoded.body.last())?,
        },
        "Swap" => Event::Swap {
            tick: int24(decoded.body.last())?,
        },
        "Mint" => Event::Mint {
            lower: int24(decoded.indexed.get(1))?,
            upper: int24(decoded.indexed.get(2))?,
        },
        "Burn" => Event::Burn {
            lower: int24(decoded.indexed.get(1))?,
            upper: int24(decoded.indexed.get(2))?,
        },
        "Flash" => Event::Flash,
        _ => {
            let index = if event.name == "Transfer" { 2 } else { 0 };
            let Some(DynSolValue::Uint(id, 256)) = decoded.indexed.get(index) else {
                return Err("locked NPM event ABI tokenId result drift");
            };
            Event::Position {
                token_id: id.to_be_bytes(),
            }
        }
    }))
}
