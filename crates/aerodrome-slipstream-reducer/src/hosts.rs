//! Authoritative host matching. The extractor registry is only a superset.
//! The future handler journal calls `record_creation_outcome` after commit or
//! rollback; a decoded Factory event by itself never installs a host.
use crate::{abi::DecodedEvent, address, input::BlockInput, pb, refuse, require, Address, Result};
use aerodrome_extractor_core::config::INITIAL_BLOCK;
use std::collections::BTreeMap;
/// Locked Factory.wasm UTF-16 constant at address3168: this pool returns before
/// dataSource.create. The unrelated Pool swap guard is not a missing-host rule.
pub const FACTORY_EXCLUDED_POOL: &str = "8fe8d9bb8eeba3ed688069c3d6b556c9ca258248";
#[derive(Clone, Default, Debug)]
pub struct HostSet {
    committed: BTreeMap<Address, u64>,
    aborted: BTreeMap<Address, u64>,
}
impl HostSet {
    pub(crate) fn contains(&self, pool: &Address) -> bool {
        self.committed.contains_key(pool)
    }
    pub fn seed(&mut self, pool: Address, created_block: u64, boundary: u64) -> Result<()> {
        require(
            created_block >= INITIAL_BLOCK && created_block <= boundary && pool != [0; 20],
            "invalid seeded host boundary",
        )?;
        require(
            hex::encode(pool) != FACTORY_EXCLUDED_POOL,
            "excluded Factory pool cannot be seeded as a host",
        )?;
        require(
            !self.committed.contains_key(&pool) && !self.aborted.contains_key(&pool),
            "duplicate seeded host",
        )?;
        self.committed.insert(pool, created_block);
        Ok(())
    }
    pub(crate) fn seed_aborted(&mut self, pool: Address, block: u64, boundary: u64) -> Result<()> {
        self.seed(pool, block, boundary)?;
        self.committed.remove(&pool);
        self.aborted.insert(pool, block);
        Ok(())
    }
    pub fn record_creation_outcome(
        &mut self,
        block: &BlockInput,
        pool: Address,
        committed: bool,
    ) -> Result<()> {
        require(
            block.block.pools_created.iter().any(|f| f.pool == pool),
            "host outcome has no validated PoolCreated fact",
        )?;
        require(
            hex::encode(pool) != FACTORY_EXCLUDED_POOL,
            "excluded Factory pool has no creation outcome",
        )?;
        require(
            !self.committed.contains_key(&pool) && !self.aborted.contains_key(&pool),
            "duplicate host outcome",
        )?;
        if committed {
            self.committed.insert(pool, block.block.number);
        } else {
            self.aborted.insert(pool, block.block.number);
        }
        Ok(())
    }
    pub fn match_candidate<'a>(
        &self,
        block: &'a BlockInput,
        index: usize,
    ) -> Result<Option<&'a DecodedEvent>> {
        let c = block
            .block
            .candidates
            .get(index)
            .ok_or_else(|| refuse("candidate index out of range"))?;
        if c.source != pb::DataSourceKind::Pool as i32 {
            return Ok(block.decoded[index].as_ref());
        }
        let pool = address(&c.address)?;
        match self.committed.get(&pool) {
            Some(created) => {
                require(
                    *created <= block.block.number
                        && u32::from(*created == block.block.number) == c.wave,
                    "host creation block does not match wave",
                )?;
                require(
                    (c.host_order_key - 2) >> 24 == *created,
                    "host order key does not match committed creation block",
                )?;
                Ok(block.decoded[index].as_ref())
            }
            None if hex::encode(pool) == FACTORY_EXCLUDED_POOL => Ok(None),
            None if self
                .aborted
                .get(&pool)
                .is_some_and(|at| *at <= block.block.number) =>
            {
                Ok(None)
            }
            None => Err(refuse(format!(
                "UnknownPoolHost: {} at block {}",
                hex::encode(pool),
                block.block.number
            ))),
        }
    }
}
