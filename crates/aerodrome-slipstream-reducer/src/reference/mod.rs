//! Development M1 reference input from raw Firehose and an independent call
//! cassette. This native path is not live Substreams WASM qualification.
pub mod capture;
mod cassette;
use crate::{abi::Abis, refuse, require, Result};
use aerodrome_extractor_core::{
    answers::{self, Store, StoreRead},
    candidates::{self, EventDecoder},
    carry::{self, InMemoryCarry},
    config::{Config, INITIAL_BLOCK, PARAMS},
    events, storage, Address,
};
use aerodrome_extractor_pb::{eth, internal as i, v1 as p};
use backfill_common::clock::{Frame, FrameKind};
pub use cassette::Cassette;
use prost::Message;
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;

// Firehose emits fields in tag order. Reuse prost's wire parser but reject
// tag resets and duplicate singular identity fields before prost can merge
// concatenated block messages into a plausible single block.
fn decode_raw(bytes: &[u8]) -> Result<eth::Block> {
    use prost::encoding::{decode_key, skip_field, DecodeContext, WireType};
    let mut input = bytes;
    let mut previous = 0;
    while !input.is_empty() {
        let (tag, wire) = decode_key(&mut input).map_err(|e| refuse(e.to_string()))?;
        require(
            tag >= previous && !(tag == previous && matches!(tag, 1 | 2 | 3 | 4 | 5 | 12)),
            "raw block has unordered or repeated singular fields; possible concatenated messages",
        )?;
        require(
            !matches!(wire, WireType::StartGroup | WireType::EndGroup),
            "raw block has unsupported protobuf group",
        )?;
        skip_field(wire, tag, &mut input, DecodeContext::default())
            .map_err(|e| refuse(e.to_string()))?;
        previous = tag;
    }
    eth::Block::decode(bytes).map_err(|e| refuse(format!("raw Firehose protobuf: {e}")))
}

#[derive(Default)]
struct Stores {
    values: BTreeMap<Store, InMemoryCarry>,
    previous_ticks: BTreeMap<Address, i64>,
}
impl StoreRead for Stores {
    fn get(&self, store: Store, key: &str) -> std::result::Result<Option<Vec<u8>>, String> {
        Ok(self
            .values
            .get(&store)
            .and_then(|s| s.get(key))
            .map(Vec::from))
    }
    fn first_tick(&self, pool: &Address) -> std::result::Result<Option<i64>, String> {
        Ok(self.previous_ticks.get(pool).copied())
    }
}
struct Decoder;
fn candidate(source: p::DataSourceKind, log: &eth::Log) -> p::CandidateLog {
    p::CandidateLog {
        source: source as i32,
        address: log.address.clone(),
        topics: log.topics.clone(),
        data: log.data.clone(),
        ..Default::default()
    }
}
impl EventDecoder for Decoder {
    fn matches(&self, source: p::DataSourceKind, log: &eth::Log) -> bool {
        log.topics
            .first()
            .is_some_and(|topic| Abis::locked().event(source as i32, topic).is_some())
    }
    // Diagnostic only. Reference uses the exact Graph Node decoder; generated
    // Substreams diagnostic flags are a separate M2 comparison obligation.
    fn decoded(&self, source: p::DataSourceKind, log: &eth::Log) -> bool {
        Abis::locked()
            .decode(&candidate(source, log))
            .is_ok_and(|e| e.is_some())
    }
    fn pool_created(&self, log: &eth::Log) -> Option<i::PoolCreatedRecord> {
        let events::Event::PoolCreated {
            pool,
            token0,
            token1,
            spacing,
        } = events::decode(&candidate(p::DataSourceKind::Factory, log)).ok()??
        else {
            return None;
        };
        Some(i::PoolCreatedRecord {
            pool: pool.to_vec(),
            token0: token0.to_vec(),
            token1: token1.to_vec(),
            tick_spacing: spacing,
            ..Default::default()
        })
    }
}
/// Streaming, poisoned on any failure. Starts from the deployment root; no
/// arbitrary-height empty carry or unverified seed is accepted.
pub struct ReferenceExtractor {
    cfg: Config,
    cassette: Cassette,
    stores: Stores,
    registry: BTreeMap<Address, i::PoolRecord>,
    next: u64,
    stop: u64,
    parent: Option<[u8; 32]>,
    poisoned: bool,
    compared_calls: u64,
}
impl ReferenceExtractor {
    pub fn new(cassette: Cassette, stop_exclusive: u64) -> Result<Self> {
        require(
            stop_exclusive > INITIAL_BLOCK && stop_exclusive <= i32::MAX as u64,
            "invalid reference range",
        )?;
        cassette.range(INITIAL_BLOCK, stop_exclusive)?;
        Ok(Self {
            cfg: Config::parse(PARAMS).map_err(|e| refuse(e.to_string()))?,
            cassette,
            stores: Stores::default(),
            registry: BTreeMap::new(),
            next: INITIAL_BLOCK,
            stop: stop_exclusive,
            parent: None,
            poisoned: false,
            compared_calls: 0,
        })
    }
    pub fn compared_calls(&self) -> u64 {
        self.compared_calls
    }
    pub fn cassette_sha256(&self) -> &str {
        self.cassette.sha256()
    }
    pub fn process(&mut self, raw: Frame) -> Result<Frame> {
        require(!self.poisoned, "reference extractor is poisoned")?;
        self.poisoned = true;
        let output = self.process_inner(raw)?;
        self.poisoned = false;
        Ok(output)
    }
    fn process_inner(&mut self, raw: Frame) -> Result<Frame> {
        require(
            self.next < self.stop
                && raw.kind == FrameKind::Observed
                && raw.block_number == self.next
                && raw.block_hash != [0; 32]
                && !raw.payload.is_empty(),
            "raw clock identity/range mismatch",
        )?;
        let block = decode_raw(&raw.payload)?;
        require(
            block.number == raw.block_number && block.hash.as_slice() == raw.block_hash,
            "raw protobuf/clock mismatch",
        )?;
        let parent = crate::word(
            &block
                .header
                .as_ref()
                .ok_or_else(|| refuse("missing raw header"))?
                .parent_hash,
        )?;
        require(
            parent != [0; 32] && self.parent.is_none_or(|p| p == parent),
            "raw parent chain mismatch",
        )?;
        let created = candidates::pools_created(&self.cfg, &block, &Decoder);
        for pool in &created.pools {
            let address = crate::address(&pool.pool)?;
            require(
                !self.registry.contains_key(&address),
                "duplicate pool creation",
            )?;
            self.registry.insert(
                address,
                i::PoolRecord {
                    token0: pool.token0.clone(),
                    token1: pool.token1.clone(),
                    tick_spacing: pool.tick_spacing,
                    created_block: block.number,
                    created_log_index: pool.log_index,
                },
            );
        }
        let deltas = storage::storage_deltas(&self.cfg, &block, &self.registry).map_err(refuse)?;
        let candidates = candidates::build_candidates(&self.cfg, &block, &self.registry, &Decoder)
            .map_err(refuse)?;
        // Apply end-of-block values before answering calls; previous_ticks is
        // intentionally unchanged until all answers have been derived.
        self.stores
            .values
            .entry(Store::Pools)
            .or_default()
            .apply(&carry::registry_ops(&created, block.number).map_err(refuse)?);
        self.stores
            .values
            .entry(Store::PoolSlots)
            .or_default()
            .apply(&carry::pool_slot_ops(&deltas, block.number).map_err(refuse)?);
        for n in 0..8 {
            self.stores
                .values
                .entry(Store::Tick(n))
                .or_default()
                .apply(&carry::tick_slot_ops(&deltas, block.number, n).map_err(refuse)?);
        }
        for n in 0..16 {
            self.stores
                .values
                .entry(Store::Position(n))
                .or_default()
                .apply(&carry::position_slot_ops(&deltas, block.number, n).map_err(refuse)?);
        }
        let ticks = answers::tick_answers(&candidates, &self.stores).map_err(refuse)?;
        let positions = answers::position_answers(&candidates, &self.stores).map_err(refuse)?;
        let metadata = self.cassette.metadata(&candidates)?;
        let mut output =
            answers::assemble(candidates, deltas, ticks, positions, metadata, &self.stores)
                .map_err(refuse)?;
        self.cassette
            .supplement_get_pool(&mut output, &self.stores, &self.cfg)?;
        self.compared_calls += self.cassette.verify(&output, &self.cfg)? as u64;
        let frame = Frame {
            kind: FrameKind::Observed,
            block_number: block.number,
            block_hash: raw.block_hash,
            payload: output.encode_to_vec(),
        };
        // Reuse the consumer's complete structural/call/provenance checks.
        crate::input::validate_block(&frame, parent)?;
        for (key, tick, _) in carry::last_tick_ops(&output).map_err(refuse)? {
            let key = key
                .strip_prefix("t:")
                .and_then(|s| s.strip_suffix(';'))
                .ok_or_else(|| refuse("bad tick carry key"))?;
            let address =
                crate::address(&hex::decode(key).map_err(|_| refuse("bad tick carry address"))?)?;
            self.stores.previous_ticks.insert(address, tick);
        }
        self.parent = Some(raw.block_hash);
        self.next += 1;
        Ok(frame)
    }
    /// Only a range check; the caller must separately establish input EOF and
    /// verify the capture receipt's raw-stream digest and successful producer.
    pub fn finish(&self) -> Result<()> {
        require(
            !self.poisoned && self.next == self.stop,
            "reference extractor incomplete or poisoned",
        )
    }
}

#[cfg(test)]
mod tests;
