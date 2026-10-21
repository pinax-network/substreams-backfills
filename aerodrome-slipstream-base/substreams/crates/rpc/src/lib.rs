#![allow(clippy::not_unsafe_ptr_arg_deref)]
use aerodrome_extractor_core::metadata;
use aerodrome_extractor_pb::internal::{PoolsCreated, TokenMetadataAnswers};
use substreams_ethereum::pb::eth::rpc::{RpcCall, RpcCalls};
substreams_ethereum::init!();

#[substreams::handlers::map]
pub fn map_token_metadata(
    created: PoolsCreated,
) -> Result<TokenMetadataAnswers, substreams::errors::Error> {
    let tokens = metadata::tokens(&created).map_err(substreams::errors::Error::msg)?;
    if tokens.is_empty() {
        return Ok(TokenMetadataAnswers::default());
    }
    let requests = RpcCalls {
        calls: metadata::calls(&tokens)
            .into_iter()
            .map(|(token, selector)| RpcCall {
                to_addr: token.to_vec(),
                data: selector.to_vec(),
            })
            .collect(),
    };
    let response = substreams_ethereum::rpc::eth_call(&requests);
    metadata::answers(
        &tokens,
        response
            .responses
            .into_iter()
            .map(|r| metadata::Response {
                failed: r.failed,
                raw: r.raw,
            })
            .collect(),
    )
    .map_err(substreams::errors::Error::msg)
}
