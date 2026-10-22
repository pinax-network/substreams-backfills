use aerodrome_decimal_audit::{classify_raw, scan, Request, MAX_WITNESSES};
use aerodrome_slipstream_reducer::pb;
use backfill_common::clock::{self, Frame, FrameKind};
use graph_numerics::{bigint, BigInt};
use prost::Message;
use sha2::{Digest, Sha256};

const INITIAL: u64 = 13_843_704;
fn block(count: u32, amount: &BigInt) -> pb::ExtractorBlock {
    let signed = amount.to_signed_bytes_be();
    let mut data = vec![if amount < &BigInt::from(0) { 255 } else { 0 }; 32];
    data[32 - signed.len()..].copy_from_slice(&signed);
    for value in [1u64, 1, 1, 0] {
        let mut word = [0; 32];
        word[24..].copy_from_slice(&value.to_be_bytes());
        data.extend_from_slice(&word);
    }
    pb::ExtractorBlock {
        number: INITIAL + 1,
        hash: vec![2; 32],
        parent_hash: vec![1; 32],
        timestamp: 1700000000,
        contract: "pinax.aerodrome.slipstream.base.extractor/v1".into(),
        firehose_block_version: 4,
        receipt_log_count: count,
        audit: Some(pb::ExtractorAudit::default()),
        calls: Some(pb::CallAnswers::default()),
        transactions: if count == 0 {
            vec![]
        } else {
            vec![pb::Transaction {
                hash: vec![3; 32],
                from: vec![4; 20],
                gas_price: Some(vec![]),
                ..Default::default()
            }]
        },
        candidates: (0..count)
            .map(|i| pb::CandidateLog {
                wave: 0,
                source_trigger_order: i,
                log_index: i,
                tx: 0,
                address: vec![5; 20],
                topics: vec![
                    hex::decode("c42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67")
                        .unwrap(),
                    vec![0; 32],
                    vec![0; 32],
                ],
                data: data.clone(),
                log_ordinal: u64::from(i) + 1,
                source: pb::DataSourceKind::Pool as i32,
                host_order_key: 2 + INITIAL * (1 << 24),
                abi_decoded: true,
            })
            .collect(),
        ..Default::default()
    }
}
fn bytes(block: &pb::ExtractorBlock) -> Vec<u8> {
    let mut bytes = vec![];
    clock::write_frame(
        &mut bytes,
        &Frame {
            kind: FrameKind::Observed,
            block_number: block.number,
            block_hash: block.hash.clone().try_into().unwrap(),
            payload: block.encode_to_vec(),
        },
    )
    .unwrap();
    bytes
}
fn request(bytes: &[u8]) -> Request {
    Request {
        format: "pinax.aerodrome.qn2-extractor-request/v1".into(),
        input: "/unused/synthetic.bcf1".into(),
        input_sha256: hex::encode(Sha256::digest(bytes)),
        input_bytes: bytes.len() as u64,
        from_block: INITIAL + 1,
        to_block: INITIAL + 1,
        parent_hash: "01".repeat(32),
        head_hash: "02".repeat(32),
    }
}
#[test]
fn exact_threshold_neighbors_and_large_fixed_point_are_distinguished() {
    let threshold = (BigInt::from(1) << 116) * BigInt::from(1000);
    for (raw, accepted) in [
        (-&threshold + BigInt::from(1), true),
        (-&threshold, false),
        (-&threshold - BigInt::from(1), false),
        (threshold, true),
        (
            bigint::parse("-10000000000000000000000000000000000000000").unwrap(),
            true,
        ),
    ] {
        let result = classify_raw(&raw).unwrap();
        assert_eq!(result.accepted_by_block_changes_v1, accepted, "{raw}");
        assert_eq!(result.fixed_point, accepted);
    }
}
#[test]
fn shared_abi_and_exact_numeric_classification_produce_bounded_diagnostic_witnesses() {
    let b = block(
        70,
        &bigint::parse("-85070591730234615865843651857942052863").unwrap(),
    );
    let encoded = bytes(&b);
    let report = scan(encoded.as_slice(), request(&encoded)).unwrap();
    assert_eq!(report.decoded_swaps, 70);
    assert_eq!(report.negative_amounts, 70);
    assert_eq!(report.potential_zero_decimal_refusals, 70);
    assert_eq!(report.witnesses.len(), MAX_WITNESSES);
    assert_eq!(report.witnesses_omitted, 6);
    assert_eq!(
        report.witnesses[0].zero_decimal_crossing.coefficient,
        "-85070591730234615865843651857942052"
    );
    assert_eq!(report.witnesses[0].zero_decimal_crossing.scale, -3);
    assert_eq!(
        report.witnesses[0].decimal_provenance,
        "unresolved_mapping_token_decimals"
    );
    assert!(
        !report.full_range_qn2_closed
            && !report.package_origin_verified
            && !report.producer_exit_verified
    );
    let fewer = bytes(&block(
        69,
        &bigint::parse("-85070591730234615865843651857942052863").unwrap(),
    ));
    assert_ne!(
        scan(fewer.as_slice(), request(&fewer))
            .unwrap()
            .witness_inventory_sha256,
        report.witness_inventory_sha256
    );
}
#[test]
fn eof_identity_canonical_payload_and_bounds_fail_closed() {
    let b = block(0, &BigInt::from(0));
    let good = bytes(&b);
    let pin = request(&good);
    assert_eq!(
        scan(good.as_slice(), pin.clone()).unwrap().observed_blocks,
        1
    );
    for altered in [
        good[..good.len() - 1].to_vec(),
        [good.clone(), vec![0]].concat(),
        vec![],
    ] {
        assert!(scan(altered.as_slice(), pin.clone()).is_err());
    }
    for (field, value) in [
        ("input_sha256", "03".repeat(32)),
        ("parent_hash", "03".repeat(32)),
        ("head_hash", "03".repeat(32)),
    ] {
        let mut bad = serde_json::to_value(&pin).unwrap();
        bad[field] = value.into();
        assert!(scan(good.as_slice(), serde_json::from_value(bad).unwrap()).is_err());
    }
    let mut bad = pin.clone();
    bad.to_block += 1;
    assert!(scan(good.as_slice(), bad).is_err());
    let mut bad = pin.clone();
    bad.to_block += 100_000;
    assert!(bad.validate().is_err());
    let mut bad = good.clone();
    bad[4] = 2;
    assert!(scan(bad.as_slice(), request(&bad)).is_err());
    let mut b = b.clone();
    b.parent_hash = vec![9; 32];
    let bad = bytes(&b);
    assert!(scan(bad.as_slice(), request(&bad)).is_err());
    let mut frame = clock::read_frame(&mut good.as_slice(), 1024)
        .unwrap()
        .unwrap();
    frame.payload.extend_from_slice(&[0xa0, 0x06, 0x01]);
    let mut bad = vec![];
    clock::write_frame(&mut bad, &frame).unwrap();
    assert!(scan(bad.as_slice(), request(&bad)).is_err());
}
