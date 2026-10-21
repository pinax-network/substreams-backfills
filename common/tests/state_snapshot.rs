use backfill_common::{
    dynamic_sources::DataSource,
    dynamic_sources_v2::{Creation, SourceOrder},
    pb::pinax::graph::backfill::v1::{
        entity_id, graph_value, BigDecimalValue, EntityField, EntityFields, EntityId, EntityKey,
        GraphValue,
    },
    state_snapshot::*,
};
use num_bigint::BigInt;
use prost::Message;
use serde::Serialize;
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeMap,
    io::{self, Cursor, Read, Write},
};

fn header(records: u64) -> SnapshotHeader {
    let boundary = Boundary {
        block_number: 100,
        block_hash: [1; 32],
    };
    SnapshotHeader {
        format: FORMAT.into(),
        version: VERSION,
        binding: SnapshotBinding {
            deployment: "QmSnapshotFixture".into(),
            network: "base".into(),
            descriptor_sha256: "11".repeat(32),
            retention_sha256: "22".repeat(32),
            type_ordinals: vec!["Token".into()],
            entity_id_policy: EntityIdPolicy::AllKinds,
        },
        boundary: boundary.clone(),
        origin: SnapshotOrigin::Landing {
            seed: SeedOrigin {
                schema: "sgd5311".into(),
                site_id: 5311,
                database: "graph".into(),
                system_identifier: "123456789".into(),
                server_version_num: 160000,
                capture_tool_sha256: "33".repeat(32),
                profile_sha256: "44".repeat(32),
                head: boundary,
                health: "healthy".into(),
                non_fatal_errors: vec![],
            },
        },
        vid: Some(VidState {
            tables: vec![TableVid {
                entity_type: "Token".into(),
                postgres_table: "token".into(),
                max_vid: 12,
                sequence_last_value: 12,
                sequence_is_called: true,
                active_rows: Some(records),
            }],
        }),
        poi: GenericPoiState::default(),
        sources: SourceSnapshot::from_rows(vec![SnapshotSource {
            vid: 3,
            creation_block: 8,
            manifest_idx: 2,
            param: vec![0xab; 20],
        }])
        .unwrap(),
        period_max: BTreeMap::new(),
        entity_count: Some(records as i64),
        records,
    }
}

fn key(id: entity_id::Value) -> EntityKey {
    EntityKey {
        entity_type: "Token".into(),
        id: Some(EntityId { value: Some(id) }),
        storage_causality_region: 0,
    }
}

fn entity(key: &EntityKey) -> StoredEntity {
    let id = match key.id.as_ref().unwrap().value.as_ref().unwrap() {
        entity_id::Value::String(s) => graph_value::Kind::String(s.clone()),
        entity_id::Value::Bytes(s) => graph_value::Kind::Bytes(s.clone()),
        entity_id::Value::Int8(s) => graph_value::Kind::Int8(*s),
    };
    StoredEntity {
        vid: 12,
        block_range_start: 99,
        fields: vec![
            EntityField {
                name: "id".into(),
                value: Some(GraphValue { kind: Some(id) }),
            },
            EntityField {
                name: "tvl".into(),
                value: Some(GraphValue {
                    kind: Some(graph_value::Kind::BigDecimal(BigDecimalValue {
                        coefficient_signed_be: "-19582627366648723548155211868460794"
                            .parse::<BigInt>()
                            .unwrap()
                            .to_signed_bytes_be(),
                        scale: 31,
                    })),
                }),
            },
        ],
    }
}

fn record(header: &SnapshotHeader, id: &str) -> SnapshotRecord {
    let key = key(entity_id::Value::String(id.into()));
    SnapshotRecord::from_entity(&header.binding, &key, &entity(&key)).unwrap()
}

fn encode(header: SnapshotHeader, records: &[SnapshotRecord]) -> (Vec<u8>, VerifiedSnapshot) {
    let mut w = SnapshotWriter::new(Vec::new(), header, Limits::default()).unwrap();
    for record in records {
        w.write_record(record).unwrap();
    }
    w.finish().unwrap()
}

fn read(bytes: &[u8], binding: &SnapshotBinding) -> Result<VerifiedSnapshot, String> {
    let mut r = SnapshotReader::new(bytes, binding, ReadPurpose::Loadable, Limits::default())?;
    while r.next_record()?.is_some() {}
    r.finish()
}

fn framed_header(bytes: &[u8]) -> (&[u8], usize) {
    let size = u32::from_be_bytes(bytes[8..12].try_into().unwrap()) as usize;
    (&bytes[12..12 + size], 12 + size)
}

fn replace_header(bytes: &[u8], new_header: &[u8]) -> Vec<u8> {
    let (_, end) = framed_header(bytes);
    let mut output = MAGIC.to_vec();
    output.extend_from_slice(&(new_header.len() as u32).to_be_bytes());
    output.extend_from_slice(new_header);
    output.extend_from_slice(&bytes[end..]);
    output
}

#[test]
fn deterministic_roundtrip_preserves_exact_negative_decimal_and_full_identity() {
    let h = header(2);
    let records = vec![record(&h, "a"), record(&h, "b")];
    let (bytes, verified) = encode(h.clone(), &records);
    let (again, identity) = encode(h.clone(), &records);
    assert_eq!(bytes, again);
    assert_eq!(identity, verified);
    assert_eq!(
        verified.file_sha256(),
        <[u8; 32]>::from(Sha256::digest(&bytes))
    );
    assert_eq!(verified.bytes(), bytes.len() as u64);
    assert_eq!(verified.records(), 2);
    assert_eq!(verified.lineage(), initial_lineage(verified.file_sha256()));
    assert_eq!(read(&bytes, &h.binding).unwrap(), verified);
    let mut r = SnapshotReader::new(
        Cursor::new(&bytes),
        &h.binding,
        ReadPurpose::Loadable,
        Limits::default(),
    )
    .unwrap();
    assert_eq!(r.header(), &h);
    assert_eq!(r.header().next_block(), 101);
    for expected in &records {
        let actual = r.next_record().unwrap().unwrap();
        assert_eq!(&actual, expected);
        let key = decode_key(&h.binding, &actual.key).unwrap();
        assert_eq!(
            StoredEntity::decode(&key, &actual.value).unwrap(),
            entity(&key)
        );
    }
    assert!(r.next_record().unwrap().is_none());
    assert_eq!(r.finish().unwrap(), verified);
    // Key/value golden fixes endian, sign-bit and EntityFields protobuf bytes.
    assert_eq!(hex::encode(&records[0].key), "0000800000000061");
    assert_eq!(
        &records[0].value[..13],
        &[1, 0, 0, 0, 0, 0, 0, 0, 12, 0, 0, 0, 99]
    );
    assert_eq!(
        EntityFields::decode(&records[0].value[13..])
            .unwrap()
            .encode_to_vec(),
        records[0].value[13..]
    );
    // Pin the complete framing, canonical named maps, header and source domain.
    assert_eq!(
        hex::encode(verified.file_sha256()),
        "bc45c3152920b291902bf5244ed6486d9559c6fef2ee5d6340cf1819bb4d78ac"
    );
}

#[test]
fn every_truncation_checksum_damage_and_trailing_bytes_are_refused() {
    let h = header(1);
    let (bytes, _) = encode(h.clone(), &[record(&h, "a")]);
    for end in 0..bytes.len() {
        assert!(
            read(&bytes[..end], &h.binding).is_err(),
            "accepted prefix {end}"
        );
    }
    let mut corrupt = bytes.clone();
    *corrupt.last_mut().unwrap() ^= 1;
    assert!(read(&corrupt, &h.binding).unwrap_err().contains("checksum"));
    let mut trailing = bytes.clone();
    trailing.push(0);
    assert!(read(&trailing, &h.binding)
        .unwrap_err()
        .contains("trailing"));
    let mut count = bytes.clone();
    let n = count.len();
    count[n - 33] ^= 1;
    assert!(read(&count, &h.binding).unwrap_err().contains("count"));
    let mut magic = bytes.clone();
    let n = magic.len();
    magic[n - 48] ^= 1;
    assert!(read(&magic, &h.binding).unwrap_err().contains("trailer"));
}

#[test]
fn incomplete_reads_and_writes_cannot_return_verified_identity() {
    let h = header(1);
    let (bytes, _) = encode(h.clone(), &[record(&h, "a")]);
    let reader = SnapshotReader::new(
        &bytes[..],
        &h.binding,
        ReadPurpose::Loadable,
        Limits::default(),
    )
    .unwrap();
    assert!(reader.finish().is_err());
    assert!(
        SnapshotWriter::new(Vec::new(), h.clone(), Limits::default())
            .unwrap()
            .finish()
            .is_err()
    );
    let mut writer = SnapshotWriter::new(Vec::new(), h.clone(), Limits::default()).unwrap();
    writer.write_record(&record(&h, "a")).unwrap();
    assert!(writer.write_record(&record(&h, "b")).is_err());
    assert!(writer.finish().is_err());
}

#[test]
fn duplicate_or_unsorted_records_are_refused_even_with_valid_payloads() {
    let h = header(2);
    for ids in [["a", "a"], ["b", "a"]] {
        let mut writer = SnapshotWriter::new(Vec::new(), h.clone(), Limits::default()).unwrap();
        writer.write_record(&record(&h, ids[0])).unwrap();
        assert!(writer
            .write_record(&record(&h, ids[1]))
            .unwrap_err()
            .contains("sorted"));
        assert!(writer.finish().is_err());
    }
    let (bytes, _) = encode(h.clone(), &[record(&h, "a"), record(&h, "b")]);
    let (_, end) = framed_header(&bytes);
    let len = u32::from_be_bytes(bytes[end..end + 4].try_into().unwrap()) as usize;
    let first = bytes[end..end + 4 + len].to_vec();
    let mut dup = bytes[..end].to_vec();
    dup.extend_from_slice(&first);
    dup.extend_from_slice(&first);
    dup.extend_from_slice(&bytes[bytes.len() - 48..]);
    let mut r = SnapshotReader::new(
        &dup[..],
        &h.binding,
        ReadPurpose::Loadable,
        Limits::default(),
    )
    .unwrap();
    assert!(r.next_record().unwrap().is_some());
    assert!(r.next_record().unwrap_err().contains("sorted"));
    assert!(r.finish().is_err());
}

#[test]
fn all_binding_axes_are_exact_and_oracle_is_never_loadable() {
    let h = header(0);
    let (bytes, _) = encode(h.clone(), &[]);
    let mut variants = vec![];
    let mut b = h.binding.clone();
    b.deployment.push('x');
    variants.push(b);
    let mut b = h.binding.clone();
    b.network.push('x');
    variants.push(b);
    let mut b = h.binding.clone();
    b.descriptor_sha256 = "55".repeat(32);
    variants.push(b);
    let mut b = h.binding.clone();
    b.retention_sha256 = "55".repeat(32);
    variants.push(b);
    let mut b = h.binding.clone();
    b.type_ordinals = vec!["Other".into()];
    variants.push(b);
    let mut b = h.binding.clone();
    b.entity_id_policy = EntityIdPolicy::StringOnly;
    variants.push(b);
    for b in variants {
        assert!(
            SnapshotReader::new(&bytes[..], &b, ReadPurpose::Loadable, Limits::default()).is_err()
        );
    }
    let mut oracle = h.clone();
    let SnapshotOrigin::Landing { seed } = oracle.origin else {
        panic!()
    };
    oracle.origin = SnapshotOrigin::Oracle { seed };
    oracle.vid = None;
    let (bytes, _) = encode(oracle.clone(), &[]);
    assert!(SnapshotReader::new(
        &bytes[..],
        &h.binding,
        ReadPurpose::Loadable,
        Limits::default()
    )
    .is_err());
    SnapshotReader::new(
        &bytes[..],
        &h.binding,
        ReadPurpose::OracleComparison,
        Limits::default(),
    )
    .unwrap()
    .finish()
    .unwrap();
    oracle.vid = h.vid;
    assert!(oracle.validate().is_err());
}

#[test]
fn empty_root_and_compaction_lineage_keep_their_distinct_meaning() {
    let mut root = header(0);
    root.origin = SnapshotOrigin::EmptyRoot { start_block: 0 };
    root.boundary = Boundary {
        block_number: 0,
        block_hash: [0; 32],
    };
    root.sources = SourceSnapshot::from_rows(vec![]).unwrap();
    root.vid.as_mut().unwrap().tables[0].max_vid = -1;
    assert_eq!(root.next_block(), 0);
    let (bytes, root_id) = encode(root.clone(), &[]);
    assert_eq!(read(&bytes, &root.binding).unwrap(), root_id);
    let delta = [0x77; 32];
    let through = advance_lineage(root_id.lineage(), delta);
    assert_ne!(through, initial_lineage(delta));
    let mut compact = header(0);
    compact.origin = SnapshotOrigin::Compaction {
        base_lineage: root_id.lineage(),
        through_lineage: through,
    };
    let (bytes, id) = encode(compact.clone(), &[]);
    assert_eq!(id.lineage(), through);
    assert_ne!(id.lineage(), initial_lineage(id.file_sha256()));
    assert_eq!(read(&bytes, &compact.binding).unwrap(), id);
}

#[test]
fn source_order_hash_is_the_existing_v2_chain_without_truncation() {
    let rows = vec![
        SnapshotSource {
            vid: 3,
            creation_block: 8,
            manifest_idx: 2,
            param: vec![0xab; 20],
        },
        SnapshotSource {
            vid: 9,
            creation_block: 10,
            manifest_idx: 2,
            param: vec![0xcd; 20],
        },
    ];
    let snapshot = SourceSnapshot::from_rows(rows.clone()).unwrap();
    let mut expected = SourceOrder::empty();
    for row in &rows {
        expected
            .append(&Creation {
                ordinal: expected.count,
                source: DataSource {
                    creation_block: row.creation_block,
                    manifest_idx: row.manifest_idx,
                    causality_region: 0,
                    param: hex::encode(&row.param),
                    context: None,
                    done_at: None,
                },
            })
            .unwrap();
    }
    assert_eq!(snapshot.count, 2);
    assert_eq!(snapshot.max_vid, 9);
    assert_eq!(snapshot.order_sha256, expected.sha256);
    assert_eq!(snapshot.rows, rows);
    assert_eq!(
        snapshot.order_sha256,
        "d2842bbad6e9bca70fdccdf3be1cadc25e5964fc41564fdfe2a88a5239ce4527"
    );
    let mut h = header(0);
    h.sources = snapshot;
    h.validate().unwrap();
    h.sources.rows.pop();
    assert!(h.validate().is_err());
    let mut duplicate = rows.clone();
    duplicate[1].param = duplicate[0].param.clone();
    assert!(SourceSnapshot::from_rows(duplicate).is_err());
    let mut reverse = rows;
    reverse.reverse();
    assert!(SourceSnapshot::from_rows(reverse).is_err());
}

#[test]
fn bounds_are_encoded_bytes_and_checked_before_payload_read() {
    struct PrefixOnly {
        data: Cursor<Vec<u8>>,
    }
    impl Read for PrefixOnly {
        fn read(&mut self, buffer: &mut [u8]) -> io::Result<usize> {
            assert!(
                (self.data.position() as usize) < self.data.get_ref().len(),
                "attempted oversized allocation/read"
            );
            self.data.read(buffer)
        }
    }
    let h = header(1);
    let mut data = MAGIC.to_vec();
    data.extend_from_slice(&u32::MAX.to_be_bytes());
    assert!(SnapshotReader::new(
        PrefixOnly {
            data: Cursor::new(data)
        },
        &h.binding,
        ReadPurpose::Loadable,
        Limits::default()
    )
    .is_err());
    assert!(SnapshotWriter::new(
        Vec::new(),
        h.clone(),
        Limits {
            header_bytes: 32,
            ..Limits::default()
        }
    )
    .is_err());
    let (bytes, _) = encode(h.clone(), &[record(&h, "a")]);
    let (_, end) = framed_header(&bytes);
    let mut data = bytes[..end].to_vec();
    data.extend_from_slice(&u32::MAX.to_be_bytes());
    let mut reader = SnapshotReader::new(
        PrefixOnly {
            data: Cursor::new(data),
        },
        &h.binding,
        ReadPurpose::Loadable,
        Limits::default(),
    )
    .unwrap();
    assert!(reader.next_record().is_err());
    assert!(reader.finish().is_err());
    let mut writer = SnapshotWriter::new(
        Vec::new(),
        h.clone(),
        Limits {
            record_bytes: 16,
            ..Limits::default()
        },
    )
    .unwrap();
    assert!(writer.write_record(&record(&h, "a")).is_err());
    assert!(writer.finish().is_err());
}

#[test]
fn noncanonical_unknown_and_duplicate_messagepack_fields_are_refused() {
    let h = header(0);
    let (bytes, _) = encode(h.clone(), &[]);
    let (encoded, _) = framed_header(&bytes);
    // Replace the minimal version=1 with uint8(1).
    let needle = b"\xa7version\x01";
    let offset = encoded
        .windows(needle.len())
        .position(|w| w == needle)
        .unwrap()
        + needle.len()
        - 1;
    let mut wide = encoded[..offset].to_vec();
    wide.extend_from_slice(&[0xcc, 1]);
    wide.extend_from_slice(&encoded[offset + 1..]);
    let variant = replace_header(&bytes, &wide);
    assert!(SnapshotReader::new(
        &variant[..],
        &h.binding,
        ReadPurpose::Loadable,
        Limits::default()
    )
    .is_err());
    for extra in [&b"\xa1x\xc0"[..], &b"\xa7version\x01"[..]] {
        let mut extra_header = encoded.to_vec();
        assert!(extra_header[0] >= 0x80 && extra_header[0] < 0x8f);
        extra_header[0] += 1;
        extra_header.extend_from_slice(extra);
        let variant = replace_header(&bytes, &extra_header);
        assert!(SnapshotReader::new(
            &variant[..],
            &h.binding,
            ReadPurpose::Loadable,
            Limits::default()
        )
        .is_err());
    }
    // Tuple structs are valid MessagePack but never canonical snapshot maps.
    let tuple = rmp_serde::to_vec(&h).unwrap();
    let variant = replace_header(&bytes, &tuple);
    assert!(SnapshotReader::new(
        &variant[..],
        &h.binding,
        ReadPurpose::Loadable,
        Limits::default()
    )
    .is_err());
}

#[test]
fn record_binary_encoding_is_canonical_and_protobuf_cannot_hide_unknown_fields() {
    let h = header(1);
    let rec = record(&h, "a");
    let (bytes, _) = encode(h.clone(), std::slice::from_ref(&rec));
    #[derive(Serialize)]
    struct Arrays<'a> {
        key: &'a Vec<u8>,
        value: &'a Vec<u8>,
    }
    let encoded = rmp_serde::to_vec_named(&Arrays {
        key: &rec.key,
        value: &rec.value,
    })
    .unwrap();
    let (_, end) = framed_header(&bytes);
    let mut variant = bytes[..end].to_vec();
    variant.extend_from_slice(&(encoded.len() as u32).to_be_bytes());
    variant.extend_from_slice(&encoded);
    let mut reader = SnapshotReader::new(
        &variant[..],
        &h.binding,
        ReadPurpose::Loadable,
        Limits::default(),
    )
    .unwrap();
    assert!(reader.next_record().is_err());
    let key = decode_key(&h.binding, &rec.key).unwrap();
    let mut unknown = rec.value.clone();
    unknown.extend_from_slice(&[0x78, 0x01]);
    assert!(StoredEntity::decode(&key, &unknown)
        .unwrap_err()
        .contains("noncanonical"));
    let mut wrong_id = entity(&key);
    wrong_id.fields[0].value.as_mut().unwrap().kind =
        Some(graph_value::Kind::String("wrong".into()));
    assert!(wrong_id.encode(&key).is_err());
    let mut unsorted = entity(&key);
    unsorted.fields.reverse();
    assert!(unsorted.encode(&key).is_err());
    let mut future = rec;
    future.value[9..13].copy_from_slice(&101i32.to_be_bytes());
    let mut writer = SnapshotWriter::new(Vec::new(), h, Limits::default()).unwrap();
    assert!(writer
        .write_record(&future)
        .unwrap_err()
        .contains("after snapshot"));
}

#[test]
fn typed_ids_and_signed_order_are_exact() {
    let h = header(0);
    let ids = vec![
        entity_id::Value::String("α".into()),
        entity_id::Value::Bytes(vec![0, 255]),
        entity_id::Value::Int8(i64::MIN),
        entity_id::Value::Int8(-1),
        entity_id::Value::Int8(0),
        entity_id::Value::Int8(i64::MAX),
    ];
    let mut encoded = vec![];
    for id in ids {
        let k = key(id);
        let bytes = encode_key(&h.binding, &k).unwrap();
        assert_eq!(decode_key(&h.binding, &bytes).unwrap(), k);
        encoded.push(bytes);
    }
    assert!(encoded.windows(2).all(|w| w[0] < w[1]));
    let mut string_only = h.binding;
    string_only.entity_id_policy = EntityIdPolicy::StringOnly;
    assert!(decode_key(&string_only, &encoded[1]).is_err());
    let mut bad = encoded[0].clone();
    bad[0..2].copy_from_slice(&1u16.to_be_bytes());
    assert!(decode_key(&string_only, &bad).is_err());
    assert!(decode_key(&string_only, &[0; 6]).is_err());
}

#[test]
fn streaming_writer_and_reader_need_neither_seek_nor_a_full_snapshot_vec() {
    let mut h = header(10_000);
    h.vid.as_mut().unwrap().tables[0].max_vid = 12;
    let file = tempfile::tempfile().unwrap();
    let mut writer = SnapshotWriter::new(file, h.clone(), Limits::default()).unwrap();
    for i in 0..h.records {
        writer
            .write_record(&record(&h, &format!("{i:08}")))
            .unwrap();
    }
    let (mut file, expected) = writer.finish().unwrap();
    std::io::Seek::rewind(&mut file).unwrap();
    struct ShortReads<R>(R);
    impl<R: Read> Read for ShortReads<R> {
        fn read(&mut self, out: &mut [u8]) -> io::Result<usize> {
            let len = out.len().min(7);
            self.0.read(&mut out[..len])
        }
    }
    let mut reader = SnapshotReader::new(
        ShortReads(file),
        &h.binding,
        ReadPurpose::Loadable,
        Limits::default(),
    )
    .unwrap();
    let mut count = 0;
    while reader.next_record().unwrap().is_some() {
        count += 1;
    }
    assert_eq!(count, 10_000);
    assert_eq!(reader.finish().unwrap(), expected);
}

#[test]
fn io_failure_poisoning_prevents_sealing_partial_streams() {
    struct FailsAfter {
        bytes: usize,
        limit: usize,
    }
    impl Write for FailsAfter {
        fn write(&mut self, b: &[u8]) -> io::Result<usize> {
            if self.bytes == self.limit {
                return Err(io::Error::other("injected write failure"));
            }
            let n = b.len().min(self.limit - self.bytes);
            self.bytes += n;
            Ok(n)
        }
        fn flush(&mut self) -> io::Result<()> {
            Ok(())
        }
    }
    let h = header(1);
    let (bytes, _) = encode(h.clone(), &[record(&h, "a")]);
    let (_, end) = framed_header(&bytes);
    let mut writer = SnapshotWriter::new(
        FailsAfter {
            bytes: 0,
            limit: end + 10,
        },
        h.clone(),
        Limits::default(),
    )
    .unwrap();
    assert!(writer.write_record(&record(&h, "a")).is_err());
    assert!(writer.finish().is_err());
}

#[test]
fn more_than_ten_thousand_sources_roundtrip_with_an_encoded_byte_ceiling() {
    let mut h = header(0);
    h.sources = SourceSnapshot::from_rows(
        (0..10_001)
            .map(|i: i32| {
                let mut param = vec![0; 20];
                param[16..].copy_from_slice(&i.to_be_bytes());
                SnapshotSource {
                    vid: i,
                    creation_block: 10,
                    manifest_idx: 2,
                    param,
                }
            })
            .collect(),
    )
    .unwrap();
    let (bytes, identity) = encode(h.clone(), &[]);
    let (encoded, _) = framed_header(&bytes);
    let exact = Limits {
        header_bytes: encoded.len() as u32,
        ..Limits::default()
    };
    let r = SnapshotReader::new(&bytes[..], &h.binding, ReadPurpose::Loadable, exact).unwrap();
    assert_eq!(r.header().sources.rows.len(), 10_001);
    assert_eq!(r.header().sources, h.sources);
    assert_eq!(r.finish().unwrap(), identity);
    let lower = Limits {
        header_bytes: exact.header_bytes - 1,
        ..exact
    };
    assert!(SnapshotReader::new(&bytes[..], &h.binding, ReadPurpose::Loadable, lower).is_err());
    assert!(SnapshotWriter::new(Vec::new(), h, lower).is_err());
}

#[test]
fn inconsistent_header_metadata_cannot_be_written_or_trusted() {
    let h = header(0);
    let mut variants = vec![];
    let mut bad = h.clone();
    bad.boundary.block_hash = [0; 32];
    variants.push(bad);
    let mut bad = h.clone();
    bad.boundary.block_number += 1;
    variants.push(bad);
    let mut bad = h.clone();
    bad.vid = None;
    variants.push(bad);
    let mut bad = h.clone();
    bad.vid.as_mut().unwrap().tables.clear();
    variants.push(bad);
    let mut bad = h.clone();
    bad.vid.as_mut().unwrap().tables[0].max_vid = -2;
    variants.push(bad);
    let mut bad = h.clone();
    bad.sources.max_vid += 1;
    variants.push(bad);
    let mut bad = h.clone();
    bad.sources.count += 1;
    variants.push(bad);
    let mut bad = h.clone();
    bad.entity_count = Some(-1);
    variants.push(bad);
    let mut bad = h.clone();
    bad.poi.region_digest = Some(vec![1; 32]);
    variants.push(bad);
    let mut bad = h.clone();
    bad.period_max.insert("Unknown".into(), 9);
    variants.push(bad);
    let mut bad = h.clone();
    bad.binding.type_ordinals.push("Another".into());
    variants.push(bad);
    let mut bad = h.clone();
    bad.sources.rows[0].param.pop();
    variants.push(bad);
    let mut bad = h.clone();
    bad.binding.descriptor_sha256 = "FF".repeat(32);
    variants.push(bad);
    for bad in variants {
        assert!(bad.validate().is_err());
        assert!(SnapshotWriter::new(Vec::new(), bad, Limits::default()).is_err());
    }
    let above_format_max = Limits {
        header_bytes: Limits::default().header_bytes + 1,
        ..Limits::default()
    };
    assert!(SnapshotWriter::new(Vec::new(), h, above_format_max).is_err());
}
