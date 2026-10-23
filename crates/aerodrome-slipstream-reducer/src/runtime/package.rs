use crate::{refuse, require, Result};
use backfill_common::descriptor::ExtractorIdentity;
use prost::Message;
use sha1::{Digest, Sha1};
use std::collections::{BTreeMap, BTreeSet};

// Package metadata and descriptors do not affect executable module identity.
// Network overrides and filters do: retain their raw fields and refuse them.
#[derive(Clone, PartialEq, Message)]
struct Package {
    #[prost(uint64, tag = "5")]
    version: u64,
    #[prost(bytes = "vec", optional, tag = "6")]
    modules: Option<Vec<u8>>,
    #[prost(string, tag = "9")]
    network: String,
    #[prost(bytes = "vec", repeated, tag = "13")]
    networks: Vec<Vec<u8>>,
    #[prost(bytes = "vec", repeated, tag = "14")]
    filters: Vec<Vec<u8>>,
}
#[derive(Clone, PartialEq, Message)]
struct Modules {
    #[prost(message, repeated, tag = "1")]
    modules: Vec<Module>,
    #[prost(message, repeated, tag = "2")]
    binaries: Vec<Binary>,
}
#[derive(Clone, PartialEq, Message)]
struct Binary {
    #[prost(string, tag = "1")]
    kind: String,
    #[prost(bytes = "vec", tag = "2")]
    content: Vec<u8>,
}
#[derive(Clone, PartialEq, Message)]
struct Module {
    #[prost(string, tag = "1")]
    name: String,
    #[prost(oneof = "Kind", tags = "2,3")]
    kind: Option<Kind>,
    #[prost(uint32, tag = "4")]
    binary: u32,
    #[prost(string, tag = "5")]
    entrypoint: String,
    #[prost(message, repeated, tag = "6")]
    inputs: Vec<Input>,
    #[prost(message, optional, tag = "7")]
    output: Option<Text>,
    #[prost(uint64, tag = "8")]
    initial: u64,
}
#[derive(Clone, PartialEq, prost::Oneof)]
enum Kind {
    #[prost(message, tag = "2")]
    Map(Text),
    #[prost(message, tag = "3")]
    Store(StoreKind),
}
#[derive(Clone, PartialEq, Message)]
struct StoreKind {
    #[prost(int32, tag = "1")]
    policy: i32,
    #[prost(string, tag = "2")]
    value: String,
}
#[derive(Clone, PartialEq, Message)]
struct Text {
    #[prost(string, tag = "1")]
    value: String,
}
#[derive(Clone, PartialEq, Message)]
struct Store {
    #[prost(string, tag = "1")]
    name: String,
    #[prost(int32, tag = "2")]
    mode: i32,
}
#[derive(Clone, PartialEq, Message)]
struct Input {
    #[prost(oneof = "InputKind", tags = "1,2,3,4")]
    kind: Option<InputKind>,
}
#[derive(Clone, PartialEq, prost::Oneof)]
enum InputKind {
    #[prost(message, tag = "1")]
    Source(Text),
    #[prost(message, tag = "2")]
    Map(Text),
    #[prost(message, tag = "3")]
    Store(Store),
    #[prost(message, tag = "4")]
    Params(Text),
}
pub(super) fn verify(bytes: &[u8], identity: &ExtractorIdentity) -> Result<()> {
    let pkg = Package::decode(bytes).map_err(|e| refuse(format!("package protobuf: {e}")))?;
    require(
        pkg.version == 1
            && pkg.network == "base"
            && pkg.networks.is_empty()
            && pkg.filters.is_empty(),
        "unsupported package version/network/overrides",
    )?;
    let raw = pkg.modules.ok_or_else(|| refuse("package lacks modules"))?;
    let modules = Modules::decode(raw.as_slice()).map_err(|e| refuse(e.to_string()))?;
    // This also refuses future executable fields rather than silently excluding
    // them from hashing. The map/store subset is sufficient for this SPKG.
    validate_wire(&raw, Schema::Modules)?;
    require(
        !modules.modules.is_empty()
            && modules.modules.len() <= 128
            && !modules.binaries.is_empty()
            && modules.binaries.len() <= 16,
        "package graph exceeds supported bounds",
    )?;
    let mut names = BTreeMap::new();
    for (i, m) in modules.modules.iter().enumerate() {
        require(
            !m.name.is_empty()
                && names.insert(m.name.as_str(), i).is_none()
                && !m.entrypoint.is_empty()
                && m.initial != u64::MAX
                && m.inputs.len() <= 128,
            "invalid or duplicate package module",
        )?;
        let binary = modules
            .binaries
            .get(m.binary as usize)
            .ok_or_else(|| refuse("invalid binary index"))?;
        require(
            binary.kind == "wasm/rust-v1" && binary.content.starts_with(b"\0asm\x01\0\0\0"),
            "unsupported package binary",
        )?;
        require(
            m.kind.is_some() && m.inputs.iter().all(|i| i.kind.is_some()),
            "missing module kind/input",
        )?;
    }
    let mut edges = vec![Vec::new(); modules.modules.len()];
    for (i, m) in modules.modules.iter().enumerate() {
        for input in &m.inputs {
            let (name, required) = match input.kind.as_ref().unwrap() {
                InputKind::Source(t) | InputKind::Params(t) => (t.value.as_str(), false),
                InputKind::Map(t) => (t.value.as_str(), true),
                InputKind::Store(s) => (s.name.as_str(), true),
            };
            if let Some(&j) = names.get(name) {
                edges[i].push(j);
            } else {
                require(!required, "package input references missing module")?;
            }
        }
    }
    let target = *names
        .get(identity.module.as_str())
        .ok_or_else(|| refuse("package output module absent"))?;
    let m = &modules.modules[target];
    require(
        matches!(&m.kind, Some(Kind::Map(t)) if t.value == identity.output_type)
            && m.output
                .as_ref()
                .is_some_and(|t| t.value == identity.output_type)
            && m.initial == identity.initial_block,
        "package output/type/start mismatch",
    )?;
    let mut cache = BTreeMap::new();
    for i in 0..modules.modules.len() {
        module_hash(i, &modules, &edges, &mut cache, &mut BTreeSet::new())?;
    }
    require(
        hex::encode(cache[&target]) == identity.module_hash,
        "package module hash mismatch",
    )
}
// Go and prost serialize oneofs in different field order. Validate the closed
// executable schema directly, retaining repeated field order, rather than
// incorrectly requiring byte-for-byte protobuf re-encoding.
#[derive(Clone, Copy)]
enum Schema {
    Modules,
    Module,
    Binary,
    Text,
    StoreKind,
    Input,
    Store,
}
fn validate_wire(mut bytes: &[u8], schema: Schema) -> Result<()> {
    let mut seen = BTreeSet::new();
    let mut oneof = false;
    while !bytes.is_empty() {
        let key = varint(&mut bytes)?;
        let tag = key >> 3;
        let wire = key & 7;
        let (expected, repeated, child, exclusive) = match (schema, tag) {
            (Schema::Modules, 1) => (2, true, Some(Schema::Module), false),
            (Schema::Modules, 2) => (2, true, Some(Schema::Binary), false),
            (Schema::Module, 1 | 5)
            | (Schema::Binary, 1 | 2)
            | (Schema::Text, 1)
            | (Schema::Store, 1)
            | (Schema::StoreKind, 2) => (2, false, None, false),
            (Schema::Module, 2) => (2, false, Some(Schema::Text), true),
            (Schema::Module, 3) => (2, false, Some(Schema::StoreKind), true),
            (Schema::Module, 4 | 8) | (Schema::Store, 2) | (Schema::StoreKind, 1) => {
                (0, false, None, false)
            }
            (Schema::Module, 6) => (2, true, Some(Schema::Input), false),
            (Schema::Module, 7) => (2, false, Some(Schema::Text), false),
            (Schema::Input, 1 | 2 | 4) => (2, false, Some(Schema::Text), true),
            (Schema::Input, 3) => (2, false, Some(Schema::Store), true),
            _ => return Err(refuse("unsupported executable package field")),
        };
        require(
            wire == expected && (repeated || seen.insert(tag)),
            "invalid or duplicate package field",
        )?;
        if exclusive {
            require(!oneof, "duplicate package oneof")?;
            oneof = true;
        }
        if wire == 0 {
            varint(&mut bytes)?;
        } else {
            let len = usize::try_from(varint(&mut bytes)?)
                .map_err(|_| refuse("package length overflow"))?;
            require(len <= bytes.len(), "truncated package field")?;
            let (value, rest) = bytes.split_at(len);
            bytes = rest;
            if let Some(child) = child {
                validate_wire(value, child)?;
            }
        }
    }
    Ok(())
}
fn varint(bytes: &mut &[u8]) -> Result<u64> {
    let mut result = 0u64;
    for shift in (0..70).step_by(7) {
        let (&byte, rest) = bytes
            .split_first()
            .ok_or_else(|| refuse("truncated package varint"))?;
        *bytes = rest;
        require(shift < 63 || byte <= 1, "package varint overflow")?;
        result |= u64::from(byte & 127) << shift;
        if byte & 128 == 0 {
            return Ok(result);
        }
    }
    Err(refuse("invalid package varint"))
}

fn module_hash(
    i: usize,
    modules: &Modules,
    edges: &[Vec<usize>],
    cache: &mut BTreeMap<usize, [u8; 20]>,
    visiting: &mut BTreeSet<usize>,
) -> Result<[u8; 20]> {
    if let Some(hash) = cache.get(&i) {
        return Ok(*hash);
    }
    require(visiting.insert(i), "package graph has a cycle")?;
    let mut ancestors = BTreeSet::new();
    let mut pending = edges[i].clone();
    while let Some(j) = pending.pop() {
        require(j != i, "package graph has a cycle")?;
        if ancestors.insert(j) {
            pending.extend(&edges[j]);
        }
    }
    let m = &modules.modules[i];
    let b = &modules.binaries[m.binary as usize];
    let mut hash = Sha1::new();
    hash.update(b"initial_block");
    hash.update(m.initial.to_le_bytes());
    hash.update(b"kind");
    hash.update(match m.kind {
        Some(Kind::Map(_)) => b"map".as_slice(),
        Some(Kind::Store(_)) => b"store".as_slice(),
        None => return Err(refuse("missing kind")),
    });
    hash.update(b"binary");
    hash.update(b.kind.as_bytes());
    hash.update(&b.content);
    hash.update(b"inputs");
    for input in &m.inputs {
        match input.kind.as_ref().unwrap() {
            InputKind::Source(t) => {
                hash.update(b"source");
                hash.update(t.value.as_bytes());
            }
            InputKind::Params(t) => {
                hash.update(b"params");
                hash.update(t.value.as_bytes());
            }
            InputKind::Map(_) => hash.update(b"map"),
            InputKind::Store(_) => hash.update(b"store"),
        }
    }
    hash.update(b"ancestors");
    // Go graph.ShortestPaths returns distances in package module index order.
    for j in ancestors {
        hash.update(module_hash(j, modules, edges, cache, visiting)?);
    }
    hash.update(b"entrypoint");
    hash.update(m.entrypoint.as_bytes());
    let result = hash.finalize().into();
    visiting.remove(&i);
    cache.insert(i, result);
    Ok(result)
}

#[cfg(test)]
pub(super) use tests::fixture;

#[cfg(test)]
mod tests {
    use super::*;
    fn synthetic() -> (Vec<u8>, ExtractorIdentity) {
        let modules = Modules {
            modules: vec![Module {
                name: crate::identity::OUTPUT_MODULE.into(),
                kind: Some(Kind::Map(Text {
                    value: crate::identity::OUTPUT_TYPE.into(),
                })),
                binary: 0,
                entrypoint: "map_extractor_block".into(),
                inputs: vec![Input {
                    kind: Some(InputKind::Source(Text {
                        value: "sf.ethereum.type.v2.Block".into(),
                    })),
                }],
                output: Some(Text {
                    value: crate::identity::OUTPUT_TYPE.into(),
                }),
                initial: aerodrome_extractor_core::config::INITIAL_BLOCK,
            }],
            binaries: vec![Binary {
                kind: "wasm/rust-v1".into(),
                content: b"\0asm\x01\0\0\0".to_vec(),
            }],
        };
        let hash = module_hash(
            0,
            &modules,
            &[vec![]],
            &mut BTreeMap::new(),
            &mut BTreeSet::new(),
        )
        .unwrap();
        let bytes = Package {
            version: 1,
            network: "base".into(),
            modules: Some(modules.encode_to_vec()),
            networks: vec![],
            filters: vec![],
        }
        .encode_to_vec();
        let identity = ExtractorIdentity {
            spkg_sha256: super::super::hash(&bytes),
            module: crate::identity::OUTPUT_MODULE.into(),
            module_hash: hex::encode(hash),
            output_type: crate::identity::OUTPUT_TYPE.into(),
            initial_block: aerodrome_extractor_core::config::INITIAL_BLOCK,
        };
        (bytes, identity)
    }
    #[test]
    fn committed_synthetic_fixture_matches_independently_encoded_vector() {
        let (bytes, identity) = synthetic();
        assert_eq!(
            bytes,
            include_bytes!("../../fixtures/runtime/synthetic-extractor.spkg")
        );
        let pinned: ExtractorIdentity = serde_json::from_slice(include_bytes!(
            "../../fixtures/runtime/synthetic-extractor-identity.json"
        ))
        .unwrap();
        assert_eq!(identity, pinned);
        super::super::verify_package(&bytes, &pinned).unwrap();
    }
    #[test]
    fn package_mutation_and_unsupported_executable_fields_refuse() {
        let (bytes, id) = synthetic();
        verify(&bytes, &id).unwrap();
        let mut p = Package::decode(bytes.as_slice()).unwrap();
        let mut m = Modules::decode(p.modules.as_ref().unwrap().as_slice()).unwrap();
        m.binaries[0].content.push(0);
        p.modules = Some(m.encode_to_vec());
        assert!(verify(&p.encode_to_vec(), &id).is_err());
        let (bytes, id) = synthetic();
        let mut p = Package::decode(bytes.as_slice()).unwrap();
        p.modules.as_mut().unwrap().extend([0x18, 0x01]);
        assert!(verify(&p.encode_to_vec(), &id).is_err());
        let (bytes, id) = synthetic();
        let mut p = Package::decode(bytes.as_slice()).unwrap();
        p.networks.push(vec![1]);
        assert!(verify(&p.encode_to_vec(), &id).is_err());
    }
    pub(crate) fn fixture() -> (Vec<u8>, ExtractorIdentity) {
        synthetic()
    }
}
