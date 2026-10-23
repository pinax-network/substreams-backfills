use backfill_common::{
    pb::pinax::graph::backfill::v1::{
        entity_id, graph_value, EntityField, EntityId, EntityKey, GraphValue,
    },
    producer_checkpoint::{FilePin, SnapshotPurpose},
    seed_manifest::{self as seed, *},
    state_snapshot::{self as snap, *},
};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;

fn boundary(n: u64) -> Boundary {
    Boundary {
        block_number: n,
        block_hash: [n as u8; 32],
    }
}
fn digest(bytes: &[u8]) -> String {
    hex::encode(Sha256::digest(bytes))
}
fn fixture(purpose: SnapshotPurpose) -> (Manifest, SnapshotHeader, Vec<SnapshotRecord>) {
    let binding = Binding {
        snapshot: SnapshotBinding {
            deployment: "QmSeedFixture".into(),
            network: "base".into(),
            descriptor_sha256: "11".repeat(32),
            retention_sha256: "22".repeat(32),
            type_ordinals: vec!["Token".into()],
            entity_id_policy: EntityIdPolicy::StringOnly,
        },
        purpose: purpose.clone(),
        boundary: boundary(100),
        start_block: 10,
        target: Target {
            schema: "sgd42".into(),
            site_id: 42,
            database: "graph".into(),
            system_identifier: "123456789".into(),
        },
        profile_sha256: "33".repeat(32),
        catalog_sha256: "44".repeat(32),
        schema_sha256: "55".repeat(32),
        raw_manifest_sha256: "66".repeat(32),
        capture_binary_sha256: "77".repeat(32),
        creating_graph_node: GraphNode {
            version: "0.44.0".into(),
            commit: "77823b5a7adc4eac4abf03202c8dd7cb00dea31d".into(),
        },
        spec_version: "1.0.0".into(),
        manifest_graft: None,
        landing_graft: None,
    };
    let capture = SeedOrigin {
        schema: binding.target.schema.clone(),
        site_id: binding.target.site_id,
        database: binding.target.database.clone(),
        system_identifier: binding.target.system_identifier.clone(),
        server_version_num: 160000,
        capture_tool_sha256: binding.capture_binary_sha256.clone(),
        profile_sha256: binding.profile_sha256.clone(),
        head: boundary(100),
        health: "healthy".into(),
        non_fatal_errors: vec![],
    };
    let header = SnapshotHeader {
        format: snap::FORMAT.into(),
        version: snap::VERSION,
        binding: binding.snapshot.clone(),
        boundary: binding.boundary.clone(),
        origin: if purpose == SnapshotPurpose::Landing {
            SnapshotOrigin::Landing {
                seed: capture.clone(),
            }
        } else {
            SnapshotOrigin::Oracle {
                seed: capture.clone(),
            }
        },
        vid: if purpose == SnapshotPurpose::Landing {
            Some(VidState {
                tables: vec![TableVid {
                    entity_type: "Token".into(),
                    postgres_table: "token".into(),
                    max_vid: 1,
                    sequence_last_value: 1,
                    sequence_is_called: true,
                    active_rows: Some(1),
                }],
            })
        } else {
            None
        },
        poi: GenericPoiState::default(),
        sources: SourceSnapshot::from_rows(vec![SnapshotSource {
            vid: 1,
            creation_block: 12,
            manifest_idx: 2,
            param: vec![3; 20],
        }])
        .unwrap(),
        period_max: BTreeMap::new(),
        entity_count: Some(1),
        records: 1,
    };
    let key = EntityKey {
        entity_type: "Token".into(),
        id: Some(EntityId {
            value: Some(entity_id::Value::String("a".into())),
        }),
        storage_causality_region: 0,
    };
    let row = SnapshotRecord::from_entity(
        &binding.snapshot,
        &key,
        &StoredEntity {
            vid: 1,
            block_range_start: 99,
            fields: vec![EntityField {
                name: "id".into(),
                value: Some(GraphValue {
                    kind: Some(graph_value::Kind::String("a".into())),
                }),
            }],
        },
    )
    .unwrap();
    let manifest = Manifest {
        format: seed::FORMAT.into(),
        deployment: DeploymentObservation {
            deployment: binding.snapshot.deployment.clone(),
            spec_version: binding.spec_version.clone(),
            start_parent: boundary(9),
            graft: None,
            schema_sha256: binding.schema_sha256.clone(),
            raw_manifest_sha256: binding.raw_manifest_sha256.clone(),
            creating_graph_node: binding.creating_graph_node.clone(),
            failed: false,
            fatal_error: None,
            retained_error_count: 0,
            current_reorg_depth: 0,
            postponed_indexes_created: true,
            namespace_count: 1,
        },
        transaction: TransactionObservation {
            isolation: "repeatable read".into(),
            read_only: true,
            backend_pid: 1234,
            write_lock: true,
            copy_lock: true,
            prune_lock: true,
        },
        history: History::UnprunedFromDeploymentStart {
            history_blocks: i32::MAX as u64,
            earliest_block: 9,
            table_last_pruned_block: [("Token".into(), None)].into(),
        },
        catalog_sha256: binding.catalog_sha256.clone(),
        sources: seed::SourceCommitment {
            count: header.sources.count,
            max_vid: header.sources.max_vid,
            order_sha256: header.sources.order_sha256.clone(),
        },
        captured_rows: [("Token".into(), 1)].into(),
        capture,
        binding,
        snapshot: FilePin {
            path: "seed.bcgsnap".into(),
            bytes: 1,
            sha256: "88".repeat(32),
        },
        lineage: "00".repeat(32),
    };
    (manifest, header, vec![row])
}
fn seal(
    mut manifest: Manifest,
    header: SnapshotHeader,
    rows: &[SnapshotRecord],
) -> (Manifest, Vec<u8>, Vec<u8>) {
    let mut writer = SnapshotWriter::new(Vec::new(), header, Limits::default()).unwrap();
    for row in rows {
        writer.write_record(row).unwrap();
    }
    let (snapshot, pin) = writer.finish().unwrap();
    manifest.snapshot.bytes = pin.bytes();
    manifest.snapshot.sha256 = hex::encode(pin.file_sha256());
    manifest.lineage = hex::encode(pin.lineage());
    let bytes = manifest.encode().unwrap();
    (manifest, bytes, snapshot)
}
fn read(
    manifest: &Manifest,
    bytes: &[u8],
    snapshot: &[u8],
    purpose: ReadPurpose,
) -> Result<VerifiedSeed, String> {
    let mut reader = SeedSnapshotReader::new(
        snapshot,
        bytes,
        &digest(bytes),
        &manifest.binding,
        purpose,
        Limits::default(),
    )?;
    while reader.next_record()?.is_some() {}
    reader.finish()
}

#[test]
fn exact_landing_manifest_and_full_stream_produce_verified_token() {
    let (m, h, r) = fixture(SnapshotPurpose::Landing);
    let (m, b, s) = seal(m, h, &r);
    assert_eq!(Manifest::decode(&b).unwrap(), m);
    let verified = read(&m, &b, &s, ReadPurpose::Loadable).unwrap();
    verified.require_loadable().unwrap();
    verified.require_complete_source_history().unwrap();
    assert_eq!(verified.manifest_sha256(), digest(&b));
    assert_eq!(
        verified.snapshot().file_sha256(),
        <[u8; 32]>::from(Sha256::digest(&s))
    );
}
#[test]
fn deferred_query_indexes_do_not_refuse_an_exact_healthy_capture() {
    for purpose in [SnapshotPurpose::Landing, SnapshotPurpose::Oracle] {
        let (mut m, h, r) = fixture(purpose.clone());
        m.deployment.postponed_indexes_created = false;
        let (m, b, s) = seal(m, h, &r);
        let decoded = Manifest::decode(&b).unwrap();
        assert!(!decoded.deployment.postponed_indexes_created);
        let read_purpose = if purpose == SnapshotPurpose::Landing {
            ReadPurpose::Loadable
        } else {
            ReadPurpose::OracleComparison
        };
        let verified = read(&m, &b, &s, read_purpose).unwrap();
        verified.require_complete_source_history().unwrap();
        assert_eq!(
            verified.require_loadable().is_ok(),
            purpose == SnapshotPurpose::Landing
        );
        let mut changed = m.clone();
        changed.catalog_sha256 = "99".repeat(32);
        assert!(changed.validate().is_err());
    }
}
#[test]
fn oracle_never_becomes_loadable_even_with_valid_snapshot_and_manifest() {
    let (m, h, r) = fixture(SnapshotPurpose::Oracle);
    let (m, b, s) = seal(m, h, &r);
    let verified = read(&m, &b, &s, ReadPurpose::OracleComparison).unwrap();
    assert!(verified.require_loadable().is_err());
    assert!(read(&m, &b, &s, ReadPurpose::Loadable).is_err());
    let mut expected = m.binding.clone();
    expected.purpose = SnapshotPurpose::Landing;
    assert!(Manifest::verify(&b, &digest(&b), &expected).is_err());
}
#[test]
fn cannot_finish_before_caller_consumes_every_record() {
    let (m, h, r) = fixture(SnapshotPurpose::Landing);
    let (m, b, s) = seal(m, h, &r);
    let reader = SeedSnapshotReader::new(
        s.as_slice(),
        &b,
        &digest(&b),
        &m.binding,
        ReadPurpose::Loadable,
        Limits::default(),
    )
    .unwrap();
    assert!(reader.finish().is_err());
}
#[test]
fn canonical_bytes_external_digest_and_capture_binding_are_independent() {
    let (m, h, r) = fixture(SnapshotPurpose::Landing);
    let (m, b, _) = seal(m, h, &r);
    assert!(Manifest::verify(&b, &"00".repeat(32), &m.binding).is_err());
    let mut expected = m.binding.clone();
    expected.capture_binary_sha256 = "99".repeat(32);
    assert!(Manifest::verify(&b, &digest(&b), &expected).is_err());
    let mut changed = b.clone();
    changed.push(b'\n');
    assert!(Manifest::decode(&changed).is_err());
    let mut value: serde_json::Value = serde_json::from_slice(&b).unwrap();
    value["unexpected"] = true.into();
    assert!(Manifest::decode(&serde_json::to_vec(&value).unwrap()).is_err());
    assert!(Manifest::decode(&vec![b' '; MAX_BYTES + 1]).is_err());
}
#[test]
fn unhealthy_failed_incomplete_locks_and_identity_observations_are_refused() {
    let (m, h, r) = fixture(SnapshotPurpose::Landing);
    let (mut m, _, _) = seal(m, h, &r);
    m.deployment.postponed_indexes_created = false;
    m.validate().unwrap();
    let mutations: Vec<fn(&mut Manifest)> = vec![
        |m| m.capture.health = "unhealthy".into(),
        |m| m.capture.non_fatal_errors.push("error".into()),
        |m| m.deployment.failed = true,
        |m| m.deployment.fatal_error = Some("error".into()),
        |m| m.deployment.retained_error_count = 1,
        |m| m.transaction.copy_lock = false,
        |m| m.transaction.prune_lock = false,
        |m| m.transaction.write_lock = false,
        |m| m.transaction.read_only = false,
        |m| m.transaction.isolation = "read committed".into(),
        |m| m.capture.system_identifier = "another".into(),
        |m| m.capture.profile_sha256 = "99".repeat(32),
        |m| m.deployment.start_parent = boundary(8),
        |m| m.deployment.schema_sha256 = "99".repeat(32),
        |m| m.deployment.namespace_count = 2,
        |m| m.deployment.current_reorg_depth = 1,
        |m| m.capture.head = boundary(99),
    ];
    for (i, mutate) in mutations.into_iter().enumerate() {
        let mut changed = m.clone();
        mutate(&mut changed);
        assert!(changed.validate().is_err(), "mutation {i}");
    }
}
#[test]
fn unsupported_or_pruned_history_cannot_supply_complete_source_claim() {
    let (m, h, r) = fixture(SnapshotPurpose::Landing);
    let (mut m, _, s) = seal(m, h, &r);
    m.deployment.postponed_indexes_created = false;
    m.validate().unwrap();
    m.history = History::Unproven {
        reason: "copy provenance is not yet retained".into(),
    };
    let b = m.encode().unwrap();
    let diagnostic = read(&m, &b, &s, ReadPurpose::OracleComparison).unwrap();
    assert!(diagnostic.require_complete_source_history().is_err());
    assert!(read(&m, &b, &s, ReadPurpose::Loadable).is_err());
    for history in [
        History::UnprunedFromDeploymentStart {
            history_blocks: 100,
            earliest_block: 9,
            table_last_pruned_block: [("Token".into(), None)].into(),
        },
        History::UnprunedFromDeploymentStart {
            history_blocks: i32::MAX as u64,
            earliest_block: 10,
            table_last_pruned_block: [("Token".into(), None)].into(),
        },
        History::UnprunedFromDeploymentStart {
            history_blocks: i32::MAX as u64,
            earliest_block: 9,
            table_last_pruned_block: [("Token".into(), Some(10))].into(),
        },
        History::UnprunedFromDeploymentStart {
            history_blocks: i32::MAX as u64,
            earliest_block: 9,
            table_last_pruned_block: BTreeMap::new(),
        },
    ] {
        m.history = history;
        assert!(m.validate().is_err());
    }
}
#[test]
fn self_copy_requires_exact_tuple_same_deployment_and_head_after_copy() {
    let (m, h, r) = fixture(SnapshotPurpose::Landing);
    let (mut m, _, _) = seal(m, h, &r);
    m.binding.landing_graft = Some(LandingGraft::SelfCopy {
        base: m.binding.snapshot.deployment.clone(),
        boundary: boundary(50),
    });
    m.deployment.graft = Some(ObservedGraft {
        base: m.binding.snapshot.deployment.clone(),
        boundary: boundary(50),
    });
    m.validate().unwrap();
    assert!(m.binding.manifest_graft.is_none());
    let mut changed = m.clone();
    changed
        .deployment
        .graft
        .as_mut()
        .unwrap()
        .boundary
        .block_hash = [7; 32];
    assert!(changed.validate().is_err());
    let mut changed = m.clone();
    changed.deployment.graft.as_mut().unwrap().base = "other".into();
    assert!(changed.validate().is_err());
    let mut changed = m.clone();
    if let Some(LandingGraft::SelfCopy { boundary, .. }) = &mut changed.binding.landing_graft {
        *boundary = Boundary {
            block_number: 100,
            block_hash: [100; 32],
        };
    }
    assert!(changed.validate().is_err());
}
#[test]
fn header_source_commitment_and_manifest_counts_are_checked_against_stream() {
    let (m, h, r) = fixture(SnapshotPurpose::Landing);
    let (m, b, s) = seal(m, h.clone(), &r);
    let mut changed = m.clone();
    changed.sources.order_sha256 = "99".repeat(32);
    let bytes = changed.encode().unwrap();
    assert!(read(&changed, &bytes, &s, ReadPurpose::Loadable).is_err());
    let mut different = h;
    different.entity_count = Some(2);
    let (_, _, different) = seal(m.clone(), different, &r);
    assert!(read(&m, &b, &different, ReadPurpose::Loadable).is_err());
    let mut changed = m;
    changed.captured_rows.insert("Token".into(), 2);
    let bytes = changed.encode().unwrap();
    assert!(read(&changed, &bytes, &s, ReadPurpose::Loadable).is_err());
}
#[test]
fn corrupt_truncated_or_trailing_snapshot_never_yields_token() {
    let (m, h, r) = fixture(SnapshotPurpose::Landing);
    let (m, b, s) = seal(m, h, &r);
    for length in [0, 8, 12, s.len() - 1] {
        assert!(read(&m, &b, &s[..length], ReadPurpose::Loadable).is_err());
    }
    let mut extra = s.clone();
    extra.push(0);
    assert!(read(&m, &b, &extra, ReadPurpose::Loadable).is_err());
    let mut corrupt = s;
    let last = corrupt.len() - 1;
    corrupt[last] ^= 1;
    assert!(read(&m, &b, &corrupt, ReadPurpose::Loadable).is_err());
}
