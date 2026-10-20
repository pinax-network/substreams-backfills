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
//! Hermetic. Both summaries were written by `graph-mapping-host summarize
//! --per-block-scope handler-blocks`, so each pins the complete per-block file
//! by digest without carrying it. The prefix's sparse file is empty, so this
//! test can check its digest outright. The window's sparse file is 672 KB and,
//! with the cassette and the frames, is a release asset that has not been
//! published; the `#[ignore]`d test at the bottom checks it when
//! `AERODROME_EVIDENCE_DIR` points at a local copy.

use std::collections::BTreeMap;
use std::path::PathBuf;
use std::sync::OnceLock;

use graph_mapping_host::bundle::sha256_hex;
use graph_mapping_host::evidence::{PerBlockLine, RunEvidence, EVIDENCE_SCHEMA};

const SEGMENT: &str = "QmasYjypV6nTLp4iNH4Vjf7fksRNxAkAskqDdKf2DCsQkV";
const PREFIX: &str = "evidence/aerodrome-root-prefix-13843704-13899663.json";
const WINDOW: &str = "evidence/aerodrome-first-pools-13899663-13919663.json";
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

#[test]
fn both_summaries_describe_the_aerodrome_oracle_segment() {
    for evidence in [prefix(), window()] {
        assert_eq!(evidence.schema, EVIDENCE_SCHEMA);
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
        // Sparse, and still pinning every block.
        let per_block = &evidence.per_block;
        assert_eq!(per_block.scope.as_deref(), Some("handler_blocks"));
        let all = per_block
            .all_blocks
            .as_ref()
            .expect("the complete file is pinned");
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
    // `Initialize`, each in the second wave of its own block.
    let invocations = &evidence.handlers.invocations;
    assert_eq!(totals.created_data_sources, 13);
    assert_eq!(invocations["handlePoolCreated"], 13);
    assert_eq!(invocations["handleInitialize"], 13);
    assert_eq!(totals.max_waves, 2);
    assert_eq!(evidence.final_store_counts["Pool"], 13);
    assert_eq!(evidence.data_source_invocations["Factory"], 13);

    let poi = evidence.final_poi.as_ref().expect("a final PoI");
    assert_eq!(poi.version, "fast");
    assert_eq!(poi.causality_region, "ethereum/base");
    assert!(poi.block <= evidence.range.last_block);
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
fn the_cassette_is_described_without_its_location() {
    // The window's cassette is a release-asset candidate, not a committed file:
    // the summary records its digest and composition, and only its file name.
    let cassette = window().cassette.as_ref().expect("cassette facts");
    assert_eq!(cassette.path, "cassette.json");
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

#[test]
#[ignore = "needs AERODROME_EVIDENCE_DIR: the window's sparse per-block file, a release asset that is not published; never network"]
fn the_window_per_block_file_is_the_one_the_summary_pins() {
    let dir = PathBuf::from(
        std::env::var("AERODROME_EVIDENCE_DIR").expect("set the local evidence directory"),
    );
    let evidence = window();
    let path = dir.join(&evidence.per_block.file);
    let bytes = std::fs::read(&path).unwrap_or_else(|e| panic!("reading {}: {e}", path.display()));
    assert_eq!(bytes.len(), evidence.per_block.bytes);
    assert_eq!(sha256_hex(&bytes), evidence.per_block.sha256);

    let lines: Vec<PerBlockLine> = String::from_utf8(bytes)
        .unwrap()
        .lines()
        .map(|line| serde_json::from_str(line).unwrap())
        .collect();
    assert_eq!(lines.len(), evidence.per_block.lines);
    // Ascending, inside the range.
    for pair in lines.windows(2) {
        assert!(pair[0].number < pair[1].number);
    }
    assert!(lines
        .iter()
        .all(|line| line.number >= evidence.range.from && line.number < evidence.range.to));
    // Every operation and every PoI in the run is in the sparse file.
    assert_eq!(
        lines.iter().map(|line| line.operations).sum::<usize>(),
        evidence.totals.operations
    );
    assert_eq!(
        lines
            .iter()
            .filter(|line| line.poi_public_digest.is_some())
            .count(),
        evidence.totals.blocks_with_poi
    );
    let last = lines
        .iter()
        .rev()
        .find(|line| line.poi_public_digest.is_some())
        .unwrap();
    let poi = evidence.final_poi.as_ref().unwrap();
    assert_eq!(poi.block, last.number);
    assert_eq!(Some(&poi.public_digest), last.poi_public_digest.as_ref());

    // The first block is the first pool, and it is the frame and the PoI the
    // `segment_aerodrome` fixture replay reproduces from the block alone.
    let first: BTreeMap<&str, String> = [
        ("number", lines[0].number.to_string()),
        ("frame_sha256", lines[0].frame_sha256.clone()),
        ("poi", lines[0].poi_public_digest.clone().unwrap()),
    ]
    .into_iter()
    .collect();
    assert_eq!(first["number"], FIRST_POOL.to_string());
    assert_eq!(
        first["frame_sha256"],
        "62c0b927ea0a70cedbf20c39a5b6683028c84e97b71dd3c457e41110db8607a3"
    );
    assert_eq!(
        first["poi"],
        "6645b82ff589f650cae124a23ac62580f93b3dd59bbc1afc0128bc50a038e765"
    );
}
