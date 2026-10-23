//! `pinax.graph.backfill.v1.BlockChanges` frames for Uniswap V3 mainnet
//! segment 1, produced from the per-save operation stream the vendored
//! `graph-runtime-wasm` recorder observes.
//!
//! Hermetic: the committed cassette and the hydrated block fixtures, no network.
//!
//! The four fixture files hold one block each since release
//! `block-fixtures-v2`, so the run produces four frames.
//!
//! ## Regenerating the goldens
//!
//! Set `UPDATE_GOLDENS=1` to rewrite them from the current run:
//!
//! ```sh
//! UPDATE_GOLDENS=1 cargo test --test mapping_host block_changes_qme66zn
//! ```
//!
//! That writes `fixtures/block-changes/<deployment>/<block>.pb` and fails the
//! run, so a regeneration is never mistaken for a passing check.

use std::collections::BTreeMap;
use std::path::PathBuf;
use std::sync::OnceLock;

use backfill_common::pb::pinax::graph::backfill::v2 as pb;
use backfill_common::{decode_canonical_in_band_block_changes, validate_in_band_block_changes};
use graph_mapping_host::runner::{SegmentHost, SegmentHostConfig};
use graph_mapping_host::{block, blockchanges};

const SEGMENT: &str = "Qme66ZNMxSdCQKzaDuvS381whCVYCQjf637sGZCqJHAWHB";
const FIXTURES: &[&str] = &["12369621", "12369739", "12369879", "12370523"];

fn crate_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

fn block_fixture(name: &str) -> PathBuf {
    crate_dir()
        .parent()
        .expect("mapping-host has a parent")
        .join(format!("uniswap-v3/fixtures/blocks/mainnet/{name}.pb"))
}

fn goldens_dir() -> PathBuf {
    crate_dir().join(format!("fixtures/block-changes/{SEGMENT}"))
}

fn updating() -> bool {
    std::env::var("UPDATE_GOLDENS").is_ok_and(|value| value == "1")
}

struct Run {
    frames: Vec<(pb::BlockChanges, Vec<u8>)>,
    compatibility: backfill_common::BlockChangesCompatibility,
    descriptor_sha256: String,
}

fn run() -> &'static Run {
    static RUN: OnceLock<Run> = OnceLock::new();
    RUN.get_or_init(|| {
        for name in FIXTURES {
            assert!(
                block_fixture(name).exists(),
                "missing block fixture; run `cargo xtask evidence fetch --lock \
                 uniswap-v3/fixtures/blocks.lock.json` from the repository root"
            );
        }
        let runtime = tokio::runtime::Builder::new_multi_thread()
            .enable_all()
            .build()
            .expect("tokio runtime");
        runtime.block_on(replay())
    })
}

async fn replay() -> Run {
    let mut host = SegmentHost::load(SegmentHostConfig {
        bundle_dir: &crate_dir().join(format!("segments/{SEGMENT}")),
        cassette_path: &crate_dir().join(format!("fixtures/cassettes/{SEGMENT}.json")),
        record: false,
    })
    .await
    .expect("loading the segment");

    use graph::blockchain::Block as _;
    let mut blocks = Vec::new();
    for name in FIXTURES {
        blocks.push(block::load_block(&block_fixture(name)).expect("loading a fixture"));
    }
    blocks.sort_by_key(|b| b.number());

    let mut frames = Vec::new();
    for b in blocks {
        let number = b.number();
        let outcome = host
            .process_block(b)
            .await
            .unwrap_or_else(|e| panic!("replaying block {number}: {e:#}"));
        let bytes = blockchanges::seal(&outcome.changes, host.compatibility())
            .unwrap_or_else(|e| panic!("sealing block {number}: {e:#}"));
        frames.push((outcome.changes, bytes));
    }

    Run {
        frames,
        compatibility: host.compatibility().clone(),
        descriptor_sha256: host.descriptor_sha256().to_string(),
    }
}

fn frame(block_number: u64) -> &'static pb::BlockChanges {
    &run()
        .frames
        .iter()
        .find(|(changes, _)| changes.block_number == block_number)
        .unwrap_or_else(|| panic!("no frame for block {block_number}"))
        .0
}

/// The `(entity type, id)` of every Set in one handler, in operation order.
fn saves_of(changes: &pb::BlockChanges, group: u64, handler: u64) -> Vec<(String, String)> {
    changes
        .operations
        .iter()
        .filter(|op| op.handler_group_order == group && op.handler_order == handler)
        .filter_map(|op| match op.operation.as_ref() {
            Some(pb::entity_operation::Operation::Set(set)) => {
                Some((set.poi_entity_type.clone(), set.poi_entity_id.clone()))
            }
            _ => None,
        })
        .collect()
}

#[test]
fn every_frame_validates_against_the_segment_descriptor() {
    for (changes, _) in &run().frames {
        validate_in_band_block_changes(changes, &run().compatibility)
            .unwrap_or_else(|e| panic!("block {} does not validate: {e}", changes.block_number));
    }
}

#[test]
fn every_frame_round_trips_through_the_canonical_codec() {
    for (changes, bytes) in &run().frames {
        let decoded = decode_canonical_in_band_block_changes(bytes, &run().compatibility)
            .unwrap_or_else(|e| panic!("block {} did not decode: {e}", changes.block_number));
        assert_eq!(&decoded, changes, "block {}", changes.block_number);
    }
}

#[test]
fn frames_match_the_goldens() {
    let dir = goldens_dir();
    if updating() {
        std::fs::create_dir_all(&dir).expect("creating the golden directory");
        for (changes, bytes) in &run().frames {
            std::fs::write(dir.join(format!("{}.pb", changes.block_number)), bytes)
                .expect("writing a golden frame");
        }
        panic!(
            "goldens rewritten under {}; re-run without UPDATE_GOLDENS to check them",
            dir.display()
        );
    }

    for (changes, bytes) in &run().frames {
        let path = dir.join(format!("{}.pb", changes.block_number));
        let golden = std::fs::read(&path).unwrap_or_else(|e| {
            panic!(
                "reading {}: {e}. Regenerate with UPDATE_GOLDENS=1",
                path.display()
            )
        });
        assert_eq!(
            bytes,
            &golden,
            "block {} frame differs from {}",
            changes.block_number,
            path.display()
        );
    }

    // No stray goldens for blocks this run no longer produces.
    let produced: Vec<String> = run()
        .frames
        .iter()
        .map(|(changes, _)| format!("{}.pb", changes.block_number))
        .collect();
    for entry in std::fs::read_dir(&dir).expect("listing the golden directory") {
        let name = entry
            .expect("a golden")
            .file_name()
            .to_string_lossy()
            .to_string();
        assert!(produced.contains(&name), "{name} is an orphaned golden");
    }
}

#[test]
fn the_descriptor_is_not_a_fixture_descriptor() {
    // The engine refuses `"fixture_only": true` unless --allow-fixture-descriptor
    // is passed, which production never does.
    let path = crate_dir().join(format!("segments/{SEGMENT}/block-changes-descriptor.json"));
    let text = std::fs::read_to_string(&path).expect("reading the descriptor");
    let value: serde_json::Value = serde_json::from_str(&text).expect("descriptor JSON");
    assert!(value.get("fixture_only").is_none());
    assert_eq!(
        value["contract"],
        serde_json::json!("pinax.graph.backfill.block-changes/v1")
    );
    assert_eq!(value["descriptor_version"], serde_json::json!(1));
    assert_eq!(
        value["deterministic_error_policy"],
        serde_json::json!("fatal")
    );
    assert_eq!(value["network"], serde_json::json!("mainnet"));
    assert_eq!(
        value["expected_poi_causality_region"],
        serde_json::json!("ethereum/mainnet")
    );
    assert_eq!(
        value["graph_node"]["poi_version"],
        serde_json::json!("legacy")
    );
    assert_eq!(
        value["graph_node"]["commit"],
        serde_json::json!("77823b5a7adc4eac4abf03202c8dd7cb00dea31d")
    );
    assert_eq!(value["deployment"], serde_json::json!(SEGMENT));

    // The sidecar the engine requires beside it.
    let sidecar =
        std::fs::read_to_string(path.with_extension("json.sha256")).expect("reading the sidecar");
    assert_eq!(sidecar.trim(), run().descriptor_sha256);
}

#[test]
fn the_operation_stream_is_per_save_not_a_coalesced_diff() {
    // Phase 1 could only report one modification set per handler, sorted by key,
    // because `EntityCache` collapses writes into a `HashMap`. This is the phase
    // 2 payoff: `handleMint` saves `Pool` *before* the `Mint` row, which is the
    // survey's ordered-save claim and is unobservable from `as_modifications`.
    let changes = frame(12369739);
    let mint_group = changes
        .operations
        .iter()
        .find(|op| {
            matches!(
                op.operation.as_ref(),
                Some(pb::entity_operation::Operation::Set(set)) if set.poi_entity_type == "Mint"
            )
        })
        .expect("a Mint save")
        .handler_group_order;
    let saves = saves_of(changes, mint_group, 0);

    let pool_at = saves
        .iter()
        .position(|(entity, _)| entity == "Pool")
        .expect("handleMint saves Pool");
    let mint_at = saves
        .iter()
        .position(|(entity, _)| entity == "Mint")
        .expect("handleMint saves Mint");
    assert!(
        pool_at < mint_at,
        "Pool.save must precede the Mint write; saves were {saves:?}"
    );

    // A coalesced diff cannot repeat a key; a save stream can, and does.
    let mut counts: BTreeMap<&str, usize> = BTreeMap::new();
    for (entity, _) in &saves {
        *counts.entry(entity.as_str()).or_default() += 1;
    }
    assert!(
        counts.values().any(|count| *count > 1),
        "handleMint saves at least one entity twice; counts were {counts:?}"
    );
}

#[test]
fn shared_transaction_upserts_are_visible_once_per_handler() {
    // Phase 1 saw a single `Transaction` modification for the whole block,
    // because the later identical upserts changed nothing and
    // `as_modifications` emitted nothing for them. The save stream shows each
    // handler's own upsert.
    let changes = frame(12369739);
    let writers: Vec<(u64, u64)> = changes
        .operations
        .iter()
        .filter(|op| matches!(
            op.operation.as_ref(),
            Some(pb::entity_operation::Operation::Set(set)) if set.poi_entity_type == "Transaction"
        ))
        .map(|op| (op.handler_group_order, op.handler_order))
        .collect();
    assert!(
        writers.len() >= 2,
        "the shared Transaction row is upserted by more than one handler; writers were {writers:?}"
    );
    let groups: std::collections::BTreeSet<u64> = writers.iter().map(|(group, _)| *group).collect();
    assert!(
        groups.len() >= 2,
        "those upserts come from different handler groups; groups were {groups:?}"
    );
}

#[test]
fn operation_indexes_are_dense_and_handler_groups_never_regress() {
    for (changes, _) in &run().frames {
        let mut previous_group = None;
        for (index, op) in changes.operations.iter().enumerate() {
            assert_eq!(
                op.operation_index, index as u64,
                "block {}",
                changes.block_number
            );
            if let Some(previous) = previous_group {
                assert!(
                    op.handler_group_order >= previous,
                    "block {} handler groups regressed",
                    changes.block_number
                );
            }
            previous_group = Some(op.handler_group_order);
        }
    }
}

#[test]
fn onchain_operations_carry_the_poi_region_and_region_zero() {
    for (changes, _) in &run().frames {
        for op in &changes.operations {
            assert_eq!(op.source_causality_region, 0, "Uniswap V3 is onchain-only");
            assert_eq!(
                op.poi_causality_region.as_deref(),
                Some("ethereum/mainnet"),
                "block {}",
                changes.block_number
            );
        }
        if changes.mapping_triggered {
            assert_eq!(
                changes.triggered_poi_causality_regions,
                vec!["ethereum/mainnet".to_string()]
            );
        } else {
            assert!(changes.triggered_poi_causality_regions.is_empty());
            assert!(changes.operations.is_empty());
        }
    }
}

#[test]
fn every_frame_declares_the_fatal_policy_of_this_segment() {
    for (changes, _) in &run().frames {
        assert_eq!(
            changes.deterministic_error_policy,
            pb::DeterministicErrorPolicy::Fatal as i32,
            "block {}",
            changes.block_number
        );
        assert_eq!(changes.block_hash.len(), 32);
        assert_eq!(changes.contract, backfill_common::BLOCK_CHANGES_V1_CONTRACT);
        assert_eq!(changes.compatibility_id, run().compatibility.to_vec());
    }
}

#[test]
fn a_fatally_discarded_block_marks_every_operation_and_keeps_the_poi() {
    // The errors themselves are a fixture-gap artifact, not deployed behaviour;
    // see `segment_qme66zn::a_fixture_gap_error_exercises_the_fatal_discard_path`.
    // What is asserted here is the frame's disposition algebra.
    let changes = frame(12370523);
    let errors: Vec<&pb::EntityOperation> = changes
        .operations
        .iter()
        .filter(|op| {
            matches!(
                op.operation.as_ref(),
                Some(pb::entity_operation::Operation::DeterministicError(_))
            )
        })
        .collect();
    assert_eq!(errors.len(), 2, "two handler groups failed");

    let failed: BTreeMap<u64, u64> = errors
        .iter()
        .map(|op| (op.handler_group_order, op.handler_order))
        .collect();

    for op in &changes.operations {
        let expected = if failed.get(&op.handler_group_order) == Some(&op.handler_order) {
            pb::StoreDisposition::Discarded
        } else {
            pb::StoreDisposition::BlockDiscarded
        } as i32;
        match op.operation.as_ref() {
            Some(pb::entity_operation::Operation::Set(set)) => {
                assert_eq!(set.store_disposition, expected, "op {}", op.operation_index);
                // The PoI event happened, so the boundary is still known.
                assert!(set.materialized.is_some(), "op {}", op.operation_index);
            }
            Some(pb::entity_operation::Operation::Remove(remove)) => {
                assert_eq!(remove.store_disposition, expected);
            }
            _ => {}
        }
    }
    assert!(changes.mapping_triggered);
}

#[test]
fn deterministic_error_redaction_counts_events_since_start_handler() {
    // Graph Node hashes the number of PoI events emitted since that group's
    // `start_handler`, counting every one, not only the discarded ones.
    let changes = frame(12370523);
    let mut seen: BTreeMap<u64, u64> = BTreeMap::new();
    for op in &changes.operations {
        match op.operation.as_ref() {
            Some(pb::entity_operation::Operation::DeterministicError(error)) => {
                let expected = seen.get(&op.handler_group_order).copied().unwrap_or(0);
                assert_eq!(
                    error.redacted_events, expected,
                    "group {} redaction",
                    op.handler_group_order
                );
            }
            Some(_) => {
                *seen.entry(op.handler_group_order).or_default() += 1;
            }
            None => panic!("an operation with no body"),
        }
    }
}

#[test]
fn written_fields_are_sorted_carry_the_id_and_exclude_vid() {
    for (changes, _) in &run().frames {
        for op in &changes.operations {
            let Some(pb::entity_operation::Operation::Set(set)) = op.operation.as_ref() else {
                continue;
            };
            let names: Vec<&str> = set
                .written_fields
                .iter()
                .map(|field| field.name.as_str())
                .collect();
            let mut sorted = names.clone();
            sorted.sort_unstable();
            assert_eq!(names, sorted, "op {}", op.operation_index);
            assert!(names.contains(&"id"), "op {}", op.operation_index);
            assert!(!names.contains(&"vid"), "op {}", op.operation_index);
        }
    }
}

#[test]
fn a_bcf1_frame_carries_the_block_identity_and_payload() {
    let (changes, payload) = &run().frames[0];
    let framed = blockchanges::bcf1_frame(changes.block_number, &changes.block_hash, payload)
        .expect("framing");
    assert_eq!(&framed[..4], b"BCF1");
    assert_eq!(framed[4], 1);
    assert_eq!(&framed[5..8], &[0, 0, 0]);
    assert_eq!(&framed[8..16], &changes.block_number.to_be_bytes());
    assert_eq!(&framed[16..48], changes.block_hash.as_slice());
    assert_eq!(
        &framed[48..52],
        &(payload.len() as u32).to_be_bytes(),
        "payload length"
    );
    assert_eq!(&framed[52..], payload.as_slice());
    assert_eq!(framed.len(), 52 + payload.len());
}

#[test]
fn the_vendored_runtime_matches_its_lock() {
    // The vendored crate is upstream code. A stray edit — a `cargo fmt` that
    // reached it, a merge, a hand fix — would silently change what the recorder
    // observes, so every file is pinned. Exactly four differ from upstream, and
    // they are the four the patch header names.
    #[derive(serde::Deserialize)]
    struct VendorLock {
        schema: String,
        upstream_revision: String,
        files: Vec<VendorFile>,
    }
    #[derive(serde::Deserialize)]
    struct VendorFile {
        path: String,
        bytes: u64,
        sha256: String,
        upstream_sha256: Option<String>,
        patched: bool,
    }

    let vendor = crate_dir().join("vendor");
    let lock: VendorLock = serde_json::from_slice(
        &std::fs::read(vendor.join("graph-runtime-wasm.lock.json")).expect("the vendor lock"),
    )
    .expect("vendor lock JSON");
    assert_eq!(
        lock.schema,
        "pinax.substreams-backfills.mapping-host.vendor/v1"
    );
    assert_eq!(
        lock.upstream_revision,
        "77823b5a7adc4eac4abf03202c8dd7cb00dea31d"
    );

    let mut patched = Vec::new();
    for file in &lock.files {
        let path = vendor.join("graph-runtime-wasm").join(&file.path);
        let bytes =
            std::fs::read(&path).unwrap_or_else(|e| panic!("reading {}: {e}", path.display()));
        assert_eq!(bytes.len() as u64, file.bytes, "{}", file.path);
        let digest = graph_mapping_host::bundle::sha256_hex(&bytes);
        assert_eq!(
            digest, file.sha256,
            "{} drifted from the vendor lock",
            file.path
        );

        match (&file.upstream_sha256, file.patched) {
            (Some(upstream), false) => assert_eq!(
                &digest, upstream,
                "{} is not patched but differs from upstream",
                file.path
            ),
            (Some(upstream), true) => {
                assert_ne!(
                    &digest, upstream,
                    "{} is marked patched but matches upstream",
                    file.path
                );
                patched.push(file.path.clone());
            }
            (None, true) => patched.push(file.path.clone()),
            (None, false) => panic!("{} has no upstream and is not marked patched", file.path),
        }
    }
    patched.sort();
    assert_eq!(
        patched,
        vec![
            "src/host.rs".to_string(),
            "src/host_exports.rs".to_string(),
            "src/lib.rs".to_string(),
            "src/op_recorder.rs".to_string(),
        ]
    );

    // No vendored source outside the lock.
    let mut on_disk = Vec::new();
    let mut stack = vec![vendor.join("graph-runtime-wasm").join("src")];
    while let Some(dir) = stack.pop() {
        for entry in std::fs::read_dir(&dir).expect("listing the vendored src") {
            let path = entry.expect("a vendored file").path();
            if path.is_dir() {
                stack.push(path);
            } else {
                on_disk.push(
                    path.strip_prefix(vendor.join("graph-runtime-wasm"))
                        .expect("under the vendored crate")
                        .to_string_lossy()
                        .replace('\\', "/"),
                );
            }
        }
    }
    on_disk.sort();
    let mut locked: Vec<String> = lock.files.iter().map(|f| f.path.clone()).collect();
    locked.sort();
    assert_eq!(on_disk, locked, "vendored files and the lock disagree");
}
