//! Graph Node receipt ordering and same-block dynamic-host rescan.
use crate::{
    config::{Config, CONTRACT},
    gas::graph_node_gas_price,
    layout, minimal,
    pb::{eth, internal as i, v1 as p},
    Address,
};
use std::collections::{BTreeMap, BTreeSet};
pub trait PoolRegistry {
    fn pool(&self, address: &Address) -> Result<Option<i::PoolRecord>, String>;
}
impl PoolRegistry for BTreeMap<Address, i::PoolRecord> {
    fn pool(&self, address: &Address) -> Result<Option<i::PoolRecord>, String> {
        Ok(self.get(address).cloned())
    }
}
/// Generated ABI adapters live outside core, so native reducers need no Substreams runtime.
pub trait EventDecoder {
    fn matches(&self, source: p::DataSourceKind, log: &eth::Log) -> bool;
    fn decoded(&self, source: p::DataSourceKind, log: &eth::Log) -> bool;
    fn pool_created(&self, log: &eth::Log) -> Option<i::PoolCreatedRecord>;
}
fn anomaly(kind: p::AnomalyKind, log: Option<&eth::Log>, detail: impl Into<String>) -> p::Anomaly {
    p::Anomaly {
        kind: kind as i32,
        address: log.map(|l| l.address.clone()).unwrap_or_default(),
        ordinal: log.map(|l| l.ordinal).unwrap_or(0),
        detail: detail.into(),
        ..Default::default()
    }
}
fn clone_code(tx: &eth::TransactionTrace, pool: &[u8]) -> Vec<u8> {
    // Firehose encodes CREATE and CREATE2 with CallType::Create (5).
    tx.calls
        .iter()
        .filter(|c| c.call_type == 5 && !c.state_reverted)
        .flat_map(|c| &c.code_changes)
        .filter(|c| c.address == pool)
        .filter_map(|c| layout::clone_implementation(&c.new_code))
        .next()
        .map(|a| a.to_vec())
        .unwrap_or_default()
}
pub fn pools_created(
    cfg: &Config,
    block: &eth::Block,
    decoder: &impl EventDecoder,
) -> i::PoolsCreated {
    let mut result = i::PoolsCreated::default();
    if block.number < cfg.factory_start {
        return result;
    }
    for tx in block.transaction_traces.iter().filter(|t| t.status == 1) {
        if let Some(receipt) = &tx.receipt {
            for log in &receipt.logs {
                if log.address != cfg.factory {
                    continue;
                }
                if let Some(mut pool) = decoder.pool_created(log) {
                    pool.tx_index = tx.index;
                    pool.log_index = log.block_index;
                    pool.log_ordinal = log.ordinal;
                    pool.clone_implementation = clone_code(tx, &pool.pool);
                    result.pools.push(pool);
                }
            }
        }
    }
    result.pools.sort_by_key(|p| p.log_index);
    result
}
pub fn build_candidates(
    cfg: &Config,
    block: &eth::Block,
    registry: &impl PoolRegistry,
    decoder: &impl EventDecoder,
) -> Result<p::ExtractorBlock, String> {
    let header = block.header.as_ref().ok_or("missing block header")?;
    if block.hash.len() != 32 || header.parent_hash.len() != 32 {
        return Err("block hashes must be 32 bytes".into());
    }
    let timestamp = u64::try_from(
        header
            .timestamp
            .as_ref()
            .ok_or("missing timestamp")?
            .seconds,
    )
    .map_err(|_| "negative timestamp")?;
    // Graph Node's codec truncates baseFee to u64. Transaction fees remain checked u128.
    let base_fee = header.base_fee_per_gas.as_ref().map(|b| {
        let mut bytes = [0; 8];
        let n = b.bytes.len().min(8);
        bytes[8 - n..].copy_from_slice(&b.bytes[b.bytes.len() - n..]);
        u64::from_be_bytes(bytes)
    });
    let mut audit = p::ExtractorAudit::default();
    if !matches!(block.ver, 4 | 5) || block.detail_level != 0 {
        audit.anomalies.push(anomaly(
            p::AnomalyKind::AnomalyUnsupportedBlockVersion,
            None,
            "requires extended Firehose v4/v5",
        ));
    }
    let mut out = p::ExtractorBlock {
        number: block.number,
        hash: block.hash.clone(),
        parent_hash: header.parent_hash.clone(),
        timestamp,
        base_fee_per_gas: base_fee,
        firehose_block_version: u32::try_from(block.ver).map_err(|_| "negative block version")?,
        contract: CONTRACT.into(),
        ..Default::default()
    };
    let mut logs = vec![];
    let mut by_index = BTreeMap::new();
    for tx in &block.transaction_traces {
        if by_index.insert(tx.index, tx).is_some() {
            return Err("duplicate transaction index".into());
        }
        let receipt = tx.receipt.as_ref();
        if tx.status != 1 {
            if receipt.is_some_and(|r| !r.logs.is_empty()) {
                audit.anomalies.push(anomaly(
                    p::AnomalyKind::AnomalyFailedTxWithReceiptLogs,
                    None,
                    format!("transaction {}", tx.index),
                ));
            }
            continue;
        }
        if let Some(receipt) = receipt {
            for log in &receipt.logs {
                logs.push((log, tx.index));
            }
        }
    }
    logs.sort_by_key(|(l, _)| l.block_index);
    out.receipt_log_count = u32::try_from(logs.len()).map_err(|_| "too many receipt logs")?;
    if logs
        .iter()
        .enumerate()
        .any(|(index, (l, _))| l.block_index as usize != index)
    {
        audit.anomalies.push(anomaly(
            p::AnomalyKind::AnomalyLogIndexNotDense,
            None,
            "receipt block_index must be unique and dense from zero",
        ));
    }
    let created = pools_created(cfg, block, decoder);
    for record in created.pools {
        if record.clone_implementation != cfg.pool_implementation {
            audit.anomalies.push(p::Anomaly {
                kind: p::AnomalyKind::AnomalyPoolNotPinnedClone as i32,
                address: record.pool.clone(),
                ordinal: record.log_ordinal,
                detail: "missing or mismatched EIP-1167 creation code".into(),
                ..Default::default()
            });
        }
        out.pools_created.push(p::PoolCreatedFact {
            pool: record.pool,
            token0: record.token0,
            token1: record.token1,
            tick_spacing: record.tick_spacing,
            log_index: record.log_index,
            clone_implementation: record.clone_implementation,
            log_ordinal: record.log_ordinal,
        });
    }
    let mut selected = BTreeSet::new();
    for (log, tx_index) in logs {
        let address: Address = match log.address.as_slice().try_into() {
            Ok(a) => a,
            Err(_) => return Err("receipt log address must be 20 bytes".into()),
        };
        let (source, wave, host) = if address == cfg.factory && block.number >= cfg.factory_start {
            (p::DataSourceKind::Factory, 0, 0)
        } else if address == cfg.npm && block.number >= cfg.npm_start {
            (p::DataSourceKind::PositionManager, 0, 1)
        } else if let Some(pool) = registry.pool(&address)? {
            if pool.created_block > block.number {
                continue;
            }
            let host = pool
                .created_block
                .checked_mul(1 << 24)
                .and_then(|n| n.checked_add(u64::from(pool.created_log_index) + 2))
                .ok_or("host order overflow")?;
            (
                p::DataSourceKind::Pool,
                u32::from(pool.created_block == block.number),
                host,
            )
        } else {
            continue;
        };
        if !decoder.matches(source, log) {
            continue;
        }
        let abi_decoded = decoder.decoded(source, log);
        if !abi_decoded {
            audit.candidate_decode_failures += 1;
        }
        selected.insert(tx_index);
        out.candidates.push(p::CandidateLog {
            wave,
            source_trigger_order: log.block_index,
            log_index: log.block_index,
            tx: tx_index,
            address: log.address.clone(),
            topics: log.topics.clone(),
            data: log.data.clone(),
            log_ordinal: log.ordinal,
            source: source as i32,
            host_order_key: host,
            abi_decoded,
        });
    }
    let mut hashes = BTreeSet::new();
    for index in selected {
        let tx = by_index[&index];
        if tx.hash.len() != 32 || tx.from.len() != 20 || (!tx.to.is_empty() && tx.to.len() != 20) {
            return Err("invalid transaction hash/from/to width".into());
        }
        if !hashes.insert(&tx.hash) {
            return Err("duplicate transaction hash".into());
        }
        let raw = |v: &Option<eth::BigInt>| v.as_ref().map(|v| minimal(&v.bytes));
        let gp = raw(&tx.gas_price);
        let cap = raw(&tx.max_fee_per_gas);
        let priority = raw(&tx.max_priority_fee_per_gas);
        let kind = u32::try_from(tx.r#type).map_err(|_| "negative transaction type")?;
        let price = graph_node_gas_price(
            kind,
            gp.as_deref(),
            cap.as_deref(),
            priority.as_deref(),
            base_fee,
        )
        .map_err(|e| e.to_string())?;
        let remapped = out.transactions.len() as u32;
        for c in out.candidates.iter_mut().filter(|c| c.tx == index) {
            c.tx = remapped;
        }
        out.transactions.push(p::Transaction {
            hash: tx.hash.clone(),
            index,
            from: tx.from.clone(),
            gas_limit: tx.gas_limit,
            r#type: kind,
            gas_price: gp,
            max_fee_per_gas: cap,
            max_priority_fee_per_gas: priority,
            to: if tx.calls.first().is_some_and(|c| c.call_type == 5) {
                vec![]
            } else {
                tx.to.clone()
            },
            graph_gas_price: minimal(&price.to_be_bytes()),
        });
    }
    out.candidates
        .sort_by_key(|c| (c.wave, c.source_trigger_order));
    out.audit = Some(audit);
    Ok(out)
}
