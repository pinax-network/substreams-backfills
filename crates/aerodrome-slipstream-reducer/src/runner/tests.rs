use super::*;
use crate::{
    identity::{build_descriptor, OUTPUT_MODULE, OUTPUT_TYPE},
    input::validate_block,
    state::Abort,
};
use aerodrome_extractor_core::config::INITIAL_BLOCK;
use backfill_common::{
    clock::{self, FrameKind},
    descriptor::ExtractorIdentity,
    pb::pinax::graph::backfill::v2 as output,
};
use prost::Message;
use sha2::{Digest, Sha256};
use std::{
    cell::Cell,
    collections::BTreeMap,
    io::{self, Cursor},
};

fn binding(nonfatal: bool) -> InputBinding {
    let extractor = ExtractorIdentity {
        spkg_sha256: "11".repeat(32),
        module: OUTPUT_MODULE.into(),
        module_hash: "22".repeat(20),
        output_type: OUTPUT_TYPE.into(),
        initial_block: INITIAL_BLOCK,
    };
    let bytes = build_descriptor(&extractor, &"33".repeat(20), nonfatal).unwrap();
    InputBinding::new(&bytes, Sha256::digest(&bytes).into(), &extractor).unwrap()
}
fn original() -> pb::ExtractorBlock {
    pb::ExtractorBlock::decode(include_bytes!("../../fixtures/first-pool-extractor.pb").as_slice())
        .unwrap()
}
fn frame(block: &pb::ExtractorBlock) -> Frame {
    Frame {
        kind: FrameKind::Observed,
        block_number: block.number,
        block_hash: block.hash.clone().try_into().unwrap(),
        payload: block.encode_to_vec(),
    }
}
fn validate(block: &pb::ExtractorBlock) -> BlockInput {
    validate_block(&frame(block), block.parent_hash.clone().try_into().unwrap()).unwrap()
}
fn runner(block: &pb::ExtractorBlock, mode: AbortMode) -> MemoryRunner {
    let binding = binding(true);
    let backend = MemoryBackend::from_images(
        &binding,
        Boundary {
            block_number: block.number - 1,
            block_hash: block.parent_hash.clone().try_into().unwrap(),
        },
        BTreeMap::new(),
        BTreeMap::new(),
    )
    .unwrap();
    MemoryRunner::with_abort_mode(binding, backend, mode).unwrap()
}
fn next_empty(b: &pb::ExtractorBlock) -> pb::ExtractorBlock {
    let mut next = b.clone();
    next.number += 1;
    next.parent_hash = b.hash.clone();
    next.hash = vec![68; 32];
    next.timestamp += 1;
    next.transactions.clear();
    next.candidates.clear();
    next.pools_created.clear();
    next.calls = Some(pb::CallAnswers::default());
    next
}
fn bytes(blocks: &[pb::ExtractorBlock]) -> Vec<u8> {
    let mut out = Vec::new();
    for block in blocks {
        clock::write_frame(&mut out, &frame(block)).unwrap();
    }
    out
}
fn limits() -> MemoryLimits {
    MemoryLimits {
        max_blocks: 10,
        max_candidates: 100,
        max_output_payload_bytes: 1_000_000,
    }
}
fn stream(data: Vec<u8>, first: &pb::ExtractorBlock, end: u64) -> InputStream<Cursor<Vec<u8>>> {
    InputStream::new(
        Cursor::new(data),
        binding(true),
        first.number,
        end,
        first.parent_hash.clone().try_into().unwrap(),
    )
    .unwrap()
}
fn decode(block: &CommittedBlock) -> output::BlockChanges {
    output::BlockChanges::decode(block.frame.payload.as_slice()).unwrap()
}

#[test]
fn complete_real_first_pool_matches_whole_original_graph_node_envelope() {
    let b = original();
    let mut runner = runner(&b, AbortMode::FailClosed);
    let got = runner.process(&validate(&b)).unwrap();
    assert_eq!(
        got.candidates
            .iter()
            .map(|r| (r.wave, r.source_trigger_order))
            .collect::<Vec<_>>(),
        [(0, 172), (0, 177), (0, 178), (1, 171), (1, 176)]
    );
    assert!(got
        .candidates
        .iter()
        .all(|r| matches!(r.outcome, CandidateOutcome::Committed { .. })));
    let corpus: serde_json::Value = serde_json::from_slice(include_bytes!(
        "../../fixtures/graph-node-first-handlers.json"
    ))
    .unwrap();
    let case = corpus["cases"]
        .as_array()
        .unwrap()
        .iter()
        .find(|c| c["name"] == "real_first_pool")
        .unwrap();
    let expected = output::BlockChanges::decode(
        hex::decode(case["changes_hex"].as_str().unwrap())
            .unwrap()
            .as_slice(),
    )
    .unwrap();
    let mut changes = decode(&got);
    changes.compatibility_id.clear();
    assert_eq!(changes, expected); // no filtered operations or renumbered groups
    assert_eq!(runner.backend.sources().len(), 1);
    assert_eq!(runner.backend.boundary().block_number, b.number);
    // Actual empty blocks are retained with mapping_triggered=false.
    let empty = runner.process(&validate(&next_empty(&b))).unwrap();
    assert!(!decode(&empty).mapping_triggered);
    assert!(empty.candidates.is_empty());
}

#[test]
fn later_missing_call_rolls_back_earlier_factory_and_poisons_runner() {
    let mut b = original();
    b.calls.as_mut().unwrap().positions.clear();
    let mut runner = runner(&b, AbortMode::FailClosed);
    assert!(runner
        .process(&validate(&b))
        .unwrap_err()
        .0
        .contains("MissingCallAnswer"));
    assert!(runner.backend.rows().is_empty());
    assert!(runner.backend.sources().is_empty());
    assert_eq!(runner.backend.boundary().block_number, b.number - 1);
    assert!(runner
        .process(&validate(&original()))
        .unwrap_err()
        .0
        .contains("poisoned"));
}

#[test]
fn nonfatal_failed_creation_never_installs_host_and_explains_future_superset() {
    // Fault injection tests scheduler rollback after dataSource.create. This is
    // not a claimed naturally reachable Factory abort or WASM oracle fixture.
    let mut b = original();
    b.candidates
        .retain(|c| c.source != pb::DataSourceKind::PositionManager as i32);
    let mut runner = runner(&b, AbortMode::EmitNonFatal);
    let result = runner
        .process_with(&validate(&b), |handler, journal| {
            handler.run(journal)?;
            Err(Step::Abort(Abort {
                message: "injected post-creation abort".into(),
            }))
        })
        .unwrap();
    assert!(matches!(
        result.candidates[0].outcome,
        CandidateOutcome::Aborted {
            handler_group_order: 0,
            ..
        }
    ));
    assert!(result.candidates[1..]
        .iter()
        .all(|r| r.outcome == CandidateOutcome::NotMatched));
    assert!(runner.backend.rows().is_empty());
    assert!(runner.backend.sources().is_empty());
    let changes = decode(&result);
    assert!(changes.created_data_sources.is_empty());
    assert!(changes.mapping_triggered);
    assert!(changes.operations.iter().any(|op| matches!(
        op.operation,
        Some(output::entity_operation::Operation::DeterministicError(_))
    )));
    let mut next = next_empty(&b);
    next.transactions = b.transactions.clone();
    next.candidates = vec![b.candidates[1].clone()];
    next.candidates[0].wave = 0;
    let skipped = runner.process(&validate(&next)).unwrap();
    assert_eq!(skipped.candidates[0].outcome, CandidateOutcome::NotMatched);
    assert!(!decode(&skipped).mapping_triggered);
}

#[test]
fn fail_closed_abort_discards_entire_block_and_does_not_publish_creation() {
    let mut b = original();
    b.candidates
        .retain(|c| c.source != pb::DataSourceKind::PositionManager as i32);
    b.candidates[1].data[32..64].fill(0);
    b.candidates[1].data[59] = 1; // 2^32
    let mut runner = runner(&b, AbortMode::FailClosed);
    assert!(runner
        .process(&validate(&b))
        .unwrap_err()
        .0
        .contains("MappingAbort"));
    assert!(runner.backend.rows().is_empty());
    assert!(runner.backend.sources().is_empty());
    assert!(!runner
        .hosts
        .contains(&address(&b.pools_created[0].pool).unwrap()));
}

#[test]
fn malformed_candidates_and_excluded_hosts_remain_accounted_for() {
    let mut b = original();
    b.candidates[1].data.push(1); // extra byte is accepted by alloy; make too short instead
    b.candidates[1].topics.truncate(1);
    b.candidates[1].abi_decoded = false;
    b.audit.as_mut().unwrap().candidate_decode_failures = 1;
    let mut r = runner(&b, AbortMode::FailClosed);
    let result = r.process(&validate(&b)).unwrap();
    assert_eq!(result.candidates.len(), 5);
    assert_eq!(result.candidates[1].outcome, CandidateOutcome::NotMatched);
    assert!(matches!(
        result.candidates[2].outcome,
        CandidateOutcome::Committed {
            handler_group_order: 1
        }
    ));
    let pool = hex::decode(FACTORY_EXCLUDED_POOL).unwrap();
    let mut b = original();
    b.candidates
        .retain(|c| c.source != pb::DataSourceKind::PositionManager as i32);
    b.candidates[0].data[12..32].copy_from_slice(&pool);
    b.pools_created[0].pool = pool.clone();
    for c in &mut b.candidates[1..] {
        c.address = pool.clone();
    }
    let result = runner(&b, AbortMode::FailClosed)
        .process(&validate(&b))
        .unwrap();
    assert_eq!(result.candidates.len(), 3);
    assert!(matches!(
        result.candidates[0].outcome,
        CandidateOutcome::Committed {
            handler_group_order: 0
        }
    ));
    assert!(result.candidates[1..]
        .iter()
        .all(|r| r.outcome == CandidateOutcome::NotMatched));
    assert!(decode(&result).mapping_triggered); // no-save handler still triggers
    assert!(decode(&result).operations.is_empty());
}

#[test]
fn missing_swap_call_answer_refuses_every_prior_effect() {
    let mut b = original();
    let swap = &mut b.candidates[4];
    swap.topics[0] =
        alloy_primitives::keccak256(b"Swap(address,address,int256,int256,uint160,uint128,int24)")
            .to_vec();
    swap.topics.truncate(3);
    swap.data = vec![0; 160];
    let mut r = runner(&b, AbortMode::FailClosed);
    let error = r.process(&validate(&b)).unwrap_err();
    assert!(
        error.0.contains("MissingCallAnswer { kind: get_pool"),
        "{}",
        error.0
    );
    assert!(r.backend.rows().is_empty());
    assert!(r.backend.sources().is_empty());
    // The first pool has USDC/USDbC at spacing 1. The synthetic Swap probes
    // these four other spacings before its missing fee-growth answer.
    let pool = &b.pools_created[0];
    for tick_spacing in [100, 500, 3000, 10000] {
        b.calls.as_mut().unwrap().get_pool.push(pb::GetPoolAnswer {
            token_a: pool.token0.clone(),
            token_b: pool.token1.clone(),
            tick_spacing,
            pool: vec![0; 20],
            created_block: 0,
        });
    }
    let mut r = runner(&b, AbortMode::FailClosed);
    let error = r.process(&validate(&b)).unwrap_err();
    assert!(
        error.0.contains("MissingCallAnswer { kind: fee_growth"),
        "{}",
        error.0
    );
    assert!(r.backend.rows().is_empty());
    assert!(r.backend.sources().is_empty());
}

#[test]
fn only_exact_eof_and_successful_producer_return_a_completed_range() {
    let b = original();
    let second = next_empty(&b);
    let input = stream(bytes(&[b.clone(), second.clone()]), &b, second.number);
    let called = Cell::new(false);
    let done = run_stream(
        runner(&b, AbortMode::FailClosed),
        input,
        limits(),
        |status| {
            assert_eq!(status, InputCompletion::Complete);
            called.set(true);
            Ok(())
        },
    )
    .unwrap();
    assert!(called.get());
    assert_eq!(done.blocks().len(), 2);
    assert_eq!(done.boundary().block_number, second.number);
    // Failed/cancelled producer is refusal even after all valid bytes + EOF.
    for reason in ["exit 1", "cancelled"] {
        let input = stream(bytes(std::slice::from_ref(&b)), &b, b.number);
        assert!(run_stream(
            runner(&b, AbortMode::FailClosed),
            input,
            limits(),
            |status| {
                assert_eq!(status, InputCompletion::Complete);
                Err(refuse(reason))
            }
        )
        .err()
        .unwrap()
        .0
        .contains(reason));
    }
    for data in [
        vec![],
        bytes(std::slice::from_ref(&b)),
        bytes(&[b.clone(), second.clone(), next_empty(&second)]),
    ] {
        let input = stream(data, &b, second.number);
        let called = Cell::new(false);
        assert!(run_stream(
            runner(&b, AbortMode::FailClosed),
            input,
            limits(),
            |status| {
                assert_eq!(status, InputCompletion::Refused);
                called.set(true);
                Ok(())
            }
        )
        .is_err());
        assert!(called.get());
    }
}

struct ReadFailure(Cursor<Vec<u8>>);
impl Read for ReadFailure {
    fn read(&mut self, b: &mut [u8]) -> io::Result<usize> {
        let n = self.0.read(b)?;
        if n == 0 {
            Err(io::Error::other("producer pipe failed"))
        } else {
            Ok(n)
        }
    }
}
#[test]
fn read_failure_and_each_memory_budget_refuse_completion() {
    let b = original();
    let input = InputStream::new(
        ReadFailure(Cursor::new(bytes(std::slice::from_ref(&b)))),
        binding(true),
        b.number,
        b.number,
        b.parent_hash.clone().try_into().unwrap(),
    )
    .unwrap();
    assert!(run_stream(
        runner(&b, AbortMode::FailClosed),
        input,
        limits(),
        |status| {
            assert_eq!(status, InputCompletion::Refused);
            Ok(())
        }
    )
    .err()
    .unwrap()
    .0
    .contains("producer pipe failed"));
    for lim in [
        MemoryLimits {
            max_blocks: 1,
            ..limits()
        },
        MemoryLimits {
            max_candidates: 1,
            ..limits()
        },
        MemoryLimits {
            max_output_payload_bytes: 1,
            ..limits()
        },
    ] {
        let next = next_empty(&b);
        let input = stream(bytes(&[b.clone(), next.clone()]), &b, next.number);
        assert!(
            run_stream(runner(&b, AbortMode::FailClosed), input, lim, |status| {
                assert_eq!(status, InputCompletion::Refused);
                Ok(())
            })
            .err()
            .unwrap()
            .0
            .contains("limit exceeded")
        );
    }
}

#[test]
fn fatal_descriptor_rejects_nonfatal_mode_before_execution() {
    let b = original();
    let binding = binding(false);
    let backend = MemoryBackend::root(&binding, b.parent_hash.try_into().unwrap()).unwrap();
    assert!(MemoryRunner::with_abort_mode(binding, backend, AbortMode::EmitNonFatal).is_err());
}

#[test]
fn nonfatal_actual_initialize_abort_matches_whole_wasm_envelope() {
    let mut b = original();
    b.candidates
        .retain(|c| c.log_index == 172 || c.log_index == 171);
    b.candidates[1].data[32..64].fill(0);
    b.candidates[1].data[59] = 1; // 2^32, proven AssemblyScript overflow
    let mut r = runner(&b, AbortMode::EmitNonFatal);
    let block = r.process(&validate(&b)).unwrap();
    assert!(matches!(
        block.candidates[1].outcome,
        CandidateOutcome::Aborted {
            handler_group_order: 1,
            ..
        }
    ));
    let corpus: serde_json::Value = serde_json::from_slice(include_bytes!(
        "../../fixtures/graph-node-first-handlers.json"
    ))
    .unwrap();
    let case = corpus["cases"]
        .as_array()
        .unwrap()
        .iter()
        .find(|c| c["name"] == "tick_overflow")
        .unwrap();
    let expected = output::BlockChanges::decode(
        hex::decode(case["changes_hex"].as_str().unwrap())
            .unwrap()
            .as_slice(),
    )
    .unwrap();
    let mut got = decode(&block);
    got.compatibility_id.clear();
    assert_eq!(got, expected);
    assert_eq!(r.backend.sources().len(), 1); // earlier successful Factory survives
}

#[test]
fn failed_block_does_not_remember_a_prior_nonfatal_creation_failure() {
    let b = original();
    let mut r = runner(&b, AbortMode::EmitNonFatal);
    let mut count = 0;
    let error = r
        .process_with(&validate(&b), |handler, journal| {
            count += 1;
            if count == 1 {
                handler.run(journal)?;
                Err(Step::Abort(Abort {
                    message: "injected creator abort".into(),
                }))
            } else {
                Err(Step::Fatal(refuse("injected later fatal error")))
            }
        })
        .unwrap_err();
    assert!(error.0.contains("later fatal error"));
    assert!(r.backend.rows().is_empty());
    assert!(r.backend.sources().is_empty());
    // No failed-creation exception leaked from the rejected block either.
    assert!(r
        .hosts
        .match_candidate(&validate(&b), 3)
        .unwrap_err()
        .0
        .contains("UnknownPoolHost"));
}
