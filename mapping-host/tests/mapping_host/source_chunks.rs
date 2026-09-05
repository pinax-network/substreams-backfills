//! v2 sealed producer chunks. Default tests are hermetic and use the real
//! root block plus explicitly synthetic bad metadata. The ignored 300-block
//! case requires a local raw, contiguous Firehose corpus, never a network.
use backfill_common::dynamic_sources_v2::seal::{self, SealedChunk};
use graph_mapping_host::{checkpoint::HostCheckpoint, descriptor};
use std::{
    fs,
    path::{Path, PathBuf},
    process::{Command, Output},
};

const SEGMENT: &str = "Qme66ZNMxSdCQKzaDuvS381whCVYCQjf637sGZCqJHAWHB";
const START: u64 = 12369621;
const GOLDEN_300_STREAM: &str = "9db817b7c0f9fd3dd7f2bb758fc6c12096668fe6cee4ad97547404d980150726";
fn root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}
fn segment() -> PathBuf {
    root().join(format!("segments/{SEGMENT}"))
}
fn cassette() -> PathBuf {
    root().join(format!("fixtures/cassettes/{SEGMENT}.json"))
}
fn fixture(number: u64) -> PathBuf {
    root().join(format!("../uniswap-v3/fixtures/blocks/mainnet/{number}.pb"))
}
fn command(cassette: &Path) -> Command {
    command_for(cassette, &segment())
}
fn command_for(cassette: &Path, segment: &Path) -> Command {
    let mut cmd = Command::new(env!("CARGO_BIN_EXE_graph-mapping-host"));
    cmd.arg("run")
        .arg("--segment")
        .arg(segment)
        .arg("--cassette")
        .arg(cassette)
        .env_remove("FIREHOSE_API_KEY")
        .env_remove("FIREHOSE_API_TOKEN")
        .env_remove("SUBSTREAMS_API_TOKEN")
        .env_remove("ETHEREUM_RPC_URL")
        .env_remove("FIREHOSE_ENDPOINT");
    cmd
}

#[test]
fn grafted_manifest_is_refused_before_any_source_or_output_is_opened() {
    let tmp = tempfile::tempdir().unwrap();
    let target = tmp.path().join("graft.ready");
    let graft = root().join("segments/QmTZ8ejXJxRo7vDBS4uwqBeGoxLSWbhaA7oXa1RvxunLy7");
    refused(
        command_for(&cassette(), &graft)
            .arg("--blocks")
            .arg("deliberately-absent.pb")
            .arg("--source-chunk-out")
            .arg(&target)
            .output()
            .unwrap(),
        "refuse grafted",
    );
    assert!(!target.exists());
    assert!(!target.with_extension("building").exists());
}

// Deliberately forge a self-consistent byte seal around a bad checkpoint. This
// proves that a hash match alone cannot bypass the producer's semantic checks.
fn alter_checkpoint(path: &Path, edit: impl FnOnce(&mut serde_json::Value)) {
    let bytes = fs::read(path.join(seal::CHECKPOINT)).unwrap();
    let newline = bytes.iter().position(|b| *b == b'\n').unwrap();
    let mut header: serde_json::Value = serde_json::from_slice(&bytes[..newline]).unwrap();
    edit(&mut header);
    let mut updated = serde_json::to_vec(&header).unwrap();
    updated.extend(&bytes[newline..]);
    fs::write(path.join(seal::CHECKPOINT), &updated).unwrap();
    let pin = backfill_common::dynamic_sources_v2::FilePin::for_bytes(&updated);
    let mut metadata = sealed_metadata(path);
    metadata.checkpoint = pin.clone();
    let updated = serde_json::to_vec(&metadata).unwrap();
    fs::write(path.join(seal::METADATA), &updated).unwrap();
    let mut manifest: seal::Manifest =
        serde_json::from_slice(&fs::read(path.join(seal::MANIFEST)).unwrap()).unwrap();
    manifest.checkpoint = pin;
    manifest.metadata = backfill_common::dynamic_sources_v2::FilePin::for_bytes(&updated);
    let updated = serde_json::to_vec(&manifest).unwrap();
    fs::write(path.join(seal::MANIFEST), &updated).unwrap();
    let ready = seal::Ready {
        format: seal::FORMAT.into(),
        manifest: backfill_common::dynamic_sources_v2::FilePin::for_bytes(&updated),
    };
    fs::write(path.join(seal::READY), serde_json::to_vec(&ready).unwrap()).unwrap();
    sealed(path); // Contract integrity valid; host semantics must still refuse.
}
fn sealed_metadata(path: &Path) -> backfill_common::dynamic_sources_v2::Chunk {
    serde_json::from_slice(&fs::read(path.join(seal::METADATA)).unwrap()).unwrap()
}

#[tokio::test]
async fn v2_requires_a_nonzero_parent_hash_without_changing_legacy_ordering() {
    use graph::blockchain::{BlockHash, BlockTime, ExtendedBlockPtr};
    use graph_chain_ethereum::chain::BlockFinality;
    use graph_mapping_host::source::{BlockSource, CheckedSource, Ordering};
    struct One(Option<BlockFinality>);
    #[async_trait::async_trait]
    impl BlockSource for One {
        async fn next_block(&mut self) -> anyhow::Result<Option<BlockFinality>> {
            Ok(self.0.take())
        }
        fn describe(&self) -> String {
            "synthetic invalid parent".into()
        }
    }
    fn invalid() -> One {
        One(Some(BlockFinality::Ptr(std::sync::Arc::new(
            ExtendedBlockPtr {
                hash: super::block_source::fake_hash(0, START as i32),
                number: START as i32,
                parent_hash: BlockHash::from(vec![0; 32]),
                timestamp: BlockTime::since_epoch(0, 0),
            },
        ))))
    }
    let ordering = Ordering::Contiguous {
        start: START as i32,
        stop: START as i32 + 1,
    };
    let mut legacy = CheckedSource::new(invalid(), ordering);
    assert!(legacy.next_block().await.unwrap().is_some());
    let mut v2 = CheckedSource::new(invalid(), ordering).require_parent_hashes();
    let error = match v2.next_block().await {
        Err(error) => error,
        Ok(_) => panic!("invalid parent accepted"),
    };
    assert!(
        error.to_string().contains("no valid parent hash"),
        "{error}"
    );
}

#[test]
fn a_self_consistent_seal_does_not_authorize_a_mismatched_checkpoint() {
    let tmp = tempfile::tempdir().unwrap();
    let original = tmp.path().join("root.ready");
    produce_root(&original);
    let cases: Vec<(&str, serde_json::Value)> = vec![
        ("block", serde_json::json!(START + 1)),
        (
            "block_hash",
            serde_json::json!(format!("0x{}", "12".repeat(32))),
        ),
        ("chunk_from", serde_json::json!(START + 1)),
        ("chunk_to", serde_json::json!(START + 2)),
        ("blocks_in_chunk", serde_json::json!(2)),
        ("blocks_total", serde_json::json!(2)),
        ("chunk_index", serde_json::json!(1)),
        (
            "previous_checkpoint_sha256",
            serde_json::json!("12".repeat(32)),
        ),
    ];
    for (field, value) in cases {
        let parent = tmp.path().join(format!("forged-{field}.ready"));
        fs::create_dir(&parent).unwrap();
        for entry in fs::read_dir(&original).unwrap() {
            let entry = entry.unwrap();
            fs::copy(entry.path(), parent.join(entry.file_name())).unwrap();
        }
        alter_checkpoint(&parent, |header| header["boundary"][field] = value);
        let target = tmp.path().join(format!("refused-{field}.ready"));
        let result = command(&cassette())
            .arg("--blocks")
            .arg("deliberately-absent.pb")
            .arg("--source-chunk-in")
            .arg(&parent)
            .arg("--source-chunk-out")
            .arg(&target)
            .output()
            .unwrap();
        refused(result, "checkpoint");
        assert!(!target.exists());
        assert!(!target.with_extension("building").exists());
    }
}
fn success(output: Output) {
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
}
fn refused(output: Output, phrase: &str) {
    let error = String::from_utf8_lossy(&output.stderr);
    assert!(!output.status.success(), "unexpected success");
    assert!(error.contains(phrase), "expected {phrase:?}, got {error}");
}
fn sealed(path: &Path) -> SealedChunk {
    let (_, descriptor) = descriptor::load(&segment()).unwrap();
    SealedChunk::open(path, &descriptor).unwrap()
}
fn produce_root(output: &Path) {
    success(
        command(&cassette())
            .arg("--blocks")
            .arg(fixture(START))
            .arg("--source-chunk-out")
            .arg(output)
            .output()
            .unwrap(),
    );
}

#[test]
fn root_cli_seals_exact_inventory_and_refuses_overwriting_or_reusing_raw_checkpoints() {
    let tmp = tempfile::tempdir().unwrap();
    let output = tmp.path().join("root.ready");
    produce_root(&output);
    let receipt = sealed(&output);
    assert_eq!(receipt.chunk.from, START);
    assert_eq!(receipt.chunk.to, START + 1);
    assert_eq!(receipt.chunk.after.order.count, 0);
    let before = fs::read(output.join(seal::READY)).unwrap();
    refused(
        command(&cassette())
            .arg("--blocks")
            .arg(fixture(START))
            .arg("--source-chunk-out")
            .arg(&output)
            .output()
            .unwrap(),
        "existing output",
    );
    assert_eq!(fs::read(output.join(seal::READY)).unwrap(), before);
    for flag in [
        "--checkpoint-in",
        "--checkpoint-out",
        "--bcf1-out",
        "--data-sources-out",
        "--store-out",
        "--out",
    ] {
        let target = tmp.path().join("bad.ready");
        refused(
            command(&cassette())
                .arg("--blocks")
                .arg(fixture(START))
                .arg("--source-chunk-out")
                .arg(&target)
                .arg(flag)
                .arg(output.join(seal::CHECKPOINT))
                .output()
                .unwrap(),
            "cannot be used with",
        );
        assert!(!target.exists());
        assert!(!target.with_extension("building").exists());
    }
}

#[test]
fn every_mutated_direct_predecessor_file_is_refused_before_creating_outputs_or_network() {
    let tmp = tempfile::tempdir().unwrap();
    let parent = tmp.path().join("root.ready");
    produce_root(&parent);
    for name in [
        seal::STREAM,
        seal::METADATA,
        seal::CHECKPOINT,
        seal::IDENTITIES,
        seal::MANIFEST,
        seal::READY,
    ] {
        let path = parent.join(name);
        let original = fs::read(&path).unwrap();
        let mut changed = original.clone();
        changed.push(b' ');
        fs::write(&path, changed).unwrap();
        let target = tmp.path().join("child.ready");
        let result = command(&cassette())
            .arg("--from")
            .arg((START + 1).to_string())
            .arg("--to")
            .arg((START + 2).to_string())
            .arg("--source-chunk-in")
            .arg(&parent)
            .arg("--source-chunk-out")
            .arg(&target)
            .output()
            .unwrap();
        assert!(!result.status.success(), "accepted changed {name}");
        assert!(
            !String::from_utf8_lossy(&result.stderr).contains("FIREHOSE_ENDPOINT"),
            "network preflight ran before rejecting {name}"
        );
        assert!(!target.exists());
        assert!(!target.with_extension("building").exists());
        fs::write(path, original).unwrap();
    }
    sealed(&parent);
}

#[test]
fn v2_refuses_sampled_gaps_and_torn_staging_without_promoting_ready() {
    let tmp = tempfile::tempdir().unwrap();
    let target = tmp.path().join("gap.ready");
    refused(
        command(&cassette())
            .arg("--blocks")
            .arg(fixture(START))
            .arg(fixture(12369739))
            .arg("--source-chunk-out")
            .arg(&target)
            .output()
            .unwrap(),
        "contiguous",
    );
    assert!(!target.exists());
    assert!(!target.with_extension("building").exists());
    fs::create_dir(target.with_extension("building")).unwrap();
    fs::write(
        target.with_extension("building").join(seal::STREAM),
        b"BCF1 torn",
    )
    .unwrap();
    refused(
        command(&cassette())
            .arg("--blocks")
            .arg(fixture(START))
            .arg("--source-chunk-out")
            .arg(&target)
            .output()
            .unwrap(),
        "existing output",
    );
    assert!(!target.exists());
    let retry = tmp.path().join("retry.ready");
    produce_root(&retry);
    sealed(&retry);
}

#[test]
#[ignore = "needs V3_SOURCE_CHUNK_CORPUS and V3_SOURCE_CHUNK_CASSETTE; local real 300-block evidence, never network"]
fn real_300_blocks_equal_200_plus_100_in_every_semantic_output() {
    let revision = git_snapshot("rev-parse", "HEAD");
    let status = git_snapshot("status", "--porcelain");
    assert!(
        status.is_empty(),
        "real-host evidence requires a clean source worktree"
    );
    let binary_path = Path::new(env!("CARGO_BIN_EXE_graph-mapping-host"));
    let binary = backfill_common::dynamic_sources_v2::FilePin::read(binary_path).unwrap();
    let corpus = PathBuf::from(
        std::env::var("V3_SOURCE_CHUNK_CORPUS").expect("set local raw corpus directory"),
    );
    let cassette = PathBuf::from(
        std::env::var("V3_SOURCE_CHUNK_CASSETTE").expect("set local retained cassette"),
    );
    let raw_pins = raw_inventory(&corpus);
    assert_eq!(
        graph_mapping_host::bundle::sha256_hex(&fs::read(&cassette).unwrap()),
        "3949a5d257ff64e92cc22dea6df2282a5d4207e79cdbfb573821112153b828d6"
    );
    let tmp = tempfile::tempdir().unwrap();
    let output_root = std::env::var_os("V3_SOURCE_CHUNK_EVIDENCE")
        .map(PathBuf::from)
        .unwrap_or_else(|| tmp.path().to_owned());
    let whole = output_root.join("whole.ready");
    let first = output_root.join("first.ready");
    let second = output_root.join("second.ready");
    for (out, from, to, parent) in [
        (&whole, START, START + 300, None),
        (&first, START, START + 200, None),
        (&second, START + 200, START + 300, Some(&first)),
    ] {
        let mut cmd = command(&cassette);
        cmd.arg("--source-chunk-out").arg(out);
        if let Some(parent) = parent {
            cmd.arg("--source-chunk-in").arg(parent);
        }
        cmd.arg("--blocks");
        for number in from..to {
            cmd.arg(corpus.join(format!("{number}.pb")));
        }
        let result = cmd.output().unwrap();
        fs::write(
            output_root.join(format!(
                "{}.report.jsonl",
                out.file_stem().unwrap().to_str().unwrap()
            )),
            &result.stdout,
        )
        .unwrap();
        success(result);
    }
    let w = sealed(&whole);
    let a = sealed(&first);
    let b = sealed(&second);
    assert_eq!(
        w.chunk.stream.sha256, GOLDEN_300_STREAM,
        "new producer changed the existing canonical real 300-block BCF fixture"
    );
    let mut split = fs::read(first.join(seal::STREAM)).unwrap();
    split.extend(fs::read(second.join(seal::STREAM)).unwrap());
    assert_eq!(fs::read(whole.join(seal::STREAM)).unwrap(), split);
    let mut blocks = a.chunk.blocks.clone();
    blocks.extend(b.chunk.blocks.clone());
    assert_eq!(w.chunk.blocks, blocks);
    assert_eq!(w.chunk.after, b.chunk.after);
    assert_eq!(
        fs::read(whole.join(seal::IDENTITIES)).unwrap(),
        fs::read(second.join(seal::IDENTITIES)).unwrap()
    );
    assert!(
        a.chunk.after.order.count > 0,
        "restart must restore accepted dynamic hosts"
    );
    assert!(
        !b.chunk.blocks[0].sources.is_empty(),
        "split boundary must exercise creation ordering"
    );
    let (mut whole_cp, _) = HostCheckpoint::read(&whole.join(seal::CHECKPOINT)).unwrap();
    let (split_cp, _) = HostCheckpoint::read(&second.join(seal::CHECKPOINT)).unwrap();
    assert_eq!(
        whole_cp.header.boundary.block,
        split_cp.header.boundary.block
    );
    assert_eq!(
        whole_cp.header.boundary.block_hash,
        split_cp.header.boundary.block_hash
    );
    assert_eq!(
        whole_cp.header.boundary.blocks_total,
        split_cp.header.boundary.blocks_total
    );
    // Only the explicit chunk provenance differs. Compare the entire remaining
    // checkpoint: identity, cassette, PoI, totals, ordered sources, every row,
    // and cache keys, without changing or normalizing any semantic field.
    whole_cp.header.boundary = split_cp.header.boundary.clone();
    assert_eq!(whole_cp, split_cp);
    assert_eq!(
        revision,
        git_snapshot("rev-parse", "HEAD"),
        "source revision changed during evidence run"
    );
    assert_eq!(
        status,
        git_snapshot("status", "--porcelain"),
        "source worktree changed during evidence run"
    );
    assert_eq!(
        binary,
        backfill_common::dynamic_sources_v2::FilePin::read(binary_path).unwrap(),
        "producer executable changed during evidence run"
    );
    assert_eq!(
        raw_pins,
        raw_inventory(&corpus),
        "raw corpus changed during evidence run"
    );
    assert_eq!(
        graph_mapping_host::bundle::sha256_hex(&fs::read(&cassette).unwrap()),
        "3949a5d257ff64e92cc22dea6df2282a5d4207e79cdbfb573821112153b828d6",
        "historical cassette changed during evidence run"
    );
    let receipt = serde_json::json!({"scope":"real host 300 vs 200+100; not production certification", "from":START,"to":START+300,"split":START+200,"stream_sha256":w.chunk.stream.sha256,"sources":w.chunk.after.order.count,"semantic_source_state":w.chunk.after,"all_semantic_checkpoint_fields_equal":true,"whole_manifest":w.manifest_pin,"first_manifest":a.manifest_pin,"second_manifest":b.manifest_pin,"producer_revision":String::from_utf8(revision).unwrap().trim(),"producer_worktree_dirty":false,"producer_binary":binary,"raw_block_inventory":raw_pins});
    fs::write(
        output_root.join("split-parity-receipt.json"),
        serde_json::to_vec_pretty(&receipt).unwrap(),
    )
    .unwrap();
}

fn git_snapshot(command: &str, option: &str) -> Vec<u8> {
    let output = Command::new("git")
        .current_dir(root())
        .args([command, option])
        .output()
        .unwrap();
    assert!(output.status.success());
    output.stdout
}

fn raw_inventory(
    corpus: &Path,
) -> std::collections::BTreeMap<String, backfill_common::dynamic_sources_v2::FilePin> {
    (START..START + 300)
        .map(|number| {
            (
                number.to_string(),
                backfill_common::dynamic_sources_v2::FilePin::read(
                    &corpus.join(format!("{number}.pb")),
                )
                .unwrap(),
            )
        })
        .collect()
}
