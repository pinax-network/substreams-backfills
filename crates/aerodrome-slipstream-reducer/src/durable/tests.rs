use super::*;
use crate::{
    identity::{build_descriptor, OUTPUT_MODULE, OUTPUT_TYPE},
    input::{validate_block, InputStream},
    pb,
    runner::{AbortMode, InputCompletion, MemoryRunner, Runner},
    state::{Abort, MemoryBackend, Step},
};
use aerodrome_extractor_core::config::INITIAL_BLOCK;
use backfill_common::{
    clock::{self, Frame, FrameKind},
    descriptor::ExtractorIdentity,
};
use std::{io::Cursor, process::Command};

mod seed_import;

fn bindings() -> (InputBinding, Binding) {
    let x = ExtractorIdentity {
        spkg_sha256: "11".repeat(32),
        module: OUTPUT_MODULE.into(),
        module_hash: "22".repeat(20),
        output_type: OUTPUT_TYPE.into(),
        initial_block: INITIAL_BLOCK,
    };
    let bytes = build_descriptor(&x, &"33".repeat(20), true).unwrap();
    let b = InputBinding::new(&bytes, Sha256::digest(&bytes).into(), &x).unwrap();
    let p = Binding {
        family: "aerodrome-slipstream".into(),
        deployment: b.compatibility().capabilities().unwrap().deployment.clone(),
        network: "base".into(),
        descriptor_sha256: hex::encode(b.compatibility().id()),
        extractor_lock_sha256: "44".repeat(32),
        spkg_sha256: x.spkg_sha256,
        module: x.module,
        module_hash: x.module_hash,
        reducer_commit: "33".repeat(20),
        reducer_binary_sha256: "55".repeat(32),
    };
    (b, p)
}
fn first() -> pb::ExtractorBlock {
    let mut b = pb::ExtractorBlock::decode(
        include_bytes!("../../fixtures/first-pool-extractor.pb").as_slice(),
    )
    .unwrap();
    b.number = INITIAL_BLOCK;
    b.candidates.truncate(1);
    let c = b.calls.as_mut().unwrap();
    c.ticks.clear();
    c.positions.clear();
    c.fee_growth.clear();
    c.get_pool.clear();
    b
}
fn next(b: &pb::ExtractorBlock) -> pb::ExtractorBlock {
    let mut n = b.clone();
    n.number += 1;
    n.parent_hash = b.hash.clone();
    n.hash = vec![91; 32];
    n.timestamp += 1;
    n.transactions.clear();
    n.candidates.clear();
    n.pools_created.clear();
    n.calls = Some(Default::default());
    n
}
fn frame(b: &pb::ExtractorBlock) -> Frame {
    Frame {
        kind: FrameKind::Observed,
        block_number: b.number,
        block_hash: b.hash.clone().try_into().unwrap(),
        payload: b.encode_to_vec(),
    }
}
fn bytes(blocks: &[pb::ExtractorBlock]) -> Vec<u8> {
    let mut v = vec![];
    for b in blocks {
        clock::write_frame(&mut v, &frame(b)).unwrap();
    }
    v
}
fn input(blocks: &[pb::ExtractorBlock], data: Vec<u8>) -> InputStream<Cursor<Vec<u8>>> {
    InputStream::new(
        Cursor::new(data),
        bindings().0,
        blocks[0].number,
        blocks.last().unwrap().number,
        blocks[0].parent_hash.clone().try_into().unwrap(),
    )
    .unwrap()
}
fn store(path: &Path) -> DurableStore {
    let (b, p) = bindings();
    DurableStore::init_empty(path, &b, p, &"66".repeat(32), 1024 * 1024).unwrap()
}
fn begin(store: &DurableStore, parent: &[u8]) -> Segment {
    let m = store.manifest().unwrap();
    store
        .begin_segment(
            &m.boundary,
            &m.reducer_lineage,
            &"66".repeat(32),
            (m.boundary.block_hash == [0; 32]).then(|| parent.try_into().unwrap()),
        )
        .unwrap()
}
fn run(store: &DurableStore, blocks: &[pb::ExtractorBlock], out: &Path) -> Manifest {
    let r = Runner::new(bindings().0, begin(store, &blocks[0].parent_hash)).unwrap();
    run_segment(r, input(blocks, bytes(blocks)), out, 50_000, true, |s| {
        assert_eq!(s, InputCompletion::Complete);
        Ok(())
    })
    .unwrap()
}

#[test]
fn segmented_restart_and_rewind_match_uninterrupted_frames_and_logical_state() {
    let t = tempfile::tempdir().unwrap();
    let b = first();
    let blocks = vec![b.clone(), next(&b)];
    let all = store(&t.path().join("all"));
    let full = run(&all, &blocks, &t.path().join("all-output"));
    let root = t.path().join("parts");
    let parts = store(&root);
    let initial = parts.manifest().unwrap();
    let one = run(&parts, &blocks[..1], &t.path().join("one"));
    assert_eq!(one.sources.count, 1);
    assert_eq!(one.retained_by_type.values().sum::<u64>(), 5);
    drop(parts);
    let (binding, pin) = bindings();
    let parts = DurableStore::open(&root, &binding, pin, 1024 * 1024).unwrap();
    let two = run(&parts, &blocks[1..], &t.path().join("two"));
    assert_eq!(two.full_state_sha256, full.full_state_sha256);
    let mut actual = fs::read(t.path().join("one/frames.bcf1")).unwrap();
    actual.extend(fs::read(t.path().join("two/frames.bcf1")).unwrap());
    assert_eq!(
        actual,
        fs::read(t.path().join("all-output/frames.bcf1")).unwrap()
    );
    let mut memory = MemoryRunner::new(
        bindings().0,
        MemoryBackend::root(&bindings().0, b.parent_hash.clone().try_into().unwrap()).unwrap(),
    )
    .unwrap();
    let mut expected = vec![];
    for block in &blocks {
        let validated =
            validate_block(&frame(block), block.parent_hash.clone().try_into().unwrap()).unwrap();
        clock::write_frame(&mut expected, memory.process(&validated).unwrap().frame()).unwrap();
    }
    assert_eq!(actual, expected);
    assert_eq!(parts.rewind_one(&two).unwrap(), one);
    assert_eq!(parts.rewind_one(&one).unwrap(), initial);
    let again = run(&parts, &blocks[..1], &t.path().join("again"));
    assert_eq!(again, one);
    assert_eq!(
        fs::read(t.path().join("again/frames.bcf1")).unwrap(),
        fs::read(t.path().join("one/frames.bcf1")).unwrap()
    );
}

#[test]
fn truncation_and_failed_producer_do_not_advance_state_or_publish_success() {
    let t = tempfile::tempdir().unwrap();
    let s = store(&t.path().join("state"));
    let initial = s.manifest().unwrap();
    let b = first();
    for (name, truncated, failed) in [("short", true, false), ("producer", false, true)] {
        let mut data = bytes(std::slice::from_ref(&b));
        if truncated {
            data.pop();
        }
        let mut called = false;
        let out = t.path().join(name);
        let r = Runner::new(bindings().0, begin(&s, &b.parent_hash)).unwrap();
        let got = run_segment(
            r,
            input(std::slice::from_ref(&b), data),
            &out,
            50_000,
            false,
            |status| {
                called = true;
                assert_eq!(
                    status,
                    if truncated {
                        InputCompletion::Refused
                    } else {
                        InputCompletion::Complete
                    }
                );
                if failed {
                    Err(refuse("producer killed"))
                } else {
                    Ok(())
                }
            },
        );
        assert!(got.is_err());
        assert!(called);
        assert!(!out.join("complete.json").exists());
        assert_eq!(s.manifest().unwrap(), initial);
    }
}

#[test]
fn storage_failure_poison_and_drop_roll_back_every_partial_block_write() {
    let t = tempfile::tempdir().unwrap();
    let s = store(&t.path().join("state"));
    let initial = s.manifest().unwrap();
    let b = first();
    let segment = begin(&s, &b.parent_hash);
    segment.fail_after.set(Some(2));
    let mut r = Runner::new(bindings().0, segment).unwrap();
    let block = validate_block(&frame(&b), b.parent_hash.clone().try_into().unwrap()).unwrap();
    assert!(r.process(&block).is_err());
    assert!(r.backend().get(&Key::new("Bundle", "1")).is_err());
    assert!(r.backend().state_digest().is_err());
    assert!(r.into_backend().is_err());
    assert_eq!(s.manifest().unwrap(), initial);
    let tx = begin(&s, &b.parent_hash);
    assert!(tx.get(&Key::new("Bundle", "1")).unwrap().is_none());
}

#[test]
fn corrupt_undo_never_partially_rewinds_committed_state() {
    let t = tempfile::tempdir().unwrap();
    let s = store(&t.path().join("state"));
    let b = first();
    let m = run(&s, std::slice::from_ref(&b), &t.path().join("out"));
    let path = s.root.join(&m.transition.as_ref().unwrap().undo.path);
    let original = fs::read(&path).unwrap();
    let mut damaged = original.clone();
    *damaged.last_mut().unwrap() ^= 1;
    fs::write(&path, damaged).unwrap();
    assert!(s.rewind_one(&m).is_err());
    assert_eq!(s.manifest().unwrap(), m);
    let tx = begin(&s, &b.hash);
    assert_eq!(
        tx.state_digest().unwrap(),
        m.full_state_sha256.clone().unwrap()
    );
    drop(tx);
    fs::write(path, original).unwrap();
    s.rewind_one(&m).unwrap();
}

#[test]
fn failed_factory_host_history_survives_backend_reconstruction_and_rewind() {
    let t = tempfile::tempdir().unwrap();
    let s = store(&t.path().join("state"));
    let b = first();
    let mut r = Runner::with_abort_mode(
        bindings().0,
        begin(&s, &b.parent_hash),
        AbortMode::EmitNonFatal,
    )
    .unwrap();
    let input = validate_block(&frame(&b), b.parent_hash.clone().try_into().unwrap()).unwrap();
    r.process_with(&input, |_, _| {
        Err(Step::Abort(Abort {
            message: "test-only Factory abort".into(),
        }))
    })
    .unwrap();
    let output = t.path().join("manual-test-only-seal");
    fs::create_dir(&output).unwrap();
    // Internal test reaches the private commit to isolate host restoration;
    // production callers only reach it via the stream completion gate.
    let m = r
        .into_backend()
        .unwrap()
        .seal_and_commit(true, &output)
        .unwrap();
    assert_eq!(m.failed_hosts.count, 1);
    assert_eq!(m.sources.count, 0);
    let real = pb::ExtractorBlock::decode(
        include_bytes!("../../fixtures/first-pool-extractor.pb").as_slice(),
    )
    .unwrap();
    let real = validate_block(&frame(&real), real.parent_hash.clone().try_into().unwrap()).unwrap();
    let tx = begin(&s, &b.hash);
    let hosts = tx.host_set().unwrap();
    for (i, c) in real.block().candidates.iter().enumerate() {
        if c.source == pb::DataSourceKind::Pool as i32 {
            assert!(hosts.match_candidate(&real, i).unwrap().is_none());
        }
    }
    drop(tx);
    s.rewind_one(&m).unwrap();
    let tx = begin(&s, &b.parent_hash);
    assert!(tx.host_set().unwrap().match_candidate(&real, 3).is_err());
}

#[test]
fn child_crash_entry() {
    let Ok(path) = std::env::var("AERODROME_CRASH_TEST_STATE") else {
        return;
    };
    let (b, p) = bindings();
    let s = DurableStore::open(Path::new(&path), &b, p, 1024 * 1024).unwrap();
    let first = first();
    let mut runner = Runner::new(b, begin(&s, &first.parent_hash)).unwrap();
    runner
        .process(
            &validate_block(
                &frame(&first),
                first.parent_hash.clone().try_into().unwrap(),
            )
            .unwrap(),
        )
        .unwrap();
    std::process::exit(77); // Deliberately skips every Rust destructor.
}
#[test]
fn process_death_leaves_exact_previous_committed_boundary() {
    let t = tempfile::tempdir().unwrap();
    let path = t.path().join("state");
    let s = store(&path);
    let initial = s.manifest().unwrap();
    drop(s);
    let status = Command::new(std::env::current_exe().unwrap())
        .args([
            "--exact",
            "durable::tests::child_crash_entry",
            "--nocapture",
        ])
        .env("AERODROME_CRASH_TEST_STATE", &path)
        .status()
        .unwrap();
    assert_eq!(status.code(), Some(77));
    let (b, p) = bindings();
    let s = DurableStore::open(&path, &b, p, 1024 * 1024).unwrap();
    assert_eq!(s.manifest().unwrap(), initial);
    run(&s, &[first()], &t.path().join("after-crash"));
}

#[test]
fn missing_and_relabelled_hosts_refuse_restoration() {
    for kind in [
        "source-ordinal",
        "missing-source",
        "failed-ordinal",
        "failed-boundary",
        "missing-failed",
    ] {
        let t = tempfile::tempdir().unwrap();
        let s = store(&t.path().join("state"));
        let b = first();
        let failed = kind.contains("failed");
        if failed {
            let mut runner = Runner::with_abort_mode(
                bindings().0,
                begin(&s, &b.parent_hash),
                AbortMode::EmitNonFatal,
            )
            .unwrap();
            runner
                .process_with(
                    &validate_block(&frame(&b), b.parent_hash.clone().try_into().unwrap()).unwrap(),
                    |_, _| {
                        Err(Step::Abort(Abort {
                            message: "test-only abort".into(),
                        }))
                    },
                )
                .unwrap();
            let out = t.path().join("test-only-seal");
            fs::create_dir(&out).unwrap();
            runner
                .into_backend()
                .unwrap()
                .seal_and_commit(false, &out)
                .unwrap();
        } else {
            run(&s, std::slice::from_ref(&b), &t.path().join("out"));
        }
        let m = s.manifest().unwrap();
        let tx = s.database.begin_write().unwrap();
        {
            let mut table = tx
                .open_table(if failed { FAILED } else { SOURCES })
                .unwrap();
            let (key, value) = {
                let first = table.iter().unwrap().next().unwrap().unwrap();
                (first.0.value().to_vec(), first.1.value().to_vec())
            };
            if kind.starts_with("missing") {
                table.remove(key.as_slice()).unwrap();
            } else {
                let mut source: Source = decode(&value).unwrap();
                if kind.ends_with("boundary") {
                    source.failed_at_hash = Some([123; 32]);
                } else {
                    source.ordinal += 1;
                }
                let bytes = canonical(&source).unwrap();
                table.insert(key.as_slice(), bytes.as_slice()).unwrap();
            }
        }
        tx.commit().unwrap();
        let attempt = s.begin_segment(&m.boundary, &m.reducer_lineage, &"66".repeat(32), None);
        match attempt {
            Err(_) => assert!(kind.starts_with("missing")),
            Ok(segment) => assert!(segment.host_set().is_err(), "{kind}"),
        }
    }
}

#[test]
fn explicit_null_cache_image_survives_restart_and_undo() {
    use backfill_common::pb::pinax::graph::backfill::v1 as wire;
    let t = tempfile::tempdir().unwrap();
    let s = store(&t.path().join("state"));
    let b = first();
    let first_manifest = run(&s, std::slice::from_ref(&b), &t.path().join("first"));
    let mut segment = begin(&s, &b.hash);
    let key = Key::new(
        "Token",
        &format!("0x{}", hex::encode(&b.pools_created[0].token0)),
    );
    let original = segment.get(&key).unwrap().unwrap();
    let mut fields = original.clone();
    fields.retain(|f| f.name != "version");
    fields.push(wire::EntityField {
        name: "version".into(),
        value: Some(wire::GraphValue {
            kind: Some(wire::graph_value::Kind::Null(wire::NullValue {})),
        }),
    });
    fields.sort_by(|a, b| a.name.cmp(&b.name));
    let second = next(&b);
    let input = validate_block(
        &frame(&second),
        second.parent_hash.clone().try_into().unwrap(),
    )
    .unwrap();
    let mut journal = crate::state::BlockStore::begin(&segment, &bindings().0, &input).unwrap();
    journal
        .run_handler(0, |h| {
            h.remove_fields("Token", &key.id)?;
            h.save_fields("Token", &key.id, &fields)?;
            Ok(())
        })
        .unwrap();
    segment.commit(journal.seal().unwrap()).unwrap();
    assert_eq!(segment.get(&key).unwrap(), Some(fields.clone()));
    let out = t.path().join("test-only-null-seal");
    fs::create_dir(&out).unwrap();
    let second_manifest = segment.seal_and_commit(true, &out).unwrap();
    drop(s);
    let (b, p) = bindings();
    let s = DurableStore::open(&t.path().join("state"), &b, p, 1024 * 1024).unwrap();
    let segment = begin(&s, &second.hash);
    assert_eq!(segment.get(&key).unwrap(), Some(fields));
    drop(segment);
    assert_eq!(s.rewind_one(&second_manifest).unwrap(), first_manifest);
    let segment = begin(&s, &second.parent_hash);
    assert_eq!(segment.get(&key).unwrap(), Some(original));
}
