// @generated and checked in for the pinned prost 0.13.3 wire contract.
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct NpmObservationPlan {
    #[prost(bytes = "vec", tag = "1")]
    pub source_frame_sha256: ::prost::alloc::vec::Vec<u8>,
    #[prost(bytes = "vec", tag = "2")]
    pub planning_state_sha256: ::prost::alloc::vec::Vec<u8>,
    #[prost(message, optional, tag = "3")]
    pub call_scope: ::core::option::Option<super::super::inputs::v1::ResolvedCallScope>,
    #[prost(string, tag = "4")]
    pub network: ::prost::alloc::string::String,
    #[prost(uint64, tag = "5")]
    pub block_number: u64,
    #[prost(bytes = "vec", tag = "6")]
    pub block_hash: ::prost::alloc::vec::Vec<u8>,
    #[prost(string, tag = "7")]
    pub segment_id: ::prost::alloc::string::String,
    #[prost(string, tag = "8")]
    pub segment_semantic_contract_sha256: ::prost::alloc::string::String,
    #[prost(string, tag = "9")]
    pub npm_profile_id: ::prost::alloc::string::String,
    #[prost(message, repeated, tag = "10")]
    pub position_requests: ::prost::alloc::vec::Vec<PositionRequest>,
    #[prost(message, repeated, tag = "11")]
    pub pool_requests: ::prost::alloc::vec::Vec<PoolRequest>,
    #[prost(message, repeated, tag = "12")]
    pub token_requests: ::prost::alloc::vec::Vec<TokenRequest>,
    #[prost(string, tag = "13")]
    pub plan_contract_sha256: ::prost::alloc::string::String,
    #[prost(string, tag = "14")]
    pub resolved_input_runtime_sha256: ::prost::alloc::string::String,
}

#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct PositionRequest {
    #[prost(bytes = "vec", tag = "1")]
    pub position_manager: ::prost::alloc::vec::Vec<u8>,
    #[prost(bytes = "vec", tag = "2")]
    pub token_id: ::prost::alloc::vec::Vec<u8>,
    #[prost(uint64, repeated, tag = "3")]
    pub event_ordinals: ::prost::alloc::vec::Vec<u64>,
    #[prost(uint32, tag = "4")]
    pub reason_mask: u32,
    #[prost(uint32, tag = "5")]
    pub expected_consumption_count: u32,
}

#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct PoolRequest {
    #[prost(bytes = "vec", tag = "1")]
    pub factory: ::prost::alloc::vec::Vec<u8>,
    #[prost(bytes = "vec", tag = "2")]
    pub token0: ::prost::alloc::vec::Vec<u8>,
    #[prost(bytes = "vec", tag = "3")]
    pub token1: ::prost::alloc::vec::Vec<u8>,
    #[prost(uint32, tag = "4")]
    pub fee: u32,
    #[prost(uint64, repeated, tag = "5")]
    pub event_ordinals: ::prost::alloc::vec::Vec<u64>,
    #[prost(uint32, tag = "6")]
    pub reason_mask: u32,
    #[prost(uint32, tag = "7")]
    pub expected_consumption_count: u32,
}

#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct TokenRequest {
    #[prost(bytes = "vec", tag = "1")]
    pub address: ::prost::alloc::vec::Vec<u8>,
    #[prost(uint64, tag = "2")]
    pub ordinal: u64,
    #[prost(uint32, tag = "3")]
    pub reason_mask: u32,
    #[prost(uint32, tag = "4")]
    pub expected_consumption_count: u32,
}
