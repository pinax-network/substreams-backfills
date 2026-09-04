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

/// Schema identifier written into every cassette file.
pub const CASSETTE_SCHEMA: &str = "pinax.substreams-backfills.mapping-host.cassette/v1";

/// Gas limit for `eth_call`, copied from `runtime_adapter.rs:42`. It is a
/// protocol-wide parameter, so it is pinned rather than configurable.
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

    let response: serde_json::Value = ureq::post(rpc_url)
        .set("content-type", "application/json")
        .send_json(body)
        .map_err(|e| anyhow!("eth_call transport failure: {e}"))?
        .into_json()
        .map_err(|e| anyhow!("eth_call response was not JSON: {e}"))?;

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
        bail!("eth_call returned an error that is not a revert: {error}");
    }

    let result = response
        .get("result")
        .and_then(|r| r.as_str())
        .ok_or_else(|| anyhow!("eth_call response has no result: {response}"))?;
    Ok(CassetteRetval::Value(result.to_lowercase()))
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
