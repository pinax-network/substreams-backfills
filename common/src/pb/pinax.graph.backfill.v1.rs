// @generated from common/proto/block_changes.proto; checked in for hermetic builds.
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
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord, ::prost::Enumeration)]
#[repr(i32)]
pub enum DeterministicErrorPolicy {
    Unspecified = 0,
    Fatal = 1,
    NonFatal = 2,
}

impl DeterministicErrorPolicy {
    pub fn as_str_name(&self) -> &'static str {
        match self {
            Self::Unspecified => "DETERMINISTIC_ERROR_POLICY_UNSPECIFIED",
            Self::Fatal => "DETERMINISTIC_ERROR_POLICY_FATAL",
            Self::NonFatal => "DETERMINISTIC_ERROR_POLICY_NON_FATAL",
        }
    }

    pub fn from_str_name(value: &str) -> ::core::option::Option<Self> {
        match value {
            "DETERMINISTIC_ERROR_POLICY_UNSPECIFIED" => Some(Self::Unspecified),
            "DETERMINISTIC_ERROR_POLICY_FATAL" => Some(Self::Fatal),
            "DETERMINISTIC_ERROR_POLICY_NON_FATAL" => Some(Self::NonFatal),
            _ => None,
        }
    }
}

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct EntityOperation {
    #[prost(uint64, tag = "1")]
    pub operation_index: u64,
    #[prost(uint64, tag = "2")]
    pub handler_group_order: u64,
    #[prost(uint64, tag = "3")]
    pub source_trigger_order: u64,
    #[prost(string, optional, tag = "4")]
    pub poi_causality_region: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(uint64, tag = "5")]
    pub handler_order: u64,
    #[prost(sint32, tag = "6")]
    pub source_causality_region: i32,
    #[prost(oneof = "entity_operation::Operation", tags = "7, 8, 9")]
    pub operation: ::core::option::Option<entity_operation::Operation>,
}

pub mod entity_operation {
    #[derive(Clone, PartialEq, ::prost::Oneof)]
    pub enum Operation {
        #[prost(message, tag = "7")]
        Set(super::SetEntity),
        #[prost(message, tag = "8")]
        Remove(super::RemoveEntity),
        #[prost(message, tag = "9")]
        DeterministicError(super::DeterministicError),
    }
}

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct EntityKey {
    #[prost(string, tag = "1")]
    pub entity_type: ::prost::alloc::string::String,
    #[prost(message, optional, tag = "2")]
    pub id: ::core::option::Option<EntityId>,
    #[prost(sint32, tag = "3")]
    pub storage_causality_region: i32,
}

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct EntityId {
    #[prost(oneof = "entity_id::Value", tags = "1, 2, 3")]
    pub value: ::core::option::Option<entity_id::Value>,
}

pub mod entity_id {
    #[derive(Clone, PartialEq, ::prost::Oneof)]
    pub enum Value {
        #[prost(string, tag = "1")]
        String(::prost::alloc::string::String),
        #[prost(bytes, tag = "2")]
        Bytes(::prost::alloc::vec::Vec<u8>),
        #[prost(sint64, tag = "3")]
        Int8(i64),
    }
}

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct SetEntity {
    #[prost(message, optional, tag = "1")]
    pub key: ::core::option::Option<EntityKey>,
    #[prost(string, tag = "2")]
    pub poi_entity_type: ::prost::alloc::string::String,
    #[prost(string, tag = "3")]
    pub poi_entity_id: ::prost::alloc::string::String,
    #[prost(message, repeated, tag = "4")]
    pub written_fields: ::prost::alloc::vec::Vec<EntityField>,
    #[prost(message, optional, tag = "5")]
    pub materialized: ::core::option::Option<EntityFields>,
    #[prost(enumeration = "StoreDisposition", tag = "6")]
    pub store_disposition: i32,
    #[prost(enumeration = "SetFailureStage", tag = "7")]
    pub failure_stage: i32,
}

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct RemoveEntity {
    #[prost(message, optional, tag = "1")]
    pub key: ::core::option::Option<EntityKey>,
    #[prost(string, tag = "2")]
    pub poi_entity_type: ::prost::alloc::string::String,
    #[prost(string, tag = "3")]
    pub poi_entity_id: ::prost::alloc::string::String,
    #[prost(enumeration = "StoreDisposition", tag = "4")]
    pub store_disposition: i32,
}

#[derive(Clone, Copy, PartialEq, ::prost::Message)]
pub struct DeterministicError {
    #[prost(uint64, tag = "1")]
    pub redacted_events: u64,
}

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct EntityField {
    #[prost(string, tag = "1")]
    pub name: ::prost::alloc::string::String,
    #[prost(message, optional, tag = "2")]
    pub value: ::core::option::Option<GraphValue>,
}

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct EntityFields {
    #[prost(message, repeated, tag = "1")]
    pub fields: ::prost::alloc::vec::Vec<EntityField>,
}

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct GraphValue {
    #[prost(oneof = "graph_value::Kind", tags = "1, 2, 3, 4, 5, 6, 7, 8, 9, 10")]
    pub kind: ::core::option::Option<graph_value::Kind>,
}

pub mod graph_value {
    #[derive(Clone, PartialEq, ::prost::Oneof)]
    pub enum Kind {
        #[prost(string, tag = "1")]
        String(::prost::alloc::string::String),
        #[prost(sint32, tag = "2")]
        Int(i32),
        #[prost(sint64, tag = "3")]
        Int8(i64),
        #[prost(sint64, tag = "4")]
        TimestampMicros(i64),
        #[prost(message, tag = "5")]
        BigDecimal(super::BigDecimalValue),
        #[prost(bool, tag = "6")]
        Bool(bool),
        #[prost(message, tag = "7")]
        List(super::ListValue),
        #[prost(message, tag = "8")]
        Null(super::NullValue),
        #[prost(bytes, tag = "9")]
        Bytes(::prost::alloc::vec::Vec<u8>),
        #[prost(message, tag = "10")]
        BigInt(super::BigIntValue),
    }
}

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct BigIntValue {
    #[prost(bytes = "vec", tag = "1")]
    pub signed_be: ::prost::alloc::vec::Vec<u8>,
}

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct BigDecimalValue {
    #[prost(bytes = "vec", tag = "1")]
    pub coefficient_signed_be: ::prost::alloc::vec::Vec<u8>,
    #[prost(sint64, tag = "2")]
    pub scale: i64,
}

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct ListValue {
    #[prost(message, repeated, tag = "1")]
    pub values: ::prost::alloc::vec::Vec<GraphValue>,
}

#[derive(Clone, Copy, PartialEq, ::prost::Message)]
pub struct NullValue {}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord, ::prost::Enumeration)]
#[repr(i32)]
pub enum StoreDisposition {
    Unspecified = 0,
    Committed = 1,
    Discarded = 2,
    BlockDiscarded = 3,
}

impl StoreDisposition {
    pub fn as_str_name(&self) -> &'static str {
        match self {
            Self::Unspecified => "STORE_DISPOSITION_UNSPECIFIED",
            Self::Committed => "STORE_DISPOSITION_COMMITTED",
            Self::Discarded => "STORE_DISPOSITION_DISCARDED",
            Self::BlockDiscarded => "STORE_DISPOSITION_BLOCK_DISCARDED",
        }
    }

    pub fn from_str_name(value: &str) -> ::core::option::Option<Self> {
        match value {
            "STORE_DISPOSITION_UNSPECIFIED" => Some(Self::Unspecified),
            "STORE_DISPOSITION_COMMITTED" => Some(Self::Committed),
            "STORE_DISPOSITION_DISCARDED" => Some(Self::Discarded),
            "STORE_DISPOSITION_BLOCK_DISCARDED" => Some(Self::BlockDiscarded),
            _ => None,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord, ::prost::Enumeration)]
#[repr(i32)]
pub enum SetFailureStage {
    Unspecified = 0,
    BeforeCacheSideEffects = 1,
    AfterCapacityAndVid = 2,
}

impl SetFailureStage {
    pub fn as_str_name(&self) -> &'static str {
        match self {
            Self::Unspecified => "SET_FAILURE_STAGE_UNSPECIFIED",
            Self::BeforeCacheSideEffects => "SET_FAILURE_STAGE_BEFORE_CACHE_SIDE_EFFECTS",
            Self::AfterCapacityAndVid => "SET_FAILURE_STAGE_AFTER_CAPACITY_AND_VID",
        }
    }

    pub fn from_str_name(value: &str) -> ::core::option::Option<Self> {
        match value {
            "SET_FAILURE_STAGE_UNSPECIFIED" => Some(Self::Unspecified),
            "SET_FAILURE_STAGE_BEFORE_CACHE_SIDE_EFFECTS" => Some(Self::BeforeCacheSideEffects),
            "SET_FAILURE_STAGE_AFTER_CAPACITY_AND_VID" => Some(Self::AfterCapacityAndVid),
            _ => None,
        }
    }
}
