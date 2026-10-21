use backfill_common::{
    decode_canonical_block_changes, decode_canonical_in_band_block_changes,
    descriptor::GRAPH_NODE_COMMIT,
    encode_canonical_in_band_block_changes,
    pb::pinax::graph::backfill::{v1, v2},
    validate_in_band_block_changes, BlockChangesCompatibility,
};
use prost::Message;
use serde_json::json;
use sha2::{Digest, Sha256};

fn descriptor(policy: &str) -> BlockChangesCompatibility {
    BlockChangesCompatibility::from_descriptor(&serde_json::to_vec(&json!({
        "contract":"pinax.graph.backfill.block-changes/v1", "descriptor_version":2,
        "network":"base", "expected_poi_causality_region":"ethereum/base", "deterministic_error_policy":policy,
        "deployment":"test", "spec_version":"1.2.0", "start_block":0,
        "graph_node":{"version":"0.44.0", "commit":GRAPH_NODE_COMMIT, "poi_version":"fast"},
        "storage_profile":{"entity_types":["Pool"]},
        "data_sources":{"transport":"in_band_v1", "templates":[{"name":"Pool", "manifest_idx":2, "param":"address20"}]},
        "entity_retention":{"version":1,"default":"persistent","types":{},"evidence":[]},
        "producer_contract":{"kind":"mapping_host_oracle","repository":"pinax-network/substreams-backfills","source_closure_sha256":"11".repeat(32),"bundle_lock_sha256":"22".repeat(32)}
    })).unwrap()).unwrap()
}

fn changes(c: &BlockChangesCompatibility) -> v2::BlockChanges {
    v2::BlockChanges {
        contract: "pinax.graph.backfill.block-changes/v1".into(),
        compatibility_id: c.to_vec(),
        block_number: 42,
        block_hash: vec![1; 32],
        mapping_triggered: true,
        triggered_poi_causality_regions: vec!["ethereum/base".into()],
        operations: vec![],
        deterministic_error_policy: c.deterministic_error_policy() as i32,
        created_data_sources: vec![v2::CreatedDataSource {
            ordinal: 0,
            manifest_idx: 2,
            template: "Pool".into(),
            handler_group_order: 0,
            param: vec![0xab; 20],
            context_json: None,
        }],
    }
}

fn error(group: u64) -> v1::EntityOperation {
    v1::EntityOperation {
        operation_index: 0,
        handler_group_order: group,
        source_trigger_order: 0,
        poi_causality_region: Some("ethereum/base".into()),
        handler_order: 0,
        source_causality_region: 0,
        operation: Some(v1::entity_operation::Operation::DeterministicError(
            v1::DeterministicError { redacted_events: 0 },
        )),
    }
}

#[test]
fn extended_golden_and_legacy_source_closure_are_stable() {
    let c = descriptor("non_fatal");
    let block = changes(&c);
    let encoded = encode_canonical_in_band_block_changes(&block, &c).unwrap();
    assert_eq!(
        decode_canonical_in_band_block_changes(&encoded, &c).unwrap(),
        block
    );
    // Field 9's message follows the unchanged 1..8 wire prefix.
    assert!(encoded.ends_with(
        &hex::decode("4a1e10021a04506f6f6c2a14abababababababababababababababababababab").unwrap()
    ));
    assert!(decode_canonical_block_changes(&encoded, &c).is_err());
    assert_eq!(
        hex::encode(Sha256::digest(include_bytes!(
            "../proto/block_changes.proto"
        ))),
        "7f9888a44138d7917d2addf332e5f04cf7980c6d3f51fa10248f6ecbab07fdee"
    );
    assert_eq!(
        hex::encode(Sha256::digest(include_bytes!(
            "../src/pb/pinax.graph.backfill.v1.rs"
        ))),
        "6cbb2a3b1dadb90c5898a69b3feeb886e3fc3ca31edc7716ed545892d5ce3f0e"
    );
}

#[test]
fn legacy_golden_roundtrips_through_extended_empty_creation_view() {
    let c = BlockChangesCompatibility::from_descriptor(include_bytes!(
        "../fixtures/block-changes-v1/compatibility.json"
    ))
    .unwrap();
    let text =
        std::str::from_utf8(include_bytes!("../fixtures/block-changes-v1/golden.pb.hex")).unwrap();
    let bytes = hex::decode(text.split_whitespace().collect::<String>()).unwrap();
    let extended = decode_canonical_in_band_block_changes(&bytes, &c).unwrap();
    assert!(extended.created_data_sources.is_empty());
    assert_eq!(
        encode_canonical_in_band_block_changes(&extended, &c).unwrap(),
        bytes
    );
    assert_eq!(
        decode_canonical_block_changes(&bytes, &c)
            .unwrap()
            .encode_to_vec(),
        bytes
    );
}

#[test]
fn capability_order_template_context_and_failed_group_refusals() {
    let c = descriptor("non_fatal");
    let b = changes(&c);
    let mut variants = Vec::new();
    let mut x = b.clone();
    x.mapping_triggered = false;
    variants.push(x);
    let mut x = b.clone();
    x.triggered_poi_causality_regions.clear();
    variants.push(x);
    let mut x = b.clone();
    x.created_data_sources[0].ordinal = 1;
    variants.push(x);
    let mut x = b.clone();
    x.created_data_sources[0].manifest_idx = 3;
    variants.push(x);
    let mut x = b.clone();
    x.created_data_sources[0].template = "Unknown".into();
    variants.push(x);
    let mut x = b.clone();
    x.created_data_sources[0].param.pop();
    variants.push(x);
    let mut x = b.clone();
    x.created_data_sources[0].context_json = Some(String::new());
    variants.push(x);
    let mut x = b.clone();
    let mut second = x.created_data_sources[0].clone();
    second.ordinal = 1;
    x.created_data_sources.push(second);
    variants.push(x);
    let mut x = b.clone();
    x.operations.push(error(0));
    variants.push(x);
    let mut x = b.clone();
    x.block_hash.fill(0);
    x.created_data_sources.clear();
    variants.push(x);
    let mut x = b.clone();
    x.created_data_sources[0].handler_group_order = 1;
    let mut second = x.created_data_sources[0].clone();
    second.ordinal = 1;
    second.param[0] = 0;
    second.handler_group_order = 0;
    x.created_data_sources.push(second);
    variants.push(x);
    for x in variants {
        assert!(
            validate_in_band_block_changes(&x, &c).is_err(),
            "accepted {x:?}"
        );
    }
    let legacy = BlockChangesCompatibility::from_descriptor(include_bytes!(
        "../fixtures/block-changes-v1/compatibility.json"
    ))
    .unwrap();
    let mut x = b.clone();
    x.compatibility_id = legacy.to_vec();
    assert!(validate_in_band_block_changes(&x, &legacy).is_err());
    let mut x = b.clone();
    x.operations.push(error(1));
    validate_in_band_block_changes(&x, &c).unwrap();
    let fatal = descriptor("fatal");
    x.compatibility_id = fatal.to_vec();
    x.deterministic_error_policy = v1::DeterministicErrorPolicy::Fatal as i32;
    assert!(validate_in_band_block_changes(&x, &fatal).is_err());
    x.created_data_sources.clear();
    validate_in_band_block_changes(&x, &fatal).unwrap();
}

#[test]
fn extended_decoder_refuses_unknown_nonminimal_and_duplicate_fields() {
    let c = descriptor("non_fatal");
    let bytes = encode_canonical_in_band_block_changes(&changes(&c), &c).unwrap();
    for suffix in [&[0x50, 1][..], &[0x18, 42][..]] {
        let mut bad = bytes.clone();
        bad.extend_from_slice(suffix);
        assert!(decode_canonical_in_band_block_changes(&bad, &c).is_err());
    }
    let mut bad = bytes.clone();
    let i = bad.iter().position(|b| *b == 0x4a).unwrap();
    bad[i + 1] = 0x9e;
    bad.insert(i + 2, 0);
    assert!(decode_canonical_in_band_block_changes(&bad, &c).is_err());
}
