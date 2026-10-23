//! Raw ERC20 RPC boundary. Mapping fallbacks belong to the reducer.
use crate::{
    calls::ERC20_SELECTORS,
    pb::{internal as i, v1 as p},
    Address,
};
use std::collections::BTreeSet;

pub fn tokens(created: &i::PoolsCreated) -> Result<BTreeSet<Address>, &'static str> {
    let mut tokens = BTreeSet::new();
    for pool in &created.pools {
        for token in [&pool.token0, &pool.token1] {
            tokens.insert(
                token
                    .as_slice()
                    .try_into()
                    .map_err(|_| "ERC20 token must be 20 bytes")?,
            );
        }
    }
    Ok(tokens)
}
pub fn calls(tokens: &BTreeSet<Address>) -> Vec<(Address, [u8; 4])> {
    tokens
        .iter()
        .flat_map(|token| ERC20_SELECTORS.map(|selector| (*token, selector)))
        .collect()
}
pub struct Response {
    pub failed: bool,
    pub raw: Vec<u8>,
}

pub fn answers(
    tokens: &BTreeSet<Address>,
    responses: Vec<Response>,
) -> Result<i::TokenMetadataAnswers, &'static str> {
    if tokens.len().checked_mul(4) != Some(responses.len()) {
        return Err("ERC20 RPC response count mismatch");
    }
    let mut output = i::TokenMetadataAnswers::default();
    let mut responses = responses.into_iter();
    for token in tokens {
        let mut failed = 0;
        let mut empty = 0;
        let mut retval = |index| {
            let response = responses.next().expect("response count checked");
            if response.failed {
                failed |= 1u32 << index;
            } else if response.raw.is_empty() {
                empty |= 1u32 << index;
            }
            Some(p::RawRetval {
                kind: Some(if response.failed || response.raw.is_empty() {
                    p::raw_retval::Kind::Reverted(p::raw_retval::Null {})
                } else {
                    p::raw_retval::Kind::Value(response.raw)
                }),
            })
        };
        let symbol = retval(0);
        let name = retval(1);
        let total_supply = retval(2);
        let decimals = retval(3);
        output.erc20.push(p::Erc20Answer {
            token: token.to_vec(),
            symbol,
            name,
            total_supply,
            decimals,
            rpc_failed_mask: failed,
            rpc_empty_mask: empty,
        });
    }
    Ok(output)
}
