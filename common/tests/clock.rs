use backfill_common::clock::{
    read_frame, write_frame, Frame, FrameKind, ObservedRange, MAX_PAYLOAD_LEN,
};
use std::io::{self, Cursor, Read};

// Literal clock-v1 bytes using the engine's published 52-byte layout. The
// payload is deliberately opaque, including NUL, 0xff and another magic word.
fn golden() -> Vec<u8> {
    hex::decode(concat!(
        "42434631010000000000000000d33df8",
        "000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f",
        "0000000600ff42434631"
    ))
    .unwrap()
}

fn observed(number: u64) -> Frame {
    Frame {
        kind: FrameKind::Observed,
        block_number: number,
        block_hash: [7; 32],
        payload: vec![],
    }
}

#[test]
fn clock_v1_bytes_match_engine_layout_without_reinterpreting_payloads() {
    let bytes = golden();
    let mut input = Cursor::new(&bytes);
    let frame = read_frame(&mut input, MAX_PAYLOAD_LEN).unwrap().unwrap();
    assert_eq!(frame.block_number, 13_843_960);
    assert_eq!(frame.kind, FrameKind::Observed);
    assert_eq!(frame.block_hash, std::array::from_fn(|i| i as u8));
    assert_eq!(frame.payload, b"\x00\xffBCF1");
    assert!(read_frame(&mut input, MAX_PAYLOAD_LEN).unwrap().is_none());
    let mut actual = Vec::new();
    write_frame(&mut actual, &frame).unwrap();
    assert_eq!(actual, bytes);
}

#[test]
fn every_partial_header_and_payload_refuses_and_concatenated_frames_do_not_read_ahead() {
    let bytes = golden();
    for end in 1..bytes.len() {
        assert_eq!(
            read_frame(&mut &bytes[..end], MAX_PAYLOAD_LEN)
                .unwrap_err()
                .kind(),
            io::ErrorKind::UnexpectedEof,
            "offset {end}"
        );
    }
    let joined = [bytes.clone(), bytes.clone()].concat();
    let mut input = Cursor::new(joined);
    assert!(read_frame(&mut input, MAX_PAYLOAD_LEN).unwrap().is_some());
    assert_eq!(input.position(), bytes.len() as u64);
    assert!(read_frame(&mut input, MAX_PAYLOAD_LEN).unwrap().is_some());
    assert!(read_frame(&mut input, MAX_PAYLOAD_LEN).unwrap().is_none());
}

#[test]
fn malformed_headers_refuse_before_reading_payload() {
    for (offset, value) in [(0, 0), (4, 0), (4, 3), (5, 1), (6, 1), (7, 1), (8, 1)] {
        let mut bytes = golden();
        bytes[offset] = value;
        assert_eq!(
            read_frame(&mut &bytes[..52], MAX_PAYLOAD_LEN)
                .unwrap_err()
                .kind(),
            io::ErrorKind::InvalidData
        );
    }
    let mut zero_hash = golden();
    zero_hash[16..48].fill(0);
    assert!(read_frame(&mut &zero_hash[..], MAX_PAYLOAD_LEN).is_err());
    let mut oversized = golden();
    oversized[48..52].copy_from_slice(&((MAX_PAYLOAD_LEN + 1) as u32).to_be_bytes());
    assert_eq!(
        read_frame(&mut &oversized[..52], usize::MAX)
            .unwrap_err()
            .kind(),
        io::ErrorKind::InvalidData
    );
    assert_eq!(
        read_frame(&mut &golden()[..52], 5).unwrap_err().kind(),
        io::ErrorKind::InvalidData
    );
}

#[test]
fn synthetic_and_empty_observed_are_distinct_and_writer_validates_before_writing() {
    for frame in [
        observed(0),
        Frame {
            kind: FrameKind::SyntheticRangeFill,
            block_number: 0,
            block_hash: [0; 32],
            payload: vec![],
        },
    ] {
        let mut bytes = Vec::new();
        write_frame(&mut bytes, &frame).unwrap();
        assert_eq!(read_frame(&mut &bytes[..], 0).unwrap(), Some(frame));
    }
    for frame in [
        Frame {
            block_hash: [0; 32],
            ..observed(0)
        },
        Frame {
            block_number: i32::MAX as u64 + 1,
            ..observed(0)
        },
        Frame {
            kind: FrameKind::SyntheticRangeFill,
            ..observed(0)
        },
        Frame {
            kind: FrameKind::SyntheticRangeFill,
            block_hash: [0; 32],
            payload: vec![1],
            ..observed(0)
        },
    ] {
        let mut bytes = Vec::new();
        assert!(write_frame(&mut bytes, &frame).is_err());
        assert!(bytes.is_empty());
    }
}

#[test]
fn range_refuses_early_eof_gaps_duplicates_synthetic_fill_and_extra_blocks() {
    assert!(ObservedRange::new(2, 1).is_err());
    assert!(ObservedRange::new(0, i32::MAX as u64 + 2).is_err());
    assert!(ObservedRange::new(1, 1).unwrap().finish().is_ok());
    assert!(ObservedRange::new(1, 2).unwrap().finish().is_err());
    let mut range = ObservedRange::new(1, 3).unwrap();
    range.accept(&observed(1)).unwrap();
    range.accept(&observed(2)).unwrap();
    range.finish().unwrap();
    for invalid in [
        observed(1),
        observed(3),
        Frame {
            kind: FrameKind::SyntheticRangeFill,
            block_hash: [0; 32],
            ..observed(2)
        },
    ] {
        let mut range = ObservedRange::new(1, 3).unwrap();
        range.accept(&observed(1)).unwrap();
        assert!(range.accept(&invalid).is_err());
        assert!(range.accept(&observed(2)).is_err());
        assert!(range.finish().is_err());
    }
    let mut extra = ObservedRange::new(1, 2).unwrap();
    extra.accept(&observed(1)).unwrap();
    assert!(extra.accept(&observed(2)).is_err());
    assert!(extra.finish().is_err());
    let mut boundary = ObservedRange::new(i32::MAX as u64, i32::MAX as u64 + 1).unwrap();
    boundary.accept(&observed(i32::MAX as u64)).unwrap();
    boundary.finish().unwrap();
}

#[test]
fn interrupted_and_short_reads_preserve_the_frame() {
    struct Choppy {
        data: Cursor<Vec<u8>>,
        interrupted: bool,
    }
    impl Read for Choppy {
        fn read(&mut self, bytes: &mut [u8]) -> io::Result<usize> {
            self.interrupted = !self.interrupted;
            if self.interrupted {
                return Err(io::ErrorKind::Interrupted.into());
            }
            let end = bytes.len().min(1);
            self.data.read(&mut bytes[..end])
        }
    }
    let mut input = Choppy {
        data: Cursor::new(golden()),
        interrupted: false,
    };
    assert!(read_frame(&mut input, MAX_PAYLOAD_LEN).unwrap().is_some());
    assert!(read_frame(&mut input, MAX_PAYLOAD_LEN).unwrap().is_none());
}
