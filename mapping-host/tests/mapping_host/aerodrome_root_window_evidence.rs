//! The committed evidence for the Aerodrome Slipstream Base root window: two
//! contiguous live replays that together cover blocks 13,843,704 to 13,919,662.
//!
//! * `aerodrome-root-prefix-13843704-13899663.json` starts at the deployment's
//!   root, the Factory's start block, and stops just before the first
//!   `PoolCreated`. Every one of its 55,959 blocks triggered nothing.
//! * `aerodrome-first-pools-13899663-13919663.json` continues from the prefix's
//!   checkpoint over the first thirteen pools and the first 20,000 blocks of
//!   activity.
//!
//! Both are `run-evidence/v2` summaries written by `graph-mapping-host summarize
//! --per-block-scope handler-blocks`. What they were derived from is not
//! committed but locked, by digest, in `evidence/aerodrome-root-window.lock.json`:
//! each run's streamed report, the window's cassette and every per-block file
//! either summary names. CI hydrates that lock with `cargo xtask evidence fetch`
//! before `cargo test`, and the tests at the bottom re-derive **both summaries,
//! byte for byte, from the published reports**, so no count, digest or pin in
//! them can drift from the run without failing here. The run's frames (`BCF1`),
//! final store and checkpoints are locked separately, in
//! `evidence/aerodrome-root-window-archive.lock.json`, which CI does not fetch.
//!
//! Hermetic either way: hydration reads a release asset or a local cache and the
//! tests never open a socket.

use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};
use std::sync::OnceLock;

use graph_mapping_host::bundle::sha256_hex;
use graph_mapping_host::evidence::{
    self, DataSourceCreation, Narrative, PerBlockLine, PerBlockScope, RunEvidence, SummarizeInputs,
    EVIDENCE_SCHEMA_V2,
};

const SEGMENT: &str = "QmasYjypV6nTLp4iNH4Vjf7fksRNxAkAskqDdKf2DCsQkV";
const PREFIX: &str = "evidence/aerodrome-root-prefix-13843704-13899663.json";
const WINDOW: &str = "evidence/aerodrome-first-pools-13899663-13919663.json";
/// What CI fetches: everything the two summaries are derived from or pin.
const WINDOW_LOCK: &str = "evidence/aerodrome-root-window.lock.json";
/// What CI does not fetch: the frames, the final store and the checkpoints.
const ARCHIVE_LOCK: &str = "evidence/aerodrome-root-window-archive.lock.json";
/// The Factory's start block, which is the deployment's root: there is no graft.
const ROOT: i32 = 13_843_704;
/// The first block with a `PoolCreated` from the Factory.
const FIRST_POOL: i32 = 13_899_663;

fn crate_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

fn load(path: &str) -> RunEvidence {
    let path = crate_dir().join(path);
    let bytes = std::fs::read(&path).unwrap_or_else(|e| panic!("reading {}: {e}", path.display()));
    serde_json::from_slice(&bytes).unwrap_or_else(|e| panic!("parsing {}: {e}", path.display()))
}

fn prefix() -> &'static RunEvidence {
    static FILE: OnceLock<RunEvidence> = OnceLock::new();
    FILE.get_or_init(|| load(PREFIX))
}

fn window() -> &'static RunEvidence {
    static FILE: OnceLock<RunEvidence> = OnceLock::new();
    FILE.get_or_init(|| load(WINDOW))
}

/// A summary's path without `.json`: every artifact of that run is named
/// `<stem>.<kind>`.
fn stem(summary: &str) -> &str {
    summary
        .strip_suffix(".json")
        .expect("a summary is a .json file")
}

/// A file a summary names, as a path relative to the crate.
fn beside(summary: &str, file: &str) -> String {
    Path::new(summary)
        .parent()
        .unwrap()
        .join(file)
        .to_string_lossy()
        .to_string()
}

/// `(release tag, [(path relative to the crate, bytes, sha256)])` for a lock.
fn locked(lock: &str) -> (String, Vec<(String, usize, String)>) {
    let path = crate_dir().join(lock);
    let value: serde_json::Value = serde_json::from_slice(
        &std::fs::read(&path).unwrap_or_else(|e| panic!("reading {}: {e}", path.display())),
    )
    .unwrap_or_else(|e| panic!("parsing {}: {e}", path.display()));
    assert_eq!(
        value["schema"],
        "pinax.substreams-backfills.evidence-assets/v1"
    );
    assert_eq!(value["repository"], "pinax-network/substreams-backfills");
    let assets = value["assets"]
        .as_array()
        .expect("a lock lists assets")
        .iter()
        .map(|asset| {
            let path = asset["path"].as_str().unwrap();
            (
                path.strip_prefix("mapping-host/")
                    .unwrap_or_else(|| panic!("{path} is not under mapping-host/"))
                    .to_string(),
                asset["bytes"].as_u64().unwrap() as usize,
                asset["sha256"].as_str().unwrap().to_string(),
            )
        })
        .collect();
    (value["release_tag"].as_str().unwrap().to_string(), assets)
}

/// The bytes of a hydrated asset, failing closed with the command that fetches
/// it.
fn hydrated(relative: &str) -> Vec<u8> {
    let path = crate_dir().join(relative);
    std::fs::read(&path).unwrap_or_else(|e| {
        panic!(
            "reading {}: {e}; hydrate it with `cargo xtask evidence fetch --lock \
             mapping-host/{WINDOW_LOCK}` from the repository root",
            path.display()
        )
    })
}

fn per_block_lines(bytes: &[u8]) -> Vec<PerBlockLine> {
    std::str::from_utf8(bytes)
        .expect("a per-block file is UTF-8")
        .lines()
        .enumerate()
        .map(|(index, line)| {
            serde_json::from_str(line)
                .unwrap_or_else(|e| panic!("per-block line {}: {e}", index + 1))
        })
        .collect()
}

#[test]
fn both_summaries_describe_the_aerodrome_oracle_segment() {
    for (path, evidence) in [(PREFIX, prefix()), (WINDOW, window())] {
        // Sparse, so v2: a v1 reader must refuse these rather than read the
        // sparse file as the whole range.
        assert_eq!(evidence.schema, EVIDENCE_SCHEMA_V2);
        evidence.check_schema().expect("version matches shape");
        let deployment = &evidence.deployment;
        assert_eq!(deployment.deployment, SEGMENT);
        assert_eq!(deployment.network, "base");
        assert_eq!(deployment.spec_version, "1.2.0");
        assert_eq!(deployment.api_versions, vec!["0.0.7"]);
        assert_eq!(deployment.features, vec!["nonFatalErrors", "grafting"]);
        assert_eq!(
            deployment.graph_node_rev,
            graph_mapping_host::runner::GRAPH_NODE_REV
        );
        assert!(deployment
            .source
            .starts_with("Firehose base.firehose.pinax.network:443 blocks ["));
        assert!(evidence.range.contiguous);
        assert_eq!(evidence.range.blocks, evidence.totals.blocks);
        assert_eq!(
            evidence.range.blocks,
            (evidence.range.to - evidence.range.from) as usize
        );
        assert_eq!(evidence.range.first_block, evidence.range.from);
        assert_eq!(evidence.range.last_block, evidence.range.to - 1);
        // Sparse, and still pinning every block, under the names the lock uses.
        let per_block = &evidence.per_block;
        assert_eq!(
            beside(path, &per_block.file),
            format!("{}.blocks.jsonl", stem(path))
        );
        let all = per_block
            .all_blocks
            .as_ref()
            .expect("the complete file is pinned");
        assert_eq!(
            beside(path, &all.file),
            format!("{}.all-blocks.jsonl", stem(path))
        );
        assert_eq!(all.lines, evidence.range.blocks);
    }
}

#[test]
fn the_two_runs_cover_the_root_window_without_a_gap() {
    assert_eq!(prefix().range.from, ROOT);
    assert_eq!(prefix().range.to, FIRST_POOL);
    assert_eq!(window().range.from, prefix().range.to);
}

#[test]
fn nothing_happens_between_the_root_and_the_first_pool() {
    // The claim that makes every block before 13,899,663 irrelevant to the
    // store and the PoI chain, checked from the summary alone: no handler ran,
    // no PoI was written, no operation was sealed, and the sparse per-block
    // file is empty, which its pinned digest proves without the file.
    let evidence = prefix();
    let totals = &evidence.totals;
    assert_eq!(totals.blocks, 55_959);
    assert_eq!(totals.blocks_with_handlers, 0);
    assert_eq!(totals.blocks_with_poi, 0);
    assert_eq!(totals.handler_groups, 0);
    assert_eq!(totals.operations, 0);
    assert_eq!(totals.created_data_sources, 0);
    assert_eq!(evidence.data_source_creations, Some(Vec::new()));
    assert_eq!(totals.deterministic_errors, 0);
    assert!(evidence.handlers.invocations.is_empty());
    assert!(evidence.final_poi.is_none());
    assert!(evidence.final_store_counts.is_empty());
    assert_eq!(evidence.per_block.lines, 0);
    assert_eq!(evidence.per_block.bytes, 0);
    assert_eq!(evidence.per_block.sha256, sha256_hex(b""));
    // One wave per block, because no data source was ever created.
    assert_eq!(totals.max_waves, 1);
}

#[test]
fn the_window_totals_are_internally_consistent() {
    let evidence = window();
    let totals = &evidence.totals;
    assert_eq!(totals.sets + totals.removes, totals.operations);
    // No deployed Aerodrome module imports `store.remove`.
    assert_eq!(totals.removes, 0);
    assert_eq!(totals.deterministic_errors, 0);
    assert_eq!(totals.blocks_discarded, 0);
    assert_eq!(
        evidence.handlers.outcomes.keys().collect::<Vec<_>>(),
        vec!["ok"]
    );
    assert!(totals.collapsed_modifications < totals.operations);
    assert_eq!(
        totals.collapsed_modifications,
        evidence.modifications_by_entity.values().sum::<usize>()
    );
    for sum in [
        evidence.handlers.invocations.values().sum::<usize>(),
        evidence.handlers.outcomes.values().sum::<usize>(),
        evidence.data_source_invocations.values().sum::<usize>(),
    ] {
        assert_eq!(totals.handler_invocations, sum);
    }
    // Every block that ran a handler wrote a PoI, and is in the sparse file.
    assert_eq!(totals.blocks_with_handlers, totals.blocks_with_poi);
    assert_eq!(evidence.per_block.lines, totals.blocks_with_poi);

    // Thirteen pools: thirteen `PoolCreated`, thirteen data sources, thirteen
    // `Pool` rows. Where each pool's handlers ran is the next test's subject.
    let invocations = &evidence.handlers.invocations;
    assert_eq!(totals.created_data_sources, 13);
    assert_eq!(invocations["handlePoolCreated"], 13);
    assert_eq!(evidence.final_store_counts["Pool"], 13);
    assert_eq!(evidence.data_source_invocations["Factory"], 13);

    let poi = evidence.final_poi.as_ref().expect("a final PoI");
    assert_eq!(poi.version, "fast");
    assert_eq!(poi.causality_region, "ethereum/base");
    assert!(poi.block <= evidence.range.last_block);
}

/// One creation row's handlers by name, as `(data source, log index, wave)`.
/// Each name occurs once per row in this window.
fn by_name(row: &DataSourceCreation) -> BTreeMap<&str, (&str, u64, usize)> {
    let mut named = BTreeMap::new();
    for handler in &row.creation_block_handlers {
        let previous = named.insert(
            handler.handler.as_str(),
            (
                handler.data_source.as_str(),
                handler.log_index,
                handler.wave,
            ),
        );
        assert!(
            previous.is_none(),
            "{} ran twice around the pool created in {}",
            handler.handler,
            row.block
        );
        assert_eq!(handler.outcome, "ok");
    }
    named
}

#[test]
fn every_pool_creation_in_the_window_is_the_wave_trap() {
    // The wave trap for all thirteen pools, not only the one block a fixture
    // replays. `summarize` derives the rows from the report, and the
    // re-derivation test below holds them to the published report.
    let evidence = window();
    let rows = evidence
        .data_source_creations
        .as_ref()
        .expect("a v2 summary records every creation");
    assert_eq!(rows.len(), evidence.totals.created_data_sources);
    assert_eq!(rows.len(), 13);
    assert_eq!(evidence.totals.max_waves, 2);
    assert_eq!(rows[0].block, FIRST_POOL);
    for pair in rows.windows(2) {
        assert!(
            pair[0].block < pair[1].block,
            "one pool per block, ascending"
        );
    }

    for row in rows {
        let block = row.block;
        assert!(block >= evidence.range.from && block < evidence.range.to);
        assert_eq!(row.template, "Pool");
        assert_eq!(row.params.len(), 1, "a Pool is created for one address");
        assert!(row.transaction_hash.is_some());
        let created_by = row.created_by.as_ref().expect("the creator is reported");
        assert_eq!(
            (
                created_by.data_source.as_str(),
                created_by.handler.as_str(),
                created_by.wave
            ),
            ("Factory", "handlePoolCreated", 0),
            "block {block}"
        );
        let pool_created = created_by.log_index;

        // The creating transaction is a position-manager multicall, so its
        // handlers share the row with the new pool's own.
        let named = by_name(row);
        assert_eq!(
            named.keys().copied().collect::<Vec<_>>(),
            vec![
                "handleIncreaseLiquidity",
                "handleInitialize",
                "handleMint",
                "handlePoolCreated",
                "handleTransfer",
            ],
            "block {block}"
        );
        assert_eq!(named["handleInitialize"].0, "Pool");
        assert_eq!(named["handleMint"].0, "Pool");
        assert_eq!(named["handleTransfer"].0, "NonfungiblePositionManager");
        assert_eq!(
            named["handleIncreaseLiquidity"].0,
            "NonfungiblePositionManager"
        );
        // Every handler on the new pool runs in wave 1, everything else in
        // wave 0.
        for (name, (data_source, _, wave)) in &named {
            let expected = usize::from(*data_source == "Pool");
            assert_eq!(*wave, expected, "{name} in block {block}");
        }

        // And by log index: `Initialize` is the log just before `PoolCreated`,
        // and `Mint` precedes the position manager's `Transfer` and
        // `IncreaseLiquidity`. Log order alone would run both wave-1 handlers
        // too early.
        let (initialize, mint) = (named["handleInitialize"].1, named["handleMint"].1);
        let (transfer, increase) = (
            named["handleTransfer"].1,
            named["handleIncreaseLiquidity"].1,
        );
        assert_eq!(initialize + 1, pool_created, "block {block}");
        assert!(
            pool_created < mint && mint < transfer && transfer < increase,
            "block {block}: PoolCreated {pool_created}, Mint {mint}, Transfer {transfer}, \
             IncreaseLiquidity {increase}"
        );
    }

    // Every `handleInitialize` and `handlePoolCreated` of the window is in a
    // row, so none ran anywhere else or in any other wave.
    let count = |name: &str| {
        rows.iter()
            .flat_map(|row| &row.creation_block_handlers)
            .filter(|handler| handler.handler == name)
            .count()
    };
    let invocations = &evidence.handlers.invocations;
    assert_eq!(count("handleInitialize"), invocations["handleInitialize"]);
    assert_eq!(count("handlePoolCreated"), invocations["handlePoolCreated"]);
}

#[test]
fn the_window_never_writes_what_the_deployed_mapping_cannot() {
    // `Collect` and `Flash` rows and `TickHourData` are declared by the schema
    // and never written: `handleCollect` updates positions without a `Collect`
    // row, and the window holds no `Flash` event at all.
    let entity_types = &window().entity_types;
    assert_eq!(
        entity_types.never_written,
        vec!["Collect", "Flash", "TickHourData"]
    );
    assert_eq!(entity_types.declared.len(), 20);
    assert!(!window().handlers.invocations.contains_key("handleFlash"));
}

#[test]
fn the_cassette_is_the_published_one() {
    // The window's cassette is a locked release asset: the summary records it
    // under the path it hydrates to, and the lock pins the same bytes.
    let cassette = window().cassette.as_ref().expect("cassette facts");
    assert_eq!(cassette.path, format!("{}.cassette.json", stem(WINDOW)));
    let (_, assets) = locked(WINDOW_LOCK);
    assert!(
        assets.contains(&(
            cassette.path.clone(),
            cassette.bytes,
            cassette.sha256.clone()
        )),
        "{WINDOW_LOCK} does not pin the cassette the summary describes"
    );
    assert_eq!(cassette.rows, cassette.rows_by_call.values().sum::<usize>());
    // The nine function signatures the deployed handlers call in this window.
    assert_eq!(
        cassette.rows_by_call.keys().collect::<Vec<_>>(),
        vec![
            "ERC20::decimals()",
            "ERC20::name()",
            "ERC20::symbol()",
            "ERC20::totalSupply()",
            "Factory::getPool(address,address,int24)",
            "NonfungiblePositionManager::positions(uint256)",
            "Pool::feeGrowthGlobal0X128()",
            "Pool::feeGrowthGlobal1X128()",
            "Pool::ticks(int24)",
        ]
    );
    // The prefix made no call at all, so it had no cassette to describe.
    assert!(prefix().cassette.is_none());
}

#[test]
fn every_locked_artifact_is_one_a_summary_names_by_digest() {
    // The two locks and the two summaries describe the same files. The CI lock
    // holds exactly what the re-derivation reads and what the summaries pin; the
    // archive lock holds the rest, and each of its digests is stated in the
    // summary of the run that wrote it.
    let (tag, assets) = locked(WINDOW_LOCK);
    assert_eq!(tag, "aerodrome-root-window-evidence-v1");
    // Path to the `(bytes, sha256)` a summary pins, or `None` for a report,
    // which no summary can pin because it is the summary's input.
    let mut named: BTreeMap<String, Option<(usize, String)>> = BTreeMap::new();
    for summary in [PREFIX, WINDOW] {
        let evidence = load(summary);
        named.insert(format!("{}.report.jsonl", stem(summary)), None);
        let all = evidence.per_block.all_blocks.as_ref().unwrap();
        named.insert(
            beside(summary, &all.file),
            Some((all.bytes, all.sha256.clone())),
        );
        // An empty sparse file is pinned by the empty digest and not published.
        let per_block = &evidence.per_block;
        if per_block.bytes > 0 {
            named.insert(
                beside(summary, &per_block.file),
                Some((per_block.bytes, per_block.sha256.clone())),
            );
        }
        if let Some(cassette) = &evidence.cassette {
            named.insert(
                cassette.path.clone(),
                Some((cassette.bytes, cassette.sha256.clone())),
            );
        }
    }
    for (path, bytes, sha256) in &assets {
        let pinned = named
            .get(path)
            .unwrap_or_else(|| panic!("{path} is locked but no summary names it"));
        if let Some(pinned) = pinned {
            assert_eq!(&(*bytes, sha256.clone()), pinned, "{path}");
        }
    }
    assert_eq!(
        assets
            .iter()
            .map(|(path, _, _)| path.clone())
            .collect::<BTreeSet<_>>(),
        named.keys().cloned().collect::<BTreeSet<_>>(),
        "a summary names a file the lock does not publish"
    );

    let (tag, archive) = locked(ARCHIVE_LOCK);
    assert_eq!(tag, "aerodrome-root-window-archive-v1");
    let kinds: BTreeSet<String> = archive
        .iter()
        .map(|(path, _, _)| {
            let (summary, kind) = [PREFIX, WINDOW]
                .into_iter()
                .find_map(|summary| {
                    path.strip_prefix(&format!("{}.", stem(summary)))
                        .map(|kind| (summary, kind))
                })
                .unwrap_or_else(|| panic!("{path} belongs to neither run"));
            format!("{}:{kind}", stem(summary))
        })
        .collect();
    assert_eq!(
        kinds,
        [
            format!("{}:bcf1", stem(PREFIX)),
            format!("{}:checkpoint.jsonl", stem(PREFIX)),
            format!("{}:bcf1", stem(WINDOW)),
            format!("{}:checkpoint.jsonl", stem(WINDOW)),
            format!("{}:store.json", stem(WINDOW)),
        ]
        .into_iter()
        .collect()
    );
    for (path, bytes, sha256) in &archive {
        let summary = if path.starts_with(stem(PREFIX)) {
            PREFIX
        } else {
            WINDOW
        };
        let text = std::fs::read_to_string(crate_dir().join(summary)).unwrap();
        assert!(
            text.contains(sha256.as_str()),
            "{summary} does not state the digest of {path}"
        );
        assert!(*bytes > 0);
    }
}

#[test]
fn neither_summary_carries_a_credential() {
    for path in [PREFIX, WINDOW] {
        let evidence = load(path);
        for name in &evidence.run.environment {
            assert!(
                name.chars()
                    .all(|c| c.is_ascii_uppercase() || c.is_ascii_digit() || c == '_'),
                "{name} is not an environment variable name"
            );
        }
        let text = std::fs::read_to_string(crate_dir().join(path)).unwrap();
        for forbidden in [
            "bearer ",
            "api_key",
            "apikey",
            "/v1/",
            "://",
            "/private/",
            "/users/",
        ] {
            assert!(
                !text.to_lowercase().contains(forbidden),
                "{path} contains {forbidden:?}"
            );
        }
    }
}

#[test]
fn every_finding_is_written_out() {
    for evidence in [prefix(), window()] {
        assert!(!evidence.findings.is_empty());
        for finding in &evidence.findings {
            assert!(!finding.id.is_empty());
            assert!(finding.statement.len() > 200, "{} is a stub", finding.id);
        }
        let run = &evidence.run;
        for value in [
            &run.recorded_on,
            &run.command,
            &run.toolchain,
            &run.firehose_endpoint,
            &run.rpc_endpoint,
            &run.artifacts_not_committed,
            &run.claim_boundary,
        ] {
            assert_ne!(value, "TODO");
        }
        assert!(run.claim_boundary.contains("not a parity claim"));
    }
}

/// Re-derive a committed summary from its published report, exactly as
/// `graph-mapping-host summarize --per-block-scope handler-blocks` would.
fn rederive(summary: &str) -> evidence::Summary {
    let committed = load(summary);
    let report = format!("{}.report.jsonl", stem(summary));
    // Fail closed, with the fetch command, before `summarize` reports a bare
    // missing file.
    drop(hydrated(&report));
    let cassette = committed
        .cassette
        .as_ref()
        .map(|cassette| crate_dir().join(&cassette.path));
    let segment = crate_dir().join(format!("segments/{SEGMENT}"));
    evidence::summarize(SummarizeInputs {
        report: &crate_dir().join(&report),
        previous: Narrative::read(&crate_dir().join(summary)).unwrap(),
        per_block_name: committed.per_block.file.clone(),
        segment: Some(&segment),
        cassette: cassette.as_deref(),
        goldens: None,
        sampled_report: None,
        per_block_scope: PerBlockScope::HandlerBlocks,
        all_blocks_name: committed
            .per_block
            .all_blocks
            .as_ref()
            .map(|all| all.file.clone()),
    })
    .unwrap_or_else(|e| panic!("re-deriving {summary}: {e:#}"))
}

/// The first line on which two texts differ, so a failure names the field
/// instead of printing two whole summaries.
fn first_difference(derived: &str, committed: &str) -> String {
    derived
        .lines()
        .zip(committed.lines())
        .enumerate()
        .find(|(_, (d, c))| d != c)
        .map(|(index, (d, c))| format!("line {}: derived {d:?}, committed {c:?}", index + 1))
        .unwrap_or_else(|| "the files differ in length".into())
}

#[test]
fn the_published_reports_rederive_both_summaries_byte_for_byte() {
    // Every derived field of both summaries (totals, handlers, creation rows,
    // final store counts, final PoI, cassette facts and every per-block pin) is
    // recomputed from the published report and must equal the committed file
    // exactly. A hand edit to any of them, or a report that is not the run's,
    // fails here. One summary at a time: the window's report alone is 90 MB.
    for summary in [PREFIX, WINDOW] {
        let derived = rederive(summary);
        let committed = std::fs::read_to_string(crate_dir().join(summary)).unwrap();
        let json = derived.evidence.to_json().unwrap();
        assert!(
            json == committed,
            "{summary} is not what its published report derives: {}",
            first_difference(&json, &committed)
        );

        // And the per-block files it pins are the published ones, byte for byte.
        let per_block = &derived.evidence.per_block;
        if per_block.bytes > 0 {
            assert!(
                derived.per_block.as_bytes() == hydrated(&beside(summary, &per_block.file)),
                "{summary}: the published sparse file differs"
            );
        } else {
            assert!(derived.per_block.is_empty());
        }
        let all = per_block.all_blocks.as_ref().unwrap();
        let complete = derived.all_blocks.expect("a sparse summary derives both");
        assert!(
            complete.as_bytes() == hydrated(&beside(summary, &all.file)),
            "{summary}: the published complete per-block file differs"
        );
    }
}

#[test]
fn the_published_per_block_files_are_the_ones_the_summaries_pin() {
    // The same pins checked straight from the published files, without
    // `summarize`: the complete file's digest is what `per_block.all_blocks`
    // says, every block of the range is in it once and in order, the sparse file
    // is exactly its handler blocks, and its totals and last PoI are the
    // summary's.
    for summary in [PREFIX, WINDOW] {
        let evidence = load(summary);
        let all = evidence.per_block.all_blocks.as_ref().unwrap();
        let complete_bytes = hydrated(&beside(summary, &all.file));
        assert_eq!(complete_bytes.len(), all.bytes, "{summary}");
        assert_eq!(sha256_hex(&complete_bytes), all.sha256, "{summary}");
        let complete = per_block_lines(&complete_bytes);
        assert_eq!(complete.len(), all.lines);
        assert!(complete
            .iter()
            .map(|line| line.number)
            .eq(evidence.range.from..evidence.range.to));

        // In these runs every block that ran a handler wrote a PoI and none was
        // discarded, so the sparse file is exactly the complete file's lines
        // with a PoI or an operation.
        assert_eq!(
            evidence.totals.blocks_with_handlers,
            evidence.totals.blocks_with_poi
        );
        assert_eq!(evidence.totals.blocks_discarded, 0);
        let sparse_text: String = complete
            .iter()
            .filter(|line| line.poi_public_digest.is_some() || line.operations > 0)
            .map(|line| graph_mapping_host::report::json_line(line).unwrap())
            .collect();
        assert_eq!(
            sparse_text.lines().count(),
            evidence.per_block.lines,
            "{summary}"
        );
        assert_eq!(sparse_text.len(), evidence.per_block.bytes, "{summary}");
        assert_eq!(
            sha256_hex(sparse_text.as_bytes()),
            evidence.per_block.sha256,
            "{summary}"
        );
        if evidence.per_block.bytes > 0 {
            assert!(
                sparse_text.as_bytes() == hydrated(&beside(summary, &evidence.per_block.file)),
                "{summary}: the published sparse file is not the complete file's handler blocks"
            );
        }

        assert_eq!(
            complete.iter().map(|line| line.operations).sum::<usize>(),
            evidence.totals.operations
        );
        let last_poi = complete
            .iter()
            .rev()
            .find(|line| line.poi_public_digest.is_some());
        match (&evidence.final_poi, last_poi) {
            (None, None) => {}
            (Some(poi), Some(line)) => {
                assert_eq!(poi.block, line.number);
                assert_eq!(Some(&poi.public_digest), line.poi_public_digest.as_ref());
            }
            (poi, line) => panic!("{summary}: final PoI {poi:?} against last PoI line {line:?}"),
        }
    }

    // The first pool's block is the frame and the PoI the `segment_aerodrome`
    // fixture replay reproduces from the block alone.
    let all = window().per_block.all_blocks.as_ref().unwrap();
    let complete = per_block_lines(&hydrated(&beside(WINDOW, &all.file)));
    let first_pool = complete
        .iter()
        .find(|line| line.number == FIRST_POOL)
        .unwrap();
    assert_eq!(
        first_pool.frame_sha256,
        "62c0b927ea0a70cedbf20c39a5b6683028c84e97b71dd3c457e41110db8607a3"
    );
    assert_eq!(
        first_pool.poi_public_digest.as_deref(),
        Some("6645b82ff589f650cae124a23ac62580f93b3dd59bbc1afc0128bc50a038e765")
    );
}
