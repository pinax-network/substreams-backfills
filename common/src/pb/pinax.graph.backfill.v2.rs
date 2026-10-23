// Checked-in prost envelope adapter for common/proto/block_changes_in_band.proto.
// Reuse the frozen v1 nested types; only the envelope is extended.
pub use super::v1::*;
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct BlockChanges {
    #[prost(string, tag = "1")]
    pub contract: ::prost::alloc::string::String,
    #[prost(bytes = "vec", tag = "2")]
    pub compatibility_id: ::prost::alloc::vec::Vec<u8>,
    #[prost(uint64, tag = "3")]
    pub block_number: u64,
    #[prost(bytes = "vec", tag = "4")]
    pub block_hash: ::prost::alloc::vec::Vec<u8>,
    #[prost(bool, tag = "5")]
    pub mapping_triggered: bool,
    #[prost(string, repeated, tag = "6")]
    pub triggered_poi_causality_regions: ::prost::alloc::vec::Vec<::prost::alloc::string::String>,
    #[prost(message, repeated, tag = "7")]
    pub operations: ::prost::alloc::vec::Vec<EntityOperation>,
    #[prost(enumeration = "DeterministicErrorPolicy", tag = "8")]
    pub deterministic_error_policy: i32,
    #[prost(message, repeated, tag = "9")]
    pub created_data_sources: ::prost::alloc::vec::Vec<CreatedDataSource>,
}

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct CreatedDataSource {
    #[prost(uint32, tag = "1")]
    pub ordinal: u32,
    #[prost(uint32, tag = "2")]
    pub manifest_idx: u32,
    #[prost(string, tag = "3")]
    pub template: ::prost::alloc::string::String,
    #[prost(uint64, tag = "4")]
    pub handler_group_order: u64,
    #[prost(bytes = "vec", tag = "5")]
    pub param: ::prost::alloc::vec::Vec<u8>,
    #[prost(string, optional, tag = "6")]
    pub context_json: ::core::option::Option<::prost::alloc::string::String>,
}

impl From<super::v1::BlockChanges> for BlockChanges {
    fn from(value: super::v1::BlockChanges) -> Self {
        Self {
            contract: value.contract,
            compatibility_id: value.compatibility_id,
            block_number: value.block_number,
            block_hash: value.block_hash,
            mapping_triggered: value.mapping_triggered,
            triggered_poi_causality_regions: value.triggered_poi_causality_regions,
            operations: value.operations,
            deterministic_error_policy: value.deterministic_error_policy,
            created_data_sources: Vec::new(),
        }
    }
}
