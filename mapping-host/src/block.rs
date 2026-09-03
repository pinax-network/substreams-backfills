//! Firehose block input.
//!
//! A fixture file is one or more bare `sf.ethereum.type.v2.Block` protobufs
//! concatenated with no framing. `graph_chain_ethereum::codec::Block` is the
//! prost type for them, and graph-node's own `TryInto<BlockFinality>`
//! (`chain/ethereum/src/codec.rs:467`) turns each into the
//! `EthereumBlockWithCalls` the runtime expects, including the per-transaction
//! receipts that carry the logs.
//!
//! ## One block per file, enforced
//!
//! A fixture must hold exactly one message. Handing a two-message file to
//! `Block::decode` is silently wrong rather than an error: prost merges them, so
//! scalar fields come from the last block while `transaction_traces` is the
//! union of both, producing a block that claims to be `N+1` while carrying `N`'s
//! logs as well. That is what release `block-fixtures-v1` shipped, and what
//! `block-fixtures-v2` fixed by re-cutting every file.
//!
//! [`load_block`] refuses a multi-message file rather than trusting the release
//! tag, and names the second block in the error. [`split_messages`] exists only
//! as the detector behind that refusal. Protobuf gives no framing, but this
//! encoder emits top-level fields in ascending tag order, so a tag lower than the
//! previous one starts a new message (a repeated field repeats its tag, so only a
//! decrease counts), and the field that opens a message must be `ver`. A stream
//! that does not split cleanly is an error, never a guess.
//!
//! Trigger construction mirrors `parse_log_triggers`
//! (`chain/ethereum/src/ethereum_adapter.rs:1932`), which is `pub(crate)` and so
//! has to be reproduced rather than called. Note what it does: once the log
//! filter is non-empty it emits a trigger for **every** log in the block, in
//! receipt order, and leaves address and topic matching to
//! `DataSource::match_and_decode`. We do exactly the same, so a trigger list here
//! is the same list Graph Node would build.
//!
//! Uniswap V3 declares only event handlers, so `EthereumTrigger::Call` and
//! `EthereumTrigger::Block` are never produced. [`log_triggers`] asserts that by
//! construction: it is the only trigger source, and [`block_triggers`] refuses a
//! manifest that declares call or block handlers rather than silently dropping
//! them.

use std::path::Path;
use std::sync::Arc;

use anyhow::{anyhow, bail, Context, Result};
use graph::blockchain::block_stream::BlockWithTriggers;
use graph::blockchain::Block as _;
use graph::components::ethereum::EthereumBlock;
use graph::prelude::prost::Message;
use graph::prelude::Logger;
use graph_chain_ethereum::chain::BlockFinality;
use graph_chain_ethereum::codec;
use graph_chain_ethereum::trigger::{EthereumTrigger, LogPosition, LogRef};
use graph_chain_ethereum::{Chain, DataSource};

/// Read the single `sf.ethereum.type.v2.Block` a fixture file must contain.
///
/// A file with more than one message is refused, naming the second block, so a
/// silent prost merge can never reach the runtime.
pub fn load_block(path: &Path) -> Result<BlockFinality> {
    let bytes =
        std::fs::read(path).with_context(|| format!("reading block fixture {}", path.display()))?;
    let chunks = split_messages(&bytes)
        .with_context(|| format!("splitting {} into block messages", path.display()))?;

    let (offset, first) = *chunks
        .first()
        .ok_or_else(|| anyhow!("{}: no blocks in fixture", path.display()))?;
    if chunks.len() > 1 {
        let (second_offset, second) = chunks[1];
        let second_number = codec::Block::decode(second)
            .map(|block| block.number.to_string())
            .unwrap_or_else(|_| "<undecodable>".to_string());
        bail!(
            "{}: a fixture must hold exactly one block, but {} messages are concatenated; the \
             second is block {second_number} at offset {second_offset}. Re-hydrate from release \
             block-fixtures-v2 with `cargo xtask evidence fetch --lock \
             uniswap-v3/fixtures/blocks.lock.json`",
            path.display(),
            chunks.len()
        );
    }

    let block = codec::Block::decode(first).with_context(|| {
        format!(
            "decoding {} at offset {offset} as sf.ethereum.type.v2.Block",
            path.display()
        )
    })?;
    (&block)
        .try_into()
        .map_err(|e| anyhow!("converting {} to BlockFinality: {e}", path.display()))
}

/// Split a concatenation of protobuf messages that were serialised with
/// ascending field tags. Returns `(offset, bytes)` per message.
///
/// Every message must start with field 1 (`ver`), which is how a boundary is
/// confirmed rather than merely guessed.
pub fn split_messages(bytes: &[u8]) -> Result<Vec<(usize, &[u8])>> {
    const VER_FIELD: u64 = 1;

    let mut chunks = Vec::new();
    let mut start = 0usize;
    let mut cursor = 0usize;
    let mut previous_field: Option<u64> = None;

    while cursor < bytes.len() {
        let tag_start = cursor;
        let (key, next) = read_varint(bytes, cursor)
            .ok_or_else(|| anyhow!("truncated field tag at offset {tag_start}"))?;
        cursor = next;
        let field = key >> 3;
        let wire_type = key & 7;

        // A repeated field emits the same tag many times, so only a *decrease*
        // marks a boundary.
        let new_message = previous_field.is_some_and(|previous| field < previous);
        if new_message {
            if field != VER_FIELD {
                bail!(
                    "message boundary at offset {tag_start} starts with field {field}, not `ver`"
                );
            }
            chunks.push((start, &bytes[start..tag_start]));
            start = tag_start;
        }
        previous_field = Some(field);

        match wire_type {
            0 => {
                let (_, next) = read_varint(bytes, cursor)
                    .ok_or_else(|| anyhow!("truncated varint at offset {cursor}"))?;
                cursor = next;
            }
            1 => cursor += 8,
            2 => {
                let (len, next) = read_varint(bytes, cursor)
                    .ok_or_else(|| anyhow!("truncated length at offset {cursor}"))?;
                cursor = next
                    .checked_add(len as usize)
                    .ok_or_else(|| anyhow!("length overflow at offset {next}"))?;
            }
            5 => cursor += 4,
            other => bail!("unsupported wire type {other} at offset {tag_start}"),
        }
        if cursor > bytes.len() {
            bail!("field at offset {tag_start} runs past the end of the buffer");
        }
    }

    chunks.push((start, &bytes[start..]));
    Ok(chunks)
}

fn read_varint(bytes: &[u8], mut i: usize) -> Option<(u64, usize)> {
    let mut value = 0u64;
    let mut shift = 0u32;
    loop {
        let byte = *bytes.get(i)?;
        i += 1;
        value |= u64::from(byte & 0x7f) << shift;
        if byte & 0x80 == 0 {
            return Some((value, i));
        }
        shift += 7;
        if shift > 63 {
            return None;
        }
    }
}

fn ethereum_block(block: &BlockFinality) -> Result<&EthereumBlock> {
    match block {
        BlockFinality::NonFinal(full) => Ok(&full.ethereum_block),
        BlockFinality::Final(_) => {
            bail!("a Firehose fixture must convert to BlockFinality::NonFinal, got Final")
        }
        BlockFinality::Ptr(_) => {
            bail!("a Firehose fixture must convert to BlockFinality::NonFinal, got Ptr")
        }
    }
}

/// Whether any handler in `data_sources` asked for the transaction receipt.
///
/// This is the flag `EthereumLogFilter::requires_transaction_receipt` computes;
/// that filter is `pub(crate)`, so we derive the same answer from the handlers,
/// which is where the filter reads it from in the first place. Getting it wrong
/// would change `event.receipt` inside the mapping, so it is computed rather than
/// hardcoded to `false`.
fn requires_receipt(data_sources: &[&DataSource]) -> bool {
    data_sources
        .iter()
        .flat_map(|ds| ds.mapping.event_handlers.iter())
        .any(|handler| handler.receipt)
}

/// Every log in the block, as `EthereumTrigger::Log`, in receipt order.
pub fn log_triggers(
    block: &BlockFinality,
    data_sources: &[&DataSource],
) -> Result<Vec<EthereumTrigger>> {
    let eth_block = ethereum_block(block)?;
    let requires_transaction_receipt = requires_receipt(data_sources);

    let total: usize = eth_block
        .transaction_receipts
        .iter()
        .map(|r| r.logs().len())
        .sum();
    let mut triggers = Vec::with_capacity(total);
    for receipt in &eth_block.transaction_receipts {
        for (index, _log) in receipt.logs().iter().enumerate() {
            triggers.push(EthereumTrigger::Log(LogRef::LogPosition(LogPosition {
                index,
                receipt: receipt.clone(),
                requires_transaction_receipt,
            })));
        }
    }
    Ok(triggers)
}

/// Build the sorted, deduplicated trigger list for one execution stage.
///
/// The sort and dedup are `BlockWithTriggers::new`, which is where Graph Node's
/// trigger determinism actually lives (`impl Ord for EthereumTrigger`), so it is
/// reused verbatim rather than reimplemented.
pub fn block_triggers(
    block: &BlockFinality,
    data_sources: &[&DataSource],
    logger: &Logger,
) -> Result<Vec<EthereumTrigger>> {
    for ds in data_sources {
        if !ds.mapping.call_handlers.is_empty() {
            bail!(
                "data source `{}` declares call handlers; this host only builds log triggers",
                ds.name
            );
        }
        if !ds.mapping.block_handlers.is_empty() {
            bail!(
                "data source `{}` declares block handlers; this host only builds log triggers",
                ds.name
            );
        }
    }

    let triggers = log_triggers(block, data_sources)?;
    // `BlockWithTriggers::new` takes the block by value; clone the header-level
    // wrapper rather than the receipts, which are already behind `Arc`.
    let with_triggers: BlockWithTriggers<Chain> =
        BlockWithTriggers::new(block.clone(), triggers, logger);
    Ok(with_triggers
        .trigger_data
        .into_iter()
        .filter_map(|t| t.as_chain().cloned())
        .collect())
}

/// A block's identity, for the report.
pub struct BlockIdentity {
    pub number: i32,
    pub hash: String,
    pub parent_hash: Option<String>,
    pub timestamp: i64,
}

pub fn identify(block: &BlockFinality) -> BlockIdentity {
    let ptr = block.ptr();
    BlockIdentity {
        number: ptr.number,
        hash: format!("0x{}", hex::encode(ptr.hash_slice())),
        parent_hash: block
            .parent_ptr()
            .map(|p| format!("0x{}", hex::encode(p.hash_slice()))),
        timestamp: block.timestamp().as_secs_since_epoch(),
    }
}

/// The transaction hash and log index identifying a log trigger.
pub fn trigger_identity(trigger: &EthereumTrigger) -> Result<(String, u64, String)> {
    match trigger {
        EthereumTrigger::Log(log_ref) => {
            let log = log_ref.log();
            let tx = log
                .transaction_hash
                .ok_or_else(|| anyhow!("log trigger without a transaction hash"))?;
            let index = log_ref
                .log_index()
                .ok_or_else(|| anyhow!("log trigger without a log index"))?;
            Ok((
                format!("0x{}", hex::encode(tx.as_slice())),
                index,
                format!("0x{}", hex::encode(log_ref.address().as_slice())),
            ))
        }
        other => bail!("unexpected non-log trigger: {other:?}"),
    }
}

/// The `Arc` wrapper the runtime host wants for a block.
pub fn shared(block: BlockFinality) -> Arc<BlockFinality> {
    Arc::new(block)
}
