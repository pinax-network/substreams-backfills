//! Contract/storage tests only. Payloads and checkpoint bytes here are synthetic,
//! not evidence that a mapping ran or a Graph Node database was reproduced.
use backfill_common::{
    dynamic_sources::DataSource,
    dynamic_sources_v2::{
        self as v2, index, seal, Block, Chunk, Creation, FilePin, SourceOrder, SourceState,
    },
};
use std::{collections::BTreeSet, fs, path::Path};

fn source(block: u64, address: u8) -> DataSource {
    DataSource {
        creation_block: block as i32,
        manifest_idx: 2,
        causality_region: 0,
        param: hex::encode([address; 20]),
        context: None,
        done_at: None,
    }
}

fn stage(
    root: &Path,
    name: &str,
    from: u64,
    to: u64,
    parent: Option<&seal::SealedChunk>,
    creations: &[(u64, u8)],
) -> (std::path::PathBuf, std::path::PathBuf, Chunk) {
    let building = root.join(format!("{name}.building"));
    let output = root.join(format!("{name}.ready"));
    fs::create_dir(&building).unwrap();
    let before = parent
        .map(|p| p.chunk.after.clone())
        .unwrap_or_else(SourceState::empty);
    let mut order = before.order.clone();
    let mut blocks = Vec::new();
    let mut bytes = Vec::new();
    let mut keys = BTreeSet::new();
    for n in from..to {
        let hash = [n as u8; 32];
        let payload = n.to_be_bytes();
        bytes.extend(b"BCF1\x01\0\0\0");
        bytes.extend(n.to_be_bytes());
        bytes.extend(hash);
        bytes.extend((payload.len() as u32).to_be_bytes());
        bytes.extend(payload);
        let mut sources = Vec::new();
        for (_, address) in creations.iter().filter(|(b, _)| *b == n) {
            let creation = Creation {
                ordinal: order.count,
                source: source(n, *address),
            };
            keys.insert(order.append(&creation).unwrap());
            sources.push(creation);
        }
        blocks.push(Block {
            block_number: n,
            block_hash: hex::encode(hash),
            payload_sha256: FilePin::for_bytes(&payload).sha256,
            sources,
        });
    }
    let parent_index = parent.map(|p| p.directory.join(seal::IDENTITIES));
    let identities = index::merge(
        &building.join(seal::IDENTITIES),
        parent_index.as_deref().map(|p| (p, &before)),
        &keys,
    )
    .unwrap();
    fs::write(building.join(seal::STREAM), &bytes).unwrap();
    let checkpoint = to.to_be_bytes();
    fs::write(building.join(seal::CHECKPOINT), checkpoint).unwrap();
    let chunk = Chunk {
        contract: v2::CONTRACT.into(),
        deployment: "deployment".into(),
        network: "mainnet".into(),
        descriptor_sha256: "ab".repeat(32),
        root_start_block: 10,
        from,
        to,
        parent: parent.map(|p| p.parent()),
        stream: FilePin::for_bytes(&bytes),
        checkpoint: FilePin::for_bytes(&checkpoint),
        before,
        after: SourceState { order, identities },
        blocks,
    };
    (building, output, chunk)
}

fn complete(
    root: &Path,
    name: &str,
    from: u64,
    to: u64,
    parent: Option<&seal::SealedChunk>,
    creations: &[(u64, u8)],
) -> seal::SealedChunk {
    let (building, output, chunk) = stage(root, name, from, to, parent, creations);
    seal::publish(&building, &output, &chunk, parent).unwrap()
}

#[test]
fn source_order_and_disk_index_are_chunk_boundary_independent() {
    let root = tempfile::tempdir().unwrap();
    // Includes empty chunks and two accepted creations in one block, in a
    // deliberately non-lexical order. Identity sorting must not sort COPY order.
    let creations = [(11, 8), (11, 3), (13, 6), (15, 1)];
    let whole = complete(root.path(), "whole", 10, 16, None, &creations);
    let a = complete(root.path(), "a", 10, 11, None, &creations);
    let b = complete(root.path(), "b", 11, 12, Some(&a), &creations);
    let c = complete(root.path(), "c", 12, 14, Some(&b), &creations);
    let d = complete(root.path(), "d", 14, 16, Some(&c), &creations);
    assert_eq!(whole.chunk.after, d.chunk.after);
    assert_eq!(
        fs::read(whole.directory.join(seal::IDENTITIES)).unwrap(),
        fs::read(d.directory.join(seal::IDENTITIES)).unwrap()
    );
    let split_blocks: Vec<_> = [&a, &b, &c, &d]
        .into_iter()
        .flat_map(|p| p.chunk.blocks.clone())
        .collect();
    assert_eq!(whole.chunk.blocks, split_blocks);
    let split_stream: Vec<_> = [&a, &b, &c, &d]
        .into_iter()
        .flat_map(|p| fs::read(p.directory.join(seal::STREAM)).unwrap())
        .collect();
    assert_eq!(
        fs::read(whole.directory.join(seal::STREAM)).unwrap(),
        split_stream
    );
    for chunk in [&whole, &a, &b, &c, &d] {
        assert_eq!(
            Chunk::parse(
                &fs::read(chunk.directory.join(seal::METADATA)).unwrap(),
                &"ab".repeat(32)
            )
            .unwrap(),
            chunk.chunk
        );
    }
}

#[test]
fn unpromoted_and_symlinked_chunks_are_not_predecessors() {
    let root = tempfile::tempdir().unwrap();
    let parent = complete(root.path(), "parent", 10, 11, None, &[]);
    let staging = root.path().join("unpromoted.building");
    fs::rename(&parent.directory, &staging).unwrap();
    let error = seal::SealedChunk::open(&staging, &parent.chunk.descriptor_sha256)
        .err()
        .unwrap();
    assert!(error.contains("promoted .ready"), "{error}");
    assert!(parent.verify_unchanged().is_err());
    #[cfg(unix)]
    {
        let linked = root.path().join("linked.ready");
        std::os::unix::fs::symlink(&staging, &linked).unwrap();
        assert!(seal::SealedChunk::open(&linked, &parent.chunk.descriptor_sha256).is_err());
        let (building, output, chunk) = stage(root.path(), "broken-target", 10, 11, None, &[]);
        std::os::unix::fs::symlink(root.path().join("absent"), &output).unwrap();
        assert!(seal::publish(&building, &output, &chunk, None).is_err());
        assert!(fs::symlink_metadata(&output)
            .unwrap()
            .file_type()
            .is_symlink());
        assert!(!building.join(seal::READY).exists());
    }
}

#[test]
fn index_refuses_cross_chunk_duplicates_before_output_and_keeps_parent_immutable() {
    let root = tempfile::tempdir().unwrap();
    let parent = complete(root.path(), "parent", 10, 12, None, &[(11, 8)]);
    let path = parent.directory.join(seal::IDENTITIES);
    let before = fs::read(&path).unwrap();
    let duplicate = v2::identity(&source(12, 8)).unwrap();
    let output = root.path().join("rejected.index");
    let error = index::merge(
        &output,
        Some((&path, &parent.chunk.after)),
        &BTreeSet::from([duplicate]),
    )
    .unwrap_err();
    assert!(error.contains("already exists"));
    assert!(!output.exists());
    assert_eq!(before, fs::read(&path).unwrap());
}

#[test]
fn exact_direct_predecessor_files_are_required_and_rechecked_before_seal() {
    let root = tempfile::tempdir().unwrap();
    let parent = complete(root.path(), "parent", 10, 12, None, &[(11, 8)]);
    let (building, output, child) = stage(root.path(), "child", 12, 14, Some(&parent), &[(13, 3)]);
    for name in [
        seal::STREAM,
        seal::CHECKPOINT,
        seal::METADATA,
        seal::MANIFEST,
        seal::READY,
        seal::IDENTITIES,
    ] {
        let path = parent.directory.join(name);
        let original = fs::read(&path).unwrap();
        fs::write(&path, b"changed").unwrap();
        assert!(
            seal::SealedChunk::open(&parent.directory, &"ab".repeat(32)).is_err(),
            "{name}"
        );
        assert!(
            seal::publish(&building, &output, &child, Some(&parent)).is_err(),
            "{name}"
        );
        assert!(!output.exists());
        assert!(!building.join(seal::READY).exists());
        fs::write(&path, &original).unwrap();
    }
    let published = seal::publish(&building, &output, &child, Some(&parent)).unwrap();
    assert_eq!(published.chunk.parent, Some(parent.parent()));
    parent.verify_unchanged().unwrap();
    fs::write(parent.directory.join("unlisted"), b"extra").unwrap();
    assert!(parent.verify_unchanged().is_err());
}

#[test]
fn corrupt_ordered_or_torn_index_is_refused_even_with_a_new_file_hash() {
    let root = tempfile::tempdir().unwrap();
    let parent = complete(root.path(), "parent", 10, 12, None, &[(11, 8), (11, 3)]);
    let original = fs::read(parent.directory.join(seal::IDENTITIES)).unwrap();
    let mut reversed = original.clone();
    reversed[8..32].copy_from_slice(&original[32..56]);
    reversed[32..56].copy_from_slice(&original[8..32]);
    let mut duplicate = original.clone();
    duplicate[32..56].copy_from_slice(&original[8..32]);
    for bytes in [original[..55].to_vec(), reversed, duplicate] {
        let path = root.path().join("bad.index");
        fs::write(&path, &bytes).unwrap();
        let mut state = parent.chunk.after.clone();
        state.identities = FilePin::for_bytes(&bytes);
        assert!(index::Index::open(&path, &state).is_err());
    }
}

#[test]
fn metadata_refuses_gaps_reordering_unsupported_values_and_false_prefixes() {
    let root = tempfile::tempdir().unwrap();
    let value = complete(root.path(), "whole", 10, 13, None, &[(11, 8), (11, 3)]).chunk;
    let mutations: Vec<fn(&mut Chunk)> = vec![
        |c| c.contract = "pinax.graph.backfill.data-sources/v1".into(),
        |c| c.blocks.pop().map(drop).unwrap(),
        |c| c.blocks.swap(0, 1),
        |c| c.to = c.from + 10_001,
        |c| c.from += 1,
        |c| c.blocks[1].sources.swap(0, 1),
        |c| c.blocks[1].sources[0].ordinal += 1,
        |c| c.blocks[1].sources[0].source.context = Some(serde_json::json!({})),
        |c| c.blocks[1].sources[0].source.done_at = Some(12),
        |c| c.blocks[1].sources[0].source.causality_region = 1,
        |c| c.blocks[1].sources[0].source.creation_block = 10,
        |c| c.before.order = c.after.order.clone(),
        |c| c.after.order.sha256 = "00".repeat(32),
    ];
    for mutate in mutations {
        let mut changed = value.clone();
        mutate(&mut changed);
        assert!(changed.validate(&"ab".repeat(32)).is_err());
    }
    assert!(Chunk::parse(&vec![b' '; v2::MAX_BYTES + 1], &"ab".repeat(32)).is_err());
}

#[test]
fn long_identity_history_uses_disk_lookup_and_streamed_merge() {
    let root = tempfile::tempdir().unwrap();
    let mut order = SourceOrder::empty();
    let mut state = SourceState::empty();
    let mut previous = None;
    for chunk in 0..10 {
        let keys: BTreeSet<_> = (0..1_000)
            .map(|i| {
                let n: u32 = chunk * 1_000 + i;
                let mut param = [0; 20];
                param[16..].copy_from_slice(&n.to_be_bytes());
                let mut source = source(10 + chunk as u64, 0);
                source.param = hex::encode(param);
                order
                    .append(&Creation {
                        ordinal: order.count,
                        source,
                    })
                    .unwrap()
            })
            .collect();
        let output = root.path().join(format!("{chunk}.index"));
        let pin = index::merge(&output, previous.as_deref().map(|p| (p, &state)), &keys).unwrap();
        state = SourceState {
            order: order.clone(),
            identities: pin,
        };
        previous = Some(output);
    }
    assert_eq!(state.order.count, 10_000);
    assert_eq!(state.identities.bytes, 8 + 24 * 10_000);
    let mut index = index::Index::open(previous.as_deref().unwrap(), &state).unwrap();
    let mut first = [0; 24];
    first[3] = 2;
    assert!(index.contains(&first).unwrap());
    let mut missing = first;
    missing[4] = 1;
    assert!(!index.contains(&missing).unwrap());
}
