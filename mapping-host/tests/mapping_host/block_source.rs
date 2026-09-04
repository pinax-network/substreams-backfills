//! [`BlockSource`] contiguity and Firehose payload validation, hermetically.
//!
//! Nothing here touches the network. The ordering tests drive a fake source that
//! yields nothing but block pointers, so they exercise exactly the
//! [`CheckedSource`] the live path runs behind. The payload tests reuse the
//! committed block fixtures as real `sf.ethereum.type.v2.Block` bytes, hydrated
//! by `cargo xtask evidence fetch --lock uniswap-v3/fixtures/blocks.lock.json`.

use std::collections::VecDeque;
use std::path::PathBuf;

use anyhow::Result;
use async_trait::async_trait;
use graph::blockchain::{Block as _, BlockHash, BlockTime, ExtendedBlockPtr};
use graph_chain_ethereum::chain::BlockFinality;
use graph_mapping_host::runner::SegmentBounds;
use graph_mapping_host::source::{
    self, BlockSource, CheckedSource, FirehoseTarget, Ordering, ETHEREUM_BLOCK_TYPE,
};

/// A source that yields exactly the block numbers it was handed, in order,
/// however wrong that order is.
struct FakeSource(VecDeque<i32>);

impl FakeSource {
    fn new(numbers: &[i32]) -> Self {
        FakeSource(numbers.iter().copied().collect())
    }
}

#[async_trait]
impl BlockSource for FakeSource {
    async fn next_block(&mut self) -> Result<Option<BlockFinality>> {
        Ok(self.0.pop_front().map(|number| {
            let hash = BlockHash::from(vec![0u8; 32]);
            let parent = BlockHash::from(vec![1u8; 32]);
            BlockFinality::Ptr(std::sync::Arc::new(ExtendedBlockPtr {
                hash,
                number,
                parent_hash: parent,
                timestamp: BlockTime::since_epoch(0, 0),
            }))
        }))
    }

    fn describe(&self) -> String {
        "fake".to_string()
    }
}

/// Drain a checked source, returning either every number it produced or the
/// first error's message.
fn drain(numbers: &[i32], ordering: Ordering) -> Result<Vec<i32>, String> {
    let runtime = tokio::runtime::Builder::new_current_thread()
        .build()
        .expect("tokio runtime");
    runtime.block_on(async {
        let mut source = CheckedSource::new(FakeSource::new(numbers), ordering);
        let mut seen = Vec::new();
        loop {
            match source.next_block().await {
                Ok(Some(block)) => seen.push(block.number()),
                Ok(None) => return Ok(seen),
                Err(e) => return Err(format!("{e:#}")),
            }
        }
    })
}

fn contiguous(start: i32, stop: i32) -> Ordering {
    Ordering::Contiguous { start, stop }
}

#[test]
fn a_contiguous_range_accepts_exactly_its_own_blocks() {
    assert_eq!(
        drain(&[100, 101, 102], contiguous(100, 103)),
        Ok(vec![100, 101, 102])
    );
}

#[test]
fn a_gap_is_refused() {
    let error = drain(&[100, 101, 103], contiguous(100, 104)).unwrap_err();
    assert!(error.contains("gap in the block stream"), "{error}");
    assert!(error.contains("expected block 102, got 103"), "{error}");
}

#[test]
fn a_duplicate_is_refused() {
    let error = drain(&[100, 101, 101], contiguous(100, 104)).unwrap_err();
    assert!(error.contains("block 101 was produced twice"), "{error}");
}

#[test]
fn a_decrease_is_refused() {
    let error = drain(&[100, 101, 99], contiguous(100, 104)).unwrap_err();
    assert!(error.contains("block 99 follows block 101"), "{error}");
    assert!(error.contains("strictly ascending"), "{error}");
}

#[test]
fn a_block_outside_the_range_is_refused() {
    let error = drain(&[100, 101, 102], contiguous(100, 102)).unwrap_err();
    assert!(error.contains("outside the requested range"), "{error}");

    let error = drain(&[99], contiguous(100, 102)).unwrap_err();
    assert!(error.contains("outside the requested range"), "{error}");
}

#[test]
fn a_stream_that_ends_early_is_refused() {
    let error = drain(&[100, 101], contiguous(100, 104)).unwrap_err();
    assert!(error.contains("ended at block 101"), "{error}");
    assert!(error.contains("needs block 103 last"), "{error}");

    let error = drain(&[], contiguous(100, 104)).unwrap_err();
    assert!(error.contains("produced no blocks at all"), "{error}");
}

#[test]
fn sampled_ordering_allows_gaps_but_not_repeats_or_regressions() {
    // The four committed fixtures are four sampled points, so gaps are the
    // normal case there and only strict ascent is enforced.
    assert_eq!(
        drain(&[12369621, 12369739, 12370523], Ordering::Sampled),
        Ok(vec![12369621, 12369739, 12370523])
    );
    assert!(drain(&[10, 10], Ordering::Sampled)
        .unwrap_err()
        .contains("produced twice"));
    assert!(drain(&[10, 9], Ordering::Sampled)
        .unwrap_err()
        .contains("strictly ascending"));
}

// ---------------------------------------------------------------------------
// Firehose payload validation
// ---------------------------------------------------------------------------

fn fixture(number: &str) -> Vec<u8> {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("mapping-host has a parent")
        .join(format!("uniswap-v3/fixtures/blocks/mainnet/{number}.pb"));
    assert!(
        path.exists(),
        "missing block fixture {}; run `cargo xtask evidence fetch --lock \
         uniswap-v3/fixtures/blocks.lock.json` from the repository root",
        path.display()
    );
    std::fs::read(&path).expect("reading a block fixture")
}

fn type_url() -> String {
    format!("type.googleapis.com/{ETHEREUM_BLOCK_TYPE}")
}

#[test]
fn a_single_block_payload_decodes() {
    let block = source::decode_block_payload(12369739, &type_url(), &fixture("12369739"))
        .expect("decoding a real block payload");
    assert_eq!(block.number(), 12369739);
}

#[test]
fn the_bare_protobuf_name_is_accepted_as_a_type_url() {
    source::decode_block_payload(12369739, ETHEREUM_BLOCK_TYPE, &fixture("12369739"))
        .expect("a bare full name is a valid Any type_url suffix");
}

#[test]
fn a_payload_of_the_wrong_type_is_refused() {
    let error = source::decode_block_payload(
        12369739,
        "type.googleapis.com/sf.near.type.v1.Block",
        &fixture("12369739"),
    )
    .unwrap_err()
    .to_string();
    assert!(error.contains("sf.near.type.v1.Block"), "{error}");
    assert!(error.contains(ETHEREUM_BLOCK_TYPE), "{error}");
}

#[test]
fn two_messages_in_one_payload_are_refused() {
    // prost would merge these silently, producing a block that claims to be
    // 12369739 while carrying 12369621's logs as well. That is exactly what
    // release `block-fixtures-v1` shipped.
    let mut merged = fixture("12369621");
    merged.extend_from_slice(&fixture("12369739"));
    let error = source::decode_block_payload(12369621, &type_url(), &merged)
        .unwrap_err()
        .to_string();
    assert!(error.contains("2 concatenated block messages"), "{error}");
    assert!(error.contains("the second is block 12369739"), "{error}");
}

#[test]
fn a_block_with_the_wrong_number_is_refused() {
    let error = source::decode_block_payload(12369740, &type_url(), &fixture("12369739"))
        .unwrap_err()
        .to_string();
    assert!(
        error.contains("produced block 12369739 where block 12369740 was expected"),
        "{error}"
    );
}

/// One `sf.firehose.v2.Response`, built without naming `prost_types`: the `Any`
/// type is reachable through the field's own default, so this crate does not
/// need a dependency on it just to write a test.
fn response(
    step: graph::firehose::ForkStep,
    type_url: &str,
    value: Vec<u8>,
) -> graph::firehose::Response {
    let mut response = graph::firehose::Response {
        block: None,
        step: step as i32,
        cursor: String::new(),
    };
    let mut any = response.block.take().unwrap_or_default();
    any.type_url = type_url.to_string();
    any.value = value;
    response.block = Some(any);
    response
}

#[test]
fn a_response_that_is_not_final_is_refused() {
    let response = response(
        graph::firehose::ForkStep::StepNew,
        &type_url(),
        fixture("12369739"),
    );
    let error = source::block_from_response(12369739, &response)
        .unwrap_err()
        .to_string();
    assert!(error.contains("STEP_NEW"), "{error}");
    assert!(error.contains("final_blocks_only"), "{error}");
}

#[test]
fn a_response_with_no_block_is_refused() {
    let mut response = response(
        graph::firehose::ForkStep::StepFinal,
        &type_url(),
        fixture("12369739"),
    );
    response.block = None;
    let error = source::block_from_response(12369739, &response)
        .unwrap_err()
        .to_string();
    assert!(error.contains("carries no block payload"), "{error}");
}

#[test]
fn a_final_response_decodes() {
    let response = response(
        graph::firehose::ForkStep::StepFinal,
        &type_url(),
        fixture("12369739"),
    );
    let block = source::block_from_response(12369739, &response).expect("decoding a final block");
    assert_eq!(block.number(), 12369739);
}

// ---------------------------------------------------------------------------
// Endpoint validation
// ---------------------------------------------------------------------------

#[test]
fn a_bare_host_and_port_is_accepted_and_means_https() {
    let target = FirehoseTarget::parse("eth.firehose.pinax.network:443").expect("a valid target");
    assert_eq!(target.uri(), "https://eth.firehose.pinax.network:443");
    assert_eq!(target.authority(), "eth.firehose.pinax.network:443");

    let explicit =
        FirehoseTarget::parse("https://eth.firehose.pinax.network:443").expect("a valid target");
    assert_eq!(explicit, target);

    let trailing =
        FirehoseTarget::parse("https://eth.firehose.pinax.network:443/").expect("a valid target");
    assert_eq!(trailing, target);
}

#[test]
fn a_credentialed_endpoint_is_refused() {
    for raw in [
        "someone:hunter2@eth.firehose.pinax.network:443",
        "https://someone:hunter2@eth.firehose.pinax.network:443",
        "https://token@eth.firehose.pinax.network:443",
    ] {
        let error = FirehoseTarget::parse(raw).unwrap_err().to_string();
        assert!(error.contains("userinfo"), "{raw}: {error}");
        assert!(error.contains("FIREHOSE_API_TOKEN"), "{raw}: {error}");
    }
}

#[test]
fn a_query_string_or_fragment_is_refused() {
    for raw in [
        "eth.firehose.pinax.network:443?token=hunter2",
        "https://eth.firehose.pinax.network:443/#hunter2",
    ] {
        let error = FirehoseTarget::parse(raw).unwrap_err().to_string();
        assert!(error.contains("query string or fragment"), "{raw}: {error}");
    }
}

#[test]
fn a_plaintext_or_unknown_scheme_is_refused() {
    for raw in [
        "http://eth.firehose.pinax.network:443",
        "grpc://eth.firehose.pinax.network:443",
    ] {
        let error = FirehoseTarget::parse(raw).unwrap_err().to_string();
        assert!(error.contains("only `https`"), "{raw}: {error}");
    }
}

#[test]
fn a_malformed_endpoint_is_refused() {
    assert!(FirehoseTarget::parse("")
        .unwrap_err()
        .to_string()
        .contains("empty"));
    assert!(FirehoseTarget::parse("eth.firehose.pinax.network")
        .unwrap_err()
        .to_string()
        .contains("no port"));
    assert!(FirehoseTarget::parse("eth.firehose.pinax.network:https")
        .unwrap_err()
        .to_string()
        .contains("not a port number"));
    assert!(FirehoseTarget::parse(":443")
        .unwrap_err()
        .to_string()
        .contains("no host"));
    assert!(
        FirehoseTarget::parse("https://eth.firehose.pinax.network:443/v2/blocks")
            .unwrap_err()
            .to_string()
            .contains("has a path")
    );
    assert!(FirehoseTarget::parse("eth.firehose.pinax.network :443")
        .unwrap_err()
        .to_string()
        .contains("whitespace"));
}

#[test]
fn a_non_ascii_token_is_refused_without_echoing_it() {
    let error = source::validate_token("FIREHOSE_API_TOKEN", "héllo")
        .unwrap_err()
        .to_string();
    assert!(error.contains("FIREHOSE_API_TOKEN"), "{error}");
    assert!(!error.contains("héllo"), "the token must never be echoed");

    assert_eq!(
        source::validate_token("FIREHOSE_API_TOKEN", " abc123 ").expect("a plain token"),
        Some("abc123".to_string())
    );
    assert_eq!(
        source::validate_token("FIREHOSE_API_TOKEN", "  ").expect("an empty token is absent"),
        None
    );
}

// ---------------------------------------------------------------------------
// Segment bounds
// ---------------------------------------------------------------------------

#[test]
fn a_range_below_the_segment_start_is_refused() {
    let bounds = SegmentBounds {
        start: 12369621,
        end: None,
    };
    bounds
        .check_range(12369621, 12369641)
        .expect("the segment's own first block is in range");

    let error = bounds
        .check_range(12369620, 12369641)
        .unwrap_err()
        .to_string();
    assert!(
        error.contains("below this segment's first block"),
        "{error}"
    );

    let error = bounds
        .check_range(12369700, 12369700)
        .unwrap_err()
        .to_string();
    assert!(error.contains("empty range"), "{error}");
}

#[test]
fn a_range_past_a_declared_end_block_is_refused() {
    let bounds = SegmentBounds {
        start: 100,
        end: Some(200),
    };
    bounds.check_range(100, 201).expect("block 200 is the last");
    let error = bounds.check_range(100, 202).unwrap_err().to_string();
    assert!(error.contains("manifest ends at 200"), "{error}");
}
