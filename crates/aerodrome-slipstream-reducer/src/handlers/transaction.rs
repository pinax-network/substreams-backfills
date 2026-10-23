//! Deployed loadTransaction saves all fields on every invocation, even if the
//! transaction already exists. gasUsed is the transaction gas limit.
use super::*;
use crate::entity::Transaction;
pub(super) fn load<B: EntityBackend>(
    handler: &SupportedHandler<'_>,
    journal: &mut HandlerJournal<'_, B>,
) -> MappingResult<Transaction> {
    let tx = &handler.input.block().transactions[handler.candidate().tx as usize];
    let id = format!("0x{}", hex::encode(&tx.hash));
    let mut value = journal.load::<Transaction>(&id)?.unwrap_or(Transaction {
        id,
        block_number: 0.into(),
        timestamp: 0.into(),
        gas_used: 0.into(),
        gas_price: 0.into(),
    });
    value.block_number = handler.input.block().number.into();
    value.timestamp = handler.input.block().timestamp.into();
    value.gas_used = tx.gas_limit.into();
    value.gas_price = handler.input.gas_prices()[handler.candidate().tx as usize].into();
    journal.save(&value)?;
    Ok(value)
}
