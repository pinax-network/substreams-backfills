//! End-to-end hermetic provider -> plan -> preflight -> joint reducer tests.

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

#[path = "../src/npm_handler_reducer.rs"]
mod npm_handler_reducer;
#[path = "../src/npm_observation_plan.rs"]
mod npm_observation_plan;
#[path = "../src/npm_provider_executor.rs"]
mod npm_provider_executor;
#[path = "../src/npm_resolved_inputs.rs"]
mod npm_resolved_inputs;
#[path = "../src/npm_source_block.rs"]
mod npm_source_block;

#[cfg(test)]
mod executor_tests {
    use std::collections::BTreeMap;

    use num_bigint::{BigInt, BigUint};

    use crate::npm_handler_reducer::{BlockDisposition, Decimal, Position, ReducerState};
    use crate::npm_plan_pb::{PoolRequest, PositionRequest, TokenRequest};
    use crate::npm_provider_executor::*;
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
    const POOL: [u8; 20] = [0x77; 20];

    #[derive(Clone, Copy)]
    struct Segment {
        network: &'static str,
        block: u64,
        id: &'static str,
        semantic: &'static str,
        profile: &'static str,
        collect_tokens: usize,
    }

    const SEGMENTS: [Segment; 8] = [
        Segment {
            network: "mainnet",
            block: 12_369_651,
            id: "mainnet:Qme66ZNMxSdCQKzaDuvS381whCVYCQjf637sGZCqJHAWHB",
            semantic: "4839ecce0391345e412ccde53a12d6d243cafd3d6a99e9072f8f1d2020b802ff",
            profile: "mainnet-root-correct-collect",
            collect_tokens: 2,
        },
        Segment {
            network: "mainnet",
            block: 13_450_881,
            id: "mainnet:QmRvEgUpbjVV326W2zPvxWimzQwcDREfjejUdFn2L92qry",
            semantic: "b344c20468dc56e3a6a4d32cf785de598f816270edbad4e5a7e979d6d5428a3c",
            profile: "mainnet-second-fee0-overwrite",
            collect_tokens: 2,
        },
        Segment {
            network: "mainnet",
            block: 13_498_329,
            id: "mainnet:QmS13421u6qsbVdBCrZhdRaZw2wH67drwF3urmueJvvJ5P",
            semantic: "cc0894a0822321f296585430bb93f705903494b832e56a20b858994c6f7052d0",
            profile: "mainnet-no-collect-amounts",
            collect_tokens: 0,
        },
        Segment {
            network: "mainnet",
            block: 13_591_198,
            id: "mainnet:QmSLHXCZBNKVtJRrWiEAF1yRQNPqAFptBsAcLdXQPsubSX",
            semantic: "9b890298b85194fb05123b7a0c5836feb63d2224c845f6714183d8588882d85a",
            profile: "mainnet-no-collect-amounts",
            collect_tokens: 0,
        },
        Segment {
            network: "mainnet",
            block: 13_605_861,
            id: "mainnet:QmZeCuoZeadgHkGwLwMeguyqUKz1WPWQYKcKyMCeQqGhsF",
            semantic: "83e4269b0582acfec8d1f868c59c6a71e362554ee41ecab4a7ccfbab87888815",
            profile: "mainnet-no-collect-amounts",
            collect_tokens: 0,
        },
        Segment {
            network: "mainnet",
            block: 19_470_001,
            id: "mainnet:QmTZ8ejXJxRo7vDBS4uwqBeGoxLSWbhaA7oXa1RvxunLy7",
            semantic: "0b2a208cc7ff5cbced29818ddb4fddabfa236393fc289686a87a48e8c309b754",
            profile: "current-amount0-to-both",
            collect_tokens: 1,
        },
        Segment {
            network: "base",
            block: 1_371_713,
            id: "base:QmPWDTWRfS8XewMJhxXoQiZX6RkrUMYH7BFnnB846v6wzR",
            semantic: "03d3fdaeecacfbb4aae325a1021117ddc6c3baf48d9589af69d0f3db7cdfab20",
            profile: "base-root-amount0-to-both",
            collect_tokens: 1,
        },
        Segment {
            network: "base",
            block: 19_852_001,
            id: "base:Qmb4VUcAY9LsVgeCuCCMs7X1XrkbRcaiuAbSK8SqhmsAfP",
            semantic: "5dd72427adcb71c3e4fd249dc4371005fb372875f236fb90439adf5fe9d7398b",
            profile: "current-amount0-to-both",
            collect_tokens: 1,
        },
    ];

    #[derive(Clone, Copy, Debug, PartialEq, Eq)]
    enum InjectedFailure {
        PossibleReorg,
        Unknown,
        Error,
    }

    #[derive(Clone, Debug)]
    struct FixtureProvider {
        authority: ProviderAuthority,
        calls: Vec<(EvaluationPhase, CapturedCallScope, usize)>,
        counters: [usize; 3],
        failure: Option<(EvaluationPhase, usize, InjectedFailure)>,
        position_results: BTreeMap<u8, CapturedPositionResult>,
        pool_none_for_token0_byte: Option<u8>,
        token_missing: bool,
    }

    impl Default for FixtureProvider {
        fn default() -> Self {
            Self {
                authority: ProviderAuthority::HermeticFixture,
                calls: Vec::new(),
                counters: [0; 3],
                failure: None,
                position_results: BTreeMap::new(),
                pool_none_for_token0_byte: None,
                token_missing: false,
            }
        }
    }

    impl FixtureProvider {
        fn response<T>(&self, phase: EvaluationPhase, index: usize, value: T) -> Result<ProviderResolution<T>, String> {
            match self.failure {
                Some((wanted_phase, wanted_index, InjectedFailure::PossibleReorg))
                    if wanted_phase == phase && wanted_index == index =>
                {
                    Ok(ProviderResolution::PossibleReorg)
                }
                Some((wanted_phase, wanted_index, InjectedFailure::Unknown))
                    if wanted_phase == phase && wanted_index == index =>
                {
                    Ok(ProviderResolution::Unknown)
                }
                Some((wanted_phase, wanted_index, InjectedFailure::Error))
                    if wanted_phase == phase && wanted_index == index =>
                {
                    Err("SECRET endpoint=https://provider.invalid token=do-not-leak".to_owned())
                }
                _ => Ok(ProviderResolution::Resolved(value)),
            }
        }

        fn record(&mut self, phase: EvaluationPhase, scope: &CapturedCallScope) -> usize {
            let slot = match phase {
                EvaluationPhase::Position => 0,
                EvaluationPhase::Pool => 1,
                EvaluationPhase::Token => 2,
                _ => unreachable!(),
            };
            let index = self.counters[slot];
            self.counters[slot] += 1;
            self.calls.push((phase, scope.clone(), index));
            index
        }
    }

    impl NpmObservationProvider for FixtureProvider {
        type Error = String;

        fn authority(&self) -> ProviderAuthority {
            self.authority
        }

        fn resolve_position(
            &mut self,
            scope: &CapturedCallScope,
            request: &PositionRequest,
        ) -> Result<ProviderResolution<CapturedPositionResult>, Self::Error> {
            let index = self.record(EvaluationPhase::Position, scope);
            let token = *request.token_id.last().unwrap();
            let result = self
                .position_results
                .get(&token)
                .cloned()
                .unwrap_or_else(|| position_result(token));
            self.response(EvaluationPhase::Position, index, result)
        }

        fn resolve_pool(
            &mut self,
            scope: &CapturedCallScope,
            request: &PoolRequest,
        ) -> Result<ProviderResolution<CapturedPoolResult>, Self::Error> {
            let index = self.record(EvaluationPhase::Pool, scope);
            let result = if self.pool_none_for_token0_byte == request.token0.first().copied() {
                CapturedPoolResult::None
            } else {
                CapturedPoolResult::Value(POOL.to_vec())
            };
            self.response(EvaluationPhase::Pool, index, result)
        }

        fn resolve_token(
            &mut self,
            scope: &CapturedCallScope,
            _request: &TokenRequest,
        ) -> Result<ProviderResolution<CapturedTokenResult>, Self::Error> {
            let index = self.record(EvaluationPhase::Token, scope);
            let result = if self.token_missing {
                CapturedTokenResult::Missing
            } else {
                CapturedTokenResult::Found(18)
            };
            self.response(EvaluationPhase::Token, index, result)
        }
    }

    fn manager(network: &str) -> [u8; 20] {
        if network == "mainnet" {
            MAINNET_MANAGER
        } else {
            BASE_MANAGER
        }
    }

    fn segment(network: &str, block: u64) -> Segment {
        *SEGMENTS
            .iter()
            .find(|segment| segment.network == network && segment.block == block)
            .unwrap()
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
        let source = NpmSourceBlock {
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
        crate::npm_source_block::validate_npm_source_block(&source).unwrap();
        source
    }

    fn eip1898(source: &NpmSourceBlock) -> Gated<CapturedCallScope> {
        Gated::resolved(CapturedCallScope::Eip1898Hash(
            source.block.as_ref().unwrap().hash.clone(),
        ))
    }

    fn fallback(source: &NpmSourceBlock) -> Gated<CapturedCallScope> {
        Gated::resolved(CapturedCallScope::BlockNumberFallback(
            source.block.as_ref().unwrap().number,
        ))
    }

    fn position_result(token: u8) -> CapturedPositionResult {
        position_result_with(
            [token.wrapping_mul(2).max(1); 20],
            [token.wrapping_mul(2).wrapping_add(1).max(1); 20],
        )
    }

    fn position_result_with(token0: [u8; 20], token1: [u8; 20]) -> CapturedPositionResult {
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
    fn all_eight_segments_execute_their_selected_profiles() {
        for segment in SEGMENTS {
            let source = source(segment.network, segment.block, vec![collect(1, segment.block, 1)]);
            let mut provider = FixtureProvider::default();
            let result =
                execute_npm_provider(&source, &ReducerState::default(), eip1898(&source), &mut provider).unwrap();
            assert_eq!(result.audit.segment_id, segment.id);
            assert_eq!(result.audit.npm_profile_id, segment.profile);
            assert_eq!(result.audit.evaluations.len(), 2 + segment.collect_tokens);
            assert!(result.audit.is_canonical());
        }
    }

    #[test]
    fn full_suffix_is_evaluated_before_fatal_reducer_projection() {
        let block = 12_369_651;
        let fatal_source = source(
            "mainnet",
            block,
            vec![transfer(1, block, 1), transfer(2, block, 2), transfer(3, block, 3)],
        );
        let mut provider = FixtureProvider {
            pool_none_for_token0_byte: Some(4),
            ..FixtureProvider::default()
        };
        let result = execute_npm_provider(
            &fatal_source,
            &ReducerState::default(),
            eip1898(&fatal_source),
            &mut provider,
        )
        .unwrap();
        assert!(matches!(
            result.reduction.disposition,
            BlockDisposition::FatalNpmUserEntityProjection {
                ordinal: 2,
                omitted_event_count: 1,
                ..
            }
        ));
        assert_eq!(result.audit.coverage.resolved_position_keys, 3);
        assert_eq!(result.audit.coverage.resolved_pool_keys, 3);
        assert_eq!(result.audit.coverage.unconsumed_position_keys, 1);
        assert_eq!(provider.counters, [3, 3, 0]);
    }

    #[test]
    fn repeated_interleaved_and_transfer_only_blocks_use_strict_phase_order() {
        let block = 19_470_001;
        let interleaved_source = source(
            "mainnet",
            block,
            vec![
                transfer(1, block, 2),
                increase(2, block, 1),
                collect(3, block, 2),
                decrease(4, block, 1),
                transfer(5, block, 1),
            ],
        );
        let mut provider = FixtureProvider::default();
        let result = execute_npm_provider(
            &interleaved_source,
            &ReducerState::default(),
            eip1898(&interleaved_source),
            &mut provider,
        )
        .unwrap();
        let phases = provider.calls.iter().map(|call| call.0).collect::<Vec<_>>();
        let first_pool = phases.iter().position(|phase| *phase == EvaluationPhase::Pool).unwrap();
        let first_token = phases
            .iter()
            .position(|phase| *phase == EvaluationPhase::Token)
            .unwrap();
        assert!(phases[..first_pool]
            .iter()
            .all(|phase| *phase == EvaluationPhase::Position));
        assert!(phases[first_pool..first_token]
            .iter()
            .all(|phase| *phase == EvaluationPhase::Pool));
        assert!(phases[first_token..]
            .iter()
            .all(|phase| *phase == EvaluationPhase::Token));
        assert_eq!(result.audit.coverage.planned_position_keys, 2);
        assert_eq!(result.audit.coverage.planned_pool_keys, 2);

        let transfer_source = source("mainnet", block, vec![transfer(1, block, 9)]);
        let mut transfer_provider = FixtureProvider::default();
        let transfer_result = execute_npm_provider(
            &transfer_source,
            &ReducerState::default(),
            eip1898(&transfer_source),
            &mut transfer_provider,
        )
        .unwrap();
        assert_eq!(transfer_provider.counters, [1, 1, 0]);
        assert_eq!(transfer_result.audit.evaluations.len(), 2);
    }

    #[test]
    fn resolved_none_and_missing_are_not_unstable_results() {
        let block = 19_470_001;
        let transfer_source = source("mainnet", block, vec![transfer(1, block, 1)]);
        let mut none_provider = FixtureProvider::default();
        none_provider.position_results.insert(1, CapturedPositionResult::None);
        let result = execute_npm_provider(
            &transfer_source,
            &ReducerState::default(),
            eip1898(&transfer_source),
            &mut none_provider,
        )
        .unwrap();
        assert_eq!(result.audit.evaluations.len(), 1);
        assert_eq!(result.audit.evaluations[0].result, ResolvedResultClass::PositionNone);

        let increase_source = source("mainnet", block, vec![increase(1, block, 1)]);
        let mut missing_provider = FixtureProvider {
            token_missing: true,
            ..FixtureProvider::default()
        };
        let result = execute_npm_provider(
            &increase_source,
            &ReducerState::default(),
            eip1898(&increase_source),
            &mut missing_provider,
        )
        .unwrap();
        assert!(result
            .audit
            .evaluations
            .iter()
            .any(|evaluation| evaluation.result == ResolvedResultClass::TokenMissing));
    }

    #[test]
    fn unstable_and_error_results_abort_with_sanitized_identity_only() {
        let block = 19_470_001;
        let source = source("mainnet", block, vec![increase(1, block, 1)]);
        for (phase, failure, kind) in [
            (
                EvaluationPhase::Position,
                InjectedFailure::Error,
                ExecutionErrorKind::ProviderError,
            ),
            (
                EvaluationPhase::Pool,
                InjectedFailure::PossibleReorg,
                ExecutionErrorKind::PossibleReorg,
            ),
            (
                EvaluationPhase::Token,
                InjectedFailure::Unknown,
                ExecutionErrorKind::Unknown,
            ),
        ] {
            let mut provider = FixtureProvider {
                failure: Some((phase, 0, failure)),
                ..FixtureProvider::default()
            };
            let error =
                execute_npm_provider(&source, &ReducerState::default(), eip1898(&source), &mut provider).unwrap_err();
            assert_eq!(error.kind, kind);
            assert_eq!(error.phase, phase);
            assert_eq!(error.request_index, Some(0));
            let rendered = format!("{error:?} {error}");
            assert!(!rendered.contains("SECRET"));
            assert!(!rendered.contains("provider.invalid"));
            assert!(!rendered.contains("do-not-leak"));
        }
    }

    #[test]
    fn exact_eip1898_and_number_fallback_scopes_reach_every_request() {
        let block = 19_470_001;
        let source = source("mainnet", block, vec![increase(1, block, 1)]);
        for scope in [eip1898(&source), fallback(&source)] {
            let expected = {
                let mut value = scope.clone();
                value.resolved_value_mut().unwrap().clone()
            };
            let mut provider = FixtureProvider::default();
            execute_npm_provider(&source, &ReducerState::default(), scope, &mut provider).unwrap();
            assert!(!provider.calls.is_empty());
            assert!(provider.calls.iter().all(|call| call.1 == expected));
        }
    }

    #[test]
    fn authority_and_scope_refusals_happen_before_provider_calls() {
        let block = 19_470_001;
        let source = source("mainnet", block, vec![transfer(1, block, 1)]);
        let mut external = FixtureProvider {
            authority: ProviderAuthority::ExternalLive,
            ..FixtureProvider::default()
        };
        let error =
            execute_npm_provider(&source, &ReducerState::default(), eip1898(&source), &mut external).unwrap_err();
        assert_eq!(error.kind, ExecutionErrorKind::AuthorityRefused);
        assert!(external.calls.is_empty());

        for invalid_scope in [
            Gated::possible_reorg(),
            Gated::unknown(),
            Gated::resolved(CapturedCallScope::Eip1898Hash(vec![0; 32])),
            Gated::resolved(CapturedCallScope::BlockNumberFallback(block + 1)),
        ] {
            let mut provider = FixtureProvider::default();
            let error =
                execute_npm_provider(&source, &ReducerState::default(), invalid_scope, &mut provider).unwrap_err();
            assert_eq!(error.kind, ExecutionErrorKind::InvalidInput);
            assert!(provider.calls.is_empty());
        }
    }

    #[test]
    fn immutable_block_start_identity_drives_derived_token_requests() {
        let block = 19_470_001;
        let source = source("mainnet", block, vec![increase(1, block, 1)]);
        let mut state = ReducerState::default();
        state
            .positions
            .insert("1".to_owned(), initial_position(1, [0x44; 20], [0x55; 20]));
        let mut provider = FixtureProvider::default();
        provider
            .position_results
            .insert(1, position_result_with([0x11; 20], [0x22; 20]));
        let result = execute_npm_provider(&source, &state, eip1898(&source), &mut provider).unwrap();
        let token_addresses = result
            .audit
            .evaluations
            .iter()
            .filter_map(|evaluation| match evaluation.key {
                CanonicalRequestKey::Token { address, .. } => Some(address),
                _ => None,
            })
            .collect::<Vec<_>>();
        assert_eq!(token_addresses, vec![[0x44; 20], [0x55; 20]]);
        assert_eq!(result.audit.coverage.planned_pool_keys, 0);
    }

    #[test]
    fn audit_binds_exact_consumption_maxima_and_is_deterministic() {
        let block = 19_470_001;
        let source = source(
            "mainnet",
            block,
            vec![increase(1, block, 1), increase(2, block, 1), collect(3, block, 1)],
        );
        let mut first_provider = FixtureProvider::default();
        first_provider
            .position_results
            .insert(1, position_result_with([0x42; 20], [0x42; 20]));
        let mut second_provider = first_provider.clone();
        let first =
            execute_npm_provider(&source, &ReducerState::default(), eip1898(&source), &mut first_provider).unwrap();
        let second = execute_npm_provider(
            &source,
            &ReducerState::default(),
            eip1898(&source),
            &mut second_provider,
        )
        .unwrap();
        assert_eq!(first.audit, second.audit);
        assert!(first.audit.is_canonical());
        assert_eq!(first.audit.coverage.consumed_position_calls, 1);
        assert_eq!(first.audit.coverage.consumed_pool_calls, 1);
        assert!(first.audit.evaluations.iter().all(|evaluation| {
            !matches!(evaluation.phase, EvaluationPhase::Position | EvaluationPhase::Pool)
                || evaluation.expected_consumption_count == 1
        }));
        assert!(first.audit.evaluations.iter().any(|evaluation| {
            evaluation.phase == EvaluationPhase::Token && evaluation.expected_consumption_count == 2
        }));
        assert_eq!(TRACE_KIND, "canonical conservative request-evaluation trace");
    }

    #[test]
    fn inherited_planner_and_resolved_adapter_surface_remains_fail_closed() {
        let block = 19_470_001;
        let empty_source = source("mainnet", block, Vec::new());
        let phase = crate::npm_observation_plan::plan_position_observations(
            &empty_source,
            &ReducerState::default(),
            eip1898(&empty_source),
        )
        .unwrap();
        assert_ne!(phase.planning_state_sha256(), [0; 32]);
        let complete = crate::npm_observation_plan::complete_observation_plan(phase, Vec::new()).unwrap();
        let preflighted =
            crate::npm_observation_plan::preflight_resolved_frame(complete, Vec::new(), Vec::new()).unwrap();
        assert!(preflighted.frame().position_calls.is_empty());
        assert!(preflighted.plan().position_requests.is_empty());
        let coverage = crate::npm_observation_plan::coverage_audit_for_test(
            preflighted.plan(),
            preflighted.frame(),
            &InputConsumption::default(),
        )
        .unwrap();
        assert_eq!(coverage, crate::npm_observation_plan::CoverageAudit::default());

        let mut unknown: Gated<CapturedCallScope> = Gated::unknown();
        assert!(unknown.resolved_value_mut().is_none());
        for digest in [
            NPM_SOURCE_PROTO_SHA256,
            NPM_SOURCE_VALIDATOR_SHA256,
            NPM_SOURCE_BINDING_SHA256,
            WRITER_RUNTIME_SHA256,
            WRITER_PROFILE_SHA256,
            WRITER_COMPATIBILITY_SHA256,
            WRITER_PROTO_SHA256,
            SEGMENT_MATRIX_SHA256,
            EXECUTION_ORDER_SHA256,
        ] {
            assert_eq!(digest.len(), 64);
        }
        assert!(decode_npm_resolved_input_frame(&[]).is_err());
        assert!(reduce_npm_resolved_input_frame(
            &ReducerState::default(),
            &crate::npm_inputs_pb::NpmResolvedInputs::default(),
        )
        .is_err());
        assert!(!reducer_disposition_authorizes_graph_block_or_checkpoint_success(
            &BlockDisposition::ModeledNpmUserEntityProjectionComplete,
        ));
    }

    #[test]
    fn executor_binds_only_selected_v1_and_keeps_broad_authority_false() {
        assert_eq!(
            EXECUTOR_SEMANTICS_SHA256,
            "42be28917cbd73c84911084e17e0869f9655c16a4cec50c8a636aa7b9f021bbe"
        );
        assert_eq!(
            SELECTED_FIELD_SEMANTICS_V1_SHA256,
            "4daa777ce2d14edd8a665a6a1239db8fb78957aa091174fd31f81b2c25136d4e"
        );
        assert_eq!(
            OBSERVATION_PLAN_RUNTIME_SHA256,
            "8cd45b0c31994332e75bd25ccd515d961fe0de9d93ac30874f5a17c0f35b6c10"
        );
        assert_eq!(
            OBSERVATION_PLAN_SEMANTICS_SHA256,
            "2d305149664b4c1e83d31a21a4131e585e44f8f25636d311ff741b9c437eaa3f"
        );
        let contract: serde_json::Value =
            serde_json::from_str(include_str!("../configs/npm-provider-executor-v1.json")).unwrap();
        let truth = contract["truth_boundary"].as_object().unwrap();
        for key in [
            "live_provider_authority",
            "exact_graph_call_trace_complete",
            "exact_graph_ordering_complete",
            "flash_integration_complete",
            "factory_pool_combined_schedule_implemented",
            "dynamic_datasource_stage_order_implemented",
            "post_fatal_graph_execution_modeled",
            "entity_changes_or_block_changes_implemented",
            "output_or_store_or_graph_out_implemented",
            "package_consumes_executor",
            "checkpoint_or_graph_block_success_authorized",
            "boundary_state_continuity_complete",
            "physical_parity_complete",
            "poi_parity_complete",
            "backfill_ready",
            "production_ready",
        ] {
            assert_eq!(
                truth.get(key).and_then(serde_json::Value::as_bool),
                Some(false),
                "{key}"
            );
        }
        let serialized = contract.to_string();
        assert!(!serialized.contains("segment-field-semantics/v2"));
        assert!(!serialized.contains("factory-pool"));
        assert!(!serialized.contains("factory-static"));
    }
}
