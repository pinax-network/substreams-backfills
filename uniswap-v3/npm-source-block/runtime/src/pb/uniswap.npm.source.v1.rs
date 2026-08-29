// @generated and checked in for the pinned prost 0.13.3 wire contract.
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct NpmSourceBlock {
    #[prost(message, optional, tag = "1")]
    pub writer_events: ::core::option::Option<super::writer::WriterEvents>,
    #[prost(message, optional, tag = "2")]
    pub block: ::core::option::Option<BlockRef>,
    #[prost(message, repeated, tag = "3")]
    pub transactions: ::prost::alloc::vec::Vec<TransactionRef>,
    #[prost(string, tag = "4")]
    pub source_contract_sha256: ::prost::alloc::string::String,
}

#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct BlockRef {
    #[prost(uint64, tag = "1")]
    pub number: u64,
    #[prost(bytes = "vec", tag = "2")]
    pub hash: ::prost::alloc::vec::Vec<u8>,
    #[prost(bytes = "vec", tag = "3")]
    pub parent_hash: ::prost::alloc::vec::Vec<u8>,
    #[prost(uint64, tag = "4")]
    pub timestamp_seconds: u64,
}

#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct TransactionRef {
    #[prost(bytes = "vec", tag = "1")]
    pub hash: ::prost::alloc::vec::Vec<u8>,
    #[prost(uint32, tag = "2")]
    pub index: u32,
    #[prost(uint64, tag = "3")]
    pub gas_limit: u64,
    #[prost(bytes = "vec", tag = "4")]
    pub gas_price_be: ::prost::alloc::vec::Vec<u8>,
}
