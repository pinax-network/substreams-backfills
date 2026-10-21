use aerodrome_extractor_core::config::INITIAL_BLOCK;
use aerodrome_slipstream_reducer::{
    differential::compare_frames,
    identity::{build_descriptor, OUTPUT_MODULE, OUTPUT_TYPE},
};
use backfill_common::{
    clock::{self, Frame, FrameKind},
    descriptor::ExtractorIdentity,
    pb::pinax::graph::backfill::v2 as pb,
    BlockChangesCompatibility,
};
use prost::Message;
use serde_json::Value;
use std::io::{self, Cursor, Read};

fn binding(reducer: &str) -> BlockChangesCompatibility {
    let extractor = ExtractorIdentity {
        spkg_sha256: "11".repeat(32),
        module: OUTPUT_MODULE.into(),
        module_hash: "22".repeat(20),
        output_type: OUTPUT_TYPE.into(),
        initial_block: INITIAL_BLOCK,
    };
    BlockChangesCompatibility::from_descriptor(
        &build_descriptor(&extractor, &reducer.repeat(20), true).unwrap(),
    )
    .unwrap()
}
fn oracle(binding: &BlockChangesCompatibility) -> Frame {
    let corpus: Value =
        serde_json::from_slice(include_bytes!("../fixtures/graph-node-first-handlers.json"))
            .unwrap();
    let case = corpus["cases"]
        .as_array()
        .unwrap()
        .iter()
        .find(|c| c["name"] == "real_first_pool")
        .unwrap();
    let mut changes = pb::BlockChanges::decode(
        hex::decode(case["changes_hex"].as_str().unwrap())
            .unwrap()
            .as_slice(),
    )
    .unwrap();
    changes.compatibility_id = binding.to_vec();
    Frame {
        kind: FrameKind::Observed,
        block_number: changes.block_number,
        block_hash: changes.block_hash.clone().try_into().unwrap(),
        payload: changes.encode_to_vec(),
    }
}
fn encoded(frame: &Frame) -> Vec<u8> {
    let mut bytes = vec![];
    clock::write_frame(&mut bytes, frame).unwrap();
    bytes
}

#[test]
fn only_compatibility_is_masked_and_source_creations_are_compared() {
    let a = binding("33");
    let b = binding("44");
    let left = oracle(&a);
    let right = oracle(&b);
    let result = compare_frames(
        Cursor::new(encoded(&left)),
        Cursor::new(encoded(&right)),
        &a,
        &b,
        left.block_number,
        left.block_number + 1,
    )
    .unwrap();
    assert_eq!(result.blocks, 1);
    assert_eq!(result.created_sources, 1);
    assert!(result.operations > 0);
    assert_ne!(result.expected_frames_sha256, result.actual_frames_sha256);
    assert!(!result.production_qualified);
    let mut changed = right.clone();
    let mut body = pb::BlockChanges::decode(changed.payload.as_slice()).unwrap();
    body.created_data_sources[0].param[0] ^= 1;
    changed.payload = body.encode_to_vec();
    assert!(compare_frames(
        Cursor::new(encoded(&left)),
        Cursor::new(encoded(&changed)),
        &a,
        &b,
        left.block_number,
        left.block_number + 1
    )
    .is_err());
}

#[test]
fn equal_prefixes_truncation_extra_frames_and_synthetic_frames_cannot_pass() {
    let a = binding("33");
    let frame = oracle(&a);
    let bytes = encoded(&frame);
    let compare = |left: &[u8], right: &[u8], stop| {
        compare_frames(left, right, &a, &a, frame.block_number, stop)
    };
    assert!(compare(&bytes, &bytes, frame.block_number + 2).is_err());
    assert!(compare(&[], &[], frame.block_number).is_err());
    for cut in [1, 51, 52, bytes.len() - 1] {
        assert!(compare(&bytes[..cut], &bytes, frame.block_number + 1).is_err());
        assert!(compare(&bytes, &bytes[..cut], frame.block_number + 1).is_err());
    }
    let mut extra = bytes.clone();
    extra.extend_from_slice(&bytes);
    assert!(compare(&extra, &extra, frame.block_number + 1).is_err());
    let synthetic = encoded(&Frame {
        kind: FrameKind::SyntheticRangeFill,
        block_number: frame.block_number,
        block_hash: [0; 32],
        payload: vec![],
    });
    assert!(compare(&synthetic, &synthetic, frame.block_number + 1).is_err());
}

#[test]
fn body_identity_schema_unknown_fields_and_operation_changes_are_refused() {
    let a = binding("33");
    let frame = oracle(&a);
    let bytes = encoded(&frame);
    for mode in ["hash", "body_number", "unknown", "operation"] {
        let mut changed = frame.clone();
        let mut body = pb::BlockChanges::decode(changed.payload.as_slice()).unwrap();
        match mode {
            "hash" => changed.block_hash[0] ^= 1,
            "body_number" => {
                body.block_number += 1;
                changed.payload = body.encode_to_vec();
            }
            "unknown" => changed.payload.extend_from_slice(&[0xa0, 0x06, 0x01]),
            "operation" => {
                body.operations[0].source_trigger_order += 1;
                changed.payload = body.encode_to_vec();
            }
            _ => unreachable!(),
        }
        assert!(
            compare_frames(
                bytes.as_slice(),
                encoded(&changed).as_slice(),
                &a,
                &a,
                frame.block_number,
                frame.block_number + 1
            )
            .is_err(),
            "{mode}"
        );
    }
    assert!(compare_frames(
        bytes.as_slice(),
        bytes.as_slice(),
        &binding("44"),
        &a,
        frame.block_number,
        frame.block_number + 1
    )
    .is_err());
}

struct BrokenAfter(Cursor<Vec<u8>>);
impl Read for BrokenAfter {
    fn read(&mut self, out: &mut [u8]) -> io::Result<usize> {
        if self.0.position() == self.0.get_ref().len() as u64 {
            Err(io::Error::other("injected terminal read failure"))
        } else {
            self.0.read(out)
        }
    }
}
#[test]
fn terminal_read_failure_is_not_eof() {
    let a = binding("33");
    let frame = oracle(&a);
    let bytes = encoded(&frame);
    assert!(compare_frames(
        BrokenAfter(Cursor::new(bytes.clone())),
        bytes.as_slice(),
        &a,
        &a,
        frame.block_number,
        frame.block_number + 1
    )
    .is_err());
}
