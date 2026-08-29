//! Combined source -> resolved adapter -> joint reducer integration harness.

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
    }
}

pub use uniswap::npm::inputs::v1 as npm_inputs_pb;

#[path = "../src/npm_source_block.rs"]
mod npm_source_block;

#[path = "../src/npm_handler_reducer.rs"]
mod npm_handler_reducer;

#[path = "../src/npm_resolved_inputs.rs"]
mod npm_resolved_inputs;

#[cfg(test)]
mod adapter_tests {
    use prost::Message;

    use crate::npm_handler_reducer::{BlockDisposition, ReducerState};
    use crate::npm_resolved_inputs::*;
    use crate::pb::npm_source::{BlockRef, NpmSourceBlock, TransactionRef};
    use crate::pb::writer::writer_event::Event;
    use crate::pb::writer::{IncreaseLiquidity, Transfer, WriterEvent, WriterEvents};

    const MAINNET_MANAGER: [u8; 20] = [
        0xc3, 0x64, 0x42, 0xb4, 0xa4, 0x52, 0x2e, 0x87, 0x13, 0x99, 0xcd, 0x71, 0x7a, 0xbd, 0xd8, 0x47, 0xab, 0x11,
        0xfe, 0x88,
    ];
    const MAINNET_FACTORY: [u8; 20] = [
        0x1f, 0x98, 0x43, 0x1c, 0x8a, 0xd9, 0x85, 0x23, 0x63, 0x1a, 0xe4, 0xa5, 0x9f, 0x26, 0x73, 0x46, 0xea, 0x31,
        0xf9, 0x84,
    ];
    const BASE_MANAGER: [u8; 20] = [
        0x03, 0xa5, 0x20, 0xb3, 0x2c, 0x04, 0xbf, 0x3b, 0xee, 0xf7, 0xbe, 0xb7, 0x2e, 0x91, 0x9c, 0xf8, 0x22, 0xed,
        0x34, 0xf1,
    ];
    const TOKEN0: [u8; 20] = [0x11; 20];
    const TOKEN1: [u8; 20] = [0x22; 20];
    const POOL: [u8; 20] = [0x33; 20];

    fn segment(network: &str, block: u64) -> (&'static str, &'static str, [u8; 20]) {
        match (network, block) {
            ("mainnet", 12_369_651) => (
                "mainnet:Qme66ZNMxSdCQKzaDuvS381whCVYCQjf637sGZCqJHAWHB",
                "4839ecce0391345e412ccde53a12d6d243cafd3d6a99e9072f8f1d2020b802ff",
                MAINNET_MANAGER,
            ),
            ("mainnet", 19_470_001) => (
                "mainnet:QmTZ8ejXJxRo7vDBS4uwqBeGoxLSWbhaA7oXa1RvxunLy7",
                "0b2a208cc7ff5cbced29818ddb4fddabfa236393fc289686a87a48e8c309b754",
                MAINNET_MANAGER,
            ),
            ("base", 1_371_713) => (
                "base:QmPWDTWRfS8XewMJhxXoQiZX6RkrUMYH7BFnnB846v6wzR",
                "03d3fdaeecacfbb4aae325a1021117ddc6c3baf48d9589af69d0f3db7cdfab20",
                BASE_MANAGER,
            ),
            _ => panic!("unsupported fixture block"),
        }
    }

    fn transfer(ordinal: u64, block: u64, token_id: u64) -> WriterEvent {
        WriterEvent {
            ordinal,
            transaction_hash: vec![ordinal as u8; 32],
            block_number: block,
            transaction_log_index: ordinal as u32,
            block_log_index: ordinal as u32,
            contract_address: Vec::new(),
            event: Some(Event::Transfer(Transfer {
                from: vec![0x44; 20],
                to: vec![0x55; 20],
                token_id: token_id.to_string(),
            })),
        }
    }

    fn increase(ordinal: u64, block: u64, token_id: u64) -> WriterEvent {
        WriterEvent {
            ordinal,
            transaction_hash: vec![ordinal as u8; 32],
            block_number: block,
            transaction_log_index: ordinal as u32,
            block_log_index: ordinal as u32,
            contract_address: Vec::new(),
            event: Some(Event::IncreaseLiquidity(IncreaseLiquidity {
                token_id: token_id.to_string(),
                liquidity: "10".to_owned(),
                amount0: "100".to_owned(),
                amount1: "200".to_owned(),
            })),
        }
    }

    fn source(network: &str, block: u64, mut events: Vec<WriterEvent>) -> NpmSourceBlock {
        let (segment_id, semantic, manager) = segment(network, block);
        for event in &mut events {
            event.contract_address = manager.to_vec();
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
                segment_id: segment_id.to_owned(),
                source_writer_contract_sha256: WRITER_COMPATIBILITY_SHA256.to_owned(),
                segment_semantic_contract_sha256: semantic.to_owned(),
            }),
            block: Some(BlockRef {
                number: block,
                hash: vec![0xaa; 32],
                parent_hash: vec![0xbb; 32],
                timestamp_seconds: 1_700_000_000,
            }),
            transactions,
            source_contract_sha256: NPM_SOURCE_SEMANTICS_SHA256.to_owned(),
        };
        crate::npm_source_block::validate_npm_source_block(&output).unwrap();
        output
    }

    fn empty_observations(source: &NpmSourceBlock) -> SuppliedResolvedObservations {
        SuppliedResolvedObservations {
            call_scope: Gated::resolved(CapturedCallScope::Eip1898Hash(
                source.block.as_ref().unwrap().hash.clone(),
            )),
            position_calls: Vec::new(),
            pool_calls: Vec::new(),
            token_reads: Vec::new(),
        }
    }

    fn token_word(token_id: u64) -> Vec<u8> {
        let mut word = vec![0; 24];
        word.extend(token_id.to_be_bytes());
        word
    }

    fn position(token_id: u64, token0: [u8; 20], result: CapturedPositionResult) -> Gated<CapturedPositionObservation> {
        let _ = token0;
        Gated::resolved(CapturedPositionObservation {
            position_manager: MAINNET_MANAGER.to_vec(),
            token_id: token_word(token_id),
            result,
        })
    }

    fn position_value(token0: [u8; 20]) -> CapturedPositionResult {
        CapturedPositionResult::Value(CapturedPositionValue {
            token0: token0.to_vec(),
            token1: TOKEN1.to_vec(),
            fee: 3_000,
            tick_lower: -120,
            tick_upper: 120,
            fee_growth_inside0_last_x128: vec![0; 32],
            fee_growth_inside1_last_x128: vec![0; 32],
        })
    }

    fn pool(token0: [u8; 20], result: CapturedPoolResult) -> Gated<CapturedPoolObservation> {
        Gated::resolved(CapturedPoolObservation {
            factory: MAINNET_FACTORY.to_vec(),
            token0: token0.to_vec(),
            token1: TOKEN1.to_vec(),
            fee: 3_000,
            result,
        })
    }

    #[test]
    fn source_to_resolved_adapter_to_joint_reducer_is_end_to_end() {
        let source = source("mainnet", 19_470_001, vec![transfer(1, 19_470_001, 1)]);
        let mut observations = empty_observations(&source);
        observations.position_calls = vec![position(1, TOKEN0, position_value(TOKEN0))];
        observations.pool_calls = vec![pool(TOKEN0, CapturedPoolResult::Value(POOL.to_vec()))];
        let frame = map_resolved_npm_inputs(&source, observations).unwrap();
        let bytes = frame.encode_to_vec();
        assert_eq!(decode_npm_resolved_input_frame(&bytes).unwrap(), frame);
        let (reduction, audit) = reduce_npm_resolved_input_frame_with_audit(&ReducerState::default(), &frame).unwrap();
        assert!(reduction.state.positions.contains_key("1"));
        assert_eq!(reduction.outcomes.len(), 1);
        assert_eq!(audit.position_requests.values().sum::<usize>(), 1);
        assert_eq!(audit.pool_requests.values().sum::<usize>(), 1);
    }

    #[test]
    fn every_resolved_value_none_zero_found_and_missing_variant_is_canonical() {
        let source = source("mainnet", 19_470_001, vec![transfer(1, 19_470_001, 1)]);
        let mut observations = empty_observations(&source);
        observations.position_calls = vec![
            position(1, TOKEN0, position_value(TOKEN0)),
            position(2, TOKEN0, CapturedPositionResult::None),
        ];
        observations.pool_calls = vec![
            pool(TOKEN0, CapturedPoolResult::Value(vec![0; 20])),
            pool([0x12; 20], CapturedPoolResult::None),
        ];
        observations.token_reads = vec![
            Gated::resolved(CapturedTokenObservation {
                address: TOKEN0.to_vec(),
                ordinal: 1,
                result: CapturedTokenResult::Found(18),
            }),
            Gated::resolved(CapturedTokenObservation {
                address: TOKEN1.to_vec(),
                ordinal: 2,
                result: CapturedTokenResult::Missing,
            }),
        ];
        let frame = map_resolved_npm_inputs(&source, observations).unwrap();
        let bytes = frame.encode_to_vec();
        assert_eq!(decode_npm_resolved_input_frame(&bytes).unwrap(), frame);
        let sentinel = ["Provider", "Unavailable"].concat();
        assert!(!String::from_utf8_lossy(&bytes).contains(&sentinel));
    }

    #[test]
    fn possible_reorg_and_unknown_abort_every_observation_class() {
        let source = source("mainnet", 19_470_001, vec![transfer(1, 19_470_001, 1)]);
        for call_scope in [
            Gated::<CapturedCallScope>::possible_reorg(),
            Gated::<CapturedCallScope>::unknown(),
        ] {
            let mut observations = empty_observations(&source);
            observations.call_scope = call_scope;
            assert!(map_resolved_npm_inputs(&source, observations).is_err());
        }
        for position_call in [
            Gated::<CapturedPositionObservation>::possible_reorg(),
            Gated::<CapturedPositionObservation>::unknown(),
        ] {
            let mut observations = empty_observations(&source);
            observations.position_calls = vec![position_call];
            assert!(map_resolved_npm_inputs(&source, observations).is_err());
        }
        for pool_call in [
            Gated::<CapturedPoolObservation>::possible_reorg(),
            Gated::<CapturedPoolObservation>::unknown(),
        ] {
            let mut observations = empty_observations(&source);
            observations.pool_calls = vec![pool_call];
            assert!(map_resolved_npm_inputs(&source, observations).is_err());
        }
        for token_read in [
            Gated::<CapturedTokenObservation>::possible_reorg(),
            Gated::<CapturedTokenObservation>::unknown(),
        ] {
            let mut observations = empty_observations(&source);
            observations.token_reads = vec![token_read];
            assert!(map_resolved_npm_inputs(&source, observations).is_err());
        }
    }

    fn fatal_middle_fixture() -> (NpmSourceBlock, SuppliedResolvedObservations) {
        let block = 12_369_651;
        let source = source(
            "mainnet",
            block,
            vec![transfer(1, block, 1), transfer(2, block, 2), transfer(3, block, 3)],
        );
        let mut observations = empty_observations(&source);
        observations.position_calls = vec![
            position(1, [0x11; 20], position_value([0x11; 20])),
            position(2, [0x12; 20], position_value([0x12; 20])),
            position(3, [0x13; 20], position_value([0x13; 20])),
        ];
        observations.pool_calls = vec![
            pool([0x11; 20], CapturedPoolResult::Value([0x31; 20].to_vec())),
            pool([0x12; 20], CapturedPoolResult::None),
            pool([0x13; 20], CapturedPoolResult::Value([0x33; 20].to_vec())),
        ];
        (source, observations)
    }

    #[test]
    fn fatal_middle_unresolved_or_malformed_later_observation_aborts_before_reducer() {
        let (source, observations) = fatal_middle_fixture();
        let frame = map_resolved_npm_inputs(&source, observations.clone()).unwrap();
        let reduction = reduce_npm_resolved_input_frame(&ReducerState::default(), &frame).unwrap();
        assert!(matches!(
            reduction.disposition,
            BlockDisposition::FatalNpmUserEntityProjection {
                ordinal: 2,
                omitted_event_count: 1,
                ..
            }
        ));

        let mut unresolved = observations.clone();
        unresolved.position_calls[2] = Gated::unknown();
        assert!(map_resolved_npm_inputs(&source, unresolved).is_err());

        let mut malformed = observations;
        let third = malformed.position_calls[2].resolved_value_mut().unwrap();
        if let CapturedPositionResult::Value(value) = &mut third.result {
            value.token0.pop();
        }
        assert!(map_resolved_npm_inputs(&source, malformed).is_err());
    }

    fn read_varint(bytes: &[u8], start: usize) -> (usize, usize) {
        let mut value = 0_usize;
        let mut shift = 0;
        let mut cursor = start;
        loop {
            let byte = bytes[cursor];
            cursor += 1;
            value |= usize::from(byte & 0x7f) << shift;
            if byte & 0x80 == 0 {
                return (value, cursor);
            }
            shift += 7;
        }
    }

    fn encode_varint(mut value: usize) -> Vec<u8> {
        let mut output = Vec::new();
        loop {
            let mut byte = (value & 0x7f) as u8;
            value >>= 7;
            if value != 0 {
                byte |= 0x80;
            }
            output.push(byte);
            if value == 0 {
                return output;
            }
        }
    }

    #[test]
    fn nested_source_canonical_unknown_field_and_drift_are_rejected() {
        let source = source("mainnet", 19_470_001, Vec::new());
        let frame = map_resolved_npm_inputs(&source, empty_observations(&source)).unwrap();
        let mut outer_unknown = frame.encode_to_vec();
        outer_unknown.extend([0xa0, 0x06, 0x01]);
        assert!(decode_npm_resolved_input_frame(&outer_unknown).is_err());

        let bytes = frame.encode_to_vec();
        assert_eq!(bytes[0], 0x0a);
        let (source_len, payload_start) = read_varint(&bytes, 1);
        let payload_end = payload_start + source_len;
        let extra = [0xa0, 0x06, 0x01];
        let mut nested_unknown = vec![0x0a];
        nested_unknown.extend(encode_varint(source_len + extra.len()));
        nested_unknown.extend(&bytes[payload_start..payload_end]);
        nested_unknown.extend(extra);
        nested_unknown.extend(&bytes[payload_end..]);
        assert!(decode_npm_resolved_input_frame(&nested_unknown).is_err());

        let mut drift = frame;
        drift.source.as_mut().unwrap().source_contract_sha256.push('x');
        assert!(decode_npm_resolved_input_frame(&drift.encode_to_vec()).is_err());
    }

    #[test]
    fn source_input_normal_and_fatal_authorities_are_independently_false() {
        let source = source("mainnet", 19_470_001, Vec::new());
        let frame = map_resolved_npm_inputs(&source, empty_observations(&source)).unwrap();
        assert!(!source_frame_authorizes_graph_block_or_checkpoint_success(&source));
        assert!(!resolved_input_frame_authorizes_graph_block_or_checkpoint_success(
            &frame
        ));
        let normal = BlockDisposition::ModeledNpmUserEntityProjectionComplete;
        let fatal = BlockDisposition::FatalNpmUserEntityProjection {
            ordinal: 1,
            message: "fixture".to_owned(),
            omitted_event_count: 0,
        };
        assert!(!reducer_disposition_authorizes_graph_block_or_checkpoint_success(
            &normal
        ));
        assert!(!reducer_disposition_authorizes_graph_block_or_checkpoint_success(
            &fatal
        ));
    }

    #[test]
    fn exact_initial_blocks_and_both_call_scope_variants_replay_empty_frames() {
        for (network, block) in [("mainnet", 12_369_651), ("base", 1_371_713)] {
            let source = source(network, block, Vec::new());
            let mut observations = empty_observations(&source);
            if network == "base" {
                observations.call_scope = Gated::resolved(CapturedCallScope::BlockNumberFallback(block));
            }
            let frame = map_resolved_npm_inputs(&source, observations).unwrap();
            let reduction = reduce_npm_resolved_input_frame(&ReducerState::default(), &frame).unwrap();
            assert!(reduction.outcomes.is_empty());
        }
    }

    #[test]
    fn source_transactions_are_reused_without_raw_block_recomputation() {
        let source = source("mainnet", 19_470_001, vec![increase(1, 19_470_001, 1)]);
        let mut observations = empty_observations(&source);
        observations.position_calls = vec![position(1, TOKEN0, CapturedPositionResult::None)];
        let frame = map_resolved_npm_inputs(&source, observations).unwrap();
        assert_eq!(frame.source.as_ref().unwrap(), &source);
        assert_eq!(frame.source.as_ref().unwrap().transactions, source.transactions);
    }

    #[test]
    fn exact_upstream_bindings_are_compile_time_visible() {
        assert_eq!(
            NPM_SOURCE_RUNTIME_SHA256,
            "701e83d3833356cff75ad4455553894e7695fb9f75f03e7c53eaa3da616b57d5"
        );
        assert_eq!(
            NPM_SOURCE_SEMANTICS_SHA256,
            "267dfc6b7240c36cdf345553e02a4f7b5332fa70548349bc6ef4b3075b4fcb4b"
        );
        assert_eq!(
            NPM_SOURCE_PROTO_SHA256,
            "bd394a11de37449710f0fd7dc10eac4e7f4ad299141a9fd54ec156980246fe1e"
        );
        assert_eq!(
            NPM_SOURCE_VALIDATOR_SHA256,
            "5dac40f6f81223b0e373eb69e12a652754bc92879c0da28244ba80849b95c177"
        );
        assert_eq!(
            NPM_SOURCE_BINDING_SHA256,
            "0dba8501e790d4efd0cda3cf64c9eddbca01cb9ce90da3931568224b38c7be3d"
        );
        assert_eq!(
            NPM_HANDLER_REDUCER_RUNTIME_SHA256,
            "6f46d5cca49506c3ee0622351324ccb62a459916f0e41f3772fe021e0e185dd6"
        );
        assert_eq!(
            NPM_HANDLER_REDUCER_SEMANTICS_SHA256,
            "86cf89d8ffe66ac9f4aeda468988306ccc9dca1dbfd2641f132f12529207b143"
        );
        assert_eq!(WRITER_PROTO_SHA256.len(), 64);
        assert_eq!(WRITER_RUNTIME_SHA256.len(), 64);
        assert_eq!(WRITER_PROFILE_SHA256.len(), 64);
        assert_eq!(SEGMENT_MATRIX_SHA256.len(), 64);
        assert_eq!(EXECUTION_ORDER_SHA256.len(), 64);
    }
}
