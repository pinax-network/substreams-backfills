// @generated and checked in for the pinned prost 0.13.3 wire contract.
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct NpmResolvedInputs {
    #[prost(message, optional, tag = "1")]
    pub source: ::core::option::Option<super::super::source::v1::NpmSourceBlock>,
    #[prost(message, optional, tag = "2")]
    pub call_scope: ::core::option::Option<ResolvedCallScope>,
    #[prost(message, repeated, tag = "3")]
    pub position_calls: ::prost::alloc::vec::Vec<PositionObservation>,
    #[prost(message, repeated, tag = "4")]
    pub pool_calls: ::prost::alloc::vec::Vec<PoolObservation>,
    #[prost(message, repeated, tag = "5")]
    pub token_reads: ::prost::alloc::vec::Vec<TokenObservation>,
    #[prost(string, tag = "6")]
    pub input_contract_sha256: ::prost::alloc::string::String,
    #[prost(string, tag = "7")]
    pub npm_source_contract_sha256: ::prost::alloc::string::String,
    #[prost(string, tag = "8")]
    pub npm_handler_reducer_contract_sha256: ::prost::alloc::string::String,
}

#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct ResolvedCallScope {
    #[prost(oneof = "resolved_call_scope::Scope", tags = "1, 2")]
    pub scope: ::core::option::Option<resolved_call_scope::Scope>,
}

pub mod resolved_call_scope {
    #[allow(clippy::derive_partial_eq_without_eq)]
    #[derive(Clone, PartialEq, ::prost::Oneof)]
    pub enum Scope {
        #[prost(bytes, tag = "1")]
        Eip1898Hash(::prost::alloc::vec::Vec<u8>),
        #[prost(uint64, tag = "2")]
        BlockNumberFallback(u64),
    }
}

#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct PositionObservation {
    #[prost(bytes = "vec", tag = "1")]
    pub position_manager: ::prost::alloc::vec::Vec<u8>,
    #[prost(bytes = "vec", tag = "2")]
    pub token_id: ::prost::alloc::vec::Vec<u8>,
    #[prost(oneof = "position_observation::Result", tags = "3, 4")]
    pub result: ::core::option::Option<position_observation::Result>,
}

pub mod position_observation {
    #[allow(clippy::derive_partial_eq_without_eq)]
    #[derive(Clone, PartialEq, ::prost::Oneof)]
    pub enum Result {
        #[prost(message, tag = "3")]
        Value(super::PositionValue),
        #[prost(message, tag = "4")]
        None(super::ResolvedNone),
    }
}

#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct PositionValue {
    #[prost(bytes = "vec", tag = "1")]
    pub token0: ::prost::alloc::vec::Vec<u8>,
    #[prost(bytes = "vec", tag = "2")]
    pub token1: ::prost::alloc::vec::Vec<u8>,
    #[prost(uint32, tag = "3")]
    pub fee: u32,
    #[prost(sint32, tag = "4")]
    pub tick_lower: i32,
    #[prost(sint32, tag = "5")]
    pub tick_upper: i32,
    #[prost(bytes = "vec", tag = "6")]
    pub fee_growth_inside0_last_x128: ::prost::alloc::vec::Vec<u8>,
    #[prost(bytes = "vec", tag = "7")]
    pub fee_growth_inside1_last_x128: ::prost::alloc::vec::Vec<u8>,
}

#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct PoolObservation {
    #[prost(bytes = "vec", tag = "1")]
    pub factory: ::prost::alloc::vec::Vec<u8>,
    #[prost(bytes = "vec", tag = "2")]
    pub token0: ::prost::alloc::vec::Vec<u8>,
    #[prost(bytes = "vec", tag = "3")]
    pub token1: ::prost::alloc::vec::Vec<u8>,
    #[prost(uint32, tag = "4")]
    pub fee: u32,
    #[prost(oneof = "pool_observation::Result", tags = "5, 6")]
    pub result: ::core::option::Option<pool_observation::Result>,
}

pub mod pool_observation {
    #[allow(clippy::derive_partial_eq_without_eq)]
    #[derive(Clone, PartialEq, ::prost::Oneof)]
    pub enum Result {
        #[prost(bytes, tag = "5")]
        Pool(::prost::alloc::vec::Vec<u8>),
        #[prost(message, tag = "6")]
        None(super::ResolvedNone),
    }
}

#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct TokenObservation {
    #[prost(bytes = "vec", tag = "1")]
    pub address: ::prost::alloc::vec::Vec<u8>,
    #[prost(uint64, tag = "2")]
    pub ordinal: u64,
    #[prost(oneof = "token_observation::Result", tags = "3, 4")]
    pub result: ::core::option::Option<token_observation::Result>,
}

pub mod token_observation {
    #[allow(clippy::derive_partial_eq_without_eq)]
    #[derive(Clone, PartialEq, ::prost::Oneof)]
    pub enum Result {
        #[prost(message, tag = "3")]
        Found(super::TokenFound),
        #[prost(message, tag = "4")]
        Missing(super::ResolvedNone),
    }
}

#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct TokenFound {
    #[prost(uint32, tag = "1")]
    pub decimals: u32,
}

#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, Copy, PartialEq, ::prost::Message)]
pub struct ResolvedNone {}
