//! Retain exactly Graph Node's accepted source inventory at the root block.
use graph_mapping_host::{block, blockchanges, SegmentHost, SegmentHostConfig};
use std::path::PathBuf;
const SEGMENT: &str = "Qme66ZNMxSdCQKzaDuvS381whCVYCQjf637sGZCqJHAWHB";

#[tokio::test]
async fn root_sources_sidecar_is_exact_and_rejects_stream_gaps() {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let mut host = SegmentHost::load(SegmentHostConfig {
        bundle_dir: &root.join(format!("segments/{SEGMENT}")),
        cassette_path: &root.join(format!("fixtures/cassettes/{SEGMENT}.json")),
        record: false,
    })
    .await
    .unwrap();
    let outcome = host
        .process_block(
            block::load_block(&root.join("../uniswap-v3/fixtures/blocks/mainnet/12369621.pb"))
                .unwrap(),
        )
        .await
        .unwrap();
    let root_sources = host.stored_dynamic_data_sources().unwrap();
    assert!(root_sources.is_empty());
    let tmp = tempfile::tempdir().unwrap();
    let stream = tmp.path().join("blocks.bcf1");
    let output = tmp.path().join("sources.json");
    let payload = blockchanges::seal(&outcome.changes, host.compatibility()).unwrap();
    std::fs::write(
        &stream,
        blockchanges::bcf1_frame(12369621, &outcome.changes.block_hash, &payload).unwrap(),
    )
    .unwrap();
    graph_mapping_host::dynamic_sources::write(&host, &stream, &output, host.compatibility())
        .unwrap();
    let sidecar = backfill_common::dynamic_sources::Sidecar::parse(
        &std::fs::read(&output).unwrap(),
        host.descriptor_sha256(),
    )
    .unwrap();
    assert!(sidecar.blocks[0].sources.is_empty());
    assert!(graph_mapping_host::dynamic_sources::write(
        &host,
        &stream,
        &output,
        host.compatibility()
    )
    .is_err());
    let next = host
        .process_block(
            block::load_block(&root.join("../uniswap-v3/fixtures/blocks/mainnet/12369739.pb"))
                .unwrap(),
        )
        .await
        .unwrap();
    let sources = host.stored_dynamic_data_sources().unwrap();
    assert!(!sources.is_empty());
    assert_eq!(sources.len(), host.dynamic_data_sources().len());
    for (stored, created) in sources.iter().zip(host.dynamic_data_sources()) {
        assert_eq!(stored.creation_block, created.creation_block);
        assert_eq!(stored.manifest_idx as u32, created.manifest_idx);
        assert_eq!(stored.param, created.params[0].trim_start_matches("0x"));
        assert_eq!(stored.causality_region, 0);
        assert_eq!(stored.context, None);
    }
    let mut bytes = std::fs::read(&stream).unwrap();
    let payload = blockchanges::seal(&next.changes, host.compatibility()).unwrap();
    bytes.extend(blockchanges::bcf1_frame(12369739, &next.changes.block_hash, &payload).unwrap());
    std::fs::write(&stream, bytes).unwrap();
    assert!(graph_mapping_host::dynamic_sources::write(
        &host,
        &stream,
        &tmp.path().join("invalid.json"),
        host.compatibility()
    )
    .is_err());
    let mut bytes = std::fs::read(&stream).unwrap();
    for number in [12369879, 12370523] {
        let outcome = host
            .process_block(
                block::load_block(
                    &root.join(format!("../uniswap-v3/fixtures/blocks/mainnet/{number}.pb")),
                )
                .unwrap(),
            )
            .await
            .unwrap();
        let payload = blockchanges::seal(&outcome.changes, host.compatibility()).unwrap();
        bytes.extend(
            blockchanges::bcf1_frame(number as u64, &outcome.changes.block_hash, &payload).unwrap(),
        );
    }
    std::fs::write(&stream, bytes).unwrap();
    let error = graph_mapping_host::dynamic_sources::write(
        &host,
        &stream,
        &tmp.path().join("error.json"),
        host.compatibility(),
    )
    .unwrap_err();
    assert!(
        error.to_string().contains("indexing-error metadata"),
        "{error}"
    );
}
