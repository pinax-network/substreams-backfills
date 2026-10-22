//! Offline Q-N2 diagnostics. This tool never widens numeric admission and never
//! attests package origin, producer success, committed hosts or token decimals.
use aerodrome_slipstream_reducer::input::validate_block;
use alloy_dyn_abi::DynSolValue;
use backfill_common::clock::{self, ObservedRange};
use graph_numerics::{bigint, BigInt, GraphDecimal};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::io::{self, Read};

pub mod saved;

pub const MAX_BLOCKS: u64 = 100_000;
pub const MAX_BYTES: u64 = 2 * 1024 * 1024 * 1024;
pub const MAX_FRAME_BYTES: usize = 16 * 1024 * 1024;
pub const MAX_WITNESSES: usize = 64;

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Request {
    pub format: String,
    pub input: std::path::PathBuf,
    pub input_sha256: String,
    pub input_bytes: u64,
    pub from_block: u64,
    pub to_block: u64,
    pub parent_hash: String,
    pub head_hash: String,
}
impl Request {
    pub fn validate(&self) -> Result<(), String> {
        if self.format != "pinax.aerodrome.qn2-extractor-request/v1"
            || !self.input.is_absolute()
            || self.input_bytes == 0
            || self.input_bytes > MAX_BYTES
            || self.from_block > self.to_block
            || self.to_block - self.from_block >= MAX_BLOCKS
            || self.to_block > clock::MAX_BLOCK_NUMBER
        {
            return Err("invalid request format, path, size or bounded range".into());
        }
        digest(&self.input_sha256)?;
        for value in [&self.parent_hash, &self.head_hash] {
            if digest(value)? == [0; 32] {
                return Err("observed boundary hash must not be zero".into());
            }
        }
        Ok(())
    }
}
pub fn digest(value: &str) -> Result<[u8; 32], String> {
    if value.len() != 64
        || !value
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    {
        return Err("expected lowercase SHA-256 or block hash".into());
    }
    Ok(hex::decode(value).unwrap().try_into().unwrap())
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct DecimalCrossing {
    pub coefficient: String,
    pub scale: i64,
    pub fixed_point: bool,
    pub accepted_by_block_changes_v1: bool,
}
fn crossing(value: &GraphDecimal) -> DecimalCrossing {
    let (coefficient, scale) = value.coefficient_and_scale();
    DecimalCrossing {
        coefficient: coefficient.to_string(),
        scale,
        fixed_point: value.is_fixed_point(),
        accepted_by_block_changes_v1: value.to_block_changes_wire().is_ok(),
    }
}
/// The exact zero-decimal mapping path is n(raw), not n(n(raw)).
pub fn classify_raw(amount: &BigInt) -> Result<DecimalCrossing, String> {
    GraphDecimal::from_bigint(amount)
        .map(|value| crossing(&value))
        .map_err(|e| e.to_string())
}

#[derive(Debug, Serialize)]
pub struct Witness {
    pub block: u64,
    pub block_hash: String,
    pub transaction_hash: String,
    pub pool: String,
    pub log_index: u32,
    pub field: String,
    pub raw_amount: String,
    pub zero_decimal_crossing: DecimalCrossing,
    pub decimal_provenance: &'static str,
    pub committed_host_provenance: &'static str,
}
#[derive(Debug, Serialize)]
pub struct Report {
    pub format: &'static str,
    pub graph_node_commit: &'static str,
    pub request: Request,
    pub observed_blocks: u64,
    pub decoded_swaps: u64,
    pub negative_amounts: u64,
    pub potential_zero_decimal_refusals: u64,
    pub witnesses: Vec<Witness>,
    pub witness_inventory_sha256: String,
    pub witnesses_omitted: u64,
    pub package_origin_verified: bool,
    pub producer_exit_verified: bool,
    pub full_range_qn2_closed: bool,
}
struct Hashed<R> {
    inner: R,
    hash: Sha256,
    bytes: u64,
    bound: u64,
}
impl<R: Read> Read for Hashed<R> {
    fn read(&mut self, buf: &mut [u8]) -> io::Result<usize> {
        // Permit one extra byte only to distinguish true EOF from a truncated
        // reader that returns EOF merely because its configured limit ended.
        let limit = (self.bound.saturating_sub(self.bytes) + 1).min(buf.len() as u64);
        let n = self.inner.read(&mut buf[..limit as usize])?;
        self.bytes += n as u64;
        if self.bytes > self.bound {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "input exceeds pinned byte length",
            ));
        }
        self.hash.update(&buf[..n]);
        Ok(n)
    }
}
pub fn scan<R: Read>(reader: R, request: Request) -> Result<Report, String> {
    request.validate()?;
    let mut reader = Hashed {
        inner: reader,
        hash: Sha256::new(),
        bytes: 0,
        bound: request.input_bytes,
    };
    let mut range =
        ObservedRange::new(request.from_block, request.to_block + 1).map_err(|e| e.to_string())?;
    let mut parent = digest(&request.parent_hash)?;
    let mut report = Report {
        format: "pinax.aerodrome.qn2-extractor-report/v1",
        graph_node_commit: graph_numerics::GRAPH_NODE_COMMIT,
        request,
        observed_blocks: 0,
        decoded_swaps: 0,
        negative_amounts: 0,
        potential_zero_decimal_refusals: 0,
        witnesses: vec![],
        witness_inventory_sha256: String::new(),
        witnesses_omitted: 0,
        package_origin_verified: false,
        producer_exit_verified: false,
        full_range_qn2_closed: false,
    };
    let mut witness_hash = Sha256::new();
    while let Some(frame) =
        clock::read_frame(&mut reader, MAX_FRAME_BYTES).map_err(|e| e.to_string())?
    {
        range.accept(&frame).map_err(|e| e.to_string())?;
        let input = validate_block(&frame, parent).map_err(|e| e.to_string())?;
        parent = frame.block_hash;
        report.observed_blocks += 1;
        for (candidate, event) in input.block().candidates.iter().zip(input.decoded()) {
            let Some(event) = event.as_ref().filter(|e| e.name == "Swap") else {
                continue;
            };
            report.decoded_swaps += 1;
            for name in ["amount0", "amount1"] {
                let Some(DynSolValue::Int(value, 256)) = event.param(name) else {
                    return Err("locked Swap signed amount ABI mismatch".into());
                };
                let raw = bigint::parse(&value.to_string()).map_err(|e| e.to_string())?;
                if raw >= BigInt::from(0) {
                    continue;
                }
                report.negative_amounts += 1;
                let result = classify_raw(&raw)?;
                if result.accepted_by_block_changes_v1 {
                    continue;
                }
                report.potential_zero_decimal_refusals += 1;
                let witness = Witness {
                    block: frame.block_number,
                    block_hash: hex::encode(frame.block_hash),
                    transaction_hash: hex::encode(
                        &input.block().transactions[candidate.tx as usize].hash,
                    ),
                    pool: format!("0x{}", hex::encode(&candidate.address)),
                    log_index: candidate.log_index,
                    field: name.into(),
                    raw_amount: raw.to_string(),
                    zero_decimal_crossing: result,
                    decimal_provenance: "unresolved_mapping_token_decimals",
                    committed_host_provenance: "extractor_candidate_only",
                };
                let mut bytes = serde_json::to_vec(&witness).map_err(|e| e.to_string())?;
                bytes.push(b'\n');
                witness_hash.update(bytes);
                if report.witnesses.len() < MAX_WITNESSES {
                    report.witnesses.push(witness);
                } else {
                    report.witnesses_omitted += 1;
                }
            }
        }
    }
    range.finish().map_err(|e| e.to_string())?;
    if reader.bytes != report.request.input_bytes
        || hex::encode(reader.hash.finalize()) != report.request.input_sha256
        || parent != digest(&report.request.head_hash)?
    {
        return Err("input byte count/digest or final observed hash differs from request".into());
    }
    report.witness_inventory_sha256 = hex::encode(witness_hash.finalize());
    Ok(report)
}
