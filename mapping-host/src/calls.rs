//! The `ethereum.call` cassette and the [`RuntimeAdapter`] that serves it.
//!
//! Graph Node's own `graph_chain_ethereum::RuntimeAdapter` cannot be reused with
//! a cassette-backed `EthereumCallCache`: `runtime_adapter.rs:100` resolves an
//! `EthereumAdapter` with `call_or_cheapest` *before* consulting the cache, so an
//! adapter-less network errors on every call. We therefore implement the
//! one-method [`RuntimeAdapter`] trait ourselves and return our own
//! `ethereum.call` host function, reproducing
//! `chain/ethereum/src/runtime/runtime_adapter.rs` `ethereum_call` and `eth_call`
//! step for step:
//!
//! 1. charge `ETHEREUM_CALL` gas,
//! 2. read the `SmartContractCall` out of WASM memory, using the `0.0.4` layout
//!    when the mapping's API version is at least 0.0.4,
//! 3. find the named ABI among the data source's ABIs, then the function by name
//!    and signature,
//! 4. ABI-encode the arguments,
//! 5. look the call up, and
//! 6. ABI-decode the output. A decode failure is a revert, exactly as
//!    `contract_calls::decode` treats it, and a revert becomes `AscPtr::null()`.
//!
//! AssemblyScript's generated `try_foo()` reads that null as `reverted = true`;
//! the non-`try` `foo()` asserts on it and aborts the handler with a
//! *deterministic* error. So the cassette records revert-versus-value, not just
//! return data, and uses graph-node's own
//! [`Retval`](graph::data::store::ethereum::call::Retval) shape on disk.
//!
//! ## Replay and record
//!
//! Replay is the default and **fails closed**: a key that is not in the cassette
//! is a hard error, never a silent revert, because a silent revert would change
//! the mapping's behaviour and the PoI. Record mode is entered only when the CLI
//! is given `--record` *and* `ETHEREUM_RPC_URL` is set; no endpoint is ever
//! compiled in.
//!
//! In record mode an RPC "execution reverted" answer is stored as `Null` and a
//! transport error is a hard failure. It is never mapped to
//! `HostExportError::PossibleReorg`: a cassette must not be able to produce one,
//! because `PossibleReorg` restarts the block stream in Graph Node and here would
//! silently mean "no answer".

use std::collections::BTreeMap;
use std::sync::{Arc, RwLock};

use anyhow::{anyhow, bail, Context, Result};
use graph::abi;
use graph::abi::FunctionExt as _;
use graph::blockchain::{HostFn, HostFnCtx, RuntimeAdapter};
use graph::cheap_clone::CheapClone;
use graph::data::store::ethereum::call;
use graph::data::store::scalar;
use graph::data::subgraph::API_VERSION_0_0_4;
use graph::data_source::common::MappingABI;
use graph::data_source::DataSource;
use graph::runtime::{asc_get, asc_new, AscPtr, HostExportError};
use graph_chain_ethereum::runtime::abi::{
    AscUnresolvedContractCall, AscUnresolvedContractCall_0_0_4,
};
use graph_chain_ethereum::runtime::runtime_adapter::{UnresolvedContractCall, ETHEREUM_CALL};
use graph_chain_ethereum::Chain;
use graph_runtime_wasm::asc_abi::class::{AscEnumArray, EthereumValueKind};
use serde::{Deserialize, Serialize};

use crate::bundle::sha256_hex;

/// Schema identifier written into every cassette file.
pub const CASSETTE_SCHEMA: &str = "pinax.substreams-backfills.mapping-host.cassette/v1";

/// Gas limit for `eth_call`, copied from `runtime_adapter.rs:43`, and sent with
/// every recorded call.
///
/// This is a pinned constant, not a rule the host follows. Graph Node's own
/// `eth_call_gas` sends it unless the RPC's `net_version` is listed in
/// `GRAPH_ETH_CALL_NO_GAS` (default `421613,421614`), and then sends no gas at
/// all. The host has no such exemption, and `env_pin` does not pin that
/// variable: the constant equals Graph Node's value for every chain this crate
/// bundles (mainnet `1`, Base `8453`) only because none is in the default list.
pub const ETH_CALL_GAS: u32 = 50_000_000;

/// The recorded outcome of one call.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(tag = "kind", content = "data", rename_all = "snake_case")]
pub enum CassetteRetval {
    /// The node reported an EVM revert, or returned `0x`.
    Null,
    /// Return data, `0x`-prefixed lowercase hex.
    Value(String),
}

impl CassetteRetval {
    fn to_retval(&self) -> Result<call::Retval> {
        Ok(match self {
            CassetteRetval::Null => call::Retval::Null,
            CassetteRetval::Value(hex_str) => {
                let raw = hex::decode(hex_str.trim_start_matches("0x"))
                    .with_context(|| format!("decoding cassette return data `{hex_str}`"))?;
                call::Retval::Value(scalar::Bytes::from(raw.as_slice()))
            }
        })
    }
}

/// One cassette row. `block_hash`, `address` and `calldata` are the key; the rest
/// is provenance that makes a cassette readable and reviewable.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct CassetteEntry {
    pub block_number: i32,
    pub block_hash: String,
    pub address: String,
    pub calldata: String,
    pub contract: String,
    pub function: String,
    pub retval: CassetteRetval,
}

impl CassetteEntry {
    fn key(&self) -> CallKey {
        (
            self.block_hash.to_lowercase(),
            self.address.to_lowercase(),
            self.calldata.to_lowercase(),
        )
    }
}

type CallKey = (String, String, String);

/// A cassette file: a schema tag and rows sorted by key.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct CassetteFile {
    pub schema: String,
    pub entries: Vec<CassetteEntry>,
}

/// How the adapter answers a call it has not seen.
#[derive(Clone, Debug)]
pub enum CassetteMode {
    /// Fail closed on a missing key.
    Replay,
    /// Perform `eth_call` against this endpoint and append the answer.
    Record { rpc_url: String },
}

/// A keyed set of recorded `eth_call` answers.
pub struct Cassette {
    entries: RwLock<BTreeMap<CallKey, CassetteEntry>>,
    mode: CassetteMode,
    dirty: RwLock<bool>,
}

impl Cassette {
    /// A bounded, exact replay input for the disk oracle. Parsing never reopens
    /// the caller's file and duplicate call identities are refused.
    pub(crate) fn replay_bytes(bytes: &[u8]) -> Result<Self> {
        if bytes.len() > 64 * 1024 * 1024 {
            bail!("disk oracle cassette exceeds 64 MiB");
        }
        let file: CassetteFile = serde_json::from_slice(bytes)?;
        if file.schema != CASSETTE_SCHEMA {
            bail!("disk oracle cassette schema mismatch");
        }
        if file.entries.len() > 100_000 {
            bail!("disk oracle cassette exceeds 100000 entries");
        }
        let mut entries = BTreeMap::new();
        for entry in file.entries {
            if entries.insert(entry.key(), entry).is_some() {
                bail!("disk oracle cassette repeats a call identity");
            }
        }
        Ok(Self {
            entries: RwLock::new(entries),
            mode: CassetteMode::Replay,
            dirty: RwLock::new(false),
        })
    }

    /// Load a cassette, or start an empty one if the file does not exist.
    pub fn load(path: &std::path::Path, mode: CassetteMode) -> Result<Self> {
        let entries = if path.exists() {
            let bytes = std::fs::read(path)
                .with_context(|| format!("reading cassette {}", path.display()))?;
            let file: CassetteFile = serde_json::from_slice(&bytes)
                .with_context(|| format!("parsing cassette {}", path.display()))?;
            if file.schema != CASSETTE_SCHEMA {
                bail!(
                    "{}: unexpected cassette schema `{}`, want `{}`",
                    path.display(),
                    file.schema,
                    CASSETTE_SCHEMA
                );
            }
            file.entries.into_iter().map(|e| (e.key(), e)).collect()
        } else {
            BTreeMap::new()
        };
        Ok(Cassette {
            entries: RwLock::new(entries),
            mode,
            dirty: RwLock::new(false),
        })
    }

    pub fn len(&self) -> usize {
        self.entries.read().expect("cassette lock poisoned").len()
    }

    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }

    pub fn is_dirty(&self) -> bool {
        *self.dirty.read().expect("cassette lock poisoned")
    }

    /// Whether this run may append rows, i.e. whether the cassette is an output
    /// as well as an input.
    pub fn is_recording(&self) -> bool {
        matches!(self.mode, CassetteMode::Record { .. })
    }

    /// Reduce the cassette to what a checkpoint needs in order to pin it.
    ///
    /// `sha256` is the digest of the file on disk, which this type does not know
    /// the path of. The rows are digested individually and ordered by key
    /// digest, so a checkpoint can later be checked against a cassette that has
    /// *grown* — which is the normal state of affairs for a `--record` run, and
    /// the reason the whole-file digest alone is not a usable rule.
    pub fn fingerprint(&self, sha256: String) -> Result<CassetteFingerprint> {
        let entries = self.entries.read().expect("cassette lock poisoned");
        let mut rows: Vec<CassetteRowFingerprint> = entries
            .values()
            .map(CassetteRowFingerprint::of)
            .collect::<Result<Vec<_>>>()?;
        rows.sort_by(|a, b| a.key_sha256.cmp(&b.key_sha256));
        Ok(CassetteFingerprint {
            sha256,
            recording: self.is_recording(),
            rows,
        })
    }
}

/// One cassette row, reduced to what pins it.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CassetteRowFingerprint {
    /// The block the call was recorded at. Provenance, and the first thing an
    /// operator needs in order to find the row in the file.
    pub block: i32,
    /// SHA-256 over the key: block hash, address and calldata, one per line.
    pub key_sha256: String,
    /// SHA-256 over the whole row — the key, the answer, and the provenance
    /// beside it. A checkpoint asserts that this has not changed, so editing a
    /// recorded row by hand is caught whether or not the answer moved.
    pub row_sha256: String,
    /// `<address> <calldata>`, carried only so a refusal can name the call
    /// rather than a digest. Never written to a checkpoint.
    pub call: String,
}

impl CassetteRowFingerprint {
    fn of(entry: &CassetteEntry) -> Result<Self> {
        let (block_hash, address, calldata) = entry.key();
        Ok(CassetteRowFingerprint {
            block: entry.block_number,
            key_sha256: sha256_hex(format!("{block_hash}\n{address}\n{calldata}").as_bytes()),
            row_sha256: sha256_hex(
                serde_json::to_string(entry)
                    .context("digesting a cassette row")?
                    .as_bytes(),
            ),
            call: format!("{address} {calldata}"),
        })
    }
}

/// The cassette as a checkpoint sees it: the file's digest, whether the run may
/// append to it, and every row reduced to a pair of digests.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CassetteFingerprint {
    /// SHA-256 of the file on disk.
    pub sha256: String,
    /// Whether the run this belongs to was recording.
    pub recording: bool,
    /// Every row, ordered by `key_sha256`.
    pub rows: Vec<CassetteRowFingerprint>,
}

impl CassetteFingerprint {
    /// Look a row up by its key digest.
    pub fn row(&self, key_sha256: &str) -> Option<&CassetteRowFingerprint> {
        self.rows
            .binary_search_by(|row| row.key_sha256.as_str().cmp(key_sha256))
            .ok()
            .map(|at| &self.rows[at])
    }
}

impl Cassette {
    /// Write the cassette back, sorted by key so the file is byte-stable, and
    /// atomically so a run that dies mid-write cannot leave a truncated one.
    ///
    /// The entries live in a `BTreeMap` keyed by `(block hash, address,
    /// calldata)`, so appending rows during a long live run rewrites the same
    /// bytes in the same order every time: a recording is a pure addition to the
    /// file, never a reshuffle.
    pub fn save(&self, path: &std::path::Path) -> Result<()> {
        let entries = self.entries.read().expect("cassette lock poisoned");
        let file = CassetteFile {
            schema: CASSETTE_SCHEMA.to_string(),
            entries: entries.values().cloned().collect(),
        };
        let mut json = serde_json::to_string_pretty(&file)?;
        json.push('\n');
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let temp = path.with_extension(format!("tmp{}", std::process::id()));
        std::fs::write(&temp, json)
            .with_context(|| format!("writing cassette {}", temp.display()))?;
        std::fs::rename(&temp, path).with_context(|| {
            format!(
                "renaming {} over cassette {}",
                temp.display(),
                path.display()
            )
        })?;
        *self.dirty.write().expect("cassette lock poisoned") = false;
        Ok(())
    }

    /// Look a call up, recording it first if we are in record mode.
    fn lookup(
        &self,
        block_number: i32,
        block_hash: &str,
        address: &str,
        calldata: &str,
        contract: &str,
        function: &str,
    ) -> Result<call::Retval> {
        let key: CallKey = (
            block_hash.to_lowercase(),
            address.to_lowercase(),
            calldata.to_lowercase(),
        );
        if let Some(entry) = self
            .entries
            .read()
            .expect("cassette lock poisoned")
            .get(&key)
        {
            return entry.retval.to_retval();
        }

        let rpc_url = match &self.mode {
            CassetteMode::Replay => {
                bail!(
                    "cassette miss in replay mode: {} {} at block {} ({}::{}); \
                     re-record with --record and ETHEREUM_RPC_URL",
                    address,
                    calldata,
                    block_hash,
                    contract,
                    function
                );
            }
            CassetteMode::Record { rpc_url } => rpc_url.clone(),
        };

        let retval = rpc_eth_call(&rpc_url, block_hash, address, calldata)?;
        let entry = CassetteEntry {
            block_number,
            block_hash: block_hash.to_lowercase(),
            address: address.to_lowercase(),
            calldata: calldata.to_lowercase(),
            contract: contract.to_string(),
            function: function.to_string(),
            retval,
        };
        let out = entry.retval.to_retval()?;
        self.entries
            .write()
            .expect("cassette lock poisoned")
            .insert(key, entry);
        *self.dirty.write().expect("cassette lock poisoned") = true;
        Ok(out)
    }
}

/// A single JSON-RPC `eth_call` pinned to a block hash (EIP-1898), which is the
/// same block identifier `EthereumAdapter::block_ptr_to_id` uses on a node that
/// supports it.
///
/// An `execution reverted` style error becomes `Null`; any other error, including
/// every transport error, is returned as an error so a recording never invents an
/// answer.
///
/// A throttled or temporarily unavailable endpoint is retried with exponential
/// backoff rather than failing the run: a 429 or 5xx is the endpoint declining to
/// answer, which is not a revert and not an answer, so inventing either would be
/// wrong and giving up discards a long recording. `ETHEREUM_RPC_MAX_RETRIES`
/// (default 6) and `ETHEREUM_RPC_BASE_DELAY_MS` (default 500) bound it, and
/// `ETHEREUM_RPC_MIN_INTERVAL_MS` paces every call so a long window does not
/// trip the limiter in the first place. An `Authorization` header is sent when
/// `ETHEREUM_RPC_BEARER` is set.
fn rpc_eth_call(
    rpc_url: &str,
    block_hash: &str,
    address: &str,
    calldata: &str,
) -> Result<CassetteRetval> {
    let body = serde_json::json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_call",
        "params": [
            {
                "to": address,
                "data": calldata,
                "gas": format!("0x{:x}", ETH_CALL_GAS),
            },
            { "blockHash": block_hash, "requireCanonical": true }
        ]
    });

    let response: serde_json::Value = send_with_backoff(rpc_url, &body)?;
    decode_eth_call_response(response)
}

fn decode_eth_call_response(response: serde_json::Value) -> Result<CassetteRetval> {
    if let Some(error) = response.get("error") {
        let message = error
            .get("message")
            .and_then(|m| m.as_str())
            .unwrap_or_default()
            .to_lowercase();
        // The revert vocabulary graph-node recognises, from
        // `chain/ethereum/src/call_helper.rs` RPC_EXECUTION_ERRORS.
        const REVERT_MARKERS: &[&str] = &[
            "reverted",
            "invalid opcode",
            "invalid jump",
            "out of gas",
            "stack underflow",
            "stack limit reached",
            "execution error",
            "invalidfeopcode",
        ];
        if REVERT_MARKERS.iter().any(|m| message.contains(m)) {
            return Ok(CassetteRetval::Null);
        }
        // An upstream error can reflect an authenticated URL or API key. Keep
        // classification unchanged, but never render the remote error body.
        bail!("eth_call returned an error that is not a revert (remote details redacted)");
    }

    let result = response
        .get("result")
        .and_then(|r| r.as_str())
        .ok_or_else(|| anyhow!("eth_call response has no result (remote details redacted)"))?;
    Ok(CassetteRetval::Value(result.to_lowercase()))
}

/// Environment knobs for the recording transport. All are optional.
const RPC_MAX_RETRIES: &str = "ETHEREUM_RPC_MAX_RETRIES";
const RPC_BASE_DELAY_MS: &str = "ETHEREUM_RPC_BASE_DELAY_MS";
const RPC_MIN_INTERVAL_MS: &str = "ETHEREUM_RPC_MIN_INTERVAL_MS";
const RPC_BEARER: &str = "ETHEREUM_RPC_BEARER";

fn env_u64(name: &str, default: u64) -> u64 {
    std::env::var(name)
        .ok()
        .and_then(|v| v.parse::<u64>().ok())
        .unwrap_or(default)
}

/// Earliest instant the next request may be sent, so `ETHEREUM_RPC_MIN_INTERVAL_MS`
/// paces the whole recording rather than one call site.
static NEXT_REQUEST_AT: std::sync::Mutex<Option<std::time::Instant>> = std::sync::Mutex::new(None);

fn pace() {
    let interval = env_u64(RPC_MIN_INTERVAL_MS, 0);
    if interval == 0 {
        return;
    }
    let gap = std::time::Duration::from_millis(interval);
    let wait = {
        let mut next = NEXT_REQUEST_AT
            .lock()
            .expect("pacing mutex is not poisoned");
        let now = std::time::Instant::now();
        let ready = next.unwrap_or(now).max(now);
        *next = Some(ready + gap);
        ready.saturating_duration_since(now)
    };
    if !wait.is_zero() {
        std::thread::sleep(wait);
    }
}

/// POST the request, retrying only statuses that mean "ask again later".
///
/// A 429 or 5xx carries no answer: it is neither a value nor a revert, so the
/// only faithful responses are to wait or to fail. Every other transport error
/// fails immediately.
fn send_with_backoff(rpc_url: &str, body: &serde_json::Value) -> Result<serde_json::Value> {
    let max_retries = env_u64(RPC_MAX_RETRIES, 6);
    let base_delay = env_u64(RPC_BASE_DELAY_MS, 500);
    let bearer = std::env::var(RPC_BEARER).ok().filter(|t| !t.is_empty());
    let mut attempt = 0;
    loop {
        pace();
        let mut request = ureq::post(rpc_url).set("content-type", "application/json");
        if let Some(token) = bearer.as_deref() {
            request = request.set("authorization", &format!("Bearer {token}"));
        }
        match request.send_json(body.clone()) {
            Ok(response) => {
                return response
                    .into_json()
                    .map_err(|e| anyhow!("eth_call response was not JSON: {e}"));
            }
            Err(ureq::Error::Status(status, _)) if retryable(status) && attempt < max_retries => {
                std::thread::sleep(backoff_delay(base_delay, attempt));
                attempt += 1;
            }
            Err(e) => return Err(redacted_transport_error(&e)),
        }
    }
}

// `ureq::Error` Display includes the URL, which may carry credentials.
fn redacted_transport_error(error: &ureq::Error) -> anyhow::Error {
    match error {
        ureq::Error::Status(status, _) => anyhow!("eth_call HTTP failure: status {status}"),
        ureq::Error::Transport(error) => anyhow!("eth_call transport failure: {:?}", error.kind()),
    }
}

#[cfg(test)]
mod credential_redaction_tests {
    #[test]
    fn reflected_credentials_never_appear_in_rpc_errors() {
        for response in [
            serde_json::json!({"error": {"code": -32000, "message": "invalid key secret-api-key?token=private-value"}}),
            serde_json::json!({"unexpected": "https://user:private-value@rpc.invalid/secret-api-key"}),
        ] {
            let rendered = super::decode_eth_call_response(response)
                .unwrap_err()
                .to_string();
            assert!(rendered.contains("redacted"));
            assert!(!rendered.contains("secret-api-key"));
            assert!(!rendered.contains("private-value"));
        }
    }

    #[test]
    fn redaction_preserves_revert_and_value_classification() {
        let reverted = super::decode_eth_call_response(
            serde_json::json!({"error": {"message": "execution reverted"}}),
        )
        .unwrap();
        assert!(matches!(reverted, super::CassetteRetval::Null));
        let value =
            super::decode_eth_call_response(serde_json::json!({"result": "0xABCD"})).unwrap();
        assert!(matches!(value, super::CassetteRetval::Value(data) if data == "0xabcd"));
    }

    #[test]
    fn a_signed_endpoint_never_appears_in_transport_errors() {
        let error = ureq::post("http://127.0.0.1:1/secret-api-key?token=private-value")
            .timeout(std::time::Duration::from_millis(100))
            .call()
            .unwrap_err();
        let rendered = super::redacted_transport_error(&error).to_string();
        for secret in ["127.0.0.1", "secret-api-key", "private-value", "http:"] {
            assert!(!rendered.contains(secret), "{rendered}");
        }
    }
}

/// Statuses that mean the endpoint declined to answer this time.
fn retryable(status: u16) -> bool {
    status == 429 || (500..=599).contains(&status)
}

/// How long to wait before attempt `attempt + 1`: the base delay doubled once
/// per attempt already made.
///
/// The shift is clamped and the multiply saturates, so an operator who sets
/// `ETHEREUM_RPC_MAX_RETRIES` to something absurd gets a very long wait rather
/// than a panic on a shift overflow or a wrapped delay that retries instantly.
fn backoff_delay(base_delay_ms: u64, attempt: u64) -> std::time::Duration {
    std::time::Duration::from_millis(base_delay_ms.saturating_mul(1u64 << attempt.min(16)))
}

/// A [`RuntimeAdapter`] whose only host function is a cassette-backed
/// `ethereum.call`.
///
/// `ethereum.getBalance` and `ethereum.hasCode` are deliberately absent: they
/// require API version 0.0.9 and no Uniswap V3 module imports them, so a mapping
/// that reached for one would fail loudly rather than read invented state.
pub struct CassetteRuntimeAdapter {
    cassette: Arc<Cassette>,
}

impl CassetteRuntimeAdapter {
    pub fn new(cassette: Arc<Cassette>) -> Self {
        CassetteRuntimeAdapter { cassette }
    }
}

impl RuntimeAdapter<Chain> for CassetteRuntimeAdapter {
    fn host_fns(&self, ds: &DataSource<Chain>) -> Result<Vec<HostFn>, anyhow::Error> {
        let Some(onchain) = ds.as_onchain() else {
            return Ok(vec![]);
        };
        let abis: Arc<Vec<Arc<MappingABI>>> = Arc::new(onchain.mapping.abis.clone());
        let cassette = self.cassette.cheap_clone();

        Ok(vec![HostFn {
            name: "ethereum.call",
            func: Arc::new(move |ctx: HostFnCtx<'_>, wasm_ptr: u32| {
                let abis = abis.clone();
                let cassette = cassette.clone();
                Box::pin(async move {
                    ethereum_call(cassette, abis, ctx, wasm_ptr)
                        .await
                        .map(|ptr| ptr.wasm_ptr())
                })
            }),
        }])
    }
}

/// `function ethereum.call(call: SmartContractCall): Array<Token> | null`
async fn ethereum_call(
    cassette: Arc<Cassette>,
    abis: Arc<Vec<Arc<MappingABI>>>,
    ctx: HostFnCtx<'_>,
    wasm_ptr: u32,
) -> Result<AscEnumArray<EthereumValueKind>, HostExportError> {
    ctx.gas
        .consume_host_fn_with_metrics(ETHEREUM_CALL, "ethereum_call")?;

    // For apiVersion >= 0.0.4 the call passed from the mapping includes the
    // function signature; subgraphs using an apiVersion < 0.0.4 do not.
    let unresolved: UnresolvedContractCall = if ctx.heap.api_version() >= &API_VERSION_0_0_4 {
        asc_get::<_, AscUnresolvedContractCall_0_0_4, _>(ctx.heap, wasm_ptr.into(), &ctx.gas, 0)?
    } else {
        asc_get::<_, AscUnresolvedContractCall, _>(ctx.heap, wasm_ptr.into(), &ctx.gas, 0)?
    };

    let block_ptr = ctx.block_ptr.clone();
    let result = resolve_call(&cassette, &abis, &block_ptr, &unresolved)?;

    match result {
        Some(tokens) => Ok(asc_new(ctx.heap, tokens.as_slice(), &ctx.gas).await?),
        None => Ok(AscPtr::null()),
    }
}

/// Encode, look up, decode. `Ok(None)` means "reverted", which the caller turns
/// into a null pointer.
fn resolve_call(
    cassette: &Cassette,
    abis: &[Arc<MappingABI>],
    block_ptr: &graph::blockchain::BlockPtr,
    unresolved: &UnresolvedContractCall,
) -> Result<Option<Vec<abi::DynSolValue>>, HostExportError> {
    let abi = abis
        .iter()
        .find(|abi| abi.name == unresolved.contract_name)
        .with_context(|| {
            format!(
                "Could not find ABI for contract \"{}\", try adding it to the 'abis' section \
                 of the subgraph manifest",
                unresolved.contract_name
            )
        })
        .map_err(HostExportError::Deterministic)?;

    let function = abi
        .function(
            &unresolved.contract_name,
            &unresolved.function_name,
            unresolved.function_signature.as_deref(),
        )
        .map_err(HostExportError::Deterministic)?;

    let encoded = function
        .abi_encode_input(&unresolved.function_args)
        .map_err(|e| {
            HostExportError::Deterministic(anyhow!(
                "failed to ABI-encode {}::{}: {e}",
                unresolved.contract_name,
                unresolved.function_name
            ))
        })?;

    let address = format!("0x{}", hex::encode(unresolved.contract_address.as_slice()));
    let calldata = format!("0x{}", hex::encode(&encoded));
    let block_hash = format!("0x{}", hex::encode(block_ptr.hash_slice()));

    let retval = cassette
        .lookup(
            block_ptr.number,
            &block_hash,
            &address,
            &calldata,
            &unresolved.contract_name,
            &function.signature(),
        )
        .map_err(HostExportError::Unknown)?;

    Ok(match retval {
        // A `0x` response is treated as a revert: a view call is meant to return
        // something. Same reasoning as `contract_calls::decode`.
        call::Retval::Null => None,
        // Decode failures are reverts: if Solidity fails to decode an argument
        // that is a revert, so the same goes for the output.
        call::Retval::Value(output) => function.abi_decode_output(&output).ok(),
    })
}

#[cfg(test)]
mod transport_tests {
    use super::*;

    #[test]
    fn only_throttle_and_server_errors_are_retried() {
        // 429 and 5xx mean "ask again later"; they carry neither a value nor a
        // revert, so retrying is the only faithful response.
        assert!(retryable(429));
        assert!(retryable(500));
        assert!(retryable(503));
        assert!(retryable(599));
        // A refusal that will not change on a second ask must fail the run.
        assert!(!retryable(200));
        assert!(!retryable(400));
        assert!(!retryable(401));
        assert!(!retryable(404));
    }

    #[test]
    fn the_backoff_doubles_and_never_overflows() {
        // Six retries at the 500 ms default is 500, 1s, 2s, 4s, 8s, 16s: about
        // half a minute of patience, which is the right order for a throttled
        // public endpoint and nowhere near a hung run.
        let delays: Vec<u64> = (0..6)
            .map(|attempt| backoff_delay(500, attempt).as_millis() as u64)
            .collect();
        assert_eq!(delays, vec![500, 1_000, 2_000, 4_000, 8_000, 16_000]);
        assert_eq!(delays.iter().sum::<u64>(), 31_500);

        // A retry count large enough to overflow the shift, and a base delay
        // large enough to overflow the multiply, must both still return a
        // duration rather than panicking or wrapping to zero.
        assert!(backoff_delay(500, 64) >= backoff_delay(500, 16));
        assert!(backoff_delay(u64::MAX, 40) > std::time::Duration::ZERO);
        assert_eq!(backoff_delay(0, 3), std::time::Duration::ZERO);
    }

    #[test]
    fn transport_knobs_fall_back_to_their_defaults() {
        let unset = "ETHEREUM_RPC_TEST_KNOB_THAT_IS_NEVER_SET";
        assert_eq!(env_u64(unset, 7), 7);
        // A value that is not a whole number is ignored rather than guessed at.
        unsafe { std::env::set_var(unset, "not-a-number") };
        assert_eq!(env_u64(unset, 7), 7);
        unsafe { std::env::set_var(unset, "11") };
        assert_eq!(env_u64(unset, 7), 11);
        unsafe { std::env::remove_var(unset) };
    }
}
