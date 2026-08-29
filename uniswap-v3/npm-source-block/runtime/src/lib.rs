pub mod npm_source_block;
pub mod pb;

use substreams::errors::Error;
use substreams_ethereum::pb::eth::v2::Block;

use pb::npm_source::NpmSourceBlock;
use pb::writer::WriterEvents;

#[substreams::handlers::map]
pub fn map_npm_source_block(block: Block, writer_events: WriterEvents) -> Result<NpmSourceBlock, Error> {
    npm_source_block::build_npm_source_block(&block, &writer_events)
}
