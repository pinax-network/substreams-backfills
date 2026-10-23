//! Compare complete observed artifacts; only the producer compatibility ID is masked.
//! This proves equality of the supplied artifacts, not their source provenance.
use crate::{refuse, require, Result};
use backfill_common::{
    clock::{self, ObservedRange},
    decode_canonical_in_band_block_changes, BlockChangesCompatibility,
};
use serde::Serialize;
use sha2::{Digest, Sha256};
use std::io::{self, Read};

struct Hashed<R> {
    inner: R,
    sha: Sha256,
}
impl<R: Read> Read for Hashed<R> {
    fn read(&mut self, out: &mut [u8]) -> io::Result<usize> {
        let n = self.inner.read(out)?;
        self.sha.update(&out[..n]);
        Ok(n)
    }
}

#[derive(Debug, Serialize)]
pub struct FrameEquality {
    pub contract: &'static str,
    pub from: u64,
    pub stop_exclusive: u64,
    pub blocks: u64,
    pub triggered_blocks: u64,
    pub operations: u64,
    pub created_sources: u64,
    pub head_hash: String,
    pub expected_descriptor_sha256: String,
    pub actual_descriptor_sha256: String,
    pub expected_frames_sha256: String,
    pub actual_frames_sha256: String,
    pub masked_fields: [&'static str; 1],
    pub production_qualified: bool,
}

/// Both readers must reach real EOF at exactly the required exclusive stop.
/// Frames are validated with their own descriptor before masking one field.
pub fn compare_frames<L: Read, R: Read>(
    expected: L,
    actual: R,
    expected_binding: &BlockChangesCompatibility,
    actual_binding: &BlockChangesCompatibility,
    from: u64,
    stop_exclusive: u64,
) -> Result<FrameEquality> {
    require(from < stop_exclusive, "comparison range must be nonempty")?;
    let error = |e: io::Error| refuse(format!("frame comparison: {e}"));
    let mut expected_range = ObservedRange::new(from, stop_exclusive).map_err(error)?;
    let mut actual_range = ObservedRange::new(from, stop_exclusive).map_err(error)?;
    let mut expected = Hashed {
        inner: expected,
        sha: Sha256::new(),
    };
    let mut actual = Hashed {
        inner: actual,
        sha: Sha256::new(),
    };
    let mut report = FrameEquality {
        contract: "pinax.aerodrome.frame-equality/v1",
        from,
        stop_exclusive,
        blocks: 0,
        triggered_blocks: 0,
        operations: 0,
        created_sources: 0,
        head_hash: String::new(),
        expected_descriptor_sha256: hex::encode(expected_binding.id()),
        actual_descriptor_sha256: hex::encode(actual_binding.id()),
        expected_frames_sha256: String::new(),
        actual_frames_sha256: String::new(),
        masked_fields: ["compatibility_id"],
        production_qualified: false,
    };
    loop {
        let left = clock::read_frame(&mut expected, clock::MAX_PAYLOAD_LEN).map_err(error)?;
        let right = clock::read_frame(&mut actual, clock::MAX_PAYLOAD_LEN).map_err(error)?;
        let (left, right) = match (left, right) {
            (None, None) => break,
            (Some(left), Some(right)) => (left, right),
            _ => return Err(refuse("frame streams end at different boundaries")),
        };
        expected_range.accept(&left).map_err(error)?;
        actual_range.accept(&right).map_err(error)?;
        require(
            left.block_number == right.block_number && left.block_hash == right.block_hash,
            "observed block identity mismatch",
        )?;
        let decode = |bytes: &[u8], binding: &BlockChangesCompatibility| {
            decode_canonical_in_band_block_changes(bytes, binding)
                .map_err(|e| refuse(format!("block {}: {e}", left.block_number)))
        };
        let mut expected = decode(&left.payload, expected_binding)?;
        let mut actual = decode(&right.payload, actual_binding)?;
        for (frame, body) in [(&left, &expected), (&right, &actual)] {
            require(
                body.block_number == frame.block_number && body.block_hash == frame.block_hash,
                "BlockChanges/envelope identity mismatch",
            )?;
        }
        expected.compatibility_id.clear();
        actual.compatibility_id.clear();
        if expected != actual {
            let first = expected
                .operations
                .iter()
                .zip(&actual.operations)
                .position(|(a, b)| a != b);
            return Err(refuse(format!("block {} differs: first unequal operation {:?}, operation counts {}/{}, source counts {}/{}", left.block_number, first, expected.operations.len(), actual.operations.len(), expected.created_data_sources.len(), actual.created_data_sources.len())));
        }
        report.blocks += 1;
        report.triggered_blocks += u64::from(actual.mapping_triggered);
        report.operations += actual.operations.len() as u64;
        report.created_sources += actual.created_data_sources.len() as u64;
        report.head_hash = hex::encode(right.block_hash);
    }
    expected_range.finish().map_err(error)?;
    actual_range.finish().map_err(error)?;
    report.expected_frames_sha256 = hex::encode(expected.sha.finalize());
    report.actual_frames_sha256 = hex::encode(actual.sha.finalize());
    Ok(report)
}
