//! The byte-compatible BCF1 clock-v1 transport used by substreams-native.
//!
//! Payloads are opaque: protobuf decoding, parent-hash linkage and whether an
//! empty observed payload is meaningful belong to the consumer. A clean EOF
//! alone does not establish that the requested range was produced.

use std::io::{self, Read, Write};

pub const HEADER_LEN: usize = 52;
pub const MAX_PAYLOAD_LEN: usize = 256 * 1024 * 1024;
pub const MAX_BLOCK_NUMBER: u64 = i32::MAX as u64;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum FrameKind {
    Observed,
    SyntheticRangeFill,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Frame {
    pub kind: FrameKind,
    pub block_number: u64,
    pub block_hash: [u8; 32],
    pub payload: Vec<u8>,
}

fn invalid(message: impl Into<String>) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, message.into())
}

fn validate(kind: FrameKind, number: u64, hash: &[u8; 32], len: usize) -> io::Result<()> {
    if number > MAX_BLOCK_NUMBER {
        return Err(invalid("BCF1 block exceeds the signed-int32 domain"));
    }
    if len > MAX_PAYLOAD_LEN {
        return Err(invalid("BCF1 payload exceeds the 256 MiB limit"));
    }
    match kind {
        FrameKind::Observed if *hash == [0; 32] => {
            Err(invalid("BCF1 observed frame has a zero hash"))
        }
        FrameKind::SyntheticRangeFill if *hash != [0; 32] || len != 0 => Err(invalid(
            "BCF1 synthetic frame requires a zero hash and empty payload",
        )),
        _ => Ok(()),
    }
}

/// Read one frame, distinguishing clean EOF from every truncated header or
/// payload. Validate the length before allocating, with an optional tighter
/// consumer limit. This function never reads ahead into the next frame.
pub fn read_frame<R: Read>(input: &mut R, max_payload_len: usize) -> io::Result<Option<Frame>> {
    let mut header = [0; HEADER_LEN];
    loop {
        match input.read(&mut header[..1]) {
            Ok(0) => return Ok(None),
            Ok(_) => break,
            Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
            Err(error) => return Err(error),
        }
    }
    input.read_exact(&mut header[1..])?;
    if &header[..4] != b"BCF1" || header[5..8] != [0; 3] {
        return Err(invalid("BCF1 magic or reserved bytes are invalid"));
    }
    let kind = match header[4] {
        1 => FrameKind::Observed,
        2 => FrameKind::SyntheticRangeFill,
        _ => return Err(invalid("BCF1 frame kind is unknown")),
    };
    let block_number = u64::from_be_bytes(header[8..16].try_into().expect("fixed slice"));
    let block_hash = header[16..48].try_into().expect("fixed slice");
    let length = u32::from_be_bytes(header[48..52].try_into().expect("fixed slice")) as usize;
    validate(kind, block_number, &block_hash, length)?;
    if length > max_payload_len {
        return Err(invalid("BCF1 payload exceeds the consumer limit"));
    }
    let mut payload = vec![0; length];
    input.read_exact(&mut payload)?;
    Ok(Some(Frame {
        kind,
        block_number,
        block_hash,
        payload,
    }))
}

/// Write a complete clock-v1 envelope. Validate before writing any bytes.
pub fn write_frame<W: Write>(output: &mut W, frame: &Frame) -> io::Result<()> {
    validate(
        frame.kind,
        frame.block_number,
        &frame.block_hash,
        frame.payload.len(),
    )?;
    let mut header = [0; HEADER_LEN];
    header[..4].copy_from_slice(b"BCF1");
    header[4] = match frame.kind {
        FrameKind::Observed => 1,
        FrameKind::SyntheticRangeFill => 2,
    };
    header[8..16].copy_from_slice(&frame.block_number.to_be_bytes());
    header[16..48].copy_from_slice(&frame.block_hash);
    header[48..52].copy_from_slice(&(frame.payload.len() as u32).to_be_bytes());
    output.write_all(&header)?;
    output.write_all(&frame.payload)
}

/// A required half-open range of observed blocks. Synthetic fill is not valid
/// evidence for a producer that promises an output for every block.
///
/// Call `finish` only after the underlying stream reaches EOF. A producer's
/// successful process exit is a separate obligation of its supervising driver.
#[derive(Debug)]
pub struct ObservedRange {
    next: u64,
    end: u64,
    failed: bool,
}

impl ObservedRange {
    pub fn new(start: u64, end_exclusive: u64) -> io::Result<Self> {
        if start > end_exclusive || end_exclusive > MAX_BLOCK_NUMBER + 1 {
            return Err(invalid(
                "BCF1 range is reversed or exceeds the block-number domain",
            ));
        }
        Ok(Self {
            next: start,
            end: end_exclusive,
            failed: false,
        })
    }

    pub fn accept(&mut self, frame: &Frame) -> io::Result<()> {
        if self.failed {
            return Err(invalid("BCF1 range is poisoned by an earlier refusal"));
        }
        if let Err(error) = validate(
            frame.kind,
            frame.block_number,
            &frame.block_hash,
            frame.payload.len(),
        ) {
            self.failed = true;
            return Err(error);
        }
        if frame.kind != FrameKind::Observed
            || self.next >= self.end
            || frame.block_number != self.next
        {
            self.failed = true;
            return Err(invalid(format!(
                "BCF1 expected observed block {} before {}, got {:?} block {}",
                self.next, self.end, frame.kind, frame.block_number
            )));
        }
        self.next += 1;
        Ok(())
    }

    pub fn finish(self) -> io::Result<()> {
        if self.failed {
            return Err(invalid("BCF1 range is poisoned by an earlier refusal"));
        }
        if self.next != self.end {
            return Err(io::Error::new(
                io::ErrorKind::UnexpectedEof,
                format!(
                    "BCF1 range ended at {}; required end is {}",
                    self.next, self.end
                ),
            ));
        }
        Ok(())
    }
}
