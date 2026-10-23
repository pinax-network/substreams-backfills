//! Bounded SQL-page planning and exact saved-numeric diagnostics. No connection
//! is opened here. SQL numeric text is parsed WITHOUT Graph Node renormalizing
//! it; `from_db_text` would erase precisely the non-fixed point being audited.
use crate::{crossing, digest, DecimalCrossing, Hashed, MAX_BLOCKS, MAX_WITNESSES};
use backfill_common::{clock, pb::pinax::graph::backfill::v1::BigDecimalValue};
use graph_numerics::{bigint, BigInt, GraphDecimal};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::io::{BufRead, BufReader, Read};

pub const MAX_SAVED_BYTES: u64 = 64 * 1024 * 1024;
const MAX_LINE: u64 = 65536;
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SqlPage {
    pub format: String,
    pub schema: String,
    pub min_vid: i64,
    pub max_vid: i64,
    pub from_block: u64,
    pub to_block: u64,
    pub max_rows: u64,
}
impl SqlPage {
    pub fn validate(&self) -> Result<(), String> {
        let suffix = self
            .schema
            .strip_prefix("sgd")
            .ok_or("schema must be sgd plus decimal digits")?;
        if self.format != "pinax.aerodrome.qn2-sql-page/v1"
            || suffix.is_empty()
            || suffix.len() > 10
            || !suffix.bytes().all(|b| b.is_ascii_digit())
            || self.min_vid > self.max_vid
            || self
                .max_vid
                .checked_sub(self.min_vid)
                .is_none_or(|n| n > 1_000_000)
            || self.from_block > self.to_block
            || self.to_block - self.from_block >= MAX_BLOCKS
            || self.to_block > clock::MAX_BLOCK_NUMBER
            || self.max_rows == 0
            || self.max_rows > 10_000
        {
            return Err("invalid bounded SQL page".into());
        }
        Ok(())
    }
    /// Execute only against an independently identified read-only source using
    /// psql -X --no-psqlrc --quiet --tuples-only --no-align --set=ON_ERROR_STOP=1.
    /// LIMIT+1 deliberately makes a saturated page fail, never appear complete.
    pub fn sql(&self) -> Result<String, String> {
        self.validate()?;
        Ok(format!("BEGIN READ ONLY;\nSET LOCAL statement_timeout = '5s';\nSET LOCAL lock_timeout = '1s';\nSELECT json_build_object('vid', s.vid, 'id', s.id, 'block_start', lower(s.block_range), 'amount0', s.\"amount_0\"::text, 'amount1', s.\"amount_1\"::text)::text\nFROM \"{}\".\"swap\" AS s\nWHERE s.vid BETWEEN {} AND {}\n  AND lower(s.block_range) BETWEEN {} AND {}\nORDER BY s.vid\nLIMIT {};\nROLLBACK;\n",self.schema,self.min_vid,self.max_vid,self.from_block,self.to_block,self.max_rows+1))
    }
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Request {
    pub format: String,
    pub page: SqlPage,
    pub input: std::path::PathBuf,
    pub input_sha256: String,
    pub input_bytes: u64,
}
#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct Row {
    vid: i64,
    id: String,
    block_start: u64,
    amount0: String,
    amount1: String,
}
#[derive(Debug, Serialize)]
pub struct Witness {
    pub vid: i64,
    pub id: String,
    pub block_start: u64,
    pub field: String,
    pub saved_text: String,
    pub saved_tuple: DecimalCrossing,
}
#[derive(Debug, Serialize)]
pub struct Report {
    pub format: &'static str,
    pub request: Request,
    pub rows: u64,
    pub saved_non_fixed_points: u64,
    pub witnesses: Vec<Witness>,
    pub witnesses_omitted: u64,
    pub witness_inventory_sha256: String,
    pub query_execution_verified: bool,
    pub source_database_identity_verified: bool,
    pub full_range_qn2_closed: bool,
}
/// Strip only decimal trailing zeroes to recover the exact numeric tuple. This
/// is a change of representation, not a precision rounding/normalization pass.
pub fn classify_text(text: &str) -> Result<DecimalCrossing, String> {
    if text.is_empty() || text.len() > 16384 {
        return Err("saved numeric text bound".into());
    }
    let (negative, value) = text.strip_prefix('-').map_or((false, text), |v| (true, v));
    let (integer, fraction) = value
        .split_once('.')
        .map_or((value, None), |(a, b)| (a, Some(b)));
    if integer.is_empty()
        || !integer.bytes().all(|b| b.is_ascii_digit())
        || (integer.len() > 1 && integer.starts_with('0'))
        || fraction.is_some_and(|v| v.is_empty() || !v.bytes().all(|b| b.is_ascii_digit()))
    {
        return Err("expected finite PostgreSQL numeric text".into());
    }
    let mut digits = format!("{}{}", integer, fraction.unwrap_or(""));
    let mut scale = fraction.map_or(0, |s| s.len()) as i64;
    while digits.ends_with('0') {
        digits.pop();
        scale -= 1;
    }
    let digits = digits.trim_start_matches('0');
    let coefficient = if digits.is_empty() {
        BigInt::from(0)
    } else {
        bigint::parse(&format!("{}{}", if negative { "-" } else { "" }, digits))
            .map_err(|e| e.to_string())?
    };
    let wire = BigDecimalValue {
        coefficient_signed_be: bigint::signed_bytes(&coefficient),
        scale: if coefficient == BigInt::from(0) {
            0
        } else {
            scale
        },
    };
    GraphDecimal::from_wire_exact(&wire)
        .map(|v| crossing(&v))
        .map_err(|e| e.to_string())
}
pub fn scan<R: Read>(reader: R, request: Request) -> Result<Report, String> {
    request.page.validate()?;
    digest(&request.input_sha256)?;
    if request.format != "pinax.aerodrome.qn2-saved-request/v1"
        || !request.input.is_absolute()
        || request.input_bytes > MAX_SAVED_BYTES
    {
        return Err("invalid saved page input".into());
    }
    let mut reader = BufReader::new(Hashed {
        inner: reader,
        hash: Sha256::new(),
        bytes: 0,
        bound: request.input_bytes,
    });
    let mut report = Report {
        format: "pinax.aerodrome.qn2-saved-report/v1",
        request,
        rows: 0,
        saved_non_fixed_points: 0,
        witnesses: vec![],
        witnesses_omitted: 0,
        witness_inventory_sha256: String::new(),
        query_execution_verified: false,
        source_database_identity_verified: false,
        full_range_qn2_closed: false,
    };
    let mut last = None;
    let mut hash = Sha256::new();
    loop {
        let mut line = vec![];
        let n = reader
            .by_ref()
            .take(MAX_LINE + 1)
            .read_until(b'\n', &mut line)
            .map_err(|e| e.to_string())?;
        if n == 0 {
            break;
        }
        if n as u64 > MAX_LINE || line.last() != Some(&b'\n') {
            return Err("saved row exceeds bound or lacks final newline".into());
        }
        report.rows += 1;
        if report.rows > report.request.page.max_rows {
            return Err("SQL page saturated; narrow its VID range".into());
        }
        let row: Row = serde_json::from_slice(&line).map_err(|e| e.to_string())?;
        let page = &report.request.page;
        if row.vid < page.min_vid
            || row.vid > page.max_vid
            || last.is_some_and(|v| row.vid <= v)
            || row.block_start < page.from_block
            || row.block_start > page.to_block
            || row.id.is_empty()
            || row.id.len() > 256
        {
            return Err("saved row outside page, unordered or invalid ID".into());
        }
        last = Some(row.vid);
        for (field, text) in [("amount0", &row.amount0), ("amount1", &row.amount1)] {
            let tuple = classify_text(text)?;
            if tuple.accepted_by_block_changes_v1 {
                continue;
            }
            report.saved_non_fixed_points += 1;
            let witness = Witness {
                vid: row.vid,
                id: row.id.clone(),
                block_start: row.block_start,
                field: field.into(),
                saved_text: text.clone(),
                saved_tuple: tuple,
            };
            let mut bytes = serde_json::to_vec(&witness).map_err(|e| e.to_string())?;
            bytes.push(b'\n');
            hash.update(bytes);
            if report.witnesses.len() < MAX_WITNESSES {
                report.witnesses.push(witness)
            } else {
                report.witnesses_omitted += 1
            }
        }
    }
    let reader = reader.into_inner();
    if reader.bytes != report.request.input_bytes
        || hex::encode(reader.hash.finalize()) != report.request.input_sha256
    {
        return Err("saved input length/digest mismatch".into());
    }
    report.witness_inventory_sha256 = hex::encode(hash.finalize());
    Ok(report)
}
