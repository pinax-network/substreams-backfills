//! Independent archive-call comparison. This checks consumed return fields;
//! it does not prove extractor completeness, carry provenance or handler parity.
use aerodrome_extractor_core::{
    calls::{CallKey, ERC20_SELECTORS},
    config::{Config, CONTRACT},
    layout, word, Address,
};
use aerodrome_extractor_pb::v1 as p;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::BTreeSet;

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Retval {
    Value { data: String },
    Reverted,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Expected {
    Raw(Retval),
    Words {
        minimum_words: usize,
        consumed: Vec<(usize, Vec<u8>)>,
    },
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Check {
    pub address: Address,
    pub calldata: Vec<u8>,
    pub expected: Expected,
}

fn address(value: &[u8]) -> Result<Address, String> {
    value
        .try_into()
        .map_err(|_| "expected 20-byte address".into())
}
fn width(value: &[u8], expected: usize) -> Result<Vec<u8>, String> {
    if value.len() != expected {
        return Err(format!("expected {expected}-byte value"));
    }
    Ok(value.to_vec())
}
fn address_word(value: &[u8]) -> Result<Vec<u8>, String> {
    let mut result = vec![0; 12];
    result.extend(address(value)?);
    Ok(result)
}
fn raw(value: &Option<p::RawRetval>) -> Result<Retval, String> {
    match value.as_ref().and_then(|v| v.kind.as_ref()) {
        Some(p::raw_retval::Kind::Value(bytes)) if !bytes.is_empty() => Ok(Retval::Value {
            data: hex::encode(bytes),
        }),
        Some(p::raw_retval::Kind::Reverted(_)) => Ok(Retval::Reverted),
        _ => Err("missing or empty raw answer".into()),
    }
}

pub fn checks(
    block: &p::ExtractorBlock,
    cfg: &Config,
    erc20_only: bool,
) -> Result<Vec<Check>, String> {
    if block.contract != CONTRACT || block.hash.len() != 32 || block.parent_hash.len() != 32 {
        return Err("wrong extractor identity or block hash width".into());
    }
    if !block
        .audit
        .as_ref()
        .ok_or("missing audit")?
        .anomalies
        .is_empty()
    {
        return Err("extractor anomalies prohibit an audit receipt".into());
    }
    let calls = block.calls.as_ref().ok_or("missing CallAnswers")?;
    let mut result = Vec::new();
    let mut seen = BTreeSet::new();
    let mut push = |key: CallKey, expected: Expected| -> Result<(), String> {
        let calldata = key.calldata()?.to_vec();
        let address = key.address(cfg);
        if !seen.insert((address, calldata.clone())) {
            return Err("duplicate call answer".into());
        }
        result.push(Check {
            address,
            calldata,
            expected,
        });
        Ok(())
    };
    for answer in &calls.erc20 {
        if (answer.rpc_failed_mask | answer.rpc_empty_mask) & !15 != 0
            || answer.rpc_failed_mask & answer.rpc_empty_mask != 0
        {
            return Err("invalid ERC20 response masks".into());
        }
        for (i, retval) in [
            &answer.symbol,
            &answer.name,
            &answer.total_supply,
            &answer.decimals,
        ]
        .into_iter()
        .enumerate()
        {
            let expected = raw(retval)?;
            let reverted = (answer.rpc_failed_mask | answer.rpc_empty_mask) & (1 << i) != 0;
            if reverted != matches!(expected, Retval::Reverted) {
                return Err("ERC20 mask/answer mismatch".into());
            }
            push(
                CallKey::Erc20 {
                    token: address(&answer.token)?,
                    selector: ERC20_SELECTORS[i],
                },
                Expected::Raw(expected),
            )?;
        }
    }
    if !erc20_only {
        for a in &calls.fee_growth {
            for (which, value) in [&a.fee_growth_global0_x128, &a.fee_growth_global1_x128]
                .into_iter()
                .enumerate()
            {
                push(
                    CallKey::FeeGrowth {
                        pool: address(&a.pool)?,
                        which: which as u8,
                    },
                    Expected::Words {
                        minimum_words: 1,
                        consumed: vec![(0, width(value, 32)?)],
                    },
                )?;
            }
        }
        for a in &calls.ticks {
            let signed = width(&a.staked_liquidity_net, 16)?;
            let mut extended = vec![if signed[0] & 128 != 0 { 255 } else { 0 }; 16];
            extended.extend(signed);
            push(
                CallKey::Ticks {
                    pool: address(&a.pool)?,
                    tick: a.tick,
                },
                Expected::Words {
                    minimum_words: 10,
                    consumed: vec![(2, extended), (3, width(&a.fee_growth_outside0_x128, 32)?)],
                },
            )?;
        }
        for a in &calls.positions {
            if a.token_id.len() > 32 || a.token_id.first() == Some(&0) {
                return Err("noncanonical token ID".into());
            }
            let expected = match a.result.as_ref().ok_or("missing position result")? {
                p::position_answer::Result::Reverted(_) => Expected::Raw(Retval::Reverted),
                p::position_answer::Result::Value(v) => {
                    for x in [v.tick_spacing, v.tick_lower, v.tick_upper] {
                        if !(-8388608..=8388607).contains(&x) {
                            return Err("position int24 overflow".into());
                        }
                    }
                    Expected::Words {
                        minimum_words: 12,
                        consumed: vec![
                            (2, address_word(&v.token0)?),
                            (3, address_word(&v.token1)?),
                            (4, layout::int_word(v.tick_spacing).to_vec()),
                            (5, layout::int_word(v.tick_lower).to_vec()),
                            (6, layout::int_word(v.tick_upper).to_vec()),
                            (8, width(&v.fee_growth_inside0_last_x128, 32)?),
                            (9, width(&v.fee_growth_inside1_last_x128, 32)?),
                        ],
                    }
                }
            };
            push(
                CallKey::Positions {
                    token_id: word(&a.token_id)?,
                },
                expected,
            )?;
        }
        for a in &calls.get_pool {
            push(
                CallKey::GetPool {
                    a: address(&a.token_a)?,
                    b: address(&a.token_b)?,
                    ts: a.tick_spacing,
                },
                Expected::Words {
                    minimum_words: 1,
                    consumed: vec![(0, address_word(&a.pool)?)],
                },
            )?;
        }
    }
    result.sort_by(|a, b| (&a.address, &a.calldata).cmp(&(&b.address, &b.calldata)));
    Ok(result)
}

pub fn compare(check: &Check, actual: &Retval) -> Result<(), String> {
    match (&check.expected, actual) {
        (Expected::Raw(expected), actual) if expected == actual => Ok(()),
        (
            Expected::Words {
                minimum_words,
                consumed,
            },
            Retval::Value { data },
        ) => {
            let bytes = hex::decode(data).map_err(|_| "invalid return hex")?;
            if bytes.len() < minimum_words * 32 {
                return Err("truncated ABI return".into());
            }
            for (index, expected) in consumed {
                if bytes.get(index * 32..(index + 1) * 32) != Some(expected.as_slice()) {
                    return Err(format!("consumed ABI word {index} differs"));
                }
            }
            Ok(())
        }
        _ => Err("archive return/revert differs".into()),
    }
}

/// Only an explicit execution-revert response is a mapping revert. Archive
/// misses, rate limits, timeouts and generic -32000 errors abort the audit.
pub fn call_retval(response: &Value, expected_id: u64) -> Result<Retval, String> {
    if response["jsonrpc"] != "2.0" || response["id"].as_u64() != Some(expected_id) {
        return Err("RPC response identity mismatch".into());
    }
    match (response.get("result"), response.get("error")) {
        (Some(Value::String(value)), None) => {
            let value = value
                .strip_prefix("0x")
                .ok_or("missing return hex prefix")?;
            let bytes = hex::decode(value).map_err(|_| "invalid RPC return hex")?;
            Ok(if bytes.is_empty() {
                Retval::Reverted
            } else {
                Retval::Value {
                    data: hex::encode(bytes),
                }
            })
        }
        (None, Some(error))
            if error["code"].as_i64() == Some(3)
                && error["message"]
                    .as_str()
                    .is_some_and(|m| m.to_ascii_lowercase().starts_with("execution reverted")) =>
        {
            Ok(Retval::Reverted)
        }
        _ => Err("RPC failed without an explicit execution revert".into()),
    }
}

pub fn request(check: &Check, hash: &[u8], id: u64) -> Value {
    json!({"jsonrpc":"2.0","id":id,"method":"eth_call","params":[
        {"to":format!("0x{}",hex::encode(check.address)),"data":format!("0x{}",hex::encode(&check.calldata)),"gas":"0x2faf080"},
        {"blockHash":format!("0x{}",hex::encode(hash)),"requireCanonical":true}]})
}
