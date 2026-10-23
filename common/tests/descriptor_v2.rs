use backfill_common::{
    descriptor::{BlockLocalProof, PeriodId, RetentionClass, GRAPH_NODE_COMMIT},
    BlockChangesCompatibility,
};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

fn descriptor() -> Value {
    json!({
        "contract": "pinax.graph.backfill.block-changes/v1",
        "descriptor_version": 2,
        "deterministic_error_policy": "non_fatal",
        "network": "base",
        "expected_poi_causality_region": "ethereum/base",
        "deployment": "test-deployment",
        "spec_version": "1.2.0",
        "start_block": 13843704,
        "graph_node": {"version": "0.44.0", "commit": GRAPH_NODE_COMMIT, "poi_version": "fast"},
        "storage_profile": {"entity_types": ["Bundle", "PoolDayData", "PositionSnapshot", "Swap"]},
        "data_sources": {"transport": "in_band_v1", "templates": [
            {"name": "Pool", "manifest_idx": 2, "param": "address20"}
        ]},
        "entity_retention": {
            "version": 1, "default": "persistent",
            "types": {
                "Swap": {"class": "block_local", "proof": {"kind": "derived_from_transaction"}},
                "PositionSnapshot": {"class": "block_local", "proof": {"kind": "block_number_suffix", "separator": "#"}},
                "PoolDayData": {"class": "period_scoped", "period_id": {"kind": "suffix_after_last", "separator": "-"}}
            },
            "evidence": [
                {"kind": "store_get_inventory", "reference": "evidence/reads.json", "sha256": "11".repeat(32)},
                {"kind": "id_scheme_inventory", "reference": "evidence/ids.json", "sha256": "22".repeat(32)}
            ]
        },
        "producer_contract": {
            "kind": "native_block_changes_reducer",
            "reducer": {"repository": "pinax-network/substreams-backfills", "commit": "33".repeat(20)},
            "extractor": {"spkg_sha256": "44".repeat(32), "module": "map_extractor_block",
                "module_hash": "55".repeat(20), "output_type": "proto:pinax.aerodrome.slipstream.base.v1.ExtractorBlock",
                "initial_block": 13843704}
        }
    })
}

fn parse(
    value: &Value,
) -> Result<BlockChangesCompatibility, backfill_common::CompatibilityDescriptorError> {
    BlockChangesCompatibility::from_descriptor(&serde_json::to_vec(value).unwrap())
}

#[test]
fn v1_identity_and_semantics_are_unchanged() {
    let bytes = include_bytes!("../fixtures/block-changes-v1/compatibility.json");
    let compatibility = BlockChangesCompatibility::from_descriptor(bytes).unwrap();
    assert_eq!(
        hex::encode(compatibility.id()),
        "e64c176c43a2490a19f1d4996b2721c637050d16362816785c3e80892e699099"
    );
    assert!(compatibility.capabilities().is_none());
}

#[test]
fn v2_binds_raw_identity_and_exposes_typed_capabilities() {
    let value = descriptor();
    let compact = serde_json::to_vec(&value).unwrap();
    let pretty = serde_json::to_vec_pretty(&value).unwrap();
    let compatibility = parse(&value).unwrap();
    assert_eq!(
        compatibility.id().as_slice(),
        Sha256::digest(&compact).as_slice()
    );
    let other = BlockChangesCompatibility::from_descriptor(&pretty).unwrap();
    assert_ne!(compatibility.id(), other.id());
    let capabilities = compatibility.capabilities().unwrap();
    assert_eq!(capabilities.start_block, 13843704);
    assert_eq!(capabilities.data_sources.templates[0].manifest_idx, 2);
    assert_eq!(
        capabilities.entity_retention.class("Bundle"),
        &RetentionClass::Persistent
    );
    assert_eq!(
        capabilities.retention_sha256(),
        other.capabilities().unwrap().retention_sha256()
    );
}

#[test]
fn retention_identity_is_canonical_but_changes_with_semantics_or_evidence() {
    let mut value = descriptor();
    let original = parse(&value)
        .unwrap()
        .capabilities()
        .unwrap()
        .retention_sha256();
    value["entity_retention"]["evidence"]
        .as_array_mut()
        .unwrap()
        .reverse();
    assert_eq!(
        original,
        parse(&value)
            .unwrap()
            .capabilities()
            .unwrap()
            .retention_sha256()
    );
    value["entity_retention"]["evidence"][0]["sha256"] = json!("ab".repeat(32));
    assert_ne!(
        original,
        parse(&value)
            .unwrap()
            .capabilities()
            .unwrap()
            .retention_sha256()
    );
    value = descriptor();
    value["entity_retention"]["types"]["Swap"] = json!({"class": "persistent"});
    assert_ne!(
        original,
        parse(&value)
            .unwrap()
            .capabilities()
            .unwrap()
            .retention_sha256()
    );
}

#[test]
fn malformed_or_unproven_capabilities_fail_closed() {
    let mutations = [
        ("/descriptor_version", json!(3)),
        ("/deployment", json!("")),
        ("/spec_version", json!("1.2")),
        ("/start_block", json!(2147483648u64)),
        ("/graph_node/commit", json!("66".repeat(20))),
        ("/graph_node/poi_version", json!("unknown")),
        ("/storage_profile/entity_types", json!(["Swap", "Bundle"])),
        ("/storage_profile/entity_types", json!(["Bundle", "Bundle"])),
        ("/storage_profile/entity_types", json!([])),
        ("/storage_profile/entity_types", json!(["1Invalid"])),
        ("/data_sources/transport", json!("companion_v2")),
        ("/data_sources/transport", json!("none")),
        ("/data_sources/templates/0/param", json!("bytes")),
        ("/entity_retention/version", json!(2)),
        ("/entity_retention/default", json!("block_local")),
        ("/entity_retention/types/Swap/class", json!("write_once")),
        ("/entity_retention/evidence", json!([])),
        (
            "/entity_retention/evidence/0/sha256",
            json!("AA".repeat(32)),
        ),
        (
            "/entity_retention/types/PositionSnapshot/proof/separator",
            json!(""),
        ),
        ("/producer_contract/kind", json!("unproven")),
        ("/producer_contract/reducer/commit", json!("main")),
        (
            "/producer_contract/extractor/module_hash",
            json!("11".repeat(32)),
        ),
        ("/producer_contract/extractor/output_type", json!("proto:")),
        (
            "/producer_contract/extractor/initial_block",
            json!(13843705),
        ),
    ];
    for (path, replacement) in mutations {
        let mut value = descriptor();
        *value.pointer_mut(path).unwrap() = replacement;
        assert!(parse(&value).is_err(), "accepted malformed {path}");
    }
    for field in [
        "deployment",
        "spec_version",
        "start_block",
        "graph_node",
        "storage_profile",
        "data_sources",
        "entity_retention",
        "producer_contract",
    ] {
        let mut value = descriptor();
        value.as_object_mut().unwrap().remove(field);
        assert!(parse(&value).is_err(), "accepted missing {field}");
    }
    let mut value = descriptor();
    value["entity_retention"]["types"]["Undeclared"] = json!({"class": "persistent"});
    assert!(parse(&value).is_err());
    let mut value = descriptor();
    let duplicate = value["data_sources"]["templates"][0].clone();
    value["data_sources"]["templates"]
        .as_array_mut()
        .unwrap()
        .push(duplicate);
    assert!(parse(&value).is_err());
    let mut value = descriptor();
    value["entity_retention"]["types"]["Swap"]["typo"] = json!(true);
    assert!(parse(&value).is_err());
}

#[test]
fn persistent_only_contract_needs_no_retention_claim() {
    let mut value = descriptor();
    value["entity_retention"]["types"] = json!({});
    value["entity_retention"]["evidence"] = json!([]);
    value["data_sources"] = json!({"transport": "none", "templates": []});
    assert!(parse(&value).is_ok());
}

#[test]
fn duplicate_json_keys_are_refused_at_every_v2_depth_including_escaped_names() {
    let original = serde_json::to_string(&descriptor()).unwrap();
    for (before, after) in [
        (
            "\"descriptor_version\":2",
            "\"descriptor_version\":1,\"descriptor_version\":2",
        ),
        (
            "\"default\":\"persistent\"",
            "\"default\":\"block_local\",\"default\":\"persistent\"",
        ),
        (
            "\"manifest_idx\":2",
            "\"manifest_idx\":999,\"manifest_idx\":2",
        ),
        (
            "\"class\":\"block_local\"",
            "\"class\":\"persistent\",\"class\":\"block_local\"",
        ),
        (
            "\"network\":\"base\"",
            "\"net\\u0077ork\":\"other\",\"network\":\"base\"",
        ),
    ] {
        assert!(original.contains(before));
        let duplicate = original.replacen(before, after, 1);
        let error = BlockChangesCompatibility::from_descriptor(duplicate.as_bytes()).unwrap_err();
        assert!(error.to_string().contains("duplicate JSON key"), "{error}");
    }
    let v1 = String::from_utf8(
        include_bytes!("../fixtures/block-changes-v1/compatibility.json").to_vec(),
    )
    .unwrap();
    let with_duplicate = v1.replacen('{', "{\"descriptor_version\":0,", 1);
    // Descriptor v1 retains its previously published parsing behavior.
    assert!(BlockChangesCompatibility::from_descriptor(with_duplicate.as_bytes()).is_ok());
}

#[test]
fn period_ids_and_block_suffixes_match_actual_aerodrome_schemes() {
    let period = PeriodId::SuffixAfterLast {
        separator: "-".to_owned(),
    };
    assert_eq!(period.parse("0x123#-200-19500").unwrap(), 19500);
    assert_eq!(PeriodId::WholeId.parse("0").unwrap(), 0);
    assert_eq!(
        PeriodId::WholeId.parse(&u64::MAX.to_string()).unwrap(),
        u64::MAX
    );
    for id in ["", "-1", "+1", " 1", "1 ", "1.0", "18446744073709551616"] {
        assert!(PeriodId::WholeId.parse(id).is_err(), "accepted {id:?}");
    }
    for id in ["no-separator", "-123", "pool-", "pool-1e2"] {
        assert!(period.parse(id).is_err(), "accepted {id:?}");
    }
    let proof = BlockLocalProof::BlockNumberSuffix {
        separator: "#".to_owned(),
    };
    assert!(proof
        .verify_block_suffix("position#13843704", 13843704)
        .is_ok());
    for id in [
        "position#13843703",
        "position#013843704",
        "#13843704",
        "position13843704",
    ] {
        assert!(
            proof.verify_block_suffix(id, 13843704).is_err(),
            "accepted {id:?}"
        );
    }
}
