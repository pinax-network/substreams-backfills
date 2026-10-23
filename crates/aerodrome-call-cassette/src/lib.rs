//! Bounded independent RPC capture for the supplied extractor call inventory.
//! This does not attest the extractor's origin, successful process exit, or
//! completeness. Replay must still refuse every oracle cassette miss.
use aerodrome_extractor_audit::{self as audit, Check, Expected, Retval};
use aerodrome_extractor_core::{
    calls::{CallKey, ERC20_SELECTORS},
    config::{Config, PARAMS},
    events::{self, Event},
};
use aerodrome_slipstream_reducer::{identity::InputBinding, input::validate_block};
use backfill_common::{
    clock::{self, ObservedRange},
    descriptor::ExtractorIdentity,
};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    fs::{self, File, OpenOptions},
    io::{self, Read, Write},
    path::{Path, PathBuf},
    time::{Duration, Instant},
};

pub mod transport;
pub type Result<T> = std::result::Result<T, String>;
pub const MAX_BLOCKS: u64 = 1_000;
pub const MAX_INPUT: u64 = 2 * 1024 * 1024 * 1024;
pub const MAX_FRAME: usize = 16 * 1024 * 1024;
pub const MAX_CALLS: usize = 100_000;
pub const MAX_CASSETTE: usize = 64 * 1024 * 1024;
pub const MAX_RESPONSE: usize = 4 * 1024 * 1024;
const MAX_REQUEST: usize = 64 * 1024;
const MAX_DESCRIPTOR: usize = 4 * 1024 * 1024;
const MAX_OBSERVATIONS: u64 = 128 * 1024 * 1024;

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FilePin {
    pub path: PathBuf,
    pub bytes: u64,
    pub sha256: String,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Request {
    pub format: String,
    pub input: FilePin,
    pub descriptor: FilePin,
    /// Externally verified package identity; frames cannot prove this provenance.
    pub extractor: ExtractorIdentity,
    pub from_block: u64,
    pub to_exclusive: u64,
    pub parent_hash: String,
    pub head_hash: String,
    pub rpc_timeout_seconds: u64,
    pub total_timeout_seconds: u64,
    pub minimum_interval_ms: u64,
}
fn require(ok: bool, reason: &str) -> Result<()> {
    if ok {
        Ok(())
    } else {
        Err(reason.into())
    }
}
pub fn digest(text: &str) -> Result<[u8; 32]> {
    require(
        text.len() == 64
            && text
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b)),
        "expected lowercase 32-byte digest",
    )?;
    Ok(hex::decode(text).unwrap().try_into().unwrap())
}
fn ioerr(error: io::Error) -> String {
    format!("local IO failure: {}", error.kind())
}
fn sha(bytes: &[u8]) -> String {
    hex::encode(Sha256::digest(bytes))
}

/// Refuse ancestor aliases and final symlinks/FIFOs before reading from one handle.
pub fn regular(path: &Path) -> Result<File> {
    use std::os::unix::fs::OpenOptionsExt;
    require(path.is_absolute(), "artifact path must be absolute")?;
    let parent = path.parent().ok_or("artifact has no parent")?;
    require(
        parent.canonicalize().map_err(ioerr)? == parent,
        "artifact parent must be canonical",
    )?;
    let file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
        .open(path)
        .map_err(ioerr)?;
    require(
        file.metadata().map_err(ioerr)?.is_file(),
        "artifact must be a regular file",
    )?;
    Ok(file)
}
fn read_bounded(mut reader: impl Read, limit: usize) -> Result<Vec<u8>> {
    let mut bytes = Vec::new();
    reader
        .by_ref()
        .take(limit as u64 + 1)
        .read_to_end(&mut bytes)
        .map_err(ioerr)?;
    require(bytes.len() <= limit, "artifact exceeds byte limit")?;
    Ok(bytes)
}
fn pinned(pin: &FilePin, limit: usize) -> Result<Vec<u8>> {
    digest(&pin.sha256)?;
    require(
        pin.bytes > 0 && pin.bytes <= limit as u64,
        "invalid artifact byte pin",
    )?;
    let file = regular(&pin.path)?;
    require(
        file.metadata().map_err(ioerr)?.len() == pin.bytes,
        "artifact size mismatch",
    )?;
    let bytes = read_bounded(file, pin.bytes as usize)?;
    require(
        bytes.len() as u64 == pin.bytes && sha(&bytes) == pin.sha256,
        "artifact digest/size mismatch",
    )?;
    Ok(bytes)
}
pub fn read_request(path: &Path, expected_sha256: &str) -> Result<(Request, Vec<u8>)> {
    digest(expected_sha256)?;
    let bytes = read_bounded(regular(path)?, MAX_REQUEST)?;
    require(sha(&bytes) == expected_sha256, "request digest mismatch")?;
    // Typed serde decoding refuses duplicate binding fields and unknown fields.
    let request: Request =
        serde_json::from_slice(&bytes).map_err(|_| "invalid or duplicate request fields")?;
    request.validate()?;
    Ok((request, bytes))
}
impl Request {
    pub fn validate(&self) -> Result<()> {
        require(
            self.format == "pinax.aerodrome.call-cassette-request/v1"
                && self.from_block < self.to_exclusive
                && self.to_exclusive - self.from_block <= MAX_BLOCKS
                && self.to_exclusive <= clock::MAX_BLOCK_NUMBER + 1
                && self.input.bytes > 0
                && self.input.bytes <= MAX_INPUT
                && (1..=30).contains(&self.rpc_timeout_seconds)
                && (1..=86400).contains(&self.total_timeout_seconds)
                && self.rpc_timeout_seconds <= self.total_timeout_seconds
                && (1..=1000).contains(&self.minimum_interval_ms),
            "invalid request bounds or format",
        )?;
        digest(&self.input.sha256)?;
        require(
            digest(&self.parent_hash)? != [0; 32] && digest(&self.head_hash)? != [0; 32],
            "zero boundary hash",
        )
    }
}
struct Hashed<R> {
    inner: R,
    bytes: u64,
    maximum: u64,
    hash: Sha256,
}
impl<R: Read> Read for Hashed<R> {
    fn read(&mut self, out: &mut [u8]) -> io::Result<usize> {
        let limit = out
            .len()
            .min((self.maximum.saturating_sub(self.bytes) + 1) as usize);
        let n = self.inner.read(&mut out[..limit])?;
        self.bytes += n as u64;
        if self.bytes > self.maximum {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "input exceeds pinned size",
            ));
        }
        self.hash.update(&out[..n]);
        Ok(n)
    }
}
struct Block {
    number: u64,
    hash: [u8; 32],
    parent: [u8; 32],
    checks: Vec<Check>,
}
pub struct Inventory {
    blocks: Vec<Block>,
    calls: usize,
}
#[derive(Serialize)]
struct InventoryCall<'a> {
    block_number: u64,
    block_hash: String,
    address: String,
    calldata: String,
    contract: &'a str,
    function: &'a str,
}
fn label(calldata: &[u8]) -> Result<(&'static str, &'static str)> {
    match calldata.get(..4) {
        Some([0x95, 0xd8, 0x9b, 0x41]) => Ok(("ERC20", "symbol()")),
        Some([0x06, 0xfd, 0xde, 0x03]) => Ok(("ERC20", "name()")),
        Some([0x18, 0x16, 0x0d, 0xdd]) => Ok(("ERC20", "totalSupply()")),
        Some([0x31, 0x3c, 0xe5, 0x67]) => Ok(("ERC20", "decimals()")),
        Some([0xf3, 0x05, 0x83, 0x99]) => Ok(("Pool", "feeGrowthGlobal0X128()")),
        Some([0x46, 0x14, 0x13, 0x19]) => Ok(("Pool", "feeGrowthGlobal1X128()")),
        Some([0xf3, 0x0d, 0xba, 0x93]) => Ok(("Pool", "ticks(int24)")),
        Some([0x99, 0xfb, 0xab, 0x88]) => Ok(("NonfungiblePositionManager", "positions(uint256)")),
        Some([0x28, 0xaf, 0x8d, 0x0b]) => Ok(("Factory", "getPool(address,address,int24)")),
        _ => Err("unsupported call selector".into()),
    }
}
// Check locally derivable mandatory keys. Historical Swap tick markers/token
// versions still require extractor carry/seed provenance: this is not a proof
// that every actual mapping call is represented.
fn mandatory_keys(
    block: &aerodrome_slipstream_reducer::pb::ExtractorBlock,
    cfg: &Config,
    checks: &[Check],
) -> Result<()> {
    let present: std::collections::BTreeSet<_> = checks
        .iter()
        .map(|c| (c.address, c.calldata.clone()))
        .collect();
    let has = |key: CallKey| {
        require(
            present.contains(&(key.address(cfg), key.calldata().map_err(str::to_owned)?)),
            "missing mandatory supplied call key",
        )
    };
    for fact in &block.pools_created {
        for token in [&fact.token0, &fact.token1] {
            for selector in ERC20_SELECTORS {
                has(CallKey::Erc20 {
                    token: token.as_slice().try_into().map_err(|_| "invalid token")?,
                    selector,
                })?;
            }
        }
    }
    for candidate in &block.candidates {
        let pool = candidate
            .address
            .as_slice()
            .try_into()
            .map_err(|_| "invalid pool address")?;
        match events::decode(candidate).map_err(str::to_owned)? {
            Some(Event::Swap { .. } | Event::Flash) => {
                for which in [0, 1] {
                    has(CallKey::FeeGrowth { pool, which })?;
                }
            }
            Some(Event::Mint { lower, upper } | Event::Burn { lower, upper }) => {
                for tick in [lower, upper] {
                    has(CallKey::Ticks { pool, tick })?;
                }
            }
            Some(Event::Position { token_id }) => has(CallKey::Positions { token_id })?,
            _ => {}
        }
    }
    for position in &block.calls.as_ref().ok_or("missing calls")?.positions {
        if let Some(aerodrome_slipstream_reducer::pb::position_answer::Result::Value(value)) =
            &position.result
        {
            has(CallKey::GetPool {
                a: value
                    .token0
                    .as_slice()
                    .try_into()
                    .map_err(|_| "invalid position token")?,
                b: value
                    .token1
                    .as_slice()
                    .try_into()
                    .map_err(|_| "invalid position token")?,
                ts: value.tick_spacing,
            })?;
        }
    }
    Ok(())
}
/// Complete validation/digest/EOF precedes every RPC. Only bounded call metadata
/// and expected comparison fields are retained, never the whole input stream.
pub fn inventory(request: &Request) -> Result<Inventory> {
    request.validate()?;
    let descriptor = pinned(&request.descriptor, MAX_DESCRIPTOR)?;
    InputBinding::new(
        &descriptor,
        digest(&request.descriptor.sha256)?,
        &request.extractor,
    )
    .map_err(|e| e.to_string())?;
    let file = regular(&request.input.path)?;
    require(
        file.metadata().map_err(ioerr)?.len() == request.input.bytes,
        "input size mismatch",
    )?;
    let mut input = Hashed {
        inner: file,
        bytes: 0,
        maximum: request.input.bytes,
        hash: Sha256::new(),
    };
    let mut range = ObservedRange::new(request.from_block, request.to_exclusive).map_err(ioerr)?;
    let cfg = Config::parse(PARAMS).map_err(|e| e.to_string())?;
    let mut parent = digest(&request.parent_hash)?;
    let mut blocks = Vec::new();
    let mut calls = 0usize;
    let mut weight = 0usize;
    let mut keys = std::collections::BTreeSet::new();
    while let Some(frame) = clock::read_frame(&mut input, MAX_FRAME).map_err(ioerr)? {
        range.accept(&frame).map_err(ioerr)?;
        let block = validate_block(&frame, parent).map_err(|e| e.to_string())?;
        let checks = audit::checks(block.block(), &cfg, false)?;
        mandatory_keys(block.block(), &cfg, &checks)?;
        calls = calls
            .checked_add(checks.len())
            .ok_or("call count overflow")?;
        require(calls <= MAX_CALLS, "supplied inventory exceeds call limit")?;
        for check in &checks {
            require(
                keys.insert((frame.block_hash, check.address, check.calldata.clone())),
                "duplicate actual call key",
            )?;
            label(&check.calldata)?;
            let expected = match &check.expected {
                Expected::Raw(Retval::Value { data }) => data.len(),
                Expected::Raw(Retval::Reverted) => 0,
                Expected::Words { consumed, .. } => {
                    consumed.iter().map(|(_, v)| v.len() + 32).sum()
                }
            };
            weight = weight
                .checked_add(1024 + check.calldata.len() + expected)
                .ok_or("inventory size overflow")?;
            require(
                weight <= MAX_CASSETTE,
                "supplied inventory exceeds memory budget",
            )?;
        }
        blocks.push(Block {
            number: frame.block_number,
            hash: frame.block_hash,
            parent,
            checks,
        });
        parent = frame.block_hash;
    }
    range.finish().map_err(ioerr)?;
    require(
        parent == digest(&request.head_hash)?,
        "input final hash mismatch",
    )?;
    require(
        input.bytes == request.input.bytes
            && hex::encode(input.hash.finalize()) == request.input.sha256,
        "input digest/length mismatch",
    )?;
    Ok(Inventory { blocks, calls })
}

/// A transport returns bounded raw JSON bytes; the caller validates typed RPC
/// envelopes, IDs and values. Tests use deterministic transports, never live RPC.
pub trait Rpc {
    fn request(&mut self, body: &Value, timeout: Duration) -> Result<Vec<u8>>;
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields, bound(deserialize = "T: Deserialize<'de>"))]
struct Envelope<T> {
    jsonrpc: String,
    id: u64,
    #[serde(default, deserialize_with = "present")]
    result: Option<T>,
    #[serde(default, deserialize_with = "present")]
    error: Option<RpcError>,
}
// Missing is distinct from explicit null. None is only produced by serde's
// absent-field default; every present response arm must decode its actual type.
fn present<'de, D, T>(deserializer: D) -> std::result::Result<Option<T>, D::Error>
where
    D: serde::Deserializer<'de>,
    T: Deserialize<'de>,
{
    T::deserialize(deserializer).map(Some)
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RpcError {
    code: i64,
    message: String,
    #[serde(default)]
    data: Option<serde::de::IgnoredAny>,
}
#[derive(Deserialize, Serialize)]
struct Header {
    hash: String,
    #[serde(rename = "parentHash")]
    parent_hash: String,
    number: String,
}
fn envelope<T: serde::de::DeserializeOwned>(bytes: &[u8], id: u64) -> Result<Envelope<T>> {
    require(
        bytes.len() <= MAX_RESPONSE,
        "RPC response exceeds byte limit",
    )?;
    let value: Envelope<T> =
        serde_json::from_slice(bytes).map_err(|_| "invalid or duplicate RPC response fields")?;
    require(
        value.jsonrpc == "2.0"
            && value.id == id
            && (value.result.is_some() ^ value.error.is_some()),
        "RPC response identity/result mismatch",
    )?;
    Ok(value)
}
struct Session<'a, R> {
    rpc: &'a mut R,
    deadline: Instant,
    timeout: Duration,
    interval: Duration,
    last: Option<Instant>,
    next_id: u64,
}
impl<R: Rpc> Session<'_, R> {
    fn get(&mut self, mut body: Value) -> Result<(u64, Vec<u8>)> {
        if let Some(last) = self.last {
            let wait = self.interval.saturating_sub(last.elapsed());
            require(
                Instant::now()
                    .checked_add(wait)
                    .is_some_and(|t| t < self.deadline),
                "total RPC deadline exceeded",
            )?;
            std::thread::sleep(wait);
        }
        let left = self
            .deadline
            .checked_duration_since(Instant::now())
            .ok_or("total RPC deadline exceeded")?;
        let id = self.next_id;
        self.next_id += 1;
        body["id"] = json!(id);
        self.last = Some(Instant::now());
        let bytes = self.rpc.request(&body, self.timeout.min(left))?;
        require(
            Instant::now() < self.deadline,
            "total RPC deadline exceeded",
        )?;
        require(
            bytes.len() <= MAX_RESPONSE,
            "RPC response exceeds byte limit",
        )?;
        Ok((id, bytes))
    }
    fn header(&mut self, block: &Block) -> Result<Value> {
        // By-number lookup also proves the archive's canonical hash for empty
        // blocks, where there is no EIP-1898 eth_call to enforce canonicality.
        let (id,bytes)=self.get(json!({"jsonrpc":"2.0","id":0,"method":"eth_getBlockByNumber","params":[format!("0x{:x}",block.number),false]}))?;
        let value = envelope::<Header>(&bytes, id)?
            .result
            .ok_or("archive block lookup failed")?;
        require(
            value.hash == format!("0x{}", hex::encode(block.hash))
                && value.parent_hash == format!("0x{}", hex::encode(block.parent))
                && value.number == format!("0x{:x}", block.number),
            "archive block identity differs from input",
        )?;
        Ok(json!({"jsonrpc":"2.0","id":id,"result":value}))
    }
}
#[derive(Serialize, Deserialize)]
#[serde(tag = "kind", content = "data", rename_all = "snake_case")]
pub enum CassetteRetval {
    Null,
    Value(String),
}
#[derive(Serialize, Deserialize)]
pub struct CassetteEntry {
    pub block_number: u64,
    pub block_hash: String,
    pub address: String,
    pub calldata: String,
    pub contract: String,
    pub function: String,
    pub retval: CassetteRetval,
}
#[derive(Serialize, Deserialize)]
pub struct CassetteFile {
    pub schema: String,
    pub entries: Vec<CassetteEntry>,
}
fn new_file(path: &Path) -> Result<File> {
    use std::os::unix::fs::OpenOptionsExt;
    OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(path)
        .map_err(ioerr)
}
fn write_json(path: &Path, value: &impl Serialize, limit: usize) -> Result<(u64, String)> {
    let bytes = bounded_json(value, limit)?;
    let mut file = new_file(path)?;
    file.write_all(&bytes).map_err(ioerr)?;
    file.sync_all().map_err(ioerr)?;
    Ok((bytes.len() as u64, sha(&bytes)))
}
fn executing_binary() -> Result<(u64, String)> {
    let path = std::env::current_exe().map_err(ioerr)?;
    let file = regular(&path)?;
    let size = file.metadata().map_err(ioerr)?.len();
    require(
        size > 0 && size <= 256 * 1024 * 1024,
        "executing binary exceeds limit",
    )?;
    let mut input = Hashed {
        inner: file,
        bytes: 0,
        maximum: size,
        hash: Sha256::new(),
    };
    io::copy(&mut input, &mut io::sink()).map_err(ioerr)?;
    require(input.bytes == size, "executing binary truncated")?;
    Ok((size, hex::encode(input.hash.finalize())))
}
struct Capped {
    bytes: Vec<u8>,
    limit: usize,
}
impl Write for Capped {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        if self
            .bytes
            .len()
            .checked_add(bytes.len())
            .is_none_or(|n| n >= self.limit)
        {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "JSON size bound",
            ));
        }
        self.bytes.extend_from_slice(bytes);
        Ok(bytes.len())
    }
    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}
fn bounded_json(value: &impl Serialize, limit: usize) -> Result<Vec<u8>> {
    let mut sink = Capped {
        bytes: Vec::new(),
        limit,
    };
    serde_json::to_writer(&mut sink, value).map_err(|_| "JSON exceeds output limit")?;
    sink.bytes.push(b'\n');
    Ok(sink.bytes)
}

/// The fresh output directory belongs to one attempt. Failure retains request,
/// inventory and observations; only `complete.json` publishes success. The
/// cassette itself is withheld until all independent calls matched.
pub fn prepare(
    request: &Request,
    request_bytes: &[u8],
    output: &Path,
    rpc: &mut impl Rpc,
) -> Result<()> {
    require(
        request_bytes.len() <= MAX_REQUEST,
        "request exceeds byte limit",
    )?;
    // Retain the exact caller bytes, but disallow a typed/byte split for any field.
    let decoded: Request =
        serde_json::from_slice(request_bytes).map_err(|_| "invalid request bytes")?;
    require(
        serde_json::to_vec(&decoded).unwrap() == serde_json::to_vec(request).unwrap(),
        "request bytes mismatch",
    )?;
    require(
        output.is_absolute()
            && output
                .parent()
                .is_some_and(|p| p.canonicalize().ok().as_deref() == Some(p)),
        "output parent must be canonical",
    )?;
    use std::os::unix::fs::DirBuilderExt;
    fs::DirBuilder::new()
        .mode(0o700)
        .create(output)
        .map_err(ioerr)?;
    let mut request_file = new_file(&output.join("request.json"))?;
    request_file.write_all(request_bytes).map_err(ioerr)?;
    request_file.sync_all().map_err(ioerr)?;
    let result = (|| {
        let executable = executing_binary()?;
        let inventory = inventory(request)?;
        let mut calls = Vec::new();
        for block in &inventory.blocks {
            for check in &block.checks {
                let (contract, function) = label(&check.calldata)?;
                calls.push(InventoryCall {
                    block_number: block.number,
                    block_hash: format!("0x{}", hex::encode(block.hash)),
                    address: format!("0x{}", hex::encode(check.address)),
                    calldata: format!("0x{}", hex::encode(&check.calldata)),
                    contract,
                    function,
                });
            }
        }
        let (_, inventory_sha) = write_json(
            &output.join("inventory.json"),
            &json!({"format":"pinax.aerodrome.supplied-call-inventory/v1","proves_completeness":false,"calls":calls}),
            MAX_CASSETTE,
        )?;
        let mut session = Session {
            rpc,
            deadline: Instant::now() + Duration::from_secs(request.total_timeout_seconds),
            timeout: Duration::from_secs(request.rpc_timeout_seconds),
            interval: Duration::from_millis(request.minimum_interval_ms),
            last: None,
            next_id: 1,
        };
        let (id, bytes) =
            session.get(json!({"jsonrpc":"2.0","id":0,"method":"eth_chainId","params":[]}))?;
        require(
            envelope::<String>(&bytes, id)?.result.as_deref() == Some("0x2105"),
            "archive is not Base8453",
        )?;
        let mut observations = new_file(&output.join("observations.jsonl"))?;
        let mut observation_hash = Sha256::new();
        let mut observation_bytes = 0u64;
        let mut entries = Vec::new();
        let mut cassette_weight = 128usize;
        let mut block_proofs = Vec::new();
        for block in &inventory.blocks {
            let before = session.header(block)?;
            for check in &block.checks {
                let mut body = audit::request(check, &block.hash, 0);
                let (id, bytes) = session.get(body.clone())?;
                body["id"] = json!(id);
                let response = envelope::<String>(&bytes, id)?;
                let normalized = match (response.result, response.error) {
                    (Some(value), None) => json!({"jsonrpc":"2.0","id":id,"result":value}),
                    (None, Some(error)) => {
                        let _ = error.data;
                        json!({"jsonrpc":"2.0","id":id,"error":{"code":error.code,"message":error.message}})
                    }
                    _ => unreachable!(),
                };
                let actual = audit::call_retval(&normalized, id)?;
                let compared = audit::compare(check, &actual);
                let line = bounded_json(
                    // Retain the exact response independently of the decoded
                    // semantic value, including unconsumed words/revert data.
                    &json!({"block_number":block.number,"request":body,"rpc_response_hex":hex::encode(&bytes),"actual":actual,"matched":compared.is_ok()}),
                    3 * MAX_RESPONSE + 4096,
                )?;
                observation_bytes += line.len() as u64;
                require(
                    observation_bytes <= MAX_OBSERVATIONS,
                    "observations exceed byte budget",
                )?;
                observations.write_all(&line).map_err(ioerr)?;
                observations.sync_all().map_err(ioerr)?;
                observation_hash.update(&line);
                compared?;
                let (contract, function) = label(&check.calldata)?;
                let entry = CassetteEntry {
                    block_number: block.number,
                    block_hash: format!("0x{}", hex::encode(block.hash)),
                    address: format!("0x{}", hex::encode(check.address)),
                    calldata: format!("0x{}", hex::encode(&check.calldata)),
                    contract: contract.into(),
                    function: function.into(),
                    retval: match actual {
                        Retval::Reverted => CassetteRetval::Null,
                        Retval::Value { data } => CassetteRetval::Value(format!("0x{data}")),
                    },
                };
                cassette_weight += bounded_json(&entry, MAX_RESPONSE + 4096)?.len() + 1;
                require(
                    cassette_weight <= MAX_CASSETTE,
                    "cassette exceeds consumer byte limit",
                )?;
                entries.push(entry);
            }
            let after = session.header(block)?;
            block_proofs.push(json!({"method":"eth_getBlockByNumber","block_number":block.number,"before":before,"after":after}));
        }
        let (proof_bytes, proof_sha) = write_json(
            &output.join("archive-blocks.json"),
            &block_proofs,
            MAX_DESCRIPTOR,
        )?;
        // Mapping-host's canonical cassette order is exact key order, not height.
        entries.sort_by(|a, b| {
            (&a.block_hash, &a.address, &a.calldata).cmp(&(&b.block_hash, &b.address, &b.calldata))
        });
        require(
            entries.windows(2).all(|w| {
                (&w[0].block_hash, &w[0].address, &w[0].calldata)
                    != (&w[1].block_hash, &w[1].address, &w[1].calldata)
            }),
            "duplicate cassette key",
        )?;
        let cassette = CassetteFile {
            schema: "pinax.substreams-backfills.mapping-host.cassette/v1".into(),
            entries,
        };
        let (cassette_bytes, cassette_sha) = write_json(
            &output.join("cassette.json.partial"),
            &cassette,
            MAX_CASSETTE,
        )?;
        require(
            executing_binary()? == executable,
            "executing binary changed",
        )?;
        let complete = json!({"format":"pinax.aerodrome.call-cassette-complete/v1","request_sha256":sha(request_bytes),"executable":{"bytes":executable.0,"sha256":executable.1},"input":request.input,"descriptor":request.descriptor,"extractor":request.extractor,"from_block":request.from_block,"to_exclusive":request.to_exclusive,"parent_hash":request.parent_hash,"head_hash":request.head_hash,"observed_blocks":inventory.blocks.len(),"calls":inventory.calls,"inventory_sha256":inventory_sha,"cassette":{"bytes":cassette_bytes,"sha256":cassette_sha},"observations":{"bytes":observation_bytes,"sha256":hex::encode(observation_hash.finalize())},"archive_blocks":{"bytes":proof_bytes,"sha256":proof_sha},"input_eof_verified":true,"archive_chain_id":8453,"archive_block_identity_before_and_after":true,"concurrency":1,"proves_completeness":false,"extractor_package_origin_verified":false,"native_process_exit_verified":false,"production_qualified":false});
        write_json(
            &output.join("complete.json.partial"),
            &complete,
            MAX_REQUEST,
        )?;
        File::open(output)
            .map_err(ioerr)?
            .sync_all()
            .map_err(ioerr)?;
        fs::hard_link(
            output.join("cassette.json.partial"),
            output.join("cassette.json"),
        )
        .map_err(ioerr)?;
        File::open(output)
            .map_err(ioerr)?
            .sync_all()
            .map_err(ioerr)?;
        fs::hard_link(
            output.join("complete.json.partial"),
            output.join("complete.json"),
        )
        .map_err(ioerr)?;
        File::open(output)
            .map_err(ioerr)?
            .sync_all()
            .map_err(ioerr)?;
        Ok(())
    })();
    if let Err(reason) = &result {
        // No provider URLs, error payloads, credentials or cursor bytes enter diagnostics.
        let _ = write_json(
            &output.join("failure.json"),
            &json!({"format":"pinax.aerodrome.call-cassette-failure/v1","reason":reason,"production_qualified":false}),
            MAX_REQUEST,
        );
    }
    result
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn response_arms_require_exactly_one_present_nonnull_field() {
        for tail in [
            r#""result":null,"error":{"code":3,"message":"execution reverted"}"#,
            r#""result":"0x","error":null"#,
            r#""result":null"#,
            r#""error":null"#,
            r#""result":"0x","result":"0x""#,
            r#""error":{"code":3,"message":"execution reverted"},"error":{"code":3,"message":"execution reverted"}"#,
        ] {
            let bytes = format!(r#"{{"jsonrpc":"2.0","id":1,{tail}}}"#);
            assert!(envelope::<String>(bytes.as_bytes(), 1).is_err(), "{tail}");
        }
        assert!(envelope::<String>(br#"{"jsonrpc":"2.0","id":1,"result":"0x"}"#, 1).is_ok());
        assert!(envelope::<String>(
            br#"{"jsonrpc":"2.0","id":1,"error":{"code":3,"message":"execution reverted"}}"#,
            1
        )
        .is_ok());
    }

    #[test]
    fn bounded_json_accounts_for_escaping_and_final_lf_before_any_file_write() {
        assert_eq!(bounded_json(&"a", 4).unwrap(), b"\"a\"\n");
        assert!(bounded_json(&"a", 3).is_err());
        assert_eq!(bounded_json(&"\n", 5).unwrap(), b"\"\\n\"\n");
        assert!(bounded_json(&"\n", 4).is_err());
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("oversized.json");
        assert!(write_json(&path, &"\n".repeat(1000), 128).is_err());
        assert!(!path.exists());
    }
}
