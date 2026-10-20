//! The deployed Aerodrome Slipstream CL Base mapping
//! (`QmasYjypV6nTLp4iNH4Vjf7fksRNxAkAskqDdKf2DCsQkV`) as an oracle segment.
//!
//! Hermetic. Everything that runs in CI needs only the committed bundle, its
//! descriptor and the M7 target record under `aerodrome-slipstream-base/`:
//!
//! * the bundle is byte-for-byte the target M7 pinned, not a second fetch;
//! * graph-node's own parser resolves it as deployed: spec 1.2.0, API 0.0.7,
//!   `nonFatalErrors`, no concrete graft, two data sources and a `Pool`
//!   template, every declared call where the manifest puts it;
//! * the host takes every identity it needs from that manifest, with nothing
//!   about Uniswap V3 or mainnet left to override: network `base`, PoI region
//!   `ethereum/base`, the `fast` PoI hasher, the non-fatal error policy and the
//!   Factory's start block as the segment's first block;
//! * the descriptor regenerates byte for byte.
//!
//! Two real Base blocks are then replayed against the committed fixture
//! cassette with recording off, so no test here opens a socket. The block files
//! (708 KB and 6.6 MB) are release assets locked by
//! `aerodrome-slipstream-base/fixtures/blocks.lock.json`, which CI hydrates with
//! `cargo xtask evidence fetch` before `cargo test`, as it does the Uniswap V3
//! fixtures:
//!
//! * 13,899,663, the first pool, must reproduce the frame and the PoI the live
//!   root-window run produced for the same block, read from that run's published
//!   per-block file: live-frame parity.
//! * 52,800,000, a dense recent block replayed behind only that one pool, is a
//!   regression pin. Its digests are this host's own, and the 175 deterministic
//!   errors in it come from rows the two-block store does not hold. It is the
//!   only replay that reaches `STORE_DISPOSITION_COMMITTED` after a
//!   deterministic error, so the non-fatal path is exercised here on a
//!   synthetic store gap, not shown against deployed behaviour.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::sync::OnceLock;

use backfill_common::pb::pinax::graph::backfill::v1 as pb;
use graph::data::subgraph::SubgraphFeature;
use graph::prelude::{o, slog, Logger};
use graph_mapping_host::bundle::{sha256_hex, SegmentBundle};
use graph_mapping_host::evidence::PerBlockLine;
use graph_mapping_host::report::BlockReport;
use graph_mapping_host::runner::{SegmentBounds, SegmentHost, SegmentHostConfig};
use graph_mapping_host::{block, blockchanges, descriptor};

const SEGMENT: &str = "QmasYjypV6nTLp4iNH4Vjf7fksRNxAkAskqDdKf2DCsQkV";
/// `segments/<cid>/block-changes-descriptor.json.sha256`, and so every frame's
/// `compatibility_id`.
const DESCRIPTOR_SHA256: &str = "0d04fcf25b04430545ec8f4e7b995aadda4444f66eeeaf9f2ce6402c2332996d";
const FACTORY: &str = "0x5e7bb104d84c7cb9b682aac2f3d509f5f406809a";
const NPM: &str = "0x827922686190790b37229fd06084350e74485b72";
const FACTORY_START: i32 = 13_843_704;
const NPM_START: i32 = 13_843_719;

fn crate_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

fn repo_root() -> PathBuf {
    crate_dir()
        .parent()
        .expect("mapping-host has a parent directory")
        .to_path_buf()
}

fn segment_dir() -> PathBuf {
    crate_dir().join(format!("segments/{SEGMENT}"))
}

fn logger() -> Logger {
    Logger::root(slog::Discard, o!())
}

fn runtime() -> tokio::runtime::Runtime {
    tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
        .expect("tokio runtime")
}

fn address(bytes: &[u8]) -> String {
    format!("0x{}", hex::encode(bytes))
}

#[test]
fn the_bundle_is_the_target_m7_pinned() {
    // `aerodrome-slipstream-base/` froze the deployment as eleven
    // content-addressed objects, verified by `cargo xtask verify-target
    // aerodrome-slipstream-base`. The bundle must be those objects and only
    // those, so the oracle executes exactly what the target record describes.
    let provenance: serde_json::Value = serde_json::from_slice(
        &std::fs::read(repo_root().join("docs/provenance/aerodrome-slipstream-base-target.json"))
            .expect("reading the M7 target record"),
    )
    .expect("parsing the M7 target record");
    let pinned: BTreeMap<String, (String, u64, String)> = provenance["artifact_lock"]
        .as_array()
        .expect("artifact_lock is a list")
        .iter()
        .map(|entry| {
            (
                entry["cid"].as_str().unwrap().to_string(),
                (
                    entry["sha256"].as_str().unwrap().to_string(),
                    entry["bytes"].as_u64().unwrap(),
                    entry["path"].as_str().unwrap().to_string(),
                ),
            )
        })
        .collect();
    assert_eq!(pinned.len(), 11);

    let bundle = SegmentBundle::load(segment_dir()).expect("the bundle verifies");
    let lock = bundle.lock();
    assert_eq!(lock.deployment, SEGMENT);
    assert_eq!(lock.network, "base");
    assert_eq!(lock.spec_version, "1.2.0");
    assert_eq!(lock.features, vec!["nonFatalErrors", "grafting"]);

    let mut covered = Vec::new();
    for file in &lock.files {
        let (sha256, bytes, reference) = pinned
            .get(&file.cid)
            .unwrap_or_else(|| panic!("{} is not an M7-pinned object", file.path));
        assert_eq!(&file.sha256, sha256, "{}", file.path);
        assert_eq!(file.bytes, *bytes, "{}", file.path);
        assert_eq!(
            std::fs::read(segment_dir().join(&file.path)).unwrap(),
            std::fs::read(repo_root().join(reference)).unwrap(),
            "{} differs from {reference}",
            file.path
        );
        covered.push(file.cid.clone());
    }
    covered.sort();
    assert_eq!(covered, pinned.keys().cloned().collect::<Vec<_>>());
}

#[test]
fn graph_node_resolves_the_manifest_as_deployed() {
    let bundle = SegmentBundle::load(segment_dir()).expect("the bundle verifies");
    let manifest = runtime()
        .block_on(bundle.manifest(&logger()))
        .expect("graph-node resolves the manifest");

    assert_eq!(manifest.spec_version.to_string(), "1.2.0");
    assert_eq!(manifest.network_name(), "base");
    assert!(manifest.features.contains(&SubgraphFeature::NonFatalErrors));
    assert!(manifest.features.contains(&SubgraphFeature::Grafting));
    // `grafting` is declared, but there is no graft: the deployment is its own
    // root, so a replay from the Factory's start block is complete.
    assert!(manifest.graft.is_none());

    let sources: Vec<_> = manifest
        .data_sources
        .iter()
        .map(|ds| {
            let ds = ds.as_onchain().expect("an onchain data source");
            (
                ds.name.clone(),
                ds.address.map(|a| address(a.as_slice())),
                ds.start_block,
                ds.mapping.api_version.to_string(),
            )
        })
        .collect();
    assert_eq!(
        sources,
        vec![
            (
                "Factory".to_string(),
                Some(FACTORY.to_string()),
                FACTORY_START,
                "0.0.7".to_string()
            ),
            (
                "NonfungiblePositionManager".to_string(),
                Some(NPM.to_string()),
                NPM_START,
                "0.0.7".to_string()
            ),
        ]
    );

    // Declared calls are spec 1.2.0's: graph-node's parser resolves them and
    // `match_and_decode` attaches them to each trigger. Graph Node runs them
    // ahead of the handler purely to warm its call cache; the handler's own
    // `ethereum.call` is what reaches the cassette here.
    let handlers = |mapping: &graph_chain_ethereum::Mapping| -> Vec<(String, Vec<String>)> {
        mapping
            .event_handlers
            .iter()
            .map(|handler| {
                (
                    handler.handler.clone(),
                    handler
                        .calls
                        .decls
                        .iter()
                        .map(|decl| decl.label.clone())
                        .collect(),
                )
            })
            .collect()
    };
    let factory = manifest.data_sources[0].as_onchain().unwrap();
    assert_eq!(
        handlers(&factory.mapping),
        vec![("handlePoolCreated".to_string(), vec![])]
    );
    let npm = manifest.data_sources[1].as_onchain().unwrap();
    assert_eq!(
        handlers(&npm.mapping),
        [
            "handleIncreaseLiquidity",
            "handleDecreaseLiquidity",
            "handleCollect",
            "handleTransfer"
        ]
        .iter()
        .map(|name| (name.to_string(), vec!["positions".to_string()]))
        .collect::<Vec<_>>()
    );

    assert_eq!(manifest.templates.len(), 1);
    let pool = manifest.templates[0]
        .as_onchain()
        .expect("an onchain template");
    assert_eq!(pool.name, "Pool");
    assert_eq!(pool.mapping.api_version.to_string(), "0.0.7");
    let fee_growth = vec![
        "feeGrowthGlobal0X128".to_string(),
        "feeGrowthGlobal1X128".to_string(),
    ];
    let ticks = vec!["poolTickLower".to_string(), "poolTickUpper".to_string()];
    let mut pool_handlers = handlers(&pool.mapping);
    for (_, labels) in pool_handlers.iter_mut() {
        labels.sort();
    }
    assert_eq!(
        pool_handlers,
        vec![
            ("handleInitialize".to_string(), vec![]),
            ("handleSwap".to_string(), fee_growth.clone()),
            ("handleMint".to_string(), ticks.clone()),
            ("handleBurn".to_string(), ticks),
            ("handleFlash".to_string(), fee_growth),
        ]
    );
}

#[test]
fn the_host_takes_every_identity_from_the_manifest() {
    let temp = tempfile::tempdir().expect("temp dir");
    let host = runtime()
        .block_on(SegmentHost::load(SegmentHostConfig {
            bundle_dir: &segment_dir(),
            // An absent cassette is an empty one. Nothing is replayed here.
            cassette_path: &temp.path().join("cassette.json"),
            record: false,
        }))
        .expect("loading the segment");

    let identity = host.checkpoint_identity();
    assert_eq!(identity.deployment, SEGMENT);
    assert_eq!(identity.network, "base");
    assert_eq!(identity.spec_version, "1.2.0");
    assert_eq!(identity.poi_version, "fast");
    assert_eq!(identity.poi_causality_region, "ethereum/base");
    assert_eq!(identity.deterministic_error_policy, "non_fatal");
    assert_eq!(identity.descriptor_sha256, DESCRIPTOR_SHA256);
    assert_eq!(host.descriptor_sha256(), DESCRIPTOR_SHA256);

    let compatibility = host.compatibility();
    assert_eq!(
        compatibility.expected_poi_causality_region(),
        "ethereum/base"
    );
    assert_eq!(
        compatibility.deterministic_error_policy(),
        pb::DeterministicErrorPolicy::NonFatal
    );

    // The Factory's start block, not the NPM's: the lowest data source start.
    assert_eq!(
        host.bounds(),
        SegmentBounds {
            start: FACTORY_START,
            end: None
        }
    );
    assert!(!host.is_grafted());
    host.bounds()
        .check_range(FACTORY_START, FACTORY_START + 1)
        .expect("the root block is in range");
    let refused = host
        .bounds()
        .check_range(FACTORY_START - 1, FACTORY_START + 1)
        .expect_err("a block before the root is refused");
    assert!(
        format!("{refused:#}").contains("first block 13843704"),
        "{refused:#}"
    );
}

#[test]
fn the_descriptor_regenerates_byte_for_byte() {
    let temp = tempfile::tempdir().expect("temp dir");
    let copy = temp.path().join(SEGMENT);
    copy_dir(&segment_dir(), &copy).expect("copying the bundle");
    for name in [descriptor::DESCRIPTOR_FILE, descriptor::DESCRIPTOR_SIDECAR] {
        std::fs::remove_file(copy.join(name)).expect("removing the committed descriptor");
    }

    let digest = runtime()
        .block_on(descriptor::write(&copy, &repo_root(), &logger()))
        .expect("building the descriptor");
    assert_eq!(digest, DESCRIPTOR_SHA256);
    for name in [descriptor::DESCRIPTOR_FILE, descriptor::DESCRIPTOR_SIDECAR] {
        assert_eq!(
            std::fs::read(copy.join(name)).unwrap(),
            std::fs::read(segment_dir().join(name)).unwrap(),
            "{name} does not regenerate byte for byte"
        );
    }

    let text = std::fs::read_to_string(segment_dir().join(descriptor::DESCRIPTOR_FILE)).unwrap();
    let value: serde_json::Value = serde_json::from_str(&text).unwrap();
    assert_eq!(value["graph_node"]["poi_version"], "fast");
    assert_eq!(value["deterministic_error_policy"], "non_fatal");
    assert_eq!(value["expected_poi_causality_region"], "ethereum/base");
    assert_eq!(value["network"], "base");
    assert_eq!(value["spec_version"], "1.2.0");
    assert_eq!(
        value["storage_profile"]["entity_types"]
            .as_array()
            .unwrap()
            .len(),
        20
    );
}

fn copy_dir(from: &Path, to: &Path) -> std::io::Result<()> {
    std::fs::create_dir_all(to)?;
    for entry in std::fs::read_dir(from)? {
        let entry = entry?;
        let target = to.join(entry.file_name());
        if entry.path().is_dir() {
            copy_dir(&entry.path(), &target)?;
        } else {
            std::fs::copy(entry.path(), &target)?;
        }
    }
    Ok(())
}

/// The two Base block fixtures, with the SHA-256 each file must have. The same
/// digests are in `aerodrome-slipstream-base/fixtures/blocks.lock.json`.
///
/// * 13,899,663 is the first block in which anything indexed happens: the first
///   `PoolCreated`, and the first NonfungiblePositionManager events, all in one
///   multicall transaction. Every block from the root at 13,843,704 to here
///   triggers no handler, which the root-window evidence shows by replaying
///   them.
/// * 52,800,000 is a dense recent block: 2,631 logs, 501 of them from the
///   position manager, three OP-stack deposit transactions (type `0x7e`) and two
///   EIP-7702 transactions.
const FIXTURES: &[(i32, &str)] = &[
    (
        13_899_663,
        "5ac312712fef494a8c03f62c0987bba3339c5f693187e5f272467eee06af59ce",
    ),
    (
        52_800_000,
        "06fe030c7921ee57b12f711f5cfb66040f5b578b25cf86dc66c9cec6e809d957",
    ),
];
const BLOCKS_LOCK: &str = "aerodrome-slipstream-base/fixtures/blocks.lock.json";
/// The live root-window run's complete per-block file, a locked release asset
/// (`mapping-host/evidence/aerodrome-root-window.lock.json`).
const LIVE_PER_BLOCK: &str = "evidence/aerodrome-first-pools-13899663-13919663.all-blocks.jsonl";

/// A frame's operations by kind and store disposition.
fn dispositions(changes: &pb::BlockChanges) -> BTreeMap<&'static str, usize> {
    let mut counts = BTreeMap::new();
    for operation in &changes.operations {
        let kind = match &operation.operation {
            Some(pb::entity_operation::Operation::Set(set)) => match set.store_disposition() {
                pb::StoreDisposition::Committed => "set_committed",
                pb::StoreDisposition::Discarded => "set_discarded",
                pb::StoreDisposition::BlockDiscarded => "set_block_discarded",
                pb::StoreDisposition::Unspecified => "set_unspecified",
            },
            Some(pb::entity_operation::Operation::Remove(_)) => "remove",
            Some(pb::entity_operation::Operation::DeterministicError(_)) => "deterministic_error",
            None => "empty",
        };
        *counts.entry(kind).or_default() += 1;
    }
    counts
}

/// One handler group as `(stage, log index, handler)`.
fn groups(report: &BlockReport) -> Vec<(usize, u64, String)> {
    report
        .handler_groups
        .iter()
        .flat_map(|group| {
            group.handlers.iter().map(move |handler| {
                (
                    group.stage,
                    group.trigger.log_index,
                    handler.handler.clone(),
                )
            })
        })
        .collect()
}

/// Both fixture blocks replayed in order through one host, each with its report
/// and its frame's dispositions. The dense block needs the first pool behind it,
/// so the two tests below share this one replay.
fn replayed() -> &'static [(BlockReport, BTreeMap<&'static str, usize>)] {
    static REPLAY: OnceLock<Vec<(BlockReport, BTreeMap<&'static str, usize>)>> = OnceLock::new();
    REPLAY.get_or_init(|| {
        let mut blocks = Vec::new();
        for (number, sha256) in FIXTURES {
            let path = repo_root().join(format!(
                "aerodrome-slipstream-base/fixtures/blocks/base/{number}.pb"
            ));
            let bytes = std::fs::read(&path).unwrap_or_else(|e| {
                panic!(
                    "reading {}: {e}; hydrate the Base block fixtures with `cargo xtask \
                     evidence fetch --lock {BLOCKS_LOCK}` from the repository root",
                    path.display()
                )
            });
            assert_eq!(
                &sha256_hex(&bytes),
                sha256,
                "{} is not the pinned fixture",
                path.display()
            );
            blocks.push(block::load_block(&path).expect("one Firehose block per file"));
        }

        runtime().block_on(async {
            let mut host = SegmentHost::load(SegmentHostConfig {
                bundle_dir: &segment_dir(),
                cassette_path: &crate_dir().join(format!("fixtures/cassettes/{SEGMENT}.json")),
                // Replay only: a cassette miss fails the test, it never reaches out.
                record: false,
            })
            .await
            .expect("loading the segment");
            let mut reports = Vec::new();
            for raw in blocks {
                let outcome = host.process_block(raw).await.expect("replaying a fixture");
                let bytes = blockchanges::seal(&outcome.changes, host.compatibility())
                    .expect("sealing a frame");
                let mut report = outcome.report;
                report.block_changes = Some(blockchanges::summarize(&outcome.changes, &bytes));
                reports.push((report, dispositions(&outcome.changes)));
            }
            assert!(!host.cassette().is_dirty());
            reports
        })
    })
}

#[test]
fn the_fixture_digests_are_the_locked_ones() {
    // The digests this file pins and the lock CI hydrates from must agree, or
    // a test could pass against a fixture the release does not hold.
    let lock: serde_json::Value = serde_json::from_slice(
        &std::fs::read(repo_root().join(BLOCKS_LOCK)).expect("reading the block-fixture lock"),
    )
    .expect("parsing the block-fixture lock");
    assert_eq!(lock["release_tag"], "aerodrome-base-block-fixtures-v1");
    let locked: Vec<(String, String)> = lock["assets"]
        .as_array()
        .unwrap()
        .iter()
        .map(|asset| {
            (
                asset["path"].as_str().unwrap().to_string(),
                asset["sha256"].as_str().unwrap().to_string(),
            )
        })
        .collect();
    let pinned: Vec<(String, String)> = FIXTURES
        .iter()
        .map(|(number, sha256)| {
            (
                format!("aerodrome-slipstream-base/fixtures/blocks/base/{number}.pb"),
                sha256.to_string(),
            )
        })
        .collect();
    assert_eq!(locked, pinned);
}

#[test]
fn the_first_pool_block_replays_to_the_live_frame() {
    // Live-frame parity: replayed from its fixture alone, 13,899,663 must give
    // the frame and the PoI the live Firehose run from the root produced for the
    // same block. Nothing before it triggers a handler, so the store behind it
    // is the same empty store either way.
    let first = &replayed()[0].0;
    assert_eq!(first.number, 13_899_663);

    // The wave trap, on real data. Slipstream's `CLFactory.createPool` calls
    // `CLPool.initialize` before it emits `PoolCreated`, so `Initialize` (log
    // 171) precedes `PoolCreated` (172) in the block. The Pool data source does
    // not exist until `handlePoolCreated` runs, so `handleInitialize` and
    // `handleMint` run in wave 1, after the wave-0 position-manager handlers at
    // higher log indices.
    assert_eq!(first.triggers_per_stage, vec![209, 209]);
    assert_eq!(first.hosts_per_stage, vec![2, 1]);
    assert_eq!(
        groups(first),
        vec![
            (0, 172, "handlePoolCreated".to_string()),
            (0, 177, "handleTransfer".to_string()),
            (0, 178, "handleIncreaseLiquidity".to_string()),
            (1, 171, "handleInitialize".to_string()),
            (1, 176, "handleMint".to_string()),
        ]
    );
    assert!(first.deterministic_errors.is_empty());
    let poi = first
        .poi
        .as_ref()
        .expect("a handler ran, so a PoI was written");
    assert_eq!(poi.version, "fast");
    assert_eq!(
        poi.causality_regions.keys().collect::<Vec<_>>(),
        vec!["ethereum/base"]
    );
    let changes = first.block_changes.as_ref().unwrap();

    // The live run's own line for this block, out of its published per-block
    // file: the comparison is against the run, not a constant copied from it.
    let path = crate_dir().join(LIVE_PER_BLOCK);
    let text = std::fs::read_to_string(&path).unwrap_or_else(|e| {
        panic!(
            "reading {}: {e}; hydrate it with `cargo xtask evidence fetch --lock \
             mapping-host/evidence/aerodrome-root-window.lock.json` from the repository root",
            path.display()
        )
    });
    let live: PerBlockLine = text
        .lines()
        .map(|line| serde_json::from_str::<PerBlockLine>(line).expect("a per-block line"))
        .find(|line| line.number == first.number)
        .expect("the live run covers the first pool");
    assert_eq!(changes.frame_sha256, live.frame_sha256);
    assert_eq!(Some(&poi.public_digest), live.poi_public_digest.as_ref());
    assert_eq!(changes.operations, live.operations);
    // The same two digests, spelled out so a reader need not fetch anything.
    assert_eq!(
        changes.frame_sha256,
        "62c0b927ea0a70cedbf20c39a5b6683028c84e97b71dd3c457e41110db8607a3"
    );
    assert_eq!(
        poi.public_digest,
        "6645b82ff589f650cae124a23ac62580f93b3dd59bbc1afc0128bc50a038e765"
    );
    // Every save in the first block committed.
    assert_eq!(replayed()[0].1, BTreeMap::from([("set_committed", 35)]));
}

#[test]
fn the_dense_block_pins_the_non_fatal_path_on_a_synthetic_store_gap() {
    // A regression pin, not parity. 52,800,000 is replayed with only the first
    // pool behind it, so its frame and PoI are this host's own and no live run
    // has produced them. Every OP-stack deposit and EIP-7702 transaction in it
    // converts through graph-node's own codec. The position-manager handlers
    // abort on rows the two-block store does not hold: a gap in the fixture,
    // not deployed behaviour. That gap is what makes this the one replay that
    // reaches the non-fatal path: under `nonFatalErrors` only the failing
    // handlers' saves are discarded, and the block is kept with everything the
    // other handlers wrote.
    let (dense, dispositions) = &replayed()[1];
    assert_eq!(dense.number, 52_800_000);
    assert_eq!(dense.triggers_per_stage, vec![2631]);
    assert_eq!(dense.hosts_per_stage, vec![3]);
    assert_eq!(dense.handler_groups.len(), 255);
    assert_eq!(dense.deterministic_errors.len(), 175);
    assert_eq!(dense.deterministic_error_policy, "non_fatal");
    assert!(!dense.block_discarded);
    let changes = dense.block_changes.as_ref().unwrap();
    assert_eq!(changes.operations, 479);
    assert_eq!(changes.deterministic_errors, 175);
    assert_eq!(
        changes.frame_sha256,
        "6bce40e52a2bf3f12199e1ec899b5bc42f1714a0bf7b73be5635808c042294a8"
    );
    assert_eq!(
        dense.poi.as_ref().unwrap().public_digest,
        "25a7187b3281f077af766830a08e11ecaa17f9423b8fd6edac524b24bf046a5f"
    );
    // The failing handlers' saves are DISCARDED, each group closed by its
    // DeterministicError, and every other save is COMMITTED: the non-fatal
    // policy, not the fatal one, which would have marked them all
    // BLOCK_DISCARDED.
    assert_eq!(
        dispositions,
        &BTreeMap::from([
            ("deterministic_error", 175),
            ("set_committed", 266),
            ("set_discarded", 38),
        ])
    );
}
