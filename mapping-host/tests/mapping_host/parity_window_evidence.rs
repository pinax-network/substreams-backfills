//! The committed evidence for the 1,053-block parity-window replay.
//!
//! Hermetic, like every test here: the committed cassette, the committed
//! goldens, the hydrated block fixtures and the two committed evidence files.
//! Nothing opens a socket, and nothing re-runs the window — that run needed
//! Firehose and an RPC endpoint and is not reproducible in CI.
//!
//! What *is* reproducible is the overlap. Four blocks of that window are
//! committed as `.pb` fixtures, and this file replays them under the same host
//! and checks their frames against the digests the summary records for the same
//! block numbers. Two of the four must agree exactly and two of the four must
//! not, and the reason is the point:
//!
//! * 12,369,621 and 12,369,739 are reached with the same store either way. The
//!   window starts at 12,369,621 and the first `PoolCreated` is in 12,369,739,
//!   so a sampled replay and a contiguous replay arrive at both with nothing
//!   behind them. Their frames are byte-identical, which is a real check on the
//!   contiguous run: it says the extra 117 blocks in between changed nothing
//!   they should not have.
//! * 12,369,879 and 12,370,523 are reached with a store the sampled run cannot
//!   have. Pools, tokens and positions created in unsampled blocks exist in the
//!   contiguous run, so the frames must differ, and the summary records both
//!   digests rather than describing the difference in prose.
//!
//! The rest of the file checks that the summary is internally honest: its totals
//! are the sum of its own per-block list, the list is the file it says it is by
//! digest, the range really is contiguous, and no credential reached either
//! file.

use std::collections::BTreeSet;
use std::path::PathBuf;
use std::sync::OnceLock;

use graph_mapping_host::bundle::sha256_hex;
use graph_mapping_host::evidence::{PerBlockLine, RunEvidence, EVIDENCE_SCHEMA};
use graph_mapping_host::runner::{SegmentHost, SegmentHostConfig};
use graph_mapping_host::{block, blockchanges};

const SEGMENT: &str = "Qme66ZNMxSdCQKzaDuvS381whCVYCQjf637sGZCqJHAWHB";
const EVIDENCE: &str = "evidence/parity-window-12369621-12370674.json";
/// The four blocks of the window that are also committed `.pb` fixtures.
const FIXTURES: &[&str] = &["12369621", "12369739", "12369879", "12370523"];
/// The two of those the sampled and the contiguous run must both reach with an
/// empty-enough store to produce the same frame.
const MUST_AGREE: &[i32] = &[12369621, 12369739];

fn crate_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

fn block_fixture(name: &str) -> PathBuf {
    crate_dir()
        .parent()
        .expect("mapping-host has a parent")
        .join(format!("uniswap-v3/fixtures/blocks/mainnet/{name}.pb"))
}

fn evidence() -> &'static RunEvidence {
    static EVIDENCE_FILE: OnceLock<RunEvidence> = OnceLock::new();
    EVIDENCE_FILE.get_or_init(|| {
        let path = crate_dir().join(EVIDENCE);
        let bytes =
            std::fs::read(&path).unwrap_or_else(|e| panic!("reading {}: {e}", path.display()));
        serde_json::from_slice(&bytes).unwrap_or_else(|e| panic!("parsing {}: {e}", path.display()))
    })
}

/// The sibling per-block file, and its exact bytes.
fn per_block() -> &'static (Vec<PerBlockLine>, Vec<u8>) {
    static PER_BLOCK: OnceLock<(Vec<PerBlockLine>, Vec<u8>)> = OnceLock::new();
    PER_BLOCK.get_or_init(|| {
        let path = crate_dir()
            .join(EVIDENCE)
            .with_file_name(&evidence().per_block.file);
        let bytes =
            std::fs::read(&path).unwrap_or_else(|e| panic!("reading {}: {e}", path.display()));
        let text = String::from_utf8(bytes.clone()).expect("the per-block file is UTF-8");
        let lines = text
            .lines()
            .enumerate()
            .map(|(index, line)| {
                serde_json::from_str(line)
                    .unwrap_or_else(|e| panic!("line {} of the per-block file: {e}", index + 1))
            })
            .collect();
        (lines, bytes)
    })
}

/// The four fixture blocks replayed under this host, as `(number, frame digest)`.
fn hermetic_replay() -> &'static Vec<(i32, String)> {
    static REPLAY: OnceLock<Vec<(i32, String)>> = OnceLock::new();
    REPLAY.get_or_init(|| {
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

async fn replay() -> Vec<(i32, String)> {
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

    let mut digests = Vec::new();
    for b in blocks {
        let number = b.number();
        let outcome = host
            .process_block(b)
            .await
            .unwrap_or_else(|e| panic!("replaying block {number}: {e:#}"));
        let bytes = blockchanges::seal(&outcome.changes, host.compatibility())
            .unwrap_or_else(|e| panic!("sealing block {number}: {e:#}"));
        digests.push((number, sha256_hex(&bytes)));
    }
    digests
}

#[test]
fn the_summary_is_the_expected_schema_for_the_expected_deployment() {
    let evidence = evidence();
    assert_eq!(evidence.schema, EVIDENCE_SCHEMA);
    assert_eq!(evidence.deployment.deployment, SEGMENT);
    assert_eq!(evidence.deployment.network, "mainnet");
    assert_eq!(evidence.deployment.spec_version, "0.0.2");
    assert_eq!(
        evidence.deployment.graph_node_rev,
        graph_mapping_host::runner::GRAPH_NODE_REV
    );
    // Spec 0.0.2 declares no features, which is what makes the policy fatal.
    assert!(evidence.deployment.features.is_empty());
}

#[test]
fn the_per_block_file_is_the_one_the_summary_pins() {
    let (lines, bytes) = per_block();
    let pinned = &evidence().per_block;
    assert_eq!(bytes.len(), pinned.bytes, "per-block file size");
    assert_eq!(sha256_hex(bytes), pinned.sha256, "per-block file digest");
    assert_eq!(lines.len(), pinned.lines, "per-block line count");
    assert_eq!(
        pinned.fields,
        vec!["number", "frame_sha256", "poi_public_digest", "operations"]
    );
}

#[test]
fn the_range_really_is_contiguous() {
    // `contiguous: true` is a derived claim in the file. Recheck it against the
    // list rather than trusting the flag, because the flag is the thing a
    // regenerated summary could get wrong.
    let evidence = evidence();
    let (lines, _) = per_block();
    assert!(evidence.range.contiguous);
    assert_eq!(
        lines.len(),
        (evidence.range.to - evidence.range.from) as usize
    );
    for (offset, line) in lines.iter().enumerate() {
        assert_eq!(
            line.number,
            evidence.range.from + offset as i32,
            "block numbers must ascend by one with no gap or repeat"
        );
    }
    assert_eq!(lines[0].number, evidence.range.first_block);
    assert_eq!(
        lines.last().expect("blocks").number,
        evidence.range.last_block
    );
    assert_eq!(evidence.range.last_block, evidence.range.to - 1);
}

#[test]
fn the_totals_are_the_sum_of_the_per_block_list() {
    let evidence = evidence();
    let (lines, _) = per_block();
    let totals = &evidence.totals;

    assert_eq!(totals.blocks, lines.len());
    assert_eq!(
        totals.operations,
        lines.iter().map(|line| line.operations).sum::<usize>()
    );
    assert_eq!(
        totals.blocks_with_poi,
        lines
            .iter()
            .filter(|line| line.poi_public_digest.is_some())
            .count()
    );
    // Every operation in this window is a Set; nothing was removed and nothing
    // failed. If that ever stops being true the summary has to say so.
    assert_eq!(totals.sets + totals.removes, totals.operations);
    assert_eq!(totals.removes, 0);
    assert_eq!(totals.deterministic_errors, 0);
    assert_eq!(totals.blocks_discarded, 0);
    // The recorder's whole reason for existing: more saves than the collapsed
    // modification set `as_modifications` reports.
    assert!(
        totals.collapsed_modifications < totals.operations,
        "{} collapsed vs {} operations",
        totals.collapsed_modifications,
        totals.operations
    );
    assert_eq!(
        totals.collapsed_modifications,
        evidence.modifications_by_entity.values().sum::<usize>()
    );
    assert_eq!(
        totals.handler_invocations,
        evidence.handlers.invocations.values().sum::<usize>()
    );
    assert_eq!(
        totals.handler_invocations,
        evidence.handlers.outcomes.values().sum::<usize>()
    );
    assert_eq!(
        totals.handler_invocations,
        evidence.data_source_invocations.values().sum::<usize>()
    );
}

#[test]
fn the_final_poi_is_the_last_one_the_run_produced() {
    let evidence = evidence();
    let (lines, _) = per_block();
    let poi = evidence.final_poi.as_ref().expect("a final PoI");
    let last = lines
        .iter()
        .rev()
        .find(|line| line.poi_public_digest.is_some())
        .expect("some block wrote a PoI");
    assert_eq!(poi.block, last.number);
    assert_eq!(Some(&poi.public_digest), last.poi_public_digest.as_ref());
    // Spec 0.0.2 is below 0.0.6, so the digest is a Legacy one; the pinned
    // `stable-hash` revisions are what make it reproducible.
    assert_eq!(poi.version, "legacy");
    assert_eq!(poi.causality_region, "ethereum/mainnet");
    // A block in which no handler ran creates no causality region, so the last
    // PoI is not the last block.
    assert!(poi.block < evidence.range.last_block);
}

#[test]
fn the_contiguous_run_exercises_the_handlers_the_fixture_set_could_not() {
    // The four sampled fixtures could not reach Swap or Burn at all and reached
    // Collect and DecreaseLiquidity only as failures. This window reaches all
    // four, successfully.
    let handlers = &evidence().handlers;
    for handler in [
        "handleSwap",
        "handleBurn",
        "handleCollect",
        "handleDecreaseLiquidity",
    ] {
        assert!(
            handlers.invocations.get(handler).copied().unwrap_or(0) > 0,
            "{handler} should have run in the contiguous window"
        );
    }
    // Every invocation succeeded, so `deterministic_error` is not an outcome at
    // all in this run.
    assert_eq!(handlers.outcomes.keys().collect::<Vec<_>>(), vec!["ok"]);
    // handleFlash is still unexercised, and README.md still says so.
    assert!(
        !handlers.invocations.contains_key("handleFlash"),
        "handleFlash ran; the limitation text in README.md needs updating"
    );
}

#[test]
fn the_entity_types_split_matches_the_deployed_schema() {
    #[derive(serde::Deserialize)]
    struct Descriptor {
        storage_profile: StorageProfile,
    }
    #[derive(serde::Deserialize)]
    struct StorageProfile {
        entity_types: Vec<String>,
    }

    let path = crate_dir().join(format!("segments/{SEGMENT}/block-changes-descriptor.json"));
    let descriptor: Descriptor =
        serde_json::from_slice(&std::fs::read(&path).expect("reading the descriptor"))
            .expect("descriptor JSON");

    let types = &evidence().entity_types;
    assert_eq!(types.declared, descriptor.storage_profile.entity_types);

    let written: BTreeSet<&str> = types.written.iter().map(String::as_str).collect();
    let never: BTreeSet<&str> = types.never_written.iter().map(String::as_str).collect();
    assert!(written.is_disjoint(&never));
    assert_eq!(written.len() + never.len(), types.declared.len());
    assert_eq!(
        types.written,
        evidence()
            .modifications_by_entity
            .keys()
            .cloned()
            .collect::<Vec<_>>()
    );
    // The three the deployed mappings are certified never to write.
    assert_eq!(types.never_written, ["Collect", "Flash", "TickHourData"]);
}

#[test]
fn the_summary_carries_no_credential() {
    // The recorded command names an endpoint and the environment list names
    // variables; neither may ever carry the value of one.
    let evidence = evidence();
    for name in &evidence.run.environment {
        assert!(
            name.chars()
                .all(|c| c.is_ascii_uppercase() || c.is_ascii_digit() || c == '_'),
            "{name} is not an environment variable name"
        );
    }
    let text = std::fs::read_to_string(crate_dir().join(EVIDENCE)).expect("reading the summary");
    for forbidden in ["bearer ", "api_key", "apikey", "@eth.", "://"] {
        assert!(
            !text.to_lowercase().contains(forbidden),
            "the summary contains {forbidden:?}"
        );
    }
    // The token variables are named, because a reader has to know what the run
    // needed, but the run itself never echoes them.
    assert!(evidence
        .run
        .environment
        .iter()
        .any(|name| name == "FIREHOSE_API_TOKEN"));
}

#[test]
fn the_cassette_is_the_one_the_summary_records() {
    let cassette = evidence().cassette.as_ref().expect("cassette facts");
    let path = crate_dir().join(&cassette.path);
    let bytes = std::fs::read(&path).unwrap_or_else(|e| panic!("reading {}: {e}", path.display()));
    assert_eq!(bytes.len(), cassette.bytes);
    assert_eq!(sha256_hex(&bytes), cassette.sha256);
    assert_eq!(
        cassette.rows,
        cassette.rows_by_call.values().sum::<usize>(),
        "the per-call breakdown covers every row"
    );
    // Replay fails closed on a miss, so a revert row and a missing row are very
    // different things; this window recorded no revert at all.
    assert_eq!(cassette.reverts, 0);
}

#[test]
fn replaying_the_fixture_blocks_reproduces_the_digests_the_summary_records() {
    // The one part of the window CI can re-run. Each committed golden must still
    // be what this host produces, and each must relate to the contiguous run's
    // digest exactly as the summary says it does.
    let checks = &evidence().fixture_block_cross_check;
    assert_eq!(
        checks.len(),
        FIXTURES.len(),
        "every committed golden should be cross-checked"
    );

    for (number, digest) in hermetic_replay() {
        let check = checks
            .iter()
            .find(|check| check.block == *number)
            .unwrap_or_else(|| panic!("no cross-check for block {number}"));

        assert_eq!(
            &check.golden_sha256, digest,
            "block {number}: the committed golden no longer matches a fixture replay"
        );
        assert_eq!(
            check.identical,
            check.golden_sha256 == check.contiguous_sha256,
            "block {number}: `identical` disagrees with the two digests beside it"
        );

        if MUST_AGREE.contains(number) {
            assert!(
                check.identical,
                "block {number} is reached with the same store either way, so the contiguous \
                 run must produce the same frame; it produced {}",
                check.contiguous_sha256
            );
            assert_eq!(&check.contiguous_sha256, digest);
        } else {
            assert!(
                !check.identical,
                "block {number} is reached with a store the sampled run cannot have, so the \
                 frames must differ"
            );
            assert_ne!(&check.contiguous_sha256, digest);
        }
    }
}

#[test]
fn the_fixture_gap_error_is_absent_from_the_contiguous_run() {
    // The sampled replay of 12,370,523 aborts two handlers because a Token row
    // created in an unsampled block is missing. The contiguous run has the row.
    // Both halves are recorded, so neither can be quietly restated as the other.
    let check = evidence()
        .fixture_block_cross_check
        .iter()
        .find(|check| check.block == 12370523)
        .expect("a cross-check for 12,370,523");
    assert_eq!(check.golden_deterministic_errors, Some(2));
    assert_eq!(check.contiguous_deterministic_errors, 0);
    assert!(check.contiguous_operations > check.golden_operations.expect("sampled operations"));

    let finding = evidence()
        .findings
        .iter()
        .find(|finding| finding.id == "fixture-gap-error-does-not-reproduce")
        .expect("the finding that explains it");
    assert!(finding.statement.contains("12,370,523"));
}

#[test]
fn every_finding_is_written_out() {
    // A regeneration carries the prose forward verbatim, which means a
    // placeholder would also survive. Refuse one.
    let evidence = evidence();
    assert!(!evidence.findings.is_empty());
    for finding in &evidence.findings {
        assert!(!finding.id.is_empty());
        assert!(finding.statement.len() > 200, "{} is a stub", finding.id);
    }
    let run = &evidence.run;
    for (field, value) in [
        ("recorded_on", &run.recorded_on),
        ("command", &run.command),
        ("toolchain", &run.toolchain),
        ("firehose_endpoint", &run.firehose_endpoint),
        ("rpc_endpoint", &run.rpc_endpoint),
        ("artifacts_not_committed", &run.artifacts_not_committed),
        ("claim_boundary", &run.claim_boundary),
    ] {
        assert_ne!(value, "TODO", "run.{field} was never filled in");
    }
    // The boundary has to keep saying what this is not.
    assert!(run.claim_boundary.contains("not a parity claim"));
}
