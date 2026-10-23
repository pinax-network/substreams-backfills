//! Graph Node v0.44 uses these exact alloy versions. Event field interleaving
//! follows graph/src/abi/event_ext.rs at 77823b5 (Apache-2.0).
use crate::{pb, refuse, Result};
use alloy_dyn_abi::{DynSolValue, EventExt, FunctionExt};
use alloy_json_abi::{Event, JsonAbi};
use alloy_primitives::B256;
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, VecDeque},
    sync::OnceLock,
};

#[derive(Clone, Debug, PartialEq)]
pub struct DecodedEvent {
    pub name: String,
    pub params: Vec<(String, DynSolValue)>,
}
impl DecodedEvent {
    pub fn param(&self, name: &str) -> Option<&DynSolValue> {
        self.params
            .iter()
            .find(|(key, _)| key == name)
            .map(|(_, v)| v)
    }
}
pub struct Abis {
    events: BTreeMap<i32, Vec<Event>>,
    erc20: JsonAbi,
    symbol_bytes: JsonAbi,
    name_bytes: JsonAbi,
}
fn pinned(bytes: &[u8], digest: &str) -> JsonAbi {
    assert_eq!(
        hex::encode(Sha256::digest(bytes)),
        digest,
        "locked ABI changed"
    );
    serde_json::from_slice(bytes).expect("locked ABI JSON")
}
impl Abis {
    pub fn locked() -> &'static Self {
        static ABI: OnceLock<Abis> = OnceLock::new();
        ABI.get_or_init(|| {
            let factory=pinned(include_bytes!("../../../aerodrome-slipstream-base/reference/abis/Factory.json"),"7dac7fd7c4ff807498cb7dcbf503474d13b1207852bb8b2b3687a7e8cfb6d979");
            let pool=pinned(include_bytes!("../../../aerodrome-slipstream-base/reference/abis/Pool.json"),"46588c2f4ad0b91f64e7b43b03190c5422d3f46f2759c53412a3f3279f816760");
            let npm=pinned(include_bytes!("../../../aerodrome-slipstream-base/reference/abis/NonfungiblePositionManager.json"),"6109c87c3dfd051c5fa283e71463d29d4c31a40339223ea3015ea0bcdd602c00");
            let select=|abi:JsonAbi,names:&[&str]|names.iter().map(|name| {
                let choices=abi.events.get(*name).expect("locked event"); assert_eq!(choices.len(),1); choices[0].clone()
            }).collect();
            Self { events:BTreeMap::from([
                (pb::DataSourceKind::Factory as i32,select(factory,&["PoolCreated"])),
                (pb::DataSourceKind::Pool as i32,select(pool,&["Initialize","Swap","Mint","Burn","Flash"])),
                (pb::DataSourceKind::PositionManager as i32,select(npm,&["IncreaseLiquidity","DecreaseLiquidity","Collect","Transfer"])),
            ]),
                erc20:pinned(include_bytes!("../../../aerodrome-slipstream-base/reference/abis/ERC20.json"),"4b83c6645aed2df5e4e9a1d11f372453fc052ac8575348c8c04a33ceacd0ae90"),
                symbol_bytes:pinned(include_bytes!("../../../aerodrome-slipstream-base/reference/abis/ERC20SymbolBytes.json"),"9ccb9b5d95394b2ffb4ced54cffa0c5ea282917f4eec36c121ce28c257965193"),
                name_bytes:pinned(include_bytes!("../../../aerodrome-slipstream-base/reference/abis/ERC20NameBytes.json"),"b874c853ffa5309e4b7fbf4934c1efdb4fe31e1a65f7041e67f4a7f2258ffb77"),
            }
        })
    }
    pub fn event(&self, source: i32, topic: &[u8]) -> Option<&Event> {
        self.events
            .get(&source)?
            .iter()
            .find(|event| event.selector().as_slice() == topic)
    }
    /// A matching topic with malformed ABI data is not a trigger. The caller
    /// independently validates source address/start/host and raw topic width.
    pub fn decode(&self, candidate: &pb::CandidateLog) -> Result<Option<DecodedEvent>> {
        let Some(topic) = candidate.topics.first() else {
            return Ok(None);
        };
        let Some(event) = self.event(candidate.source, topic) else {
            return Ok(None);
        };
        let topics = candidate
            .topics
            .iter()
            .map(|t| crate::word(t).map(B256::from))
            .collect::<Result<Vec<_>>>()?;
        let Ok(decoded) = event.decode_log_parts(topics, &candidate.data) else {
            return Ok(None);
        };
        let mut indexed: VecDeque<_> = decoded.indexed.into();
        let mut body: VecDeque<_> = decoded.body.into();
        if event.inputs.len() != indexed.len() + body.len() {
            return Err(refuse("ABI input count mismatch"));
        }
        let params = event
            .inputs
            .iter()
            .map(|param| {
                (
                    param.name.clone(),
                    if param.indexed {
                        indexed.pop_front().unwrap()
                    } else {
                        body.pop_front().unwrap()
                    },
                )
            })
            .collect();
        Ok(Some(DecodedEvent {
            name: event.name.clone(),
            params,
        }))
    }
    pub fn erc20_output(&self, name: &str, bytes32: bool, data: &[u8]) -> Option<DynSolValue> {
        let abi = if bytes32 {
            match name {
                "symbol" => &self.symbol_bytes,
                "name" => &self.name_bytes,
                _ => return None,
            }
        } else {
            &self.erc20
        };
        let mut values = abi
            .functions
            .get(name)?
            .first()?
            .abi_decode_output(data)
            .ok()?;
        (values.len() == 1).then(|| values.remove(0))
    }
}
