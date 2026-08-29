//! Deterministic, provider-free source frames for host-side NPM execution.
//!
//! This module accepts only a Firehose block and the exact upstream
//! `map_writer_events` output. It contains no RPC, Store, database, reducer,
//! checkpoint, or `graph_out` integration.

use std::collections::BTreeSet;

use prost::Message;
use serde::Deserialize;
use sha2::{Digest, Sha256};
use substreams::errors::Error;
use substreams_ethereum::pb::eth::v2::{Block, TransactionTraceStatus};

use crate::pb::npm_source::{BlockRef, NpmSourceBlock, TransactionRef};
use crate::pb::writer::WriterEvents;

pub const SOURCE_CONTRACT_SHA256: &str = "267dfc6b7240c36cdf345553e02a4f7b5332fa70548349bc6ef4b3075b4fcb4b";
const PROFILE_SET_SHA256: &str = "2b6635c061a7a0bfce39430c71c41dacc1567f095fe41134e890a697aa27f823";
const PROFILE_CONTRACT_VERSION: &str = "uniswap-v3-writer-runtime-segment-profiles/v1";
const SOURCE_WRITER_CONTRACT_SHA256: &str = "259481724561d5aa725c17f90b5a19ea93ad6f7cd6074cf2cb8a8661c39f81c4";
const SOURCE_WRITER_PROTO_SHA256: &str = "f87b4bc718349bae2ff8fe799e4a4dadbb507240b7b6e9bc8d7a199299e33c59";
const SOURCE_SEGMENT_MATRIX_SHA256: &str = "7f6d1a34a8c885fe5ddcd81895818ba7ae8a0d736d541b881c1cc7cd54275161";
const SOURCE_EXECUTION_ORDER_SHA256: &str = "241e970cfcec4d76610b29a10141d3bff2512d80454a6308594f3db23621cde2";
const SOURCE_WRITER_CONTRACT_VERSION: &str = "uniswap-v3-writer-compatibility/v3";
const MAX_PROTOBUF_TIMESTAMP_SECONDS: i64 = 253_402_300_799;

const MAINNET_MANAGER: [u8; 20] = [
    0xc3, 0x64, 0x42, 0xb4, 0xa4, 0x52, 0x2e, 0x87, 0x13, 0x99, 0xcd, 0x71, 0x7a, 0xbd, 0xd8, 0x47, 0xab, 0x11, 0xfe,
    0x88,
];
const BASE_MANAGER: [u8; 20] = [
    0x03, 0xa5, 0x20, 0xb3, 0x2c, 0x04, 0xbf, 0x3b, 0xee, 0xf7, 0xbe, 0xb7, 0x2e, 0x91, 0x9c, 0xf8, 0x22, 0xed, 0x34,
    0xf1,
];

const EXPECTED_RANGES: &[(&str, u64, Option<u64>)] = &[
    ("mainnet", 12_369_621, Some(13_450_880)),
    ("mainnet", 13_450_881, Some(13_498_328)),
    ("mainnet", 13_498_329, Some(13_591_197)),
    ("mainnet", 13_591_198, Some(13_605_860)),
    ("mainnet", 13_605_861, Some(19_470_000)),
    ("mainnet", 19_470_001, None),
    ("base", 1_371_679, Some(19_852_000)),
    ("base", 19_852_001, None),
];

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct SourceContract {
    format_version: u32,
    contract_version: String,
    mode: String,
    source_writer_runtime_sha256: String,
    source_writer_profiles_sha256: String,
    source_writer_contract_sha256: String,
    source_writer_proto_sha256: String,
    source_segment_matrix_sha256: String,
    source_execution_order_sha256: String,
    protobuf_namespace: String,
    output_type: String,
    provider_observations_serialized: bool,
    unresolved_errors_serialized: bool,
    checkpoint_authority: bool,
    graph_block_success_authority: bool,
    backfill_ready: bool,
    production_ready: bool,
}

#[derive(Debug, Deserialize)]
struct SegmentProfiles {
    format_version: u32,
    profile_contract_version: String,
    profiles: Vec<SegmentProfile>,
    source_writer_contract: SourceWriterContract,
}

#[derive(Debug, Deserialize)]
struct SourceWriterContract {
    contract_version: String,
    raw_sha256: String,
}

#[derive(Debug, Deserialize)]
struct SegmentProfile {
    network: String,
    start_block_inclusive: u64,
    end_block_inclusive: Option<u64>,
    segment_id: String,
    semantic_contract_sha256: String,
}

impl SegmentProfiles {
    fn embedded() -> Result<Self, Error> {
        let raw = include_str!("../configs/segment-profiles-v1.json");
        if sha256(raw.as_bytes()) != PROFILE_SET_SHA256 {
            return Err(Error::msg("NPM source writer-profile digest drift"));
        }
        let profiles: Self = serde_json::from_str(raw)
            .map_err(|error| Error::msg(format!("invalid NPM source writer profiles: {error}")))?;
        profiles.validate()?;
        Ok(profiles)
    }

    fn validate(&self) -> Result<(), Error> {
        if self.format_version != 1
            || self.profile_contract_version != PROFILE_CONTRACT_VERSION
            || self.source_writer_contract.contract_version != SOURCE_WRITER_CONTRACT_VERSION
            || self.source_writer_contract.raw_sha256 != SOURCE_WRITER_CONTRACT_SHA256
            || self.profiles.len() != EXPECTED_RANGES.len()
        {
            return Err(Error::msg("NPM source writer-profile binding drift"));
        }
        for (profile, expected) in self.profiles.iter().zip(EXPECTED_RANGES) {
            if (
                profile.network.as_str(),
                profile.start_block_inclusive,
                profile.end_block_inclusive,
            ) != *expected
                || profile.segment_id.is_empty()
                || !valid_sha256(&profile.semantic_contract_sha256)
            {
                return Err(Error::msg("NPM source writer-profile range or identity drift"));
            }
        }
        Ok(())
    }

    fn select(&self, network: &str, block_number: u64) -> Result<&SegmentProfile, Error> {
        let mut matches = self.profiles.iter().filter(|profile| {
            profile.network == network
                && profile.start_block_inclusive <= block_number
                && profile.end_block_inclusive.map_or(true, |end| block_number <= end)
        });
        let profile = matches
            .next()
            .ok_or_else(|| Error::msg(format!("no NPM source segment for {network} block {block_number}")))?;
        if matches.next().is_some() {
            return Err(Error::msg(format!(
                "overlapping NPM source segments for {network} block {block_number}"
            )));
        }
        Ok(profile)
    }
}

pub fn build_npm_source_block(block: &Block, writer_events: &WriterEvents) -> Result<NpmSourceBlock, Error> {
    verify_source_contract()?;
    let header = validate_firehose_block(block)?;
    let profiles = SegmentProfiles::embedded()?;
    validate_writer_events(writer_events, block.number, &profiles)?;
    let timestamp = header.timestamp.as_ref().expect("validated timestamp");
    let output = NpmSourceBlock {
        writer_events: Some(writer_events.clone()),
        block: Some(BlockRef {
            number: block.number,
            hash: block.hash.clone(),
            parent_hash: header.parent_hash.clone(),
            timestamp_seconds: timestamp.seconds as u64,
        }),
        transactions: extract_transactions(block, writer_events)?,
        source_contract_sha256: SOURCE_CONTRACT_SHA256.to_owned(),
    };
    validate_npm_source_block(&output)?;
    Ok(output)
}

pub fn decode_npm_source_block(bytes: &[u8]) -> Result<NpmSourceBlock, Error> {
    let output =
        NpmSourceBlock::decode(bytes).map_err(|error| Error::msg(format!("invalid NPM source protobuf: {error}")))?;
    if output.encode_to_vec() != bytes {
        return Err(Error::msg(
            "NPM source protobuf is noncanonical or contains unknown fields",
        ));
    }
    validate_npm_source_block(&output)?;
    Ok(output)
}

pub fn validate_npm_source_block(output: &NpmSourceBlock) -> Result<(), Error> {
    verify_source_contract()?;
    if output.source_contract_sha256 != SOURCE_CONTRACT_SHA256 {
        return Err(Error::msg("NPM source contract digest drift"));
    }
    let block = output
        .block
        .as_ref()
        .ok_or_else(|| Error::msg("NPM source block reference is missing"))?;
    exact_array::<32>("NPM source block hash", &block.hash)?;
    exact_array::<32>("NPM source parent hash", &block.parent_hash)?;
    if !(1..=MAX_PROTOBUF_TIMESTAMP_SECONDS as u64).contains(&block.timestamp_seconds) {
        return Err(Error::msg(
            "NPM source timestamp must be in the positive protobuf Timestamp range",
        ));
    }
    let writer_events = output
        .writer_events
        .as_ref()
        .ok_or_else(|| Error::msg("NPM source WriterEvents are missing"))?;
    let profiles = SegmentProfiles::embedded()?;
    validate_writer_events(writer_events, block.number, &profiles)?;
    validate_transactions(&output.transactions, writer_events)
}

fn verify_source_contract() -> Result<(), Error> {
    let raw = include_str!("../configs/npm-source-block-v1.json");
    if sha256(raw.as_bytes()) != SOURCE_CONTRACT_SHA256 {
        return Err(Error::msg("NPM source semantic contract digest drift"));
    }
    let contract: SourceContract = serde_json::from_str(raw)
        .map_err(|error| Error::msg(format!("invalid NPM source semantic contract: {error}")))?;
    if contract.format_version != 1
        || contract.contract_version != "uniswap-v3-npm-source-block/v1"
        || contract.mode != "provider-free-source-only"
        || contract.source_writer_runtime_sha256 != "765806bf19fca7695ef4d97f557593e4f791759589fe55c20f18c6523a5d07ca"
        || contract.source_writer_profiles_sha256 != PROFILE_SET_SHA256
        || contract.source_writer_contract_sha256 != SOURCE_WRITER_CONTRACT_SHA256
        || contract.source_writer_proto_sha256 != SOURCE_WRITER_PROTO_SHA256
        || contract.source_segment_matrix_sha256 != SOURCE_SEGMENT_MATRIX_SHA256
        || contract.source_execution_order_sha256 != SOURCE_EXECUTION_ORDER_SHA256
        || contract.protobuf_namespace != "uniswap.npm.source.v1"
        || contract.output_type != "proto:uniswap.npm.source.v1.NpmSourceBlock"
        || contract.provider_observations_serialized
        || contract.unresolved_errors_serialized
        || contract.checkpoint_authority
        || contract.graph_block_success_authority
        || contract.backfill_ready
        || contract.production_ready
    {
        return Err(Error::msg("NPM source semantic contract binding drift"));
    }
    Ok(())
}

fn validate_firehose_block(block: &Block) -> Result<&substreams_ethereum::pb::eth::v2::BlockHeader, Error> {
    let block_hash = exact_array::<32>("Firehose block hash", &block.hash)?;
    let header = block
        .header
        .as_ref()
        .ok_or_else(|| Error::msg("Firehose block header is missing"))?;
    if header.number != block.number {
        return Err(Error::msg("Firehose block/header number drift"));
    }
    if exact_array::<32>("Firehose header hash", &header.hash)? != block_hash {
        return Err(Error::msg("Firehose block/header hash drift"));
    }
    exact_array::<32>("Firehose parent hash", &header.parent_hash)?;
    let timestamp = header
        .timestamp
        .as_ref()
        .ok_or_else(|| Error::msg("Firehose block timestamp is missing"))?;
    if !(1..=MAX_PROTOBUF_TIMESTAMP_SECONDS).contains(&timestamp.seconds) || timestamp.nanos != 0 {
        return Err(Error::msg(
            "Firehose block timestamp must be a positive whole second in the protobuf Timestamp range",
        ));
    }
    Ok(header)
}

fn validate_writer_events(
    writer_events: &WriterEvents,
    block_number: u64,
    profiles: &SegmentProfiles,
) -> Result<(), Error> {
    if writer_events.block_number != block_number {
        return Err(Error::msg("NPM source WriterEvents block-number drift"));
    }
    let manager = match writer_events.network.as_str() {
        "mainnet" => MAINNET_MANAGER,
        "base" => BASE_MANAGER,
        other => return Err(Error::msg(format!("unsupported NPM source network `{other}`"))),
    };
    let profile = profiles.select(&writer_events.network, block_number)?;
    if writer_events.segment_id != profile.segment_id
        || writer_events.segment_semantic_contract_sha256 != profile.semantic_contract_sha256
        || writer_events.source_writer_contract_sha256 != SOURCE_WRITER_CONTRACT_SHA256
    {
        return Err(Error::msg("NPM source WriterEvents contract binding drift"));
    }
    let mut previous: Option<(u32, u64)> = None;
    for event in &writer_events.events {
        if event.block_number != block_number {
            return Err(Error::msg("NPM source WriterEvent block-number drift"));
        }
        if exact_array::<20>("NPM source WriterEvent contract", &event.contract_address)? != manager {
            return Err(Error::msg(
                "NPM source WriterEvent is not from the configured static NPM",
            ));
        }
        exact_array::<32>("NPM source WriterEvent transaction hash", &event.transaction_hash)?;
        if event.event.is_none() {
            return Err(Error::msg("NPM source WriterEvent oneof is missing"));
        }
        if let Some((block_log_index, ordinal)) = previous {
            if event.block_log_index <= block_log_index || event.ordinal <= ordinal {
                return Err(Error::msg(
                    "NPM source block_log_index and ordinal must increase together",
                ));
            }
        }
        previous = Some((event.block_log_index, event.ordinal));
    }
    Ok(())
}

fn extract_transactions(block: &Block, writer_events: &WriterEvents) -> Result<Vec<TransactionRef>, Error> {
    let referenced = writer_events
        .events
        .iter()
        .map(|event| exact_array::<32>("NPM source WriterEvent transaction hash", &event.transaction_hash))
        .collect::<Result<BTreeSet<_>, _>>()?;
    let mut transactions = Vec::with_capacity(referenced.len());
    let mut indexes = BTreeSet::new();
    for hash in referenced {
        let matching = block
            .transaction_traces
            .iter()
            .filter(|trace| trace.hash.as_slice() == hash)
            .collect::<Vec<_>>();
        if matching.len() != 1 || matching[0].status != TransactionTraceStatus::Succeeded as i32 {
            return Err(Error::msg(format!(
                "referenced transaction {} requires exactly one successful trace",
                hex::encode(hash)
            )));
        }
        let trace = matching[0];
        if !indexes.insert(trace.index) {
            return Err(Error::msg(format!(
                "duplicate referenced transaction index {}",
                trace.index
            )));
        }
        let gas_price = trace
            .gas_price
            .as_ref()
            .ok_or_else(|| Error::msg(format!("referenced transaction {} has no gas_price", hex::encode(hash))))?;
        let gas_price_be = canonical_unsigned(&gas_price.bytes);
        if gas_price_be.len() > 32 {
            return Err(Error::msg(format!(
                "referenced transaction {} gas_price exceeds uint256",
                hex::encode(hash)
            )));
        }
        transactions.push(TransactionRef {
            hash: hash.to_vec(),
            index: trace.index,
            gas_limit: trace.gas_limit,
            gas_price_be,
        });
    }
    transactions.sort_by(|left, right| (left.index, &left.hash).cmp(&(right.index, &right.hash)));
    Ok(transactions)
}

fn validate_transactions(transactions: &[TransactionRef], writer_events: &WriterEvents) -> Result<(), Error> {
    let referenced = writer_events
        .events
        .iter()
        .map(|event| exact_array::<32>("NPM source WriterEvent transaction hash", &event.transaction_hash))
        .collect::<Result<BTreeSet<_>, _>>()?;
    let mut hashes = BTreeSet::new();
    let mut indexes = BTreeSet::new();
    let mut previous: Option<(u32, [u8; 32])> = None;
    for transaction in transactions {
        let hash = exact_array::<32>("NPM source transaction hash", &transaction.hash)?;
        if !hashes.insert(hash) || !indexes.insert(transaction.index) {
            return Err(Error::msg("duplicate NPM source transaction hash or index"));
        }
        if transaction.gas_price_be.len() > 32 || transaction.gas_price_be.first() == Some(&0) {
            return Err(Error::msg(
                "NPM source gas_price_be must be minimal unsigned uint256 bytes",
            ));
        }
        let key = (transaction.index, hash);
        if previous.is_some_and(|prior| prior >= key) {
            return Err(Error::msg("NPM source transactions are not canonically sorted"));
        }
        previous = Some(key);
    }
    if hashes != referenced {
        return Err(Error::msg(
            "NPM source transactions must exactly match referenced WriterEvents",
        ));
    }
    Ok(())
}

fn canonical_unsigned(bytes: &[u8]) -> Vec<u8> {
    let first_nonzero = bytes.iter().position(|byte| *byte != 0).unwrap_or(bytes.len());
    bytes[first_nonzero..].to_vec()
}

fn exact_array<const N: usize>(field: &str, bytes: &[u8]) -> Result<[u8; N], Error> {
    bytes
        .try_into()
        .map_err(|_| Error::msg(format!("{field} must be exactly {N} bytes")))
}

fn sha256(bytes: &[u8]) -> String {
    hex::encode(Sha256::digest(bytes))
}

fn valid_sha256(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
}

#[cfg(test)]
mod tests {
    use prost::Message;
    use prost_types::Timestamp;
    use substreams_ethereum::pb::eth::v2::{BigInt, BlockHeader, TransactionReceipt, TransactionTrace};

    use crate::pb::writer::writer_event::Event;
    use crate::pb::writer::{Transfer, WriterEvent};

    use super::*;

    fn block(number: u64, traces: Vec<TransactionTrace>) -> Block {
        let hash = vec![0x44; 32];
        Block {
            hash: hash.clone(),
            number,
            header: Some(BlockHeader {
                parent_hash: vec![0x33; 32],
                number,
                hash,
                timestamp: Some(Timestamp {
                    seconds: 1_700_000_000,
                    nanos: 0,
                }),
                ..Default::default()
            }),
            transaction_traces: traces,
            ..Default::default()
        }
    }

    fn trace(hash: u8, index: u32, gas_limit: u64, gas_price: Vec<u8>) -> TransactionTrace {
        TransactionTrace {
            hash: vec![hash; 32],
            index,
            gas_limit,
            gas_price: Some(BigInt { bytes: gas_price }),
            gas_used: 999_999,
            receipt: Some(TransactionReceipt {
                cumulative_gas_used: 777_777,
                ..Default::default()
            }),
            status: TransactionTraceStatus::Succeeded as i32,
            ..Default::default()
        }
    }

    fn writer(network: &str, number: u64, hashes: &[u8]) -> WriterEvents {
        let profiles = SegmentProfiles::embedded().unwrap();
        let profile = profiles.select(network, number).unwrap();
        let manager = match network {
            "mainnet" => MAINNET_MANAGER,
            "base" => BASE_MANAGER,
            _ => unreachable!(),
        };
        WriterEvents {
            events: hashes
                .iter()
                .enumerate()
                .map(|(offset, hash)| WriterEvent {
                    ordinal: 100 + offset as u64,
                    transaction_hash: vec![*hash; 32],
                    block_number: number,
                    transaction_log_index: offset as u32,
                    block_log_index: 10 + offset as u32,
                    contract_address: manager.to_vec(),
                    event: Some(Event::Transfer(Transfer {
                        from: vec![0x11; 20],
                        to: vec![0x22; 20],
                        token_id: (offset + 1).to_string(),
                    })),
                })
                .collect(),
            network: network.to_owned(),
            block_number: number,
            segment_id: profile.segment_id.clone(),
            source_writer_contract_sha256: SOURCE_WRITER_CONTRACT_SHA256.to_owned(),
            segment_semantic_contract_sha256: profile.semantic_contract_sha256.clone(),
        }
    }

    #[test]
    fn all_eight_segment_boundaries_emit_deterministic_empty_source_frames() {
        for (network, start, _) in EXPECTED_RANGES {
            let input = block(*start, Vec::new());
            let events = writer(network, *start, &[]);
            let first = build_npm_source_block(&input, &events).unwrap();
            let second = build_npm_source_block(&input, &events).unwrap();
            assert_eq!(first.encode_to_vec(), second.encode_to_vec());
            assert!(first.transactions.is_empty());
            assert_eq!(first.block.as_ref().unwrap().parent_hash, vec![0x33; 32]);
            assert_eq!(decode_npm_source_block(&first.encode_to_vec()).unwrap(), first);
        }
    }

    #[test]
    fn referenced_transactions_are_successful_unique_sorted_and_use_transaction_gas() {
        let number = 19_470_001;
        let input = block(
            number,
            vec![
                trace(0xaa, 9, 90_000, vec![0, 0, 5]),
                trace(0xbb, 2, 21_000, vec![0]),
                trace(0xcc, 1, 1, vec![7]),
            ],
        );
        let events = writer("mainnet", number, &[0xaa, 0xbb, 0xaa]);
        let output = build_npm_source_block(&input, &events).unwrap();
        assert_eq!(output.transactions.len(), 2);
        assert_eq!(output.transactions[0].index, 2);
        assert_eq!(output.transactions[0].gas_limit, 21_000);
        assert!(output.transactions[0].gas_price_be.is_empty());
        assert_eq!(output.transactions[1].index, 9);
        assert_eq!(output.transactions[1].gas_limit, 90_000);
        assert_eq!(output.transactions[1].gas_price_be, vec![5]);
        assert!(output.transactions.iter().all(|item| item.hash != vec![0xcc; 32]));
    }

    #[test]
    fn missing_failed_duplicate_and_malformed_transaction_metadata_fail_closed() {
        let number = 19_470_001;
        let events = writer("mainnet", number, &[0xaa]);

        assert!(build_npm_source_block(&block(number, Vec::new()), &events).is_err());

        let mut failed = trace(0xaa, 0, 1, vec![1]);
        failed.status = TransactionTraceStatus::Failed as i32;
        assert!(build_npm_source_block(&block(number, vec![failed]), &events).is_err());

        let duplicate = trace(0xaa, 0, 1, vec![1]);
        assert!(build_npm_source_block(&block(number, vec![duplicate.clone(), duplicate]), &events).is_err());

        let mut missing_price = trace(0xaa, 0, 1, vec![1]);
        missing_price.gas_price = None;
        assert!(build_npm_source_block(&block(number, vec![missing_price]), &events).is_err());

        assert!(build_npm_source_block(&block(number, vec![trace(0xaa, 0, 1, vec![1; 33])]), &events).is_err());
    }

    #[test]
    fn block_identity_header_parent_and_timestamp_corruption_fail_closed() {
        let number = 19_470_001;
        let events = writer("mainnet", number, &[]);
        for mutation in 0..8 {
            let mut input = block(number, Vec::new());
            match mutation {
                0 => {
                    input.hash.pop();
                }
                1 => input.header.as_mut().unwrap().hash[0] ^= 1,
                2 => input.header.as_mut().unwrap().number += 1,
                3 => {
                    input.header.as_mut().unwrap().parent_hash.pop();
                }
                4 => input.header.as_mut().unwrap().timestamp.as_mut().unwrap().seconds = -1,
                5 => input.header.as_mut().unwrap().timestamp.as_mut().unwrap().nanos = 1,
                6 => input.header.as_mut().unwrap().timestamp.as_mut().unwrap().seconds = 0,
                7 => {
                    input.header.as_mut().unwrap().timestamp.as_mut().unwrap().seconds =
                        MAX_PROTOBUF_TIMESTAMP_SECONDS + 1;
                }
                _ => unreachable!(),
            }
            assert!(build_npm_source_block(&input, &events).is_err());
        }
    }

    #[test]
    fn writer_network_segment_contract_address_and_order_corruption_fail_closed() {
        let number = 19_470_001;
        let input = block(number, vec![trace(0xaa, 0, 1, vec![1]), trace(0xbb, 1, 1, vec![1])]);
        for mutation in 0..8 {
            let mut events = writer("mainnet", number, &[0xaa, 0xbb]);
            match mutation {
                0 => "arbitrum".clone_into(&mut events.network),
                1 => events.block_number += 1,
                2 => events.segment_id.push('x'),
                3 => events.source_writer_contract_sha256.push('x'),
                4 => events.segment_semantic_contract_sha256.push('x'),
                5 => {
                    events.events[0].contract_address.pop();
                }
                6 => events.events[1].ordinal = events.events[0].ordinal,
                7 => events.events[1].block_log_index = events.events[0].block_log_index,
                _ => unreachable!(),
            }
            assert!(build_npm_source_block(&input, &events).is_err());
        }
    }

    #[test]
    fn canonical_decoder_rejects_unknown_fields_and_source_table_corruption() {
        let number = 19_470_001;
        let input = block(number, vec![trace(0xaa, 0, 1, vec![1])]);
        let events = writer("mainnet", number, &[0xaa]);
        let output = build_npm_source_block(&input, &events).unwrap();
        let mut unknown = output.encode_to_vec();
        unknown.extend([0xa0, 0x06, 0x01]);
        assert!(decode_npm_source_block(&unknown).is_err());

        let mut corrupt = output.clone();
        corrupt.transactions[0].gas_price_be.insert(0, 0);
        assert!(validate_npm_source_block(&corrupt).is_err());

        corrupt = output.clone();
        corrupt.transactions[0].index += 1;
        corrupt.transactions.push(corrupt.transactions[0].clone());
        assert!(validate_npm_source_block(&corrupt).is_err());

        corrupt = output.clone();
        corrupt.block.as_mut().unwrap().timestamp_seconds = 0;
        assert!(validate_npm_source_block(&corrupt).is_err());

        corrupt = output;
        corrupt.source_contract_sha256.push('x');
        assert!(validate_npm_source_block(&corrupt).is_err());
    }
}
