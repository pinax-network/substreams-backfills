//! Per-block answers are required input facts. Absence is a fatal contract
//! failure; only an explicit revert or ABI decode failure uses mapping fallback.
use crate::{
    abi::Abis, address, int24, pb, refuse, require, unsigned, word, Address, Result, Word,
};
use alloy_dyn_abi::DynSolValue;
use graph_numerics::BigInt;
use std::{
    cell::RefCell,
    collections::{BTreeMap, BTreeSet},
};

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TokenMetadata {
    pub symbol: String,
    pub name: String,
    pub total_supply: BigInt,
    pub decimals: u8,
}
pub fn graph_store_string(value: &str) -> String {
    value.replace('\0', "")
}
fn raw(value: &pb::RawRetval) -> Option<&[u8]> {
    match value.kind.as_ref()? {
        pb::raw_retval::Kind::Value(v) => Some(v),
        pb::raw_retval::Kind::Reverted(_) => None,
    }
}
fn token_text(name: &str, retval: &pb::RawRetval) -> String {
    let Some(bytes) = raw(retval) else {
        return "unknown".into();
    };
    let abi = Abis::locked();
    if let Some(DynSolValue::String(text)) = abi.erc20_output(name, false, bytes) {
        return text;
    }
    if let Some(DynSolValue::FixedBytes(bytes, 32)) = abi.erc20_output(name, true, bytes) {
        let mut sentinel = [0; 32];
        sentinel[31] = 1;
        if bytes.as_slice() != sentinel {
            return String::from_utf8_lossy(bytes.as_slice())
                .trim_end_matches('\0')
                .to_owned();
        }
    }
    "unknown".into()
}
pub fn token_metadata(answer: &pb::Erc20Answer) -> Result<TokenMetadata> {
    validate_erc20(answer)?;
    let abi = Abis::locked();
    let supply = raw(answer.total_supply.as_ref().unwrap())
        .and_then(|bytes| abi.erc20_output("totalSupply", false, bytes));
    let total_supply = match supply {
        Some(DynSolValue::Uint(n, _)) => n.to_string().parse().unwrap(),
        _ => BigInt::from(0),
    };
    let decimals = raw(answer.decimals.as_ref().unwrap())
        .and_then(|bytes| abi.erc20_output("decimals", false, bytes));
    let decimals = match decimals {
        Some(DynSolValue::Uint(n, _)) if n <= alloy_primitives::U256::from(255) => n.to::<u8>(),
        _ => 0,
    };
    Ok(TokenMetadata {
        symbol: token_text("symbol", answer.symbol.as_ref().unwrap()),
        name: token_text("name", answer.name.as_ref().unwrap()),
        total_supply,
        decimals,
    })
}
fn validate_erc20(a: &pb::Erc20Answer) -> Result<()> {
    address(&a.token)?;
    require(
        (a.rpc_failed_mask | a.rpc_empty_mask) & !15 == 0
            && a.rpc_failed_mask & a.rpc_empty_mask == 0,
        "invalid ERC20 RPC masks",
    )?;
    for (i, raw) in [&a.symbol, &a.name, &a.total_supply, &a.decimals]
        .into_iter()
        .enumerate()
    {
        let kind = raw
            .as_ref()
            .and_then(|r| r.kind.as_ref())
            .ok_or_else(|| refuse("missing ERC20 raw result"))?;
        let marked = (a.rpc_failed_mask | a.rpc_empty_mask) & (1 << i) != 0;
        match kind {
            pb::raw_retval::Kind::Value(bytes) => require(
                !bytes.is_empty() && !marked,
                "empty or falsely reverted ERC20 value",
            )?,
            pb::raw_retval::Kind::Reverted(_) => {
                require(marked, "ERC20 revert lacks failed/empty provenance")?
            }
        }
    }
    Ok(())
}
fn provenance(p: &Option<pb::SlotProvenance>, block: u64, zero: bool) -> Result<()> {
    let p = p
        .as_ref()
        .ok_or_else(|| refuse("missing slot provenance"))?;
    match pb::SlotSource::try_from(p.source).ok() {
        Some(pb::SlotSource::InBlock) => require(
            p.last_change_block == block && p.last_change_ordinal > 0,
            "invalid in-block provenance",
        ),
        Some(pb::SlotSource::Carried) => require(
            p.last_change_block > 0 && p.last_change_block < block && p.last_change_ordinal > 0,
            "invalid carried provenance",
        ),
        Some(pb::SlotSource::Zero) => require(
            p.last_change_block == 0 && p.last_change_ordinal == 0 && zero,
            "invalid zero provenance",
        ),
        _ => Err(refuse("unknown slot provenance source")),
    }
}
fn key32(bytes: &[u8]) -> Result<Word> {
    unsigned(bytes, 32)?;
    Ok(aerodrome_extractor_core::word(bytes).unwrap())
}
fn insert<K: Ord, V>(map: &mut BTreeMap<K, V>, key: K, value: V) -> Result<()> {
    require(
        map.insert(key, value).is_none(),
        "duplicate call answer key",
    )
}

#[derive(Debug)]
pub struct CallBook {
    block: u64,
    erc20: BTreeMap<Address, pb::Erc20Answer>,
    fee_growth: BTreeMap<Address, pb::FeeGrowthGlobalAnswer>,
    ticks: BTreeMap<(Address, i32), pb::TickAnswer>,
    positions: BTreeMap<Word, pb::PositionAnswer>,
    get_pool: BTreeMap<(Address, Address, i32), pb::GetPoolAnswer>,
    used: RefCell<BTreeSet<String>>,
}
impl CallBook {
    pub fn from_block(block: &pb::ExtractorBlock) -> Result<Self> {
        let calls = block.calls.as_ref().ok_or_else(|| {
            refuse("missing CallAnswers; candidate-only output is not reducer input")
        })?;
        let mut book = Self {
            block: block.number,
            erc20: BTreeMap::new(),
            fee_growth: BTreeMap::new(),
            ticks: BTreeMap::new(),
            positions: BTreeMap::new(),
            get_pool: BTreeMap::new(),
            used: RefCell::new(BTreeSet::new()),
        };
        for a in &calls.erc20 {
            validate_erc20(a)?;
            insert(&mut book.erc20, address(&a.token)?, a.clone())?;
        }
        for a in &calls.fee_growth {
            let v0 = word(&a.fee_growth_global0_x128)?;
            let v1 = word(&a.fee_growth_global1_x128)?;
            provenance(&a.p0, block.number, v0 == [0; 32])?;
            provenance(&a.p1, block.number, v1 == [0; 32])?;
            insert(&mut book.fee_growth, address(&a.pool)?, a.clone())?;
        }
        for a in &calls.ticks {
            int24(a.tick)?;
            require(
                a.staked_liquidity_net.len() == 16,
                "staked liquidity must be I128-16",
            )?;
            let fee = word(&a.fee_growth_outside0_x128)?;
            require(
                a.reasons != 0 && a.reasons & !3 == 0,
                "unknown or empty tick reason",
            )?;
            provenance(
                &a.p_staked,
                block.number,
                a.staked_liquidity_net.iter().all(|b| *b == 0),
            )?;
            provenance(&a.p_fee0, block.number, fee == [0; 32])?;
            insert(&mut book.ticks, (address(&a.pool)?, a.tick), a.clone())?;
        }
        for a in &calls.positions {
            let key = key32(&a.token_id)?;
            match a
                .result
                .as_ref()
                .ok_or_else(|| refuse("position answer missing result"))?
            {
                pb::position_answer::Result::Reverted(_) => (),
                pb::position_answer::Result::Value(v) => {
                    address(&v.token0)?;
                    address(&v.token1)?;
                    int24(v.tick_spacing)?;
                    int24(v.tick_lower)?;
                    int24(v.tick_upper)?;
                    require(
                        v.pool_id > 0 && v.tick_spacing > 0 && v.tick_lower < v.tick_upper,
                        "invalid position key fragment",
                    )?;
                    let f0 = word(&v.fee_growth_inside0_last_x128)?;
                    let f1 = word(&v.fee_growth_inside1_last_x128)?;
                    provenance(&v.p_key, block.number, false)?;
                    provenance(&v.p_fee0, block.number, f0 == [0; 32])?;
                    provenance(&v.p_fee1, block.number, f1 == [0; 32])?;
                }
            }
            insert(&mut book.positions, key, a.clone())?;
        }
        for a in &calls.get_pool {
            int24(a.tick_spacing)?;
            let pool = address(&a.pool)?;
            require(
                if pool == [0; 20] {
                    a.created_block == 0
                } else {
                    a.created_block >= aerodrome_extractor_core::config::INITIAL_BLOCK
                        && a.created_block <= block.number
                },
                "invalid getPool creation provenance",
            )?;
            insert(
                &mut book.get_pool,
                (address(&a.token_a)?, address(&a.token_b)?, a.tick_spacing),
                a.clone(),
            )?;
        }
        Ok(book)
    }
    fn used<'a, T>(&self, kind: &str, key: String, value: Option<&'a T>) -> Result<&'a T> {
        value
            .ok_or_else(|| {
                refuse(format!(
                    "MissingCallAnswer {{ kind: {kind}, key: {key}, block: {} }}",
                    self.block
                ))
            })
            .inspect(|_| {
                self.used.borrow_mut().insert(format!("{kind}:{key}"));
            })
    }
    pub fn erc20(&self, token: &Address) -> Result<&pb::Erc20Answer> {
        self.used("erc20", hex::encode(token), self.erc20.get(token))
    }
    pub fn fee_growth(&self, pool: &Address) -> Result<&pb::FeeGrowthGlobalAnswer> {
        self.used("fee_growth", hex::encode(pool), self.fee_growth.get(pool))
    }
    pub fn tick(&self, pool: &Address, tick: i32) -> Result<&pb::TickAnswer> {
        self.used(
            "tick",
            format!("{}:{tick}", hex::encode(pool)),
            self.ticks.get(&(*pool, tick)),
        )
    }
    pub fn position(&self, token_id: &Word) -> Result<&pb::PositionAnswer> {
        self.used(
            "position",
            hex::encode(token_id),
            self.positions.get(token_id),
        )
    }
    pub fn pool(&self, a: &Address, b: &Address, spacing: i32) -> Result<&pb::GetPoolAnswer> {
        self.used(
            "get_pool",
            format!("{}:{}:{spacing}", hex::encode(a), hex::encode(b)),
            self.get_pool.get(&(*a, *b, spacing)),
        )
    }
    pub fn unused_answer_count(&self) -> usize {
        self.erc20.len()
            + self.fee_growth.len()
            + self.ticks.len()
            + self.positions.len()
            + self.get_pool.len()
            - self.used.borrow().len()
    }
}
