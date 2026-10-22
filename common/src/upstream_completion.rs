//! Supervisor-to-producer completion, distinct from the final engine receipt.
//! Only the supervisor that actually reaps the native child may send this on
//! the attempt's private control pipe. Canonical bytes and a nonce bind that
//! assertion; they do not independently prove a process exit.
use crate::{producer_checkpoint::Binding, state_snapshot::Boundary};
use serde::{Deserialize, Serialize};
use std::io::Read;

pub const FORMAT: &str = "pinax.backfill.upstream-completion/v1";
pub const MAX_BYTES: usize = 64 * 1024;

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Request {
    pub binding: Binding,
    /// Fresh unpredictable 32-byte token for this attempt, not an API secret.
    pub attempt_nonce: String,
    pub substreams_native_sha256: String,
    pub from: u64,
    pub stop_exclusive: u64,
    pub predecessor: Boundary,
    pub observed_parent_hash: String,
    pub reducer_lineage_before: String,
    pub engine_lineage_before: String,
}
impl Request {
    pub fn validate(&self) -> Result<(), String> {
        self.binding.validate()?;
        if ![
            &self.attempt_nonce,
            &self.substreams_native_sha256,
            &self.observed_parent_hash,
            &self.reducer_lineage_before,
            &self.engine_lineage_before,
        ]
        .iter()
        .all(|s| digest(s))
            || self.attempt_nonce == "00".repeat(32)
            || self.observed_parent_hash == "00".repeat(32)
            || self.from == 0
            || self.predecessor.block_number.checked_add(1) != Some(self.from)
            || self.from >= self.stop_exclusive
            || self.stop_exclusive - self.from > 50_000
            || self.stop_exclusive > i32::MAX as u64 + 1
            || (self.predecessor.block_hash != [0; 32]
                && hex::encode(self.predecessor.block_hash) != self.observed_parent_hash)
        {
            return Err("invalid upstream completion request".into());
        }
        Ok(())
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Completion {
    pub format: String,
    pub request: Request,
    pub native_exit_code: i32,
    pub input_sha256: String,
    pub input_bytes: u64,
    pub head: Boundary,
}
impl Completion {
    pub fn validate(&self) -> Result<(), String> {
        self.request.validate()?;
        if self.format != FORMAT
            || self.native_exit_code != 0
            || !digest(&self.input_sha256)
            || self.input_bytes == 0
            || self.head.block_hash == [0; 32]
            || self.head.block_number.checked_add(1) != Some(self.request.stop_exclusive)
        {
            return Err("upstream did not prove exact successful completion".into());
        }
        Ok(())
    }
    pub fn encode(&self) -> Result<Vec<u8>, String> {
        self.validate()?;
        let mut bytes = serde_json::to_vec_pretty(self).map_err(|e| e.to_string())?;
        bytes.push(b'\n');
        if bytes.len() > MAX_BYTES {
            return Err("upstream completion exceeds limit".into());
        }
        Ok(bytes)
    }
    /// Require EOF on the private control pipe, then compare every identity
    /// and the bytes/head independently observed by the producer.
    pub fn read_verified(
        reader: impl Read,
        request: &Request,
        input_sha256: &str,
        input_bytes: u64,
        head: &Boundary,
    ) -> Result<(Self, Vec<u8>), String> {
        request.validate()?;
        let mut bytes = Vec::new();
        reader
            .take(MAX_BYTES as u64 + 1)
            .read_to_end(&mut bytes)
            .map_err(|e| e.to_string())?;
        if bytes.is_empty() || bytes.len() > MAX_BYTES {
            return Err("missing or oversized upstream completion".into());
        }
        let value: Self = serde_json::from_slice(&bytes).map_err(|e| e.to_string())?;
        if value.encode()? != bytes
            || &value.request != request
            || value.input_sha256 != input_sha256
            || value.input_bytes != input_bytes
            || &value.head != head
        {
            return Err("upstream completion differs from this attempt or observed input".into());
        }
        Ok((value, bytes))
    }
}
fn digest(s: &str) -> bool {
    s.len() == 64
        && s.bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}

#[cfg(test)]
mod tests {
    use super::*;
    fn completion() -> Completion {
        Completion {
            format: FORMAT.into(),
            request: Request {
                binding: Binding {
                    family: "test".into(),
                    deployment: "deployment".into(),
                    network: "base".into(),
                    descriptor_sha256: "11".repeat(32),
                    extractor_lock_sha256: "22".repeat(32),
                    spkg_sha256: "33".repeat(32),
                    module: "map_extractor_block".into(),
                    module_hash: "44".repeat(20),
                    reducer_commit: "55".repeat(20),
                    reducer_binary_sha256: "66".repeat(32),
                },
                attempt_nonce: "77".repeat(32),
                substreams_native_sha256: "88".repeat(32),
                from: 100,
                stop_exclusive: 102,
                predecessor: Boundary {
                    block_number: 99,
                    block_hash: [0; 32],
                },
                observed_parent_hash: "aa".repeat(32),
                reducer_lineage_before: "bb".repeat(32),
                engine_lineage_before: "cc".repeat(32),
            },
            native_exit_code: 0,
            input_sha256: "dd".repeat(32),
            input_bytes: 1234,
            head: Boundary {
                block_number: 101,
                block_hash: [0xee; 32],
            },
        }
    }
    #[test]
    fn completion_requires_every_attempt_pin_consumed_byte_digest_and_head() {
        let v = completion();
        let bytes = v.encode().unwrap();
        let verify = |b: &[u8]| {
            Completion::read_verified(b, &v.request, &v.input_sha256, v.input_bytes, &v.head)
        };
        assert_eq!(verify(&bytes).unwrap(), (v.clone(), bytes.clone()));
        for change in 0..12 {
            let mut changed = v.clone();
            match change {
                0 => changed.request.attempt_nonce = "01".repeat(32),
                1 => changed.request.substreams_native_sha256 = "02".repeat(32),
                2 => changed.request.binding.reducer_binary_sha256 = "03".repeat(32),
                3 => changed.request.binding.spkg_sha256 = "04".repeat(32),
                4 => changed.request.binding.module_hash = "05".repeat(20),
                5 => changed.request.reducer_lineage_before = "06".repeat(32),
                6 => changed.request.engine_lineage_before = "07".repeat(32),
                7 => changed.input_sha256 = "08".repeat(32),
                8 => changed.input_bytes += 1,
                9 => changed.head.block_hash[0] ^= 1,
                10 => changed.request.observed_parent_hash = "09".repeat(32),
                _ => changed.request.predecessor.block_hash = [0xaa; 32],
            }
            assert!(
                verify(&changed.encode().unwrap()).is_err(),
                "mutation {change}"
            );
        }
    }
    #[test]
    fn failed_truncated_noncanonical_unknown_duplicate_oversized_or_faulted_control_refuses() {
        let v = completion();
        let bytes = v.encode().unwrap();
        let verify = |b: &[u8]| {
            Completion::read_verified(b, &v.request, &v.input_sha256, v.input_bytes, &v.head)
        };
        for end in [0, 1, bytes.len() - 2, bytes.len() - 1] {
            assert!(verify(&bytes[..end]).is_err());
        }
        assert!(verify(&serde_json::to_vec(&v).unwrap()).is_err());
        assert!(verify(&vec![b' '; MAX_BYTES + 1]).is_err());
        for addition in ["\"extra\":1,", "\"native_exit_code\":0,"] {
            let modified = format!(
                "{{{addition}{}",
                String::from_utf8(bytes[1..].to_vec()).unwrap()
            );
            assert!(verify(modified.as_bytes()).is_err());
        }
        let mut failed = v.clone();
        failed.native_exit_code = 1;
        assert!(failed.encode().is_err());
        struct Fault;
        impl Read for Fault {
            fn read(&mut self, _: &mut [u8]) -> std::io::Result<usize> {
                Err(std::io::ErrorKind::Other.into())
            }
        }
        assert!(Completion::read_verified(
            Fault,
            &v.request,
            &v.input_sha256,
            v.input_bytes,
            &v.head
        )
        .is_err());
    }
}
