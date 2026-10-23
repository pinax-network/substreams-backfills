use super::*;
use serde_json::{json, Value};
fn cassette() -> Value {
    serde_json::from_slice(include_bytes!(
        "../../fixtures/reference-first-pool.cassette.json"
    ))
    .unwrap()
}
fn parsed(value: &Value) -> Cassette {
    Cassette::from_json(&serde_json::to_vec(value).unwrap()).unwrap()
}
fn raw() -> Frame {
    let bytes = std::fs::read(
        std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../aerodrome-slipstream-base/fixtures/blocks/base/13899663.pb"),
    )
    .expect("hydrate locked raw block");
    assert_eq!(
        hex::encode(Sha256::digest(&bytes)),
        "5ac312712fef494a8c03f62c0987bba3339c5f693187e5f272467eee06af59ce"
    );
    let b = eth::Block::decode(bytes.as_slice()).unwrap();
    Frame {
        kind: FrameKind::Observed,
        block_number: b.number,
        block_hash: b.hash.try_into().unwrap(),
        payload: bytes,
    }
}
fn first(value: &Value) -> ReferenceExtractor {
    let mut r = ReferenceExtractor::new(parsed(value), 13899664).unwrap();
    // Bounded fixture-only test: the actual full M1 path cannot skip R0.
    r.next = 13899663;
    r
}
#[test]
fn first_pool_has_exact_order_and_all_independent_call_values() {
    let mut r = first(&cassette());
    let frame = r.process(raw()).unwrap();
    r.finish().unwrap();
    assert_eq!(r.compared_calls(), 12);
    let got = p::ExtractorBlock::decode(frame.payload.as_slice()).unwrap();
    let expected = p::ExtractorBlock::decode(
        include_bytes!("../../fixtures/first-pool-extractor.pb").as_slice(),
    )
    .unwrap();
    assert_eq!(got, expected);
    assert_eq!(
        got.candidates
            .iter()
            .map(|c| c.log_index)
            .collect::<Vec<_>>(),
        vec![172, 177, 178, 171, 176]
    );
}
#[test]
fn storage_disagreement_or_wrong_hash_poison_instead_of_overriding() {
    for wrong_hash in [false, true] {
        let mut c = cassette();
        let entry = c["entries"]
            .as_array_mut()
            .unwrap()
            .iter_mut()
            .find(|e| e["function"] == "ticks(int24)")
            .unwrap();
        if wrong_hash {
            entry["block_hash"] = json!(format!("0x{}", "11".repeat(32)));
        } else {
            let mut data = hex::decode(
                entry["retval"]["data"]
                    .as_str()
                    .unwrap()
                    .trim_start_matches("0x"),
            )
            .unwrap();
            data[127] = 99;
            entry["retval"]["data"] = json!(format!("0x{}", hex::encode(data)));
        }
        let mut r = first(&c);
        let err = r.process(raw()).unwrap_err();
        assert!(
            err.0.contains(if wrong_hash {
                "block hash"
            } else {
                "consumed ABI word 3 differs"
            }),
            "{err}"
        );
        assert!(r.process(raw()).unwrap_err().0.contains("poisoned"));
        assert!(r.finish().is_err());
    }
}
#[test]
fn missing_metadata_group_duplicate_and_ambiguous_null_are_refused() {
    let mut c = cassette();
    c["entries"]
        .as_array_mut()
        .unwrap()
        .retain(|e| e["function"] != "decimals()");
    assert!(first(&c)
        .process(raw())
        .unwrap_err()
        .0
        .contains("partial ERC20"));
    let mut c = cassette();
    let duplicate = c["entries"][0].clone();
    c["entries"].as_array_mut().unwrap().push(duplicate);
    assert!(Cassette::from_json(&serde_json::to_vec(&c).unwrap()).is_err());
    let mut c = cassette();
    for e in c["entries"].as_array_mut().unwrap() {
        if e["function"] == "name()" {
            e["retval"] = json!({"kind":"null"});
        }
    }
    assert!(first(&c)
        .process(raw())
        .unwrap_err()
        .0
        .contains("failed/empty provenance"));
}
#[test]
fn extra_get_pool_probe_uses_registry_and_is_still_verified() {
    let cfg = Config::parse(PARAMS).unwrap();
    let mut c = cassette();
    let key = aerodrome_extractor_core::calls::CallKey::GetPool {
        a: [1; 20],
        b: [2; 20],
        ts: 100,
    };
    c["entries"].as_array_mut().unwrap().push(json!({"block_number":13899663,"block_hash":format!("0x{}",hex::encode(raw().block_hash)),"address":format!("0x{}",hex::encode(cfg.factory)),"calldata":format!("0x{}",hex::encode(key.calldata().unwrap())),"contract":"Factory","function":"getPool(address,address,int24)","retval":{"kind":"value","data":format!("0x{}","00".repeat(32))}}));
    let mut r = first(&c);
    let out = r.process(raw()).unwrap();
    assert_eq!(r.compared_calls(), 13);
    assert_eq!(
        p::ExtractorBlock::decode(out.payload.as_slice())
            .unwrap()
            .calls
            .unwrap()
            .get_pool
            .len(),
        2
    );
    c["entries"].as_array_mut().unwrap().last_mut().unwrap()["retval"]["data"] =
        json!(format!("0x{}01", "00".repeat(31)));
    assert!(first(&c)
        .process(raw())
        .unwrap_err()
        .0
        .contains("consumed ABI word 0 differs"));
}
#[test]
fn synthetic_gap_wrong_parent_and_early_finish_are_refused() {
    let empty =
        json!({"schema":"pinax.substreams-backfills.mapping-host.cassette/v1","entries":[]});
    let mut r = ReferenceExtractor::new(parsed(&empty), INITIAL_BLOCK + 1).unwrap();
    assert!(r.finish().is_err());
    assert!(r.process(raw()).unwrap_err().0.contains("identity/range"));
    let mut r = first(&cassette());
    let mut frame = raw();
    frame.kind = FrameKind::SyntheticRangeFill;
    assert!(r.process(frame).unwrap_err().0.contains("identity/range"));
    let mut r = first(&cassette());
    r.parent = Some([4; 32]);
    assert!(r.process(raw()).unwrap_err().0.contains("parent chain"));
}

/// Early diagnostic only: intentionally starts at the first pool with empty
/// state, using the separately established empty R0 oracle checkpoint. It does
/// not qualify raw-capture EOF, root carry, or the complete M1 range.
#[test]
#[ignore = "requires privately captured raw R1, retained cassette and Graph Node oracle"]
fn early_r1_diagnostic_against_actual_graph_node() {
    use crate::{
        identity::{build_descriptor, InputBinding, OUTPUT_MODULE, OUTPUT_TYPE},
        input::validate_block,
        runner::MemoryRunner,
        state::MemoryBackend,
    };
    use backfill_common::{
        clock, descriptor::ExtractorIdentity, pb::pinax::graph::backfill::v2::BlockChanges,
        state_snapshot::Boundary,
    };
    use std::io::BufReader;
    let mut c: Value = serde_json::from_slice(
        &std::fs::read(std::env::var("AERODROME_DIAGNOSTIC_CASSETTE").unwrap()).unwrap(),
    )
    .unwrap();
    let stop = std::env::var("AERODROME_DIAGNOSTIC_STOP")
        .ok()
        .map(|s| s.parse::<u64>().unwrap())
        .unwrap_or(13_900_000);
    c["entries"]
        .as_array_mut()
        .unwrap()
        .retain(|e| e["block_number"].as_u64().unwrap() < stop);
    let mut reference = ReferenceExtractor::new(parsed(&c), stop).unwrap();
    reference.next = 13_899_663;
    let mut raw = BufReader::new(
        std::fs::File::open(std::env::var("AERODROME_DIAGNOSTIC_RAW").unwrap()).unwrap(),
    );
    let mut oracle = BufReader::new(
        std::fs::File::open(std::env::var("AERODROME_DIAGNOSTIC_ORACLE").unwrap()).unwrap(),
    );
    let extractor = ExtractorIdentity {
        spkg_sha256: "11".repeat(32),
        module: OUTPUT_MODULE.into(),
        module_hash: "22".repeat(20),
        output_type: OUTPUT_TYPE.into(),
        initial_block: INITIAL_BLOCK,
    };
    let descriptor = build_descriptor(&extractor, &"33".repeat(20), true).unwrap();
    let binding =
        InputBinding::new(&descriptor, Sha256::digest(&descriptor).into(), &extractor).unwrap();
    let mut runner: Option<MemoryRunner> = None;
    let mut parent = None;
    let mut raw_digest = Sha256::new();
    let mut oracle_digest = Sha256::new();
    let mut handlers = 0;
    let mut per_handler = BTreeMap::<String, u64>::new();
    for number in 13_899_663..stop {
        let frame = clock::read_frame(&mut raw, clock::MAX_PAYLOAD_LEN)
            .unwrap()
            .unwrap();
        let mut encoded = vec![];
        clock::write_frame(&mut encoded, &frame).unwrap();
        raw_digest.update(encoded);
        let block = eth::Block::decode(frame.payload.as_slice()).unwrap();
        let this_parent: [u8; 32] = block.header.unwrap().parent_hash.try_into().unwrap();
        if runner.is_none() {
            let backend = MemoryBackend::from_images(
                &binding,
                Boundary {
                    block_number: number - 1,
                    block_hash: this_parent,
                },
                BTreeMap::new(),
                BTreeMap::new(),
            )
            .unwrap();
            runner = Some(MemoryRunner::new(binding.clone(), backend).unwrap());
            parent = Some(this_parent);
        }
        let input = reference
            .process(frame)
            .unwrap_or_else(|e| panic!("reference block {number}: {e}"));
        let actual = runner
            .as_mut()
            .unwrap()
            .process(&validate_block(&input, parent.unwrap()).unwrap())
            .unwrap_or_else(|e| panic!("native block {number}: {e}"));
        handlers += actual
            .candidates()
            .iter()
            .filter(|c| matches!(c.outcome, crate::runner::CandidateOutcome::Committed { .. }))
            .count();
        for candidate in actual.candidates() {
            if matches!(
                candidate.outcome,
                crate::runner::CandidateOutcome::Committed { .. }
            ) {
                *per_handler
                    .entry(candidate.handler.clone().unwrap())
                    .or_default() += 1;
            }
        }
        let expected = clock::read_frame(&mut oracle, clock::MAX_PAYLOAD_LEN)
            .unwrap()
            .unwrap();
        let mut encoded = vec![];
        clock::write_frame(&mut encoded, &expected).unwrap();
        oracle_digest.update(encoded);
        assert_eq!(actual.frame().block_number, expected.block_number);
        assert_eq!(actual.frame().block_hash, expected.block_hash);
        let mut got = BlockChanges::decode(actual.frame().payload.as_slice()).unwrap();
        let mut want = BlockChanges::decode(expected.payload.as_slice()).unwrap();
        got.compatibility_id.clear();
        want.compatibility_id.clear();
        assert_eq!(got, want, "whole envelope block {number}");
        parent = Some(input.block_hash);
    }
    reference.finish().unwrap();
    if let Ok(path) = std::env::var("AERODROME_DIAGNOSTIC_RECEIPT") {
        let receipt = json!({"schema":"aerodrome-reference-early-diagnostic/v1","scope":"test-only first-pool empty seed; not root M1 or capture completion","from":13899663,"to_exclusive":stop,"blocks":stop-13899663,"committed_handlers":handlers,"per_handler":per_handler,"compared_cassette_calls":reference.compared_calls(),"raw_prefix_bcf1_sha256":hex::encode(raw_digest.finalize()),"oracle_prefix_bcf1_sha256":hex::encode(oracle_digest.finalize()),"comparison":"entire canonical v2 envelope; compatibility ID only masked","raw_capture_eof_qualified":false});
        let file = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(path)
            .unwrap();
        serde_json::to_writer_pretty(file, &receipt).unwrap();
    }
    eprintln!(
        "diagnostic {} blocks: {handlers} committed handlers; {} cassette calls matched; per handler {per_handler:?}",
        stop-13_899_663,
        reference.compared_calls()
    );
}

#[test]
fn concatenated_blocks_and_repeated_identity_fields_are_refused() {
    let original = raw();
    let mut bad = original.clone();
    bad.payload.extend(&original.payload);
    assert!(first(&cassette())
        .process(bad)
        .unwrap_err()
        .0
        .contains("concatenated"));
    let mut bad = original;
    bad.payload.splice(0..0, [8, 4]);
    assert!(first(&cassette())
        .process(bad)
        .unwrap_err()
        .0
        .contains("concatenated"));
}
