//! Helpers shared by the pinned-target baseline verifiers (#110): IPFS
//! CIDv0 for single-chunk files, Git blob hashing, GraphQL schema parsing,
//! the logical schema hash, and ABI event-signature normalization. Each is
//! a direct port of the helper the Python verifiers duplicated per family.

use std::collections::{BTreeMap, BTreeSet};
use std::path::Path;

use serde_json::Value;
use sha2::{Digest, Sha256};

pub fn sha256_hex(payload: &[u8]) -> String {
    hex::encode(Sha256::digest(payload))
}

pub fn git_blob_hash(payload: &[u8]) -> String {
    use sha1::Digest as _;
    let mut hasher = sha1::Sha1::new();
    hasher.update(format!("blob {}\0", payload.len()).as_bytes());
    hasher.update(payload);
    hex::encode(hasher.finalize())
}

pub fn encode_varint(mut value: u64) -> Vec<u8> {
    let mut out = Vec::new();
    while value > 0x7f {
        out.push(((value & 0x7f) as u8) | 0x80);
        value >>= 7;
    }
    out.push(value as u8);
    out
}

const BASE58_ALPHABET: &[u8; 58] = b"123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";

pub fn base58btc(payload: &[u8]) -> String {
    let leading_zeroes = payload.iter().take_while(|b| **b == 0).count();
    // Big-number base conversion over a byte vector (payload is at most 34 bytes here).
    let mut digits: Vec<u8> = Vec::new();
    for byte in payload {
        let mut carry = u32::from(*byte);
        for digit in digits.iter_mut() {
            carry += u32::from(*digit) << 8;
            *digit = (carry % 58) as u8;
            carry /= 58;
        }
        while carry > 0 {
            digits.push((carry % 58) as u8);
            carry /= 58;
        }
    }
    let mut encoded = String::with_capacity(leading_zeroes + digits.len());
    encoded.extend(std::iter::repeat_n('1', leading_zeroes));
    for digit in digits.iter().rev() {
        encoded.push(BASE58_ALPHABET[*digit as usize] as char);
    }
    encoded
}

pub const IPFS_SINGLE_CHUNK: usize = 262_144;

/// CIDv0 of a UnixFS `File` node holding `payload` as a single default IPFS
/// chunk: the canonical UnixFS protobuf wrapped in a link-free DAG-PB node.
pub fn unixfs_file_cidv0(payload: &[u8]) -> Result<String, String> {
    if payload.len() > IPFS_SINGLE_CHUNK {
        return Err("CID verifier only accepts a single default IPFS chunk".into());
    }
    let mut unixfs = vec![0x08, 0x02, 0x12];
    unixfs.extend(encode_varint(payload.len() as u64));
    unixfs.extend_from_slice(payload);
    unixfs.push(0x18);
    unixfs.extend(encode_varint(payload.len() as u64));
    let mut node = vec![0x0a];
    node.extend(encode_varint(unixfs.len() as u64));
    node.extend(unixfs);
    let mut multihash = vec![0x12, 0x20];
    multihash.extend(Sha256::digest(&node));
    Ok(base58btc(&multihash))
}

/// `{"/": "/ipfs/Qm…"}` → `Qm…`.
pub fn cid_from_file(value: &Value) -> Result<String, String> {
    let map = value
        .as_object()
        .filter(|m| m.len() == 1 && m.contains_key("/"))
        .ok_or_else(|| format!("unexpected IPFS file value: {value}"))?;
    let location = map["/"]
        .as_str()
        .filter(|s| s.starts_with("/ipfs/Qm"))
        .ok_or_else(|| format!("unexpected IPFS location: {}", map["/"]))?;
    Ok(location.trim_start_matches("/ipfs/").to_string())
}

/// Remove all whitespace from an ABI event signature.
pub fn normalize_event(event: &str) -> String {
    event.chars().filter(|c| !c.is_whitespace()).collect()
}

fn is_ident(c: char) -> bool {
    c == '_' || c.is_ascii_alphanumeric()
}

fn take_ident(s: &str) -> Option<(&str, &str)> {
    let first = s.chars().next()?;
    if !(first == '_' || first.is_ascii_alphabetic()) {
        return None;
    }
    let end = s
        .char_indices()
        .find(|(_, c)| !is_ident(*c))
        .map(|(i, _)| i)
        .unwrap_or(s.len());
    Some((&s[..end], &s[end..]))
}

/// Parsed entity declarations: fields per entity, entities declared
/// `@entity(immutable: true)`, and entities declared `@entity(immutable: false)`.
#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub struct ParsedSchema {
    pub entities: BTreeMap<String, BTreeMap<String, String>>,
    pub immutable: BTreeSet<String>,
    pub explicit_mutable: BTreeSet<String>,
}

/// Port of the per-family `parse_schema`: comments stripped, `type X @entity`
/// with an optional `(immutable: true|false)` directive, fields as `name: Type`.
pub fn parse_schema(text: &str) -> ParsedSchema {
    let mut parsed = ParsedSchema::default();
    let mut current: Option<String> = None;
    for raw in text.lines() {
        let line = raw.split('#').next().unwrap_or_default().trim();
        if let Some(rest) = line.strip_prefix("type") {
            if rest.starts_with(char::is_whitespace) {
                if let Some((name, after)) = take_ident(rest.trim_start()) {
                    if let Some(after) = after.trim_start().strip_prefix("@entity") {
                        let after = after.trim_start();
                        let (directive, tail) = match after.strip_prefix('(') {
                            Some(inner) => match inner.find(')') {
                                Some(end) => {
                                    (Some(inner[..end].trim()), inner[end + 1..].trim_start())
                                }
                                None => (None, after),
                            },
                            None => (None, after),
                        };
                        let directive_ok = match directive {
                            None => true,
                            Some(d) => {
                                let d: String = d.chars().filter(|c| !c.is_whitespace()).collect();
                                d == "immutable:true" || d == "immutable:false"
                            }
                        };
                        if directive_ok && tail.starts_with('{') {
                            current = Some(name.to_string());
                            parsed.entities.insert(name.to_string(), BTreeMap::new());
                            if let Some(d) = directive {
                                let d: String = d.chars().filter(|c| !c.is_whitespace()).collect();
                                if d == "immutable:true" {
                                    parsed.immutable.insert(name.to_string());
                                } else {
                                    parsed.explicit_mutable.insert(name.to_string());
                                }
                            }
                            continue;
                        }
                    }
                }
            }
        }
        if let Some(name) = current.clone() {
            if line == "}" {
                current = None;
                continue;
            }
            if let Some((field, after)) = take_ident(line) {
                if let Some(after) = after.trim_start().strip_prefix(':') {
                    let after = after.trim_start();
                    let end = after
                        .char_indices()
                        .find(|(_, c)| {
                            !(c.is_ascii_alphanumeric() || matches!(c, '[' | ']' | '!' | '_'))
                        })
                        .map(|(i, _)| i)
                        .unwrap_or(after.len());
                    if end > 0 {
                        parsed
                            .entities
                            .get_mut(&name)
                            .expect("entity exists")
                            .insert(field.to_string(), after[..end].to_string());
                    }
                }
            }
        }
    }
    parsed
}

/// `sha256(json.dumps(entities, sort_keys=True, separators=(",", ":")))`.
pub fn logical_hash(entities: &BTreeMap<String, BTreeMap<String, String>>) -> String {
    sha256_hex(
        serde_json::to_string(entities)
            .expect("map serializes")
            .as_bytes(),
    )
}

/// `[(abi.name, cid)]` for a manifest mapping's `abis` list.
pub fn abi_contract(mapping: &Value) -> Result<Vec<(String, String)>, String> {
    let abis = mapping
        .get("abis")
        .and_then(Value::as_array)
        .ok_or("mapping ABI inventory must be a list")?;
    abis.iter()
        .map(|abi| {
            Ok((
                abi.get("name")
                    .map(|n| {
                        n.as_str()
                            .map(str::to_string)
                            .unwrap_or_else(|| n.to_string())
                    })
                    .unwrap_or_else(|| "None".into()),
                cid_from_file(abi.get("file").unwrap_or(&Value::Null))?,
            ))
        })
        .collect()
}

pub fn read_json(path: &Path) -> Result<Value, String> {
    let text = std::fs::read_to_string(path)
        .map_err(|e| format!("cannot read {}: {e}", path.display()))?;
    serde_json::from_str(&text).map_err(|e| format!("cannot parse {}: {e}", path.display()))
}

pub fn read_yaml(path: &Path) -> Result<Value, String> {
    let text = std::fs::read_to_string(path)
        .map_err(|e| format!("cannot read {}: {e}", path.display()))?;
    let value: serde_yaml::Value =
        serde_yaml::from_str(&text).map_err(|e| format!("cannot parse {}: {e}", path.display()))?;
    serde_json::to_value(value).map_err(|e| format!("cannot convert {}: {e}", path.display()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    fn repository() -> PathBuf {
        Path::new(env!("CARGO_MANIFEST_DIR")).join("..")
    }

    #[test]
    fn base58_and_varint_match_reference_values() {
        assert_eq!(base58btc(&[0, 0, 1]), "112");
        assert_eq!(base58btc(&[]), "");
        assert_eq!(base58btc(b"hello"), "Cn8eVZg");
        assert_eq!(encode_varint(0), vec![0]);
        assert_eq!(encode_varint(300), vec![0xac, 0x02]);
        assert_eq!(encode_varint(262_144), vec![0x80, 0x80, 0x10]);
    }

    #[test]
    fn unixfs_cidv0_matches_the_deployed_schema_cid() {
        // The pinned Aerodrome deployment manifest names its schema file by
        // CID; recomputing that CID from the retained bytes must match.
        let root = repository();
        let manifest =
            read_yaml(&root.join("aerodrome-slipstream-base/reference/deployment.yaml")).unwrap();
        let expected = cid_from_file(manifest["schema"].get("file").unwrap()).unwrap();
        let schema =
            std::fs::read(root.join("aerodrome-slipstream-base/reference/schema.graphql")).unwrap();
        assert_eq!(unixfs_file_cidv0(&schema).unwrap(), expected);
        assert!(unixfs_file_cidv0(&vec![0u8; IPFS_SINGLE_CHUNK + 1]).is_err());
    }

    #[test]
    fn schema_parser_reports_directives_and_fields() {
        let text = "type A @entity(immutable: true) {\n  id: ID!\n  amount: BigInt! # comment\n}\ntype B @entity(immutable: false) {\n  id: Bytes!\n}\ntype C @entity {\n  id: ID!\n  refs: [A!]!\n}\n";
        let parsed = parse_schema(text);
        assert_eq!(parsed.entities.len(), 3);
        assert_eq!(parsed.entities["A"]["amount"], "BigInt!");
        assert_eq!(parsed.entities["C"]["refs"], "[A!]!");
        assert_eq!(parsed.immutable, BTreeSet::from(["A".to_string()]));
        assert_eq!(parsed.explicit_mutable, BTreeSet::from(["B".to_string()]));
        assert_eq!(
            normalize_event("Swap(indexed address, int256 ,uint160)"),
            "Swap(indexedaddress,int256,uint160)"
        );
        assert_eq!(
            git_blob_hash(b"hello\n"),
            "ce013625030ba8dba906f756967f9e9ca394464a"
        );
    }
}
