//! Combined source -> staged plan -> resolved frame -> joint reducer harness.

pub mod pb {
    pub mod writer {
        pub use substreams_uniswap_v3::pb::writer::*;
    }

    pub mod npm_source {
        include!("../src/uniswap.npm.source.v1.rs");
    }
}

pub mod uniswap {
    pub mod npm {
        pub mod source {
            pub mod v1 {
                pub use crate::pb::npm_source::*;
            }
        }

        pub mod inputs {
            pub mod v1 {
                include!("../src/uniswap.npm.inputs.v1.rs");
            }
        }

        pub mod plan {
            pub mod v1 {
                include!("../src/uniswap.npm.plan.v1.rs");
            }
        }
    }
}

pub use uniswap::npm::inputs::v1 as npm_inputs_pb;
pub use uniswap::npm::plan::v1 as npm_plan_pb;

#[path = "../src/npm_source_block.rs"]
mod npm_source_block;

#[path = "../src/npm_handler_reducer.rs"]
mod npm_handler_reducer;

#[path = "../src/npm_resolved_inputs.rs"]
mod npm_resolved_inputs;

#[path = "../src/npm_observation_plan.rs"]
mod npm_observation_plan;

#[cfg(test)]
mod planner_tests {
    use std::collections::{BTreeMap, BTreeSet};

    use num_bigint::{BigInt, BigUint};
    use prost::Message;
    use serde_json::Value;

    use crate::npm_handler_reducer::{BlockDisposition, Decimal, Position, ReducerState, TransactionEntity};
    use crate::npm_observation_plan::*;
    use crate::npm_resolved_inputs::*;
    use crate::pb::npm_source::{BlockRef, NpmSourceBlock, TransactionRef};
    use crate::pb::writer::writer_event::Event;
    use crate::pb::writer::{Collect, DecreaseLiquidity, IncreaseLiquidity, Transfer, WriterEvent, WriterEvents};

    const MAINNET_MANAGER: [u8; 20] = [
        0xc3, 0x64, 0x42, 0xb4, 0xa4, 0x52, 0x2e, 0x87, 0x13, 0x99, 0xcd, 0x71, 0x7a, 0xbd, 0xd8, 0x47, 0xab, 0x11,
        0xfe, 0x88,
    ];
    const BASE_MANAGER: [u8; 20] = [
        0x03, 0xa5, 0x20, 0xb3, 0x2c, 0x04, 0xbf, 0x3b, 0xee, 0xf7, 0xbe, 0xb7, 0x2e, 0x91, 0x9c, 0xf8, 0x22, 0xed,
        0x34, 0xf1,
    ];
    const BASE_FACTORY: [u8; 20] = [
        0x33, 0x12, 0x8a, 0x8f, 0xc1, 0x78, 0x69, 0x89, 0x7d, 0xce, 0x68, 0xed, 0x02, 0x6d, 0x69, 0x46, 0x21, 0xf6,
        0xfd, 0xfd,
    ];
    const POOL: [u8; 20] = [0x77; 20];

    #[derive(Clone, Copy)]
    struct SegmentFixture {
        network: &'static str,
        block: u64,
        id: &'static str,
        semantic: &'static str,
        profile: &'static str,
        collect_tokens: usize,
    }

    const SEGMENTS: [SegmentFixture; 8] = [
        SegmentFixture {
            network: "mainnet",
            block: 12_369_651,
            id: "mainnet:Qme66ZNMxSdCQKzaDuvS381whCVYCQjf637sGZCqJHAWHB",
            semantic: "4839ecce0391345e412ccde53a12d6d243cafd3d6a99e9072f8f1d2020b802ff",
            profile: "mainnet-root-correct-collect",
            collect_tokens: 2,
        },
        SegmentFixture {
            network: "mainnet",
            block: 13_450_881,
            id: "mainnet:QmRvEgUpbjVV326W2zPvxWimzQwcDREfjejUdFn2L92qry",
            semantic: "b344c20468dc56e3a6a4d32cf785de598f816270edbad4e5a7e979d6d5428a3c",
            profile: "mainnet-second-fee0-overwrite",
            collect_tokens: 2,
        },
        SegmentFixture {
            network: "mainnet",
            block: 13_498_329,
            id: "mainnet:QmS13421u6qsbVdBCrZhdRaZw2wH67drwF3urmueJvvJ5P",
            semantic: "cc0894a0822321f296585430bb93f705903494b832e56a20b858994c6f7052d0",
            profile: "mainnet-no-collect-amounts",
            collect_tokens: 0,
        },
        SegmentFixture {
            network: "mainnet",
            block: 13_591_198,
            id: "mainnet:QmSLHXCZBNKVtJRrWiEAF1yRQNPqAFptBsAcLdXQPsubSX",
            semantic: "9b890298b85194fb05123b7a0c5836feb63d2224c845f6714183d8588882d85a",
            profile: "mainnet-no-collect-amounts",
            collect_tokens: 0,
        },
        SegmentFixture {
            network: "mainnet",
            block: 13_605_861,
            id: "mainnet:QmZeCuoZeadgHkGwLwMeguyqUKz1WPWQYKcKyMCeQqGhsF",
            semantic: "83e4269b0582acfec8d1f868c59c6a71e362554ee41ecab4a7ccfbab87888815",
            profile: "mainnet-no-collect-amounts",
            collect_tokens: 0,
        },
        SegmentFixture {
            network: "mainnet",
            block: 19_470_001,
            id: "mainnet:QmTZ8ejXJxRo7vDBS4uwqBeGoxLSWbhaA7oXa1RvxunLy7",
            semantic: "0b2a208cc7ff5cbced29818ddb4fddabfa236393fc289686a87a48e8c309b754",
            profile: "current-amount0-to-both",
            collect_tokens: 1,
        },
        SegmentFixture {
            network: "base",
            block: 1_371_713,
            id: "base:QmPWDTWRfS8XewMJhxXoQiZX6RkrUMYH7BFnnB846v6wzR",
            semantic: "03d3fdaeecacfbb4aae325a1021117ddc6c3baf48d9589af69d0f3db7cdfab20",
            profile: "base-root-amount0-to-both",
            collect_tokens: 1,
        },
        SegmentFixture {
            network: "base",
            block: 19_852_001,
            id: "base:Qmb4VUcAY9LsVgeCuCCMs7X1XrkbRcaiuAbSK8SqhmsAfP",
            semantic: "5dd72427adcb71c3e4fd249dc4371005fb372875f236fb90439adf5fe9d7398b",
            profile: "current-amount0-to-both",
            collect_tokens: 1,
        },
    ];

    fn segment(network: &str, block: u64) -> SegmentFixture {
        *SEGMENTS
            .iter()
            .find(|segment| segment.network == network && segment.block == block)
            .expect("fixture segment")
    }

    fn manager(network: &str) -> [u8; 20] {
        match network {
            "mainnet" => MAINNET_MANAGER,
            "base" => BASE_MANAGER,
            _ => panic!("unsupported fixture network"),
        }
    }

    fn transfer(ordinal: u64, block: u64, token_id: u64) -> WriterEvent {
        writer_event(
            ordinal,
            block,
            Event::Transfer(Transfer {
                from: vec![0x44; 20],
                to: vec![0x55; 20],
                token_id: token_id.to_string(),
            }),
        )
    }

    fn increase(ordinal: u64, block: u64, token_id: u64) -> WriterEvent {
        writer_event(
            ordinal,
            block,
            Event::IncreaseLiquidity(IncreaseLiquidity {
                token_id: token_id.to_string(),
                liquidity: "10".to_owned(),
                amount0: "100".to_owned(),
                amount1: "200".to_owned(),
            }),
        )
    }

    fn decrease(ordinal: u64, block: u64, token_id: u64) -> WriterEvent {
        writer_event(
            ordinal,
            block,
            Event::DecreaseLiquidity(DecreaseLiquidity {
                token_id: token_id.to_string(),
                liquidity: "5".to_owned(),
                amount0: "20".to_owned(),
                amount1: "30".to_owned(),
            }),
        )
    }

    fn collect(ordinal: u64, block: u64, token_id: u64) -> WriterEvent {
        writer_event(
            ordinal,
            block,
            Event::Collect(Collect {
                token_id: token_id.to_string(),
                recipient: vec![0x66; 20],
                amount0: "7".to_owned(),
                amount1: "8".to_owned(),
            }),
        )
    }

    fn writer_event(ordinal: u64, block: u64, event: Event) -> WriterEvent {
        WriterEvent {
            ordinal,
            transaction_hash: vec![ordinal as u8; 32],
            block_number: block,
            transaction_log_index: ordinal as u32,
            block_log_index: ordinal as u32,
            contract_address: Vec::new(),
            event: Some(event),
        }
    }

    fn source(network: &str, block: u64, mut events: Vec<WriterEvent>) -> NpmSourceBlock {
        let segment = segment(network, block);
        for event in &mut events {
            event.contract_address = manager(network).to_vec();
        }
        let mut hashes = events
            .iter()
            .map(|event| event.transaction_hash.clone())
            .collect::<Vec<_>>();
        hashes.sort();
        hashes.dedup();
        let transactions = hashes
            .into_iter()
            .enumerate()
            .map(|(index, hash)| TransactionRef {
                hash,
                index: index as u32,
                gas_limit: 21_000 + index as u64,
                gas_price_be: if index == 0 { Vec::new() } else { vec![index as u8] },
            })
            .collect();
        let output = NpmSourceBlock {
            writer_events: Some(WriterEvents {
                events,
                network: network.to_owned(),
                block_number: block,
                segment_id: segment.id.to_owned(),
                source_writer_contract_sha256: crate::npm_observation_plan::WRITER_COMPATIBILITY_SHA256.to_owned(),
                segment_semantic_contract_sha256: segment.semantic.to_owned(),
            }),
            block: Some(BlockRef {
                number: block,
                hash: vec![0xaa; 32],
                parent_hash: vec![0xbb; 32],
                timestamp_seconds: 1_700_000_000,
            }),
            transactions,
            source_contract_sha256: crate::npm_resolved_inputs::NPM_SOURCE_SEMANTICS_SHA256.to_owned(),
        };
        crate::npm_source_block::validate_npm_source_block(&output).unwrap();
        output
    }

    fn scope(source: &NpmSourceBlock) -> Gated<CapturedCallScope> {
        Gated::resolved(CapturedCallScope::Eip1898Hash(
            source.block.as_ref().unwrap().hash.clone(),
        ))
    }

    fn token_word(token_id: u64) -> Vec<u8> {
        let mut output = vec![0; 24];
        output.extend(token_id.to_be_bytes());
        output
    }

    fn token_number(word: &[u8]) -> u8 {
        *word.last().expect("nonempty uint256")
    }

    fn token0(token_id: u8) -> [u8; 20] {
        [token_id.wrapping_mul(2).max(1); 20]
    }

    fn token1(token_id: u8) -> [u8; 20] {
        [token_id.wrapping_mul(2).wrapping_add(1).max(1); 20]
    }

    fn position_value(token_id: u8) -> CapturedPositionResult {
        position_value_with(token0(token_id), token1(token_id))
    }

    fn position_value_with(token0: [u8; 20], token1: [u8; 20]) -> CapturedPositionResult {
        CapturedPositionResult::Value(CapturedPositionValue {
            token0: token0.to_vec(),
            token1: token1.to_vec(),
            fee: 3_000,
            tick_lower: -120,
            tick_upper: 120,
            fee_growth_inside0_last_x128: vec![0; 32],
            fee_growth_inside1_last_x128: vec![0; 32],
        })
    }

    fn resolved_positions(phase: &PositionPlanningPhase) -> Vec<Gated<CapturedPositionObservation>> {
        phase
            .requests()
            .iter()
            .map(|request| {
                Gated::resolved(CapturedPositionObservation {
                    position_manager: request.position_manager.clone(),
                    token_id: request.token_id.clone(),
                    result: position_value(token_number(&request.token_id)),
                })
            })
            .collect()
    }

    fn resolved_pools(phase: &CompletePlanningPhase) -> Vec<Gated<CapturedPoolObservation>> {
        phase
            .plan()
            .pool_requests
            .iter()
            .map(|request| {
                Gated::resolved(CapturedPoolObservation {
                    factory: request.factory.clone(),
                    token0: request.token0.clone(),
                    token1: request.token1.clone(),
                    fee: request.fee,
                    result: CapturedPoolResult::Value(POOL.to_vec()),
                })
            })
            .collect()
    }

    fn resolved_tokens(phase: &CompletePlanningPhase) -> Vec<Gated<CapturedTokenObservation>> {
        phase
            .plan()
            .token_requests
            .iter()
            .map(|request| {
                Gated::resolved(CapturedTokenObservation {
                    address: request.address.clone(),
                    ordinal: request.ordinal,
                    result: CapturedTokenResult::Found(18),
                })
            })
            .collect()
    }

    fn complete(source: &NpmSourceBlock, state: &ReducerState) -> CompletePlanningPhase {
        let phase = plan_position_observations(source, state, scope(source)).unwrap();
        let positions = resolved_positions(&phase);
        complete_observation_plan(phase, positions).unwrap()
    }

    fn preflight_complete(source: &NpmSourceBlock, state: &ReducerState) -> PreflightedResolvedFrame {
        let complete = complete(source, state);
        let pools = resolved_pools(&complete);
        let tokens = resolved_tokens(&complete);
        preflight_resolved_frame(complete, pools, tokens).unwrap()
    }

    fn initial_position(token_id: u64, token0: [u8; 20], token1: [u8; 20]) -> Position {
        Position {
            token_id: token_id.to_string(),
            owner: [0x91; 20],
            pool: [0x92; 20],
            token0,
            token1,
            tick_lower: -120,
            tick_upper: 120,
            liquidity: BigInt::from(10_u8),
            deposited_token0: Decimal::zero(),
            deposited_token1: Decimal::zero(),
            withdrawn_token0: Decimal::zero(),
            withdrawn_token1: Decimal::zero(),
            collected_fees_token0: Decimal::zero(),
            collected_fees_token1: Decimal::zero(),
            transaction: [0x93; 32],
            fee_growth_inside0_last_x128: BigUint::from(1_u8),
            fee_growth_inside1_last_x128: BigUint::from(2_u8),
        }
    }

    #[test]
    fn every_segment_selects_its_exact_profile_and_collect_closure() {
        for segment in SEGMENTS {
            let source = source(segment.network, segment.block, vec![collect(1, segment.block, 1)]);
            let complete = complete(&source, &ReducerState::default());
            assert_eq!(complete.plan().segment_id, segment.id);
            assert_eq!(complete.plan().segment_semantic_contract_sha256, segment.semantic);
            assert_eq!(complete.plan().npm_profile_id, segment.profile);
            assert_eq!(complete.plan().position_requests.len(), 1);
            assert_eq!(complete.plan().pool_requests.len(), 1);
            assert_eq!(complete.plan().token_requests.len(), segment.collect_tokens);
        }
    }

    #[test]
    fn base_new_position_value_reaches_exact_preflight_and_reduction() {
        let block = 1_371_713;
        let source = source("base", block, vec![increase(1, block, 1)]);
        let complete = complete(&source, &ReducerState::default());
        assert_eq!(complete.plan().pool_requests.len(), 1);
        assert_eq!(complete.plan().pool_requests[0].factory, BASE_FACTORY);
        let pools = resolved_pools(&complete);
        let tokens = resolved_tokens(&complete);
        let preflighted = preflight_resolved_frame(complete, pools, tokens).unwrap();
        let (reduction, audit) = reduce_preflighted_npm_frame(&ReducerState::default(), preflighted).unwrap();
        assert!(matches!(
            reduction.disposition,
            BlockDisposition::ModeledNpmUserEntityProjectionComplete
        ));
        assert_eq!(audit.planned_position_keys, 1);
        assert_eq!(audit.planned_pool_keys, 1);
        assert_eq!(audit.planned_token_keys, 2);
        assert_eq!(audit.resolved_pool_keys, 1);
        assert_eq!(audit.consumed_pool_calls, 1);
    }

    #[test]
    fn repeated_interleaved_events_are_sorted_deduplicated_and_counted() {
        let block = 19_470_001;
        let source = source(
            "mainnet",
            block,
            vec![
                transfer(1, block, 2),
                increase(2, block, 1),
                collect(3, block, 2),
                decrease(4, block, 1),
            ],
        );
        let complete = complete(&source, &ReducerState::default());
        let plan = complete.plan();
        assert_eq!(plan.position_requests.len(), 2);
        assert_eq!(plan.position_requests[0].token_id, token_word(1));
        assert_eq!(plan.position_requests[0].event_ordinals, [2, 4]);
        assert_eq!(plan.position_requests[0].expected_consumption_count, 1);
        assert_eq!(plan.position_requests[1].token_id, token_word(2));
        assert_eq!(plan.position_requests[1].event_ordinals, [1, 3]);
        assert_eq!(plan.position_requests[1].expected_consumption_count, 1);
        assert_eq!(plan.pool_requests.len(), 2);
        assert!(plan
            .pool_requests
            .iter()
            .all(|request| request.expected_consumption_count == 1));
        assert_eq!(plan.token_requests.len(), 5);
        assert!(plan
            .token_requests
            .windows(2)
            .all(|pair| { (pair[0].ordinal, &pair[0].address) < (pair[1].ordinal, &pair[1].address) }));
    }

    #[test]
    fn existing_position_uses_immutable_block_start_identity() {
        let block = 19_470_001;
        let source = source("mainnet", block, vec![increase(1, block, 1)]);
        let mut state = ReducerState::default();
        state
            .positions
            .insert("1".to_owned(), initial_position(1, [0x44; 20], [0x55; 20]));
        let phase = plan_position_observations(&source, &state, scope(&source)).unwrap();
        let positions = vec![Gated::resolved(CapturedPositionObservation {
            position_manager: MAINNET_MANAGER.to_vec(),
            token_id: token_word(1),
            result: position_value_with([0x11; 20], [0x22; 20]),
        })];
        let complete = complete_observation_plan(phase, positions).unwrap();
        assert!(complete.plan().pool_requests.is_empty());
        let addresses = complete
            .plan()
            .token_requests
            .iter()
            .map(|request| request.address.clone())
            .collect::<BTreeSet<_>>();
        assert_eq!(addresses, BTreeSet::from([vec![0x44; 20], vec![0x55; 20]]));
        let pools = resolved_pools(&complete);
        let tokens = resolved_tokens(&complete);
        let preflighted = preflight_resolved_frame(complete, pools, tokens).unwrap();
        let (_, audit) = reduce_preflighted_npm_frame(&state, preflighted).unwrap();
        assert_eq!(audit.consumed_position_calls, 1);
        assert_eq!(audit.consumed_pool_calls, 0);
        assert_eq!(audit.consumed_token_reads, 2);
    }

    #[test]
    fn resolved_none_closes_position_without_pool_or_token_requests() {
        let block = 19_470_001;
        let source = source("mainnet", block, vec![transfer(1, block, 1)]);
        let phase = plan_position_observations(&source, &ReducerState::default(), scope(&source)).unwrap();
        let complete = complete_observation_plan(
            phase,
            vec![Gated::resolved(CapturedPositionObservation {
                position_manager: MAINNET_MANAGER.to_vec(),
                token_id: token_word(1),
                result: CapturedPositionResult::None,
            })],
        )
        .unwrap();
        assert!(complete.plan().pool_requests.is_empty());
        assert!(complete.plan().token_requests.is_empty());
        let preflighted = preflight_resolved_frame(complete, Vec::new(), Vec::new()).unwrap();
        let (_, audit) = reduce_preflighted_npm_frame(&ReducerState::default(), preflighted).unwrap();
        assert_eq!(audit.consumed_position_calls, 1);
    }

    #[test]
    fn normal_pipeline_is_canonical_and_consumption_is_audited() {
        let block = 19_470_001;
        let source = source("mainnet", block, vec![increase(1, block, 1), transfer(2, block, 2)]);
        let preflighted = preflight_complete(&source, &ReducerState::default());
        let bytes = preflighted.plan().encode_to_vec();
        assert_eq!(decode_npm_observation_plan(&bytes).unwrap(), *preflighted.plan());
        let (reduction, audit) = reduce_preflighted_npm_frame(&ReducerState::default(), preflighted).unwrap();
        assert!(matches!(
            reduction.disposition,
            BlockDisposition::ModeledNpmUserEntityProjectionComplete
        ));
        assert_eq!(audit.planned_position_keys, audit.resolved_position_keys);
        assert_eq!(audit.planned_pool_keys, audit.resolved_pool_keys);
        assert_eq!(audit.planned_token_keys, audit.resolved_token_keys);
        assert_eq!(audit.unconsumed_position_keys, 0);
    }

    #[test]
    fn fatal_middle_still_resolves_and_audits_the_full_suffix() {
        let block = 12_369_651;
        let source = source(
            "mainnet",
            block,
            vec![transfer(1, block, 1), transfer(2, block, 2), transfer(3, block, 3)],
        );
        let complete = complete(&source, &ReducerState::default());
        assert_eq!(complete.plan().position_requests.len(), 3);
        assert_eq!(complete.plan().pool_requests.len(), 3);
        let pools = complete
            .plan()
            .pool_requests
            .iter()
            .map(|request| {
                Gated::resolved(CapturedPoolObservation {
                    factory: request.factory.clone(),
                    token0: request.token0.clone(),
                    token1: request.token1.clone(),
                    fee: request.fee,
                    result: if request.token0 == token0(2) {
                        CapturedPoolResult::None
                    } else {
                        CapturedPoolResult::Value(POOL.to_vec())
                    },
                })
            })
            .collect();
        let preflighted = preflight_resolved_frame(complete, pools, Vec::new()).unwrap();
        let (reduction, audit) = reduce_preflighted_npm_frame(&ReducerState::default(), preflighted).unwrap();
        assert!(matches!(
            reduction.disposition,
            BlockDisposition::FatalNpmUserEntityProjection {
                ordinal: 2,
                omitted_event_count: 1,
                ..
            }
        ));
        assert_eq!(audit.resolved_position_keys, 3);
        assert_eq!(audit.resolved_pool_keys, 3);
        assert_eq!(audit.unconsumed_position_keys, 1);
        assert_eq!(audit.unconsumed_pool_keys, 1);
    }

    #[test]
    fn unresolved_full_envelope_rows_abort_both_stages() {
        let block = 12_369_651;
        let suffix_source = source("mainnet", block, vec![transfer(1, block, 1), transfer(2, block, 2)]);
        let phase =
            plan_position_observations(&suffix_source, &ReducerState::default(), scope(&suffix_source)).unwrap();
        let mut positions = resolved_positions(&phase);
        positions[1] = Gated::unknown();
        assert!(complete_observation_plan(phase, positions).is_err());

        let suffix_complete = complete(&suffix_source, &ReducerState::default());
        let mut pools = resolved_pools(&suffix_complete);
        pools[1] = Gated::possible_reorg();
        assert!(preflight_resolved_frame(suffix_complete, pools, Vec::new()).is_err());

        let token_source = source("mainnet", 19_470_001, vec![increase(1, 19_470_001, 1)]);
        let complete = complete(&token_source, &ReducerState::default());
        let pools = resolved_pools(&complete);
        let mut tokens = resolved_tokens(&complete);
        tokens[1] = Gated::unknown();
        assert!(preflight_resolved_frame(complete, pools, tokens).is_err());
    }

    #[test]
    fn exact_key_set_rejects_missing_extra_and_duplicate_rows() {
        let block = 19_470_001;
        let source = source("mainnet", block, vec![increase(1, block, 1)]);

        let phase = plan_position_observations(&source, &ReducerState::default(), scope(&source)).unwrap();
        assert!(complete_observation_plan(phase, Vec::new()).is_err());

        let phase = plan_position_observations(&source, &ReducerState::default(), scope(&source)).unwrap();
        let mut positions = resolved_positions(&phase);
        positions.push(positions[0].clone());
        assert!(complete_observation_plan(phase, positions).is_err());

        let missing_pool_complete = complete(&source, &ReducerState::default());
        let tokens = resolved_tokens(&missing_pool_complete);
        assert!(preflight_resolved_frame(missing_pool_complete, Vec::new(), tokens).is_err());

        let extra_token_complete = complete(&source, &ReducerState::default());
        let pools = resolved_pools(&extra_token_complete);
        let mut tokens = resolved_tokens(&extra_token_complete);
        tokens.push(Gated::resolved(CapturedTokenObservation {
            address: vec![0xee; 20],
            ordinal: 99,
            result: CapturedTokenResult::Found(18),
        }));
        assert!(preflight_resolved_frame(extra_token_complete, pools, tokens).is_err());
    }

    #[test]
    fn call_scope_and_planning_state_drift_fail_closed() {
        let block = 19_470_001;
        let mainnet_source = source("mainnet", block, vec![transfer(1, block, 1)]);
        assert!(plan_position_observations(
            &mainnet_source,
            &ReducerState::default(),
            Gated::resolved(CapturedCallScope::BlockNumberFallback(block - 1))
        )
        .is_err());

        let preflighted = preflight_complete(&mainnet_source, &ReducerState::default());
        let mut drift = ReducerState::default();
        drift
            .positions
            .insert("9".to_owned(), initial_position(9, [0x11; 20], [0x22; 20]));
        assert!(reduce_preflighted_npm_frame(&drift, preflighted).is_err());

        let source = source("base", 1_371_713, Vec::new());
        let phase = plan_position_observations(
            &source,
            &ReducerState::default(),
            Gated::resolved(CapturedCallScope::BlockNumberFallback(1_371_713)),
        )
        .unwrap();
        let complete = complete_observation_plan(phase, Vec::new()).unwrap();
        assert!(preflight_resolved_frame(complete, Vec::new(), Vec::new()).is_ok());
    }

    #[test]
    fn possible_reorg_and_unknown_call_scopes_fail_before_planning() {
        let source = source("mainnet", 19_470_001, vec![transfer(1, 19_470_001, 1)]);
        for scope in [Gated::possible_reorg(), Gated::unknown()] {
            assert_eq!(
                plan_position_observations(&source, &ReducerState::default(), scope)
                    .unwrap_err()
                    .0,
                "planning call scope is unresolved or unstable"
            );
        }
    }

    #[test]
    fn plan_bytes_are_stable_across_supplied_position_order() {
        let block = 19_470_001;
        let source = source("mainnet", block, vec![transfer(1, block, 2), transfer(2, block, 1)]);
        let phase = plan_position_observations(&source, &ReducerState::default(), scope(&source)).unwrap();
        let positions = resolved_positions(&phase);
        let first = complete_observation_plan(phase, positions.clone()).unwrap();

        let phase = plan_position_observations(&source, &ReducerState::default(), scope(&source)).unwrap();
        let second = complete_observation_plan(phase, positions.into_iter().rev().collect()).unwrap();
        assert_eq!(first.plan().encode_to_vec(), second.plan().encode_to_vec());
        assert_eq!(first.plan().planning_state_sha256, second.plan().planning_state_sha256);
    }

    #[test]
    fn same_token_address_tracks_two_role_consumptions_once() {
        let block = 19_470_001;
        let source = source("mainnet", block, vec![increase(1, block, 1)]);
        let phase = plan_position_observations(&source, &ReducerState::default(), scope(&source)).unwrap();
        let complete = complete_observation_plan(
            phase,
            vec![Gated::resolved(CapturedPositionObservation {
                position_manager: MAINNET_MANAGER.to_vec(),
                token_id: token_word(1),
                result: position_value_with([0x42; 20], [0x42; 20]),
            })],
        )
        .unwrap();
        assert_eq!(complete.plan().token_requests.len(), 1);
        let token = &complete.plan().token_requests[0];
        assert_eq!(token.expected_consumption_count, 2);
        assert_eq!(
            token.reason_mask,
            TOKEN_REASON_TOKEN0_SCALE | TOKEN_REASON_TOKEN1_SCALE | TOKEN_REASON_FULL_ENVELOPE
        );
        let pools = resolved_pools(&complete);
        let tokens = resolved_tokens(&complete);
        let preflighted = preflight_resolved_frame(complete, pools, tokens).unwrap();
        let (_, audit) = reduce_preflighted_npm_frame(&ReducerState::default(), preflighted).unwrap();
        assert_eq!(audit.consumed_token_reads, 2);
    }

    #[test]
    fn canonical_wire_rejects_unknown_fields_and_never_contains_provider_failures() {
        let block = 19_470_001;
        let source = source("mainnet", block, vec![increase(1, block, 1)]);
        let preflighted = preflight_complete(&source, &ReducerState::default());
        let mut bytes = preflighted.plan().encode_to_vec();
        let forbidden = ["provider", " failed", " endpoint"].concat();
        assert!(!String::from_utf8_lossy(&bytes).contains(&forbidden));
        bytes.extend([0xa0, 0x06, 0x01]);
        assert!(decode_npm_observation_plan(&bytes).is_err());
        assert!(!String::from_utf8_lossy(&preflighted.frame().encode_to_vec()).contains(&forbidden));
    }

    #[test]
    fn planning_state_is_canonical_and_rejects_identity_drift() {
        let source = source("mainnet", 19_470_001, Vec::new());
        let mut first = ReducerState::default();
        first
            .positions
            .insert("2".to_owned(), initial_position(2, [0x21; 20], [0x22; 20]));
        first
            .positions
            .insert("1".to_owned(), initial_position(1, [0x11; 20], [0x12; 20]));
        let second = first.clone();
        let first_digest = plan_position_observations(&source, &first, scope(&source))
            .unwrap()
            .planning_state_sha256();
        let second_digest = plan_position_observations(&source, &second, scope(&source))
            .unwrap()
            .planning_state_sha256();
        assert_eq!(first_digest, second_digest);

        let mut drift = first;
        let token_id = &mut drift.positions.get_mut("1").unwrap().token_id;
        token_id.clear();
        token_id.push('2');
        assert!(plan_position_observations(&source, &drift, scope(&source)).is_err());
    }

    #[test]
    fn inherited_resolved_adapter_surface_remains_exercised() {
        assert_eq!(
            crate::npm_resolved_inputs::NPM_SOURCE_PROTO_SHA256,
            "bd394a11de37449710f0fd7dc10eac4e7f4ad299141a9fd54ec156980246fe1e"
        );
        assert_eq!(crate::npm_resolved_inputs::NPM_SOURCE_VALIDATOR_SHA256.len(), 64);
        assert_eq!(crate::npm_resolved_inputs::NPM_SOURCE_BINDING_SHA256.len(), 64);
        assert_eq!(crate::npm_resolved_inputs::WRITER_RUNTIME_SHA256.len(), 64);
        assert_eq!(crate::npm_resolved_inputs::WRITER_PROFILE_SHA256.len(), 64);
        assert_eq!(crate::npm_resolved_inputs::WRITER_COMPATIBILITY_SHA256.len(), 64);
        assert_eq!(crate::npm_resolved_inputs::WRITER_PROTO_SHA256.len(), 64);
        assert_eq!(crate::npm_resolved_inputs::SEGMENT_MATRIX_SHA256.len(), 64);
        assert_eq!(crate::npm_resolved_inputs::EXECUTION_ORDER_SHA256.len(), 64);

        let source = source("mainnet", 19_470_001, Vec::new());
        let preflighted = preflight_complete(&source, &ReducerState::default());
        let frame = preflighted.frame().clone();
        assert_eq!(decode_npm_resolved_input_frame(&frame.encode_to_vec()).unwrap(), frame);
        let reduction = reduce_npm_resolved_input_frame(&ReducerState::default(), &frame).unwrap();
        assert!(!reducer_disposition_authorizes_graph_block_or_checkpoint_success(
            &reduction.disposition
        ));

        let mut missing = Gated::resolved(CapturedTokenObservation {
            address: vec![0x11; 20],
            ordinal: 1,
            result: CapturedTokenResult::Missing,
        });
        assert!(missing.resolved_value_mut().is_some());
    }

    #[test]
    fn truth_boundary_keeps_every_broader_authority_false() {
        let contract: Value = serde_json::from_str(include_str!("../configs/npm-observation-plan-v1.json")).unwrap();
        let truth = contract["truth_boundary"].as_object().unwrap();
        for key in [
            "integrated_provider_executor_added",
            "all_required_observations_evaluated",
            "exact_graph_call_trace_complete",
            "post_fatal_execution_modeled",
            "graph_execution_trace_complete",
            "factory_pool_combined_schedule_implemented",
            "dynamic_datasource_stage_order_implemented",
            "entity_changes_or_block_changes_implemented",
            "checkpoint_or_graph_block_success_authorized",
            "boundary_state_continuity_complete",
            "physical_parity_complete",
            "poi_parity_complete",
            "backfill_ready",
            "production_ready",
        ] {
            assert_eq!(truth.get(key).and_then(Value::as_bool), Some(false), "{key}");
        }
        assert_eq!(
            PLAN_SEMANTICS_SHA256,
            "2d305149664b4c1e83d31a21a4131e585e44f8f25636d311ff741b9c437eaa3f"
        );
        assert_eq!(
            RESOLVED_INPUT_RUNTIME_SHA256,
            "5df1d6f5d6852ff8aea9ef6b054be786d0df78021e6ed271439f744a330cfc1f"
        );
    }

    #[test]
    fn empty_frames_have_no_requests_and_still_preflight() {
        for segment in SEGMENTS {
            let source = source(segment.network, segment.block, Vec::new());
            let preflighted = preflight_complete(&source, &ReducerState::default());
            assert!(preflighted.plan().position_requests.is_empty());
            assert!(preflighted.plan().pool_requests.is_empty());
            assert!(preflighted.plan().token_requests.is_empty());
            let (_, audit) = reduce_preflighted_npm_frame(&ReducerState::default(), preflighted).unwrap();
            assert_eq!(audit, CoverageAudit::default());
        }
    }

    #[test]
    fn request_keys_are_unique_after_normalization() {
        let block = 19_470_001;
        let source = source(
            "mainnet",
            block,
            vec![increase(1, block, 1), increase(2, block, 1), collect(3, block, 1)],
        );
        let complete = complete(&source, &ReducerState::default());
        let plan = complete.plan();
        assert_eq!(plan.position_requests.len(), 1);
        assert_eq!(plan.position_requests[0].expected_consumption_count, 1);
        assert_eq!(plan.position_requests[0].event_ordinals, [1, 2, 3]);
        assert_eq!(plan.pool_requests.len(), 1);
        assert_eq!(plan.pool_requests[0].expected_consumption_count, 1);
        let keys = plan
            .token_requests
            .iter()
            .map(|request| (request.ordinal, request.address.clone()))
            .collect::<BTreeSet<_>>();
        assert_eq!(keys.len(), plan.token_requests.len());
    }

    #[test]
    fn repeated_event_cache_limits_reject_position_and_pool_overconsumption() {
        let block = 19_470_001;
        let source = source(
            "mainnet",
            block,
            vec![increase(1, block, 1), increase(2, block, 1), collect(3, block, 1)],
        );
        let complete = complete(&source, &ReducerState::default());
        let pools = resolved_pools(&complete);
        let tokens = resolved_tokens(&complete);
        let preflighted = preflight_resolved_frame(complete, pools, tokens).unwrap();
        let plan = preflighted.plan().clone();
        let frame = preflighted.frame().clone();
        let (_, audit) = reduce_preflighted_npm_frame(&ReducerState::default(), preflighted).unwrap();
        assert_eq!(audit.consumed_position_calls, 1);
        assert_eq!(audit.consumed_pool_calls, 1);

        let position = &plan.position_requests[0];
        let position_key: ([u8; 20], [u8; 32]) = (
            position.position_manager.as_slice().try_into().unwrap(),
            position.token_id.as_slice().try_into().unwrap(),
        );
        let mut position_overconsumption = InputConsumption::default();
        position_overconsumption.position_requests.insert(position_key, 2);
        assert!(coverage_audit_for_test(&plan, &frame, &position_overconsumption)
            .unwrap_err()
            .0
            .contains("planned limit is 1"));

        let pool = &plan.pool_requests[0];
        let pool_key: ([u8; 20], [u8; 20], [u8; 20], u32) = (
            pool.factory.as_slice().try_into().unwrap(),
            pool.token0.as_slice().try_into().unwrap(),
            pool.token1.as_slice().try_into().unwrap(),
            pool.fee,
        );
        let mut pool_overconsumption = InputConsumption::default();
        pool_overconsumption.pool_requests.insert(pool_key, 2);
        assert!(coverage_audit_for_test(&plan, &frame, &pool_overconsumption)
            .unwrap_err()
            .0
            .contains("planned limit is 1"));
    }

    #[test]
    fn planning_projection_ignores_nonposition_state() {
        let source = source("mainnet", 19_470_001, Vec::new());
        let baseline = plan_position_observations(&source, &ReducerState::default(), scope(&source))
            .unwrap()
            .planning_state_sha256();
        let state = ReducerState {
            transactions: BTreeMap::from([(
                "fixture".to_owned(),
                TransactionEntity {
                    id: "fixture".to_owned(),
                    block_number: 1,
                    timestamp: 2,
                    gas_used: "3".to_owned(),
                    gas_price: "4".to_owned(),
                },
            )]),
            ..ReducerState::default()
        };
        let projected = plan_position_observations(&source, &state, scope(&source))
            .unwrap()
            .planning_state_sha256();
        assert_eq!(baseline, projected);
    }
}
