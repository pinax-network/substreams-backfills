//! Family: uniswap-v3 — schema Qma8a81T9XoX5Pbkrk8J3kxMhWdXJzFSYZge1wGi3QZBru
//! Targets: Qmb4VUcA… ("Uniswap V3 Base") + QmTZ8ejX… ("Uniswap-V3", mainnet).
//!
//! M2 scope grows from here in the order the subgraph's own mappings define them:
//! factory.ts (PoolCreated → Factory/Pool/Token/Bundle) is DONE below; next
//! core.ts (Swap/Mint/Burn on Pool logs + aggregates), then position-manager.ts.
//! Reference: streamingfast/substreams-uniswap-v3 (entity-parity port of this subgraph).

// The Substreams handler macro exposes an FFI wrapper whose generated pointer
// dereference triggers this lint; the handwritten handler remains safe Rust.
#![allow(clippy::not_unsafe_ptr_arg_deref)]

use substreams::errors::Error;
use substreams::Hex;
use substreams_entity_change::pb::entity::EntityChanges;
use substreams_entity_change::tables::Tables;
use substreams_ethereum::pb::eth::v2::Block;

/// keccak("PoolCreated(address,address,uint24,int24,address)")
const POOL_CREATED_TOPIC: [u8; 32] = [
    0x78, 0x3c, 0xca, 0x1c, 0x04, 0x12, 0xdd, 0x0d, 0x69, 0x5e, 0x78, 0x45, 0x68, 0xc9, 0x6d, 0xa2,
    0xe9, 0xc2, 0x2f, 0xf9, 0x89, 0x35, 0x7a, 0x2e, 0x8b, 0x1d, 0x9b, 0x2b, 0x4e, 0x6b, 0x71, 0x18,
];

fn addr(bytes: &[u8]) -> String {
    format!("0x{}", Hex(bytes))
}

/// params: hex factory address without 0x (bound per target in substreams.yaml / target yaml).
#[substreams::handlers::map]
fn map_entities(params: String, block: Block) -> Result<EntityChanges, Error> {
    let factory = Hex::decode(&params).expect("params must be the hex factory address");
    let mut tables = Tables::new();

    for log_view in block.logs() {
        let log = log_view.log;
        if log.address != factory {
            continue;
        }
        if log.topics.first().map(|t| t.as_slice()) != Some(POOL_CREATED_TOPIC.as_slice()) {
            continue;
        }
        // PoolCreated(address indexed token0, address indexed token1, uint24 indexed fee,
        //             int24 tickSpacing, address pool)
        let token0 = addr(&log.topics[1][12..]);
        let token1 = addr(&log.topics[2][12..]);
        let fee = u64::from_be_bytes(log.topics[3][24..32].try_into().unwrap());
        let tick_spacing = i32::from_be_bytes(log.data[28..32].try_into().unwrap());
        let pool = addr(&log.data[32 + 12..64]);

        tables
            .create_row("Pool", &pool)
            .set("token0", &token0)
            .set("token1", &token1)
            .set("feeTier", fee.to_string())
            .set("tickSpacing", tick_spacing.to_string())
            .set("createdAtTimestamp", block.timestamp_seconds().to_string())
            .set("createdAtBlockNumber", block.number.to_string());
        // Token rows are created lazily here and enriched (symbol/name/decimals via eth_calls)
        // in the next milestone step, mirroring factory.ts.
        tables.create_row("Token", &token0);
        tables.create_row("Token", &token1);
    }

    Ok(tables.to_entity_changes())
}
