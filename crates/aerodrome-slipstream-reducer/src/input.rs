use crate::{
    abi::{Abis, DecodedEvent},
    address,
    calls::CallBook,
    identity::InputBinding,
    pb, refuse, require, unsigned, word, Result,
};
use aerodrome_extractor_core::{
    config::{Config, CONTRACT, INITIAL_BLOCK, PARAMS},
    gas::graph_node_gas_price,
};
use alloy_dyn_abi::DynSolValue;
use backfill_common::clock::{self, Frame, FrameKind, ObservedRange};
use prost::Message;
use std::{
    collections::{BTreeMap, BTreeSet},
    io::Read,
};

#[derive(Debug)]
pub struct BlockInput {
    pub(crate) block: pb::ExtractorBlock,
    pub(crate) decoded: Vec<Option<DecodedEvent>>,
    calls: CallBook,
    gas_prices: Vec<u128>,
}
impl BlockInput {
    pub fn block(&self) -> &pb::ExtractorBlock {
        &self.block
    }
    pub fn decoded(&self) -> &[Option<DecodedEvent>] {
        &self.decoded
    }
    pub fn calls(&self) -> &CallBook {
        &self.calls
    }
    pub fn gas_prices(&self) -> &[u128] {
        &self.gas_prices
    }
}
/// Structural/ABI validation only. A later runner must apply its authoritative
/// committed host set; `decoded` alone is not permission to execute a handler.
pub fn validate_block(frame: &Frame, parent_hash: [u8; 32]) -> Result<BlockInput> {
    require(
        frame.kind == FrameKind::Observed && !frame.payload.is_empty(),
        "reducer requires a nonempty Observed frame",
    )?;
    require(
        frame.block_hash != [0; 32] && frame.block_number <= clock::MAX_BLOCK_NUMBER,
        "invalid envelope identity",
    )?;
    let b = pb::ExtractorBlock::decode(frame.payload.as_slice())
        .map_err(|e| refuse(format!("extractor protobuf: {e}")))?;
    require(
        b.encode_to_vec() == frame.payload,
        "extractor protobuf is not canonical or has unknown fields",
    )?;
    require(b.contract == CONTRACT, "extractor contract mismatch")?;
    require(
        matches!(b.firehose_block_version, 4 | 5),
        "unsupported Firehose block version",
    )?;
    require(
        b.number == frame.block_number && b.hash == frame.block_hash,
        "extractor/envelope block identity mismatch",
    )?;
    require(
        b.parent_hash == parent_hash && parent_hash != [0; 32],
        "parent hash mismatch or zero boundary",
    )?;
    require(
        b.number >= INITIAL_BLOCK && b.timestamp > 0 && b.timestamp <= i64::MAX as u64,
        "block precedes deployment or has no timestamp",
    )?;
    require(
        b.receipt_log_count <= (1 << 24),
        "receipt count exceeds the host-order encoding",
    )?;
    let audit = b
        .audit
        .as_ref()
        .ok_or_else(|| refuse("missing extractor audit"))?;
    require(
        audit.anomalies.is_empty(),
        "ExtractorAnomaly: block has extractor anomalies",
    )?;
    require(
        audit.candidate_decode_failures as usize
            == b.candidates.iter().filter(|c| !c.abi_decoded).count(),
        "decode-failure audit count mismatch",
    )?;
    let mut tx_hashes = BTreeSet::new();
    let mut last_index = None;
    let mut prices = Vec::new();
    for tx in &b.transactions {
        let hash = word(&tx.hash)?;
        require(
            hash != [0; 32] && tx_hashes.insert(hash),
            "zero or duplicate transaction hash",
        )?;
        address(&tx.from)?;
        require(
            tx.to.is_empty() || tx.to.len() == 20,
            "transaction recipient must be empty or 20 bytes",
        )?;
        require(
            last_index.is_none_or(|i| i < tx.index),
            "transactions must have unique ascending indexes",
        )?;
        last_index = Some(tx.index);
        require(
            tx.r#type <= i32::MAX as u32,
            "transaction type exceeds Firehose int32",
        )?;
        for bytes in [
            &tx.gas_price,
            &tx.max_fee_per_gas,
            &tx.max_priority_fee_per_gas,
        ]
        .into_iter()
        .flatten()
        {
            unsigned(bytes, 16)?;
        }
        let price = graph_node_gas_price(
            tx.r#type,
            tx.gas_price.as_deref(),
            tx.max_fee_per_gas.as_deref(),
            tx.max_priority_fee_per_gas.as_deref(),
            b.base_fee_per_gas,
        )
        .map_err(|e| refuse(e.to_string()))?;
        unsigned(&tx.graph_gas_price, 16)?;
        require(
            tx.graph_gas_price == aerodrome_extractor_core::minimal(&price.to_be_bytes()),
            "graph_gas_price cross-check mismatch",
        )?;
        prices.push(price);
    }
    let cfg = Config::parse(PARAMS).unwrap();
    let abi = Abis::locked();
    let mut facts = BTreeMap::new();
    let mut fact_log = None;
    for fact in &b.pools_created {
        let pool = address(&fact.pool)?;
        address(&fact.token0)?;
        address(&fact.token1)?;
        crate::int24(fact.tick_spacing)?;
        require(
            fact.tick_spacing > 0 && pool != [0; 20],
            "invalid pool creation",
        )?;
        require(
            fact.clone_implementation == cfg.pool_implementation,
            "pool implementation mismatch",
        )?;
        require(
            fact.log_index < b.receipt_log_count && fact_log.is_none_or(|i| i < fact.log_index),
            "pool creation facts out of order",
        )?;
        fact_log = Some(fact.log_index);
        require(
            facts.insert(pool, fact).is_none(),
            "duplicate pool creation",
        )?;
    }
    let mut prior = None;
    let mut log_indexes = BTreeSet::new();
    let mut references = BTreeSet::new();
    let mut decoded = Vec::new();
    let mut observed_facts = Vec::new();
    for c in &b.candidates {
        require(
            c.wave <= 1
                && c.source_trigger_order == c.log_index
                && c.log_index < b.receipt_log_count,
            "invalid candidate order coordinates",
        )?;
        let key = (c.wave, c.source_trigger_order);
        require(
            prior.is_none_or(|previous| previous < key) && log_indexes.insert(c.log_index),
            "candidates repeated or out of order",
        )?;
        prior = Some(key);
        require(
            (c.tx as usize) < b.transactions.len(),
            "candidate transaction out of range",
        )?;
        references.insert(c.tx);
        let addr = address(&c.address)?;
        for topic in &c.topics {
            word(topic)?;
        }
        require(c.log_ordinal > 0, "candidate has zero ordinal")?;
        match pb::DataSourceKind::try_from(c.source).ok() {
            Some(pb::DataSourceKind::Factory) => require(
                addr == cfg.factory && c.wave == 0 && c.host_order_key == 0,
                "wrong Factory source",
            )?,
            Some(pb::DataSourceKind::PositionManager) => require(
                addr == cfg.npm
                    && b.number >= cfg.npm_start
                    && c.wave == 0
                    && c.host_order_key == 1,
                "wrong NPM source/start",
            )?,
            Some(pb::DataSourceKind::Pool) => {
                require(
                    addr != cfg.factory && addr != cfg.npm && addr != [0; 20],
                    "invalid pool emitter",
                )?;
                if let Some(fact) = facts.get(&addr) {
                    require(
                        c.wave == 1
                            && c.host_order_key
                                == 2 + b.number * (1 << 24) + u64::from(fact.log_index),
                        "new-pool wave/host-order mismatch",
                    )?;
                } else {
                    require(
                        c.wave == 0
                            && c.host_order_key >= 2 + INITIAL_BLOCK * (1 << 24)
                            && c.host_order_key < 2 + b.number * (1 << 24),
                        "prior-pool wave/host-order mismatch",
                    )?;
                }
            }
            _ => return Err(refuse("unknown candidate source kind")),
        }
        require(
            c.topics
                .first()
                .is_some_and(|topic| abi.event(c.source, topic).is_some()),
            "candidate has no locked event signature",
        )?;
        let event = abi.decode(c)?;
        if c.source == pb::DataSourceKind::Factory as i32 {
            if let Some(event) = &event {
                let field_address = |name| match event.param(name) {
                    Some(DynSolValue::Address(a)) => Ok(a.into_array()),
                    _ => Err(refuse("PoolCreated address ABI mismatch")),
                };
                let pool = field_address("pool")?;
                let fact = facts
                    .get(&pool)
                    .ok_or_else(|| refuse("decoded PoolCreated has no fact"))?;
                let spacing = match event.param("tickSpacing") {
                    Some(DynSolValue::Int(v, _)) => v
                        .to_string()
                        .parse::<i32>()
                        .map_err(|_| refuse("PoolCreated spacing exceeds i32"))?,
                    _ => return Err(refuse("PoolCreated spacing ABI mismatch")),
                };
                require(
                    fact.token0 == field_address("token0")?
                        && fact.token1 == field_address("token1")?
                        && fact.tick_spacing == spacing
                        && fact.log_index == c.log_index
                        && fact.log_ordinal == c.log_ordinal,
                    "PoolCreated fact differs from decoded event",
                )?;
                observed_facts.push(pool);
            }
        }
        decoded.push(event);
    }
    require(
        references.len() == b.transactions.len(),
        "transaction table contains unreferenced entries",
    )?;
    require(
        observed_facts
            == b.pools_created
                .iter()
                .map(|p| address(&p.pool).unwrap())
                .collect::<Vec<_>>(),
        "pool facts do not equal decoded Factory candidates",
    )?;
    let calls = CallBook::from_block(&b)?;
    Ok(BlockInput {
        block: b,
        decoded,
        calls,
        gas_prices: prices,
    })
}

/// Reads a required inclusive block range. Any read/validation error poisons
/// the stream; `finish` requires real EOF after all requested observed blocks.
pub struct InputStream<R> {
    reader: R,
    range: Option<ObservedRange>,
    parent: [u8; 32],
    failed: bool,
    eof: bool,
    binding: InputBinding,
}
impl<R: Read> InputStream<R> {
    pub fn new(
        reader: R,
        binding: InputBinding,
        start: u64,
        end_inclusive: u64,
        parent: [u8; 32],
    ) -> Result<Self> {
        require(
            start >= INITIAL_BLOCK
                && start <= end_inclusive
                && end_inclusive <= clock::MAX_BLOCK_NUMBER
                && parent != [0; 32],
            "invalid required reducer range/boundary",
        )?;
        Ok(Self {
            reader,
            range: Some(
                ObservedRange::new(start, end_inclusive + 1).map_err(|e| refuse(e.to_string()))?,
            ),
            parent,
            failed: false,
            eof: false,
            binding,
        })
    }
    pub fn next_block(&mut self) -> Result<Option<BlockInput>> {
        require(
            !self.failed && !self.eof,
            "input stream already failed or reached EOF",
        )?;
        let result = (|| {
            let Some(frame) = clock::read_frame(&mut self.reader, clock::MAX_PAYLOAD_LEN)
                .map_err(|e| refuse(e.to_string()))?
            else {
                self.range
                    .take()
                    .unwrap()
                    .finish()
                    .map_err(|e| refuse(e.to_string()))?;
                self.eof = true;
                return Ok(None);
            };
            self.range
                .as_mut()
                .unwrap()
                .accept(&frame)
                .map_err(|e| refuse(e.to_string()))?;
            let block = validate_block(&frame, self.parent)?;
            self.parent = frame.block_hash;
            Ok(Some(block))
        })();
        if result.is_err() {
            self.failed = true;
        }
        result
    }
    pub fn finish(self) -> Result<[u8; 32]> {
        require(
            self.eof && !self.failed,
            "input range completion has not been proven",
        )?;
        Ok(self.parent)
    }
    pub fn binding(&self) -> &InputBinding {
        &self.binding
    }
}
