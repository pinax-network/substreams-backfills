use super::*;
use aerodrome_extractor_audit::{self as audit, Retval};
use aerodrome_extractor_core::{calls::ERC20_SELECTORS, layout, metadata};
use serde::Deserialize;
use std::collections::BTreeSet;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Document {
    schema: String,
    entries: Vec<RawEntry>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RawEntry {
    block_number: u64,
    block_hash: String,
    address: String,
    calldata: String,
    contract: String,
    function: String,
    retval: RawRetval,
}
#[derive(Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
enum RawRetval {
    Value { data: String },
    Null,
}
#[derive(Clone)]
struct Entry {
    hash: [u8; 32],
    address: Address,
    calldata: Vec<u8>,
    retval: Retval,
}
/// Exact hash/address/calldata cassette. No RPC fallback and no invented answers.
pub struct Cassette {
    entries: BTreeMap<u64, Vec<Entry>>,
    pub(crate) sha256: String,
}
fn unhex(s: &str) -> Result<Vec<u8>> {
    hex::decode(
        s.strip_prefix("0x")
            .ok_or_else(|| refuse("cassette hex lacks 0x"))?,
    )
    .map_err(|_| refuse("invalid cassette hex"))
}
impl Cassette {
    pub fn from_json(bytes: &[u8]) -> Result<Self> {
        let document: Document =
            serde_json::from_slice(bytes).map_err(|e| refuse(format!("cassette JSON: {e}")))?;
        require(
            document.schema == "pinax.substreams-backfills.mapping-host.cassette/v1",
            "wrong cassette schema",
        )?;
        let mut entries: BTreeMap<u64, Vec<Entry>> = BTreeMap::new();
        let mut seen = BTreeSet::new();
        for raw in document.entries {
            let hash = crate::word(&unhex(&raw.block_hash)?)?;
            let address = crate::address(&unhex(&raw.address)?)?;
            let calldata = unhex(&raw.calldata)?;
            require(
                hash != [0; 32] && calldata.len() >= 4,
                "invalid cassette identity",
            )?;
            let selector = &calldata[..4];
            let valid_name = match (raw.contract.as_str(), raw.function.as_str()) {
                ("ERC20", "symbol()") => calldata.len() == 4 && selector == ERC20_SELECTORS[0],
                ("ERC20", "name()") => calldata.len() == 4 && selector == ERC20_SELECTORS[1],
                ("ERC20", "totalSupply()") => calldata.len() == 4 && selector == ERC20_SELECTORS[2],
                ("ERC20", "decimals()") => calldata.len() == 4 && selector == ERC20_SELECTORS[3],
                ("Pool", "feeGrowthGlobal0X128()") => {
                    calldata.len() == 4 && selector == [0xf3, 0x05, 0x83, 0x99]
                }
                ("Pool", "feeGrowthGlobal1X128()") => {
                    calldata.len() == 4 && selector == [0x46, 0x14, 0x13, 0x19]
                }
                ("Pool", "ticks(int24)") => {
                    calldata.len() == 36 && selector == [0xf3, 0x0d, 0xba, 0x93]
                }
                ("NonfungiblePositionManager", "positions(uint256)") => {
                    calldata.len() == 36 && selector == [0x99, 0xfb, 0xab, 0x88]
                }
                ("Factory", "getPool(address,address,int24)") => {
                    calldata.len() == 100 && selector == [0x28, 0xaf, 0x8d, 0x0b]
                }
                _ => false,
            };
            require(
                valid_name,
                "cassette function/calldata mismatch or unsupported call",
            )?;
            require(
                seen.insert((raw.block_number, address, calldata.clone())),
                "duplicate cassette call identity",
            )?;
            let retval = match raw.retval {
                RawRetval::Null => Retval::Reverted,
                RawRetval::Value { data } => {
                    let value = unhex(&data)?;
                    require(!value.is_empty(), "empty cassette Value must be Null")?;
                    Retval::Value {
                        data: hex::encode(value),
                    }
                }
            };
            entries.entry(raw.block_number).or_default().push(Entry {
                hash,
                address,
                calldata,
                retval,
            });
        }
        Ok(Self {
            entries,
            sha256: hex::encode(Sha256::digest(bytes)),
        })
    }
    pub fn sha256(&self) -> &str {
        &self.sha256
    }
    pub(super) fn range(&self, start: u64, stop: u64) -> Result<()> {
        require(
            self.entries.keys().all(|n| (*n >= start) && (*n < stop)),
            "cassette has calls outside reference range",
        )
    }
    fn at(&self, block: &p::ExtractorBlock) -> Result<&[Entry]> {
        let entries = self
            .entries
            .get(&block.number)
            .map(Vec::as_slice)
            .unwrap_or_default();
        require(
            entries.iter().all(|e| e.hash.as_slice() == block.hash),
            "cassette block hash disagrees with raw Firehose",
        )?;
        Ok(entries)
    }
    pub(super) fn metadata(&self, block: &p::ExtractorBlock) -> Result<i::TokenMetadataAnswers> {
        let entries = self.at(block)?;
        let mut tokens = BTreeSet::new();
        for e in entries {
            if e.calldata.len() == 4 && ERC20_SELECTORS.iter().any(|s| s.as_slice() == e.calldata) {
                tokens.insert(e.address);
            }
        }
        let mut responses = vec![];
        for (token, selector) in metadata::calls(&tokens) {
            let entry = entries
                .iter()
                .find(|e| e.address == token && e.calldata == selector)
                .ok_or_else(|| refuse("partial ERC20 cassette group"))?;
            // The original cassette collapses failed/empty returns to Null. It
            // cannot prove the transport mask, so refuse ambiguous metadata.
            let Retval::Value { data } = &entry.retval else {
                return Err(refuse("ERC20 Null cassette lacks failed/empty provenance"));
            };
            responses.push(metadata::Response {
                failed: false,
                raw: hex::decode(data).expect("normalized hex"),
            });
        }
        metadata::answers(&tokens, responses).map_err(refuse)
    }
    pub(super) fn supplement_get_pool(
        &self,
        block: &mut p::ExtractorBlock,
        stores: &Stores,
        cfg: &Config,
    ) -> Result<()> {
        let entries = self.at(block)?.to_vec();
        let calls = block
            .calls
            .as_mut()
            .ok_or_else(|| refuse("missing answers"))?;
        for entry in entries
            .into_iter()
            .filter(|e| e.calldata.starts_with(&[0x28, 0xaf, 0x8d, 0x0b]))
        {
            require(
                entry.address == cfg.factory,
                "getPool cassette wrong factory",
            )?;
            let data = &entry.calldata;
            require(
                data.len() == 100 && data[4..16] == [0; 12] && data[36..48] == [0; 12],
                "noncanonical getPool addresses",
            )?;
            let a = crate::address(&data[16..36])?;
            let b = crate::address(&data[48..68])?;
            let spacing = i32::from_be_bytes(data[96..100].try_into().unwrap());
            crate::int24(spacing)?;
            require(
                layout::int_word(spacing).as_slice() == &data[68..100],
                "noncanonical getPool int24",
            )?;
            if calls
                .get_pool
                .iter()
                .any(|p| p.token_a == a && p.token_b == b && p.tick_spacing == spacing)
            {
                continue;
            }
            let record = stores
                .get(
                    Store::Pools,
                    &format!("g:{}:{}:{spacing};", hex::encode(a), hex::encode(b)),
                )
                .map_err(refuse)?;
            let (pool, created_block) = match record {
                Some(bytes) => {
                    let value =
                        i::PoolRef::decode(bytes.as_slice()).map_err(|e| refuse(e.to_string()))?;
                    (value.pool, value.created_block)
                }
                None => (vec![0; 20], 0),
            };
            calls.get_pool.push(p::GetPoolAnswer {
                token_a: a.to_vec(),
                token_b: b.to_vec(),
                tick_spacing: spacing,
                pool,
                created_block,
            });
        }
        calls.get_pool.sort_by(|a, b| {
            (&a.token_a, &a.token_b, a.tick_spacing).cmp(&(&b.token_a, &b.token_b, b.tick_spacing))
        });
        Ok(())
    }
    pub(super) fn verify(&self, block: &p::ExtractorBlock, cfg: &Config) -> Result<usize> {
        let checks = audit::checks(block, cfg, false).map_err(refuse)?;
        let mut compared = 0;
        // Cassette coverage is only actual mapping calls. Additional derived
        // answers remain permitted; every retained expected call must match.
        for entry in self.at(block)? {
            let check = checks
                .iter()
                .find(|c| c.address == entry.address && c.calldata == entry.calldata)
                .ok_or_else(|| {
                    refuse(format!(
                        "no derived answer for cassette call {}:{} at {}",
                        hex::encode(entry.address),
                        hex::encode(&entry.calldata),
                        block.number
                    ))
                })?;
            audit::compare(check, &entry.retval).map_err(|e| {
                refuse(format!(
                    "cassette mismatch at {} {}:{}: {e}",
                    block.number,
                    hex::encode(entry.address),
                    hex::encode(&entry.calldata)
                ))
            })?;
            compared += 1;
        }
        Ok(compared)
    }
}
