//! Independent S-R2 raw ABI oracle: actual Graph Node EventExt/FunctionExt.
//! No reducer dependency or reducer decoding/fallback implementation is used.
use graph::{
    abi::{EventExt, FunctionExt, JsonAbi},
    prelude::alloy,
};
use serde_json::{json, Value};
use std::path::PathBuf;
fn root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..")
}
fn abi(file: &str) -> JsonAbi {
    serde_json::from_slice(
        &std::fs::read(
            root()
                .join("aerodrome-slipstream-base/reference/abis")
                .join(file),
        )
        .unwrap(),
    )
    .unwrap()
}
fn bytes(v: &Value) -> Vec<u8> {
    hex::decode(v.as_str().unwrap_or("")).unwrap()
}
fn word(n: u64) -> Vec<u8> {
    let mut b = vec![0; 32];
    b[24..].copy_from_slice(&n.to_be_bytes());
    b
}
fn string(bytes: &[u8]) -> Vec<u8> {
    let mut b = word(32);
    b.extend(word(bytes.len() as u64));
    b.extend(bytes);
    while !b.len().is_multiple_of(32) {
        b.push(0)
    }
    b
}
#[test]
fn aerodrome_input_corpus() {
    let projection: Value = serde_json::from_slice(
        &std::fs::read(
            root().join("aerodrome-slipstream-base/substreams/fixtures/candidates-13899663.json"),
        )
        .unwrap(),
    )
    .unwrap();
    let logs = projection["transactions"][55]["logs"].as_array().unwrap();
    let mut events = Vec::new();
    for (index, source, file, name) in [
        (172, 1, "Factory.json", "PoolCreated"),
        (177, 2, "NonfungiblePositionManager.json", "Transfer"),
        (
            178,
            2,
            "NonfungiblePositionManager.json",
            "IncreaseLiquidity",
        ),
        (171, 3, "Pool.json", "Initialize"),
        (176, 3, "Pool.json", "Mint"),
    ] {
        let original = logs
            .iter()
            .find(|l| l["blockIndex"].as_u64() == Some(index))
            .unwrap();
        let abi = abi(file);
        let event = abi.events.get(name).unwrap().first().unwrap();
        for mutation in [
            "original",
            "empty_data",
            "extra_word",
            "missing_topic",
            "extra_topic",
            "bad_topic0",
        ] {
            let mut topics = original["topics"]
                .as_array()
                .unwrap()
                .iter()
                .map(bytes)
                .collect::<Vec<_>>();
            let mut data = bytes(&original["data"]);
            match mutation {
                "empty_data" => data.clear(),
                "extra_word" => data.extend([0; 32]),
                "missing_topic" => {
                    topics.pop();
                }
                "extra_topic" => topics.push(vec![0; 32]),
                "bad_topic0" => topics[0][0] ^= 1,
                _ => (),
            }
            let log = alloy::rpc::types::Log {
                inner: alloy::primitives::Log {
                    address: [1; 20].into(),
                    data: alloy::primitives::LogData::new_unchecked(
                        topics
                            .iter()
                            .map(|b| alloy::primitives::B256::from_slice(b))
                            .collect(),
                        data.clone().into(),
                    ),
                },
                ..Default::default()
            };
            let result = event.decode_log(&log).ok().map(|params| {
                params
                    .into_iter()
                    .map(|p| json!({"name":p.name,"value":format!("{:?}",p.value)}))
                    .collect::<Vec<_>>()
            });
            events.push(json!({"log_index":index,"source":source,"event":name,"mutation":mutation,"topics":topics.iter().map(hex::encode).collect::<Vec<_>>(),"data":hex::encode(data),"result":result}));
        }
    }
    let mut functions = Vec::new();
    let mut padded = b"M\0KR!".to_vec();
    padded.resize(32, 0);
    let mut raws = vec![
        vec![],
        vec![1],
        vec![0; 32],
        word(1),
        word(18),
        word(255),
        word(256),
        vec![255; 32],
        padded,
        string(b"SYMBOL"),
        string(b"N\0a\0me\0"),
        string(&[255, b'b', b'c']),
    ];
    let mut trailing = string(b"Name");
    trailing.extend([0; 32]);
    raws.push(trailing);
    for (file, name, as_bytes) in [
        ("ERC20.json", "symbol", false),
        ("ERC20.json", "name", false),
        ("ERC20SymbolBytes.json", "symbol", true),
        ("ERC20NameBytes.json", "name", true),
        ("ERC20.json", "totalSupply", false),
        ("ERC20.json", "decimals", false),
    ] {
        let abi = abi(file);
        let function = abi.functions.get(name).unwrap().first().unwrap();
        for raw in &raws {
            let result = function
                .abi_decode_output(raw)
                .ok()
                .map(|v| v.into_iter().map(|v| format!("{v:?}")).collect::<Vec<_>>());
            functions.push(
                json!({"function":name,"bytes32":as_bytes,"raw":hex::encode(raw),"result":result}),
            );
        }
    }
    let corpus = json!({"schema":"pinax.aerodrome.reducer-input-abi/v1","graph_node_commit":"77823b5a7adc4eac4abf03202c8dd7cb00dea31d","alloy_dyn_abi":"1.7.2","events":events,"functions":functions});
    let bytes = format!("{}\n", serde_json::to_string_pretty(&corpus).unwrap());
    let path =
        root().join("crates/aerodrome-slipstream-reducer/fixtures/graph-node-input-abi.json");
    if std::env::var_os("UPDATE_AERODROME_INPUT_CORPUS").as_deref()
        == Some(std::ffi::OsStr::new("1"))
    {
        std::fs::write(&path, &bytes).unwrap();
    }
    assert_eq!(
        std::fs::read_to_string(path).unwrap(),
        bytes,
        "Graph Node ABI corpus drift; investigate before regenerating"
    );
}
