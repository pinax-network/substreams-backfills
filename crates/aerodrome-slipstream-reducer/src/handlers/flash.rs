use super::*;
use crate::entity::Pool;
pub(super) fn flash<B: EntityBackend>(
    handler: &SupportedHandler<'_>,
    journal: &mut HandlerJournal<'_, B>,
) -> MappingResult<()> {
    let address = crate::address(&handler.candidate().address)?;
    let mut pool: Pool = required(journal, &id(&address), "src/mappings/core.ts:514:14")?;
    let answer = handler.input.calls().fee_growth(&address)?;
    pool.fee_growth_global0_x128 = unsigned_integer(&answer.fee_growth_global0_x128);
    pool.fee_growth_global1_x128 = unsigned_integer(&answer.fee_growth_global1_x128);
    journal.save(&pool)?;
    Ok(())
}
