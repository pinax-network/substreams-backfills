//! Hermetic replay of Uniswap V3 mainnet segment 1
//! (`Qme66ZNMxSdCQKzaDuvS381whCVYCQjf637sGZCqJHAWHB`, blocks 12,369,621 to
//! 13,450,880) over the committed block fixtures and `eth_call` cassette.
//!
//! Nothing here touches the network. The block fixtures come from
//! `uniswap-v3/fixtures/blocks/mainnet/`, hydrated by
//! `cargo xtask evidence fetch --lock uniswap-v3/fixtures/blocks.lock.json`;
//! the cassette and the golden report are committed under `fixtures/`.
//!
//! The four files hold one block each: 12,369,621, 12,369,739, 12,369,879 and
//! 12,370,523. They are **not** contiguous, which is visible in the results and
//! is discussed in `README.md`.

use std::path::{Path, PathBuf};
use std::sync::OnceLock;

use graph_mapping_host::report::{BlockReport, RunReport};
use graph_mapping_host::runner::{SegmentHost, SegmentHostConfig};
use graph_mapping_host::{block, bundle};

const SEGMENT: &str = "Qme66ZNMxSdCQKzaDuvS381whCVYCQjf637sGZCqJHAWHB";
const FIXTURES: &[&str] = &["12369621", "12369739", "12369879", "12370523"];

/// Entity types the twenty deployed Uniswap V3 modules certify as never written.
const REQUIRED_ABSENT: &[&str] = &["Collect", "Flash", "TickHourData"];

fn crate_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

fn repo_root() -> PathBuf {
    crate_dir()
        .parent()
        .expect("mapping-host has a parent directory")
        .to_path_buf()
}

fn block_fixture(name: &str) -> PathBuf {
    repo_root().join(format!("uniswap-v3/fixtures/blocks/mainnet/{name}.pb"))
}

/// Replaying is not cheap, so every test shares one run.
fn report() -> &'static RunReport {
    static REPORT: OnceLock<RunReport> = OnceLock::new();
    REPORT.get_or_init(|| {
        for name in FIXTURES {
            let path = block_fixture(name);
            assert!(
                path.exists(),
                "missing block fixture {}; run `cargo xtask evidence fetch --lock \
                 uniswap-v3/fixtures/blocks.lock.json` from the repository root",
                path.display()
            );
        }
        let runtime = tokio::runtime::Builder::new_multi_thread()
            .enable_all()
            .build()
            .expect("tokio runtime");
        runtime.block_on(replay())
    })
}

async fn replay() -> RunReport {
    let cassette = crate_dir().join(format!("fixtures/cassettes/{SEGMENT}.json"));
    let mut host = SegmentHost::load(SegmentHostConfig {
        bundle_dir: &crate_dir().join(format!("segments/{SEGMENT}")),
        cassette_path: &cassette,
        // Replay only. A cassette miss must fail the test, never reach out.
        record: false,
    })
    .await
    .expect("loading the segment");

    let mut report = host.new_report();
    let mut blocks = Vec::new();
    for name in FIXTURES {
        blocks.push(block::load_block(&block_fixture(name)).expect("loading a fixture"));
    }
    use graph::blockchain::Block as _;
    blocks.sort_by_key(|b| b.number());
    for b in blocks {
        let number = b.number();
        let outcome = host
            .process_block(b)
            .await
            .unwrap_or_else(|e| panic!("replaying block {number}: {e:#}"));
        let bytes = graph_mapping_host::blockchanges::seal(&outcome.changes, host.compatibility())
            .unwrap_or_else(|e| panic!("sealing block {number}: {e:#}"));
        let mut block_report = outcome.report;
        block_report.block_changes = Some(graph_mapping_host::blockchanges::summarize(
            &outcome.changes,
            &bytes,
        ));
        report.blocks.push(block_report);
    }
    report.cassette_entries = host.cassette().len();
    assert!(
        !host.cassette().is_dirty(),
        "a hermetic replay must not add cassette entries"
    );
    report
}

fn block(number: i32) -> &'static BlockReport {
    report()
        .blocks
        .iter()
        .find(|b| b.number == number)
        .unwrap_or_else(|| panic!("block {number} is not in the report"))
}

#[test]
fn report_matches_the_golden() {
    let golden_path = crate_dir().join(format!("fixtures/reports/{SEGMENT}.json"));
    let golden = std::fs::read_to_string(&golden_path)
        .unwrap_or_else(|e| panic!("reading {}: {e}", golden_path.display()));
    let produced = report().to_json().expect("serialising the report");
    if produced != golden {
        // Write the fresh report next to the golden so a reviewer can diff it.
        let fresh = golden_path.with_extension("json.actual");
        std::fs::write(&fresh, &produced).ok();
        panic!(
            "report differs from {}; fresh output written to {}",
            golden_path.display(),
            fresh.display()
        );
    }
}

#[test]
fn all_four_fixture_blocks_replay() {
    // One block per file since release `block-fixtures-v2`.
    let numbers: Vec<i32> = report().blocks.iter().map(|b| b.number).collect();
    assert_eq!(numbers, vec![12369621, 12369739, 12369879, 12370523]);
}

#[test]
fn hosts_accumulate_across_the_run() {
    // One host set and one store across the whole run, so Pool template
    // instances persist: two manifest hosts, then one more per `PoolCreated`.
    let starts: Vec<usize> = report()
        .blocks
        .iter()
        .map(|b| b.hosts_per_stage[0])
        .collect();
    assert_eq!(starts, vec![2, 2, 3, 4]);
}

#[test]
fn segment_one_uses_the_fatal_error_policy() {
    // No `nonFatalErrors` in this manifest, so one deterministic error discards
    // every other write in the block.
    assert_eq!(report().features, Vec::<String>::new());
    for b in &report().blocks {
        assert_eq!(b.deterministic_error_policy, "fatal", "block {}", b.number);
    }
}

#[test]
fn factory_deployment_block_triggers_no_handler() {
    // 12,369,621 is the Factory's `startBlock`. The Factory contract exists but
    // has emitted no `PoolCreated` yet, and the position manager's own start
    // block is 12,369,651, so no handler runs.
    let b = block(12369621);
    assert!(!b.mapping_triggered);
    assert!(b.handler_groups.is_empty());
    assert_eq!(b.hosts_per_stage, vec![2], "Factory and NPM only");
    assert!(b.triggers_per_stage[0] > 0, "the block does contain logs");
    assert_eq!(b.modification_count, 0);
}

#[test]
fn a_block_with_no_handler_writes_no_poi() {
    // `update_proof_of_indexing` iterates only the causality regions a handler
    // touched, so an untriggered block writes no PoI entity and the digest does
    // not advance. That is Graph Node's behaviour, not a shortcut here.
    for b in &report().blocks {
        assert_eq!(
            b.mapping_triggered,
            b.poi.is_some(),
            "block {} has mapping_triggered={} but poi={}",
            b.number,
            b.mapping_triggered,
            b.poi.is_some()
        );
    }
}

#[test]
fn first_pool_created_builds_the_factory_bundle_pool_and_tokens() {
    let b = block(12369739);
    let group = &b.handler_groups[0];
    let handler = &group.handlers[0];
    assert_eq!(handler.data_source, "Factory");
    assert_eq!(handler.handler, "handlePoolCreated");
    assert_eq!(group.stage, 0, "the Factory is a manifest data source");

    let written: Vec<&str> = handler
        .modifications
        .iter()
        .map(|m| m.entity.as_str())
        .collect();
    assert_eq!(written, vec!["Bundle", "Factory", "Pool", "Token", "Token"]);
    assert!(handler.modifications.iter().all(|m| m.op == "insert"));

    // The Pool template is instantiated from this handler.
    assert_eq!(b.created_data_sources.len(), 1);
    assert_eq!(b.created_data_sources[0].template, "Pool");
    assert_eq!(b.created_data_sources[0].creation_block, 12369739);
}

#[test]
fn legacy_total_supply_is_a_pointer_not_a_supply() {
    // The six legacy mappings convert the ERC-20 `totalSupply` CallResult with
    // `ByteArray.fromI32`, which yields the pointer rather than the value. UNI's
    // real supply is 10^27; anything small enough to be a WASM heap offset is the
    // quirk. This is the executable form of the survey's `total_supply_model`.
    let b = block(12369739);
    let handler = &b.handler_groups[0].handlers[0];
    let tokens: Vec<&std::collections::BTreeMap<String, serde_json::Value>> = handler
        .modifications
        .iter()
        .filter(|m| m.entity == "Token")
        .filter_map(|m| m.data.as_ref())
        .collect();
    assert_eq!(tokens.len(), 2);
    for token in tokens {
        let supply = token["totalSupply"]["data"]
            .as_str()
            .expect("totalSupply is a BigInt string");
        let supply: u128 = supply.parse().expect("totalSupply parses");
        assert!(
            supply < 1_000_000,
            "totalSupply {supply} is too large to be an allocation pointer; the \
             legacy `ByteArray.fromI32` quirk is not reproducing"
        );
    }
}

#[test]
fn pool_template_handlers_run_in_a_later_wave_than_lower_log_indices() {
    // The canonical wave fact. In block 12,369,739 the Pool template's
    // `Initialize` (log 25) and `Mint` (log 29) sit at *lower* log indices than
    // the position manager's `Transfer` (30) and `IncreaseLiquidity` (31), yet
    // they run in stage 1 because the data source that handles them did not
    // exist when stage 0 was scheduled. A flat global log ordering is wrong.
    let b = block(12369739);
    let stage0: Vec<(usize, u64, &str)> = b
        .handler_groups
        .iter()
        .filter(|g| g.stage == 0)
        .map(|g| (g.stage, g.trigger.log_index, g.handlers[0].handler.as_str()))
        .collect();
    let stage1: Vec<(usize, u64, &str)> = b
        .handler_groups
        .iter()
        .filter(|g| g.stage == 1)
        .map(|g| (g.stage, g.trigger.log_index, g.handlers[0].handler.as_str()))
        .collect();

    assert_eq!(
        stage0,
        vec![
            (0, 24, "handlePoolCreated"),
            (0, 30, "handleTransfer"),
            (0, 31, "handleIncreaseLiquidity"),
        ]
    );
    assert_eq!(
        stage1,
        vec![(1, 25, "handleInitialize"), (1, 29, "handleMint")]
    );

    // Stage 1 rescans the whole block, so it sees the same trigger count.
    assert_eq!(b.triggers_per_stage, vec![199, 199]);
    assert_eq!(b.hosts_per_stage, vec![2, 1], "one new Pool host in wave 2");
}

#[test]
fn handler_group_order_is_dense_and_monotonic_per_block() {
    for b in &report().blocks {
        let orders: Vec<u32> = b
            .handler_groups
            .iter()
            .map(|g| g.handler_group_order)
            .collect();
        let expected: Vec<u32> = (0..orders.len() as u32).collect();
        assert_eq!(orders, expected, "block {}", b.number);
    }
}

#[test]
fn source_trigger_order_is_stage_local() {
    // It indexes into the wave's own sorted trigger list, so it may regress
    // between handler groups when a later wave starts over.
    let b = block(12369739);
    let per_stage: Vec<(usize, usize)> = b
        .handler_groups
        .iter()
        .map(|g| (g.stage, g.source_trigger_order))
        .collect();
    assert_eq!(
        per_stage,
        vec![(0, 24), (0, 30), (0, 31), (1, 25), (1, 29)],
        "the last two regress relative to the first three"
    );
    // Within a stage it is non-decreasing.
    for stage in 0..=1 {
        let orders: Vec<usize> = per_stage
            .iter()
            .filter(|(s, _)| *s == stage)
            .map(|(_, o)| *o)
            .collect();
        let mut sorted = orders.clone();
        sorted.sort_unstable();
        assert_eq!(orders, sorted, "stage {stage}");
    }
}

#[test]
fn transaction_upserts_coalesce_across_handlers() {
    // Seven handlers share setter authority over `Transaction`, and in block
    // 12,369,739 every trigger belongs to one transaction, so `handleTransfer`,
    // `handleIncreaseLiquidity` and `handleMint` all upsert the same row.
    //
    // Only the first upsert is observable. `loadTransaction` writes identical
    // values every time, and `EntityCache::as_modifications` emits nothing when a
    // write does not change the entity, so the later handlers produce no
    // modification at all. Shared setter authority is therefore visible in the
    // deployed mappings but *not* in any modification stream, this one included.
    // Detecting the redundant `store.set` calls needs the `HostExports` recorder
    // patch that phase 2 adds.
    let b = block(12369739);

    let transactions: Vec<&str> = b
        .handler_groups
        .iter()
        .map(|g| g.trigger.transaction_hash.as_str())
        .collect();
    assert_eq!(transactions.len(), 5);
    assert!(
        transactions.windows(2).all(|w| w[0] == w[1]),
        "every trigger in this block is in one transaction: {transactions:?}"
    );

    let mut writers: Vec<(&str, &str, &str)> = Vec::new();
    for group in &b.handler_groups {
        for handler in &group.handlers {
            for m in &handler.modifications {
                if m.entity == "Transaction" {
                    writers.push((
                        handler.data_source.as_str(),
                        handler.handler.as_str(),
                        m.id.as_str(),
                    ));
                }
            }
        }
    }
    assert_eq!(
        writers,
        vec![(
            "NonfungiblePositionManager",
            "handleTransfer",
            transactions[0]
        )],
        "only the first upsert of the shared row shows up"
    );
}

#[test]
fn required_absent_entities_are_never_written() {
    for b in &report().blocks {
        for group in &b.handler_groups {
            for handler in &group.handlers {
                for m in &handler.modifications {
                    assert!(
                        !REQUIRED_ABSENT.contains(&m.entity.as_str()),
                        "block {} handler {} wrote a {} row",
                        b.number,
                        handler.handler,
                        m.entity
                    );
                }
            }
        }
        for entity in REQUIRED_ABSENT {
            assert!(
                !b.store_counts.contains_key(*entity),
                "block {} left {} rows in the store",
                b.number,
                entity
            );
        }
    }
}

#[test]
fn handle_flash_never_runs() {
    // The Pool template declares `handleFlash`, but no `Flash` event occurs in
    // the first 2,500 blocks after the factory, so it is never invoked here.
    for b in &report().blocks {
        for group in &b.handler_groups {
            for handler in &group.handlers {
                assert_ne!(handler.handler, "handleFlash", "block {}", b.number);
            }
        }
    }
}

#[test]
fn a_fixture_gap_error_exercises_the_fatal_discard_path() {
    // READ THIS BEFORE TREATING THE ERRORS BELOW AS DEPLOYED BEHAVIOUR.
    //
    // The two deterministic errors in block 12,370,523 are an artifact of this
    // fixture set, not something the deployed subgraph does at this height. The
    // position manager events here concern token id 33, whose position lives in
    // pool `0xdc7b403e2e967eaf6c97d79316d285b8a112fda7` with token0
    // `0x956f47f50a910163d8bf957cf5846d573e7f87ca`. That pool was created
    // somewhere in 12,369,881 to 12,370,522, which the four sampled fixture
    // files do not cover, so no `Token` row for it exists in this run's store.
    // `Token.load` returns null and the old-codegen dereference aborts the
    // handler. The contiguous replay of 12,369,621 to 12,370,673 has since
    // confirmed that: it has the row, and the same block runs handleBurn,
    // handleDecreaseLiquidity and handleCollect cleanly, 23 operations and no
    // error. See `evidence/parity-window-12369621-12370674.json` and
    // `tests/mapping_host/parity_window_evidence.rs`.
    //
    // What this test therefore asserts is the *host's* fatal-policy machinery —
    // that a deterministic error under a manifest without `nonFatalErrors`
    // discards every non-PoI write in the block and leaves the store untouched —
    // using a conveniently available error as the input. It asserts nothing
    // about what the deployed mapping does at block 12,370,523.
    let b = block(12370523);

    // Pin the cause, so a future change that makes these handlers fail for some
    // other reason does not quietly keep passing.
    assert_eq!(b.deterministic_errors.len(), 2);
    for e in &b.deterministic_errors {
        assert!(
            e.contains("Token#get:decimals") && e.contains("Value is not a BigInt"),
            "the error should still be the missing-Token dereference: {e}"
        );
    }

    let handlers: Vec<(&str, &str, &str)> = b
        .handler_groups
        .iter()
        .flat_map(|g| g.handlers.iter())
        .map(|h| {
            (
                h.data_source.as_str(),
                h.handler.as_str(),
                h.outcome.as_str(),
            )
        })
        .collect();
    assert_eq!(
        handlers,
        vec![
            (
                "NonfungiblePositionManager",
                "handleDecreaseLiquidity",
                "deterministic_error"
            ),
            (
                "NonfungiblePositionManager",
                "handleCollect",
                "deterministic_error"
            ),
        ]
    );

    // The host's part: the block is discarded, each handler rolled itself back,
    // and only the PoI survives.
    assert!(b.block_discarded);
    assert_eq!(b.modification_count, 0);
    assert!(b.poi.is_some(), "the PoI still advances");

    // The store is unchanged across a discarded block, apart from the PoI row.
    let before = block(12369879);
    for (entity, count) in &before.store_counts {
        if entity == "Poi$" {
            continue;
        }
        assert_eq!(
            b.store_counts.get(entity),
            Some(count),
            "{entity} changed across a discarded block"
        );
    }
}

#[test]
fn the_fixture_set_leaves_five_handlers_unexercised() {
    // Four sampled blocks, not a contiguous range. Any handler whose data source
    // was created in an unsampled block cannot fire here, so this run is silent
    // about Swap, Burn, Flash, and a *successful* Collect or DecreaseLiquidity.
    // Recorded as a test so the gap cannot be forgotten when reading the report.
    //
    // This is a fact about the *fixture set*, and it stays one. Four of those
    // five have since run successfully in the contiguous parity-window replay
    // (`evidence/parity-window-12369621-12370674.json`); only handleFlash is
    // unexercised there too, because the window holds no Flash event. Keeping
    // this assertion hermetic is the point: it pins what these four blocks can
    // and cannot show, so the two kinds of evidence are never conflated.
    let ran: Vec<&str> = report()
        .blocks
        .iter()
        .flat_map(|b| b.handler_groups.iter())
        .flat_map(|g| g.handlers.iter())
        .map(|h| h.handler.as_str())
        .collect();
    for unexercised in ["handleSwap", "handleBurn", "handleFlash"] {
        assert!(
            !ran.contains(&unexercised),
            "{unexercised} ran in the four-block fixture replay; the fixture gap discussion in \
             README.md needs updating"
        );
    }
    // The two that did run, ran only as failures.
    for h in ["handleCollect", "handleDecreaseLiquidity"] {
        let outcomes: Vec<&str> = report()
            .blocks
            .iter()
            .flat_map(|b| b.handler_groups.iter())
            .flat_map(|g| g.handlers.iter())
            .filter(|x| x.handler == h)
            .map(|x| x.outcome.as_str())
            .collect();
        assert!(
            !outcomes.is_empty() && outcomes.iter().all(|o| *o == "deterministic_error"),
            "{h} outcomes were {outcomes:?}; no successful run is covered here"
        );
    }
}

#[test]
fn poi_is_legacy_for_this_spec_version() {
    assert_eq!(report().spec_version, "0.0.2");
    for b in &report().blocks {
        if let Some(poi) = &b.poi {
            assert_eq!(poi.version, "legacy");
            assert_eq!(poi.public_digest.len(), 64);
            assert_eq!(
                poi.causality_regions.keys().collect::<Vec<_>>(),
                vec!["ethereum/mainnet"]
            );
        }
    }
}

#[test]
fn gas_is_not_reachable_through_the_public_api() {
    // Documented limitation rather than an oversight: `process_mapping_trigger`
    // discards the `Gas` it is handed. If this ever starts reporting a value the
    // README's reuse boundary needs updating.
    for b in &report().blocks {
        for group in &b.handler_groups {
            for handler in &group.handlers {
                assert!(handler.gas.is_none());
            }
        }
    }
}

#[test]
fn every_segment_bundle_verifies() {
    let segments = crate_dir().join("segments");
    let mut found = Vec::new();
    for entry in std::fs::read_dir(&segments).expect("listing segments") {
        let path = entry.expect("a segment directory").path();
        if !path.is_dir() {
            continue;
        }
        let bundle = bundle::SegmentBundle::load(&path)
            .unwrap_or_else(|e| panic!("verifying {}: {e:#}", path.display()));
        assert!(!bundle.lock().files.is_empty());
        assert!(bundle
            .lock()
            .files
            .iter()
            .any(|f| f.path == "manifest.yaml"));
        assert!(bundle
            .lock()
            .files
            .iter()
            .any(|f| f.path == "schema.graphql"));
        found.push(bundle.lock().deployment.clone());
    }
    found.sort();
    // All eight Uniswap V3 deployments, plus the Aerodrome Slipstream Base
    // oracle segment.
    assert_eq!(
        found,
        vec![
            "QmPWDTWRfS8XewMJhxXoQiZX6RkrUMYH7BFnnB846v6wzR",
            "QmRvEgUpbjVV326W2zPvxWimzQwcDREfjejUdFn2L92qry",
            "QmS13421u6qsbVdBCrZhdRaZw2wH67drwF3urmueJvvJ5P",
            "QmSLHXCZBNKVtJRrWiEAF1yRQNPqAFptBsAcLdXQPsubSX",
            "QmTZ8ejXJxRo7vDBS4uwqBeGoxLSWbhaA7oXa1RvxunLy7",
            "QmZeCuoZeadgHkGwLwMeguyqUKz1WPWQYKcKyMCeQqGhsF",
            "QmasYjypV6nTLp4iNH4Vjf7fksRNxAkAskqDdKf2DCsQkV",
            "Qmb4VUcAY9LsVgeCuCCMs7X1XrkbRcaiuAbSK8SqhmsAfP",
            "Qme66ZNMxSdCQKzaDuvS381whCVYCQjf637sGZCqJHAWHB",
        ]
    );
}

#[test]
fn the_bundle_loader_refuses_drift() {
    let source = crate_dir().join(format!("segments/{SEGMENT}"));
    let temp = tempfile::tempdir().expect("temp dir");
    let target = temp.path().join(SEGMENT);
    copy_dir(&source, &target).expect("copying the bundle");
    bundle::SegmentBundle::load(&target).expect("the copy verifies");

    // Flip one byte of the schema.
    let schema = target.join("schema.graphql");
    let mut bytes = std::fs::read(&schema).expect("reading the schema");
    bytes[0] ^= 0x01;
    std::fs::write(&schema, &bytes).expect("writing the schema");
    let err = match bundle::SegmentBundle::load(&target) {
        Ok(_) => panic!("drift must be refused"),
        Err(e) => e,
    };
    assert!(format!("{err:#}").contains("bundle drift"), "{err:#}");

    // An unlisted file is drift too.
    std::fs::write(&schema, &bytes[..]).ok();
    copy_dir(&source, &target).expect("restoring the bundle");
    std::fs::write(target.join("abis/Extra.json"), b"[]").expect("adding a file");
    let err = match bundle::SegmentBundle::load(&target) {
        Ok(_) => panic!("an extra file must be refused"),
        Err(e) => e,
    };
    assert!(format!("{err:#}").contains("bundle drift"), "{err:#}");
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

#[test]
fn a_multi_message_fixture_is_refused() {
    // Release `block-fixtures-v1` shipped two blocks per file, which prost
    // merges silently into a block claiming to be N+1 while carrying N's logs.
    // The loader refuses that shape rather than trusting the release tag, so the
    // check is made against a synthetic concatenation rather than a v1 file.
    let first = std::fs::read(block_fixture(FIXTURES[0])).expect("a fixture");
    let second = std::fs::read(block_fixture(FIXTURES[1])).expect("a fixture");
    let mut concatenated = first.clone();
    concatenated.extend_from_slice(&second);

    let temp = tempfile::tempdir().expect("temp dir");
    let path = temp.path().join("two-blocks.pb");
    std::fs::write(&path, &concatenated).expect("writing the concatenation");

    let error = match block::load_block(&path) {
        Ok(_) => panic!("a two-message fixture must be refused"),
        Err(error) => format!("{error:#}"),
    };
    assert!(
        error.contains("exactly one block"),
        "unexpected error: {error}"
    );
    assert!(
        error.contains("the second is block 12369739"),
        "the error must name the second block: {error}"
    );
    assert!(
        error.contains(&first.len().to_string()),
        "the error must give the second block's offset: {error}"
    );

    // The detector still sees both, which is how the refusal knows what to say.
    let chunks = block::split_messages(&concatenated).expect("splitting");
    assert_eq!(chunks.len(), 2);
    assert_eq!(chunks[0].0, 0);
    assert_eq!(chunks[1].0, first.len());
}

#[test]
fn each_hydrated_fixture_holds_exactly_one_block() {
    use graph::blockchain::Block as _;
    for name in FIXTURES {
        let block =
            block::load_block(&block_fixture(name)).unwrap_or_else(|e| panic!("{name}: {e:#}"));
        let expected: i32 = name.parse().expect("fixture names are block numbers");
        assert_eq!(block.number(), expected, "{name}");
    }
}

#[test]
fn split_messages_rejects_a_truncated_stream() {
    let bytes = std::fs::read(block_fixture(FIXTURES[0])).expect("reading a fixture");
    let truncated = &bytes[..bytes.len() - 1];
    let split = block::split_messages(truncated);
    // Either the split itself fails, or the last chunk fails to decode.
    match split {
        Err(_) => {}
        Ok(chunks) => {
            let last = chunks.last().expect("at least one chunk").1;
            use graph::prelude::prost::Message;
            assert!(
                graph_chain_ethereum::codec::Block::decode(last).is_err(),
                "a truncated stream must not decode cleanly"
            );
        }
    }

    // And the loader refuses it whichever way that lands.
    let temp = tempfile::tempdir().expect("temp dir");
    let path = temp.path().join("truncated.pb");
    std::fs::write(&path, truncated).expect("writing the truncation");
    assert!(block::load_block(&path).is_err());
}
