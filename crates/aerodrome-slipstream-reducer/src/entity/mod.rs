//! Typed mapping objects and exact stored-field schema. Objects are owned
//! copies; only save publishes them into a handler's cache.
use crate::{calls::graph_store_string, refuse, require, Result};
use backfill_common::pb::pinax::graph::backfill::v1 as pb;
use graph_numerics::{bigint, BigInt, GraphDecimal};
use pb::graph_value::Kind;

#[derive(Clone, Debug, PartialEq, Eq, Default)]
pub enum Presence<T> {
    #[default]
    Absent,
    Null,
    Set(T),
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum EntityClass {
    Hot,
    Tiered,
    PeriodDay,
    PeriodHour,
    BlockLocal,
    NeverWritten,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct FieldDef {
    pub name: &'static str,
    pub graphql_type: &'static str,
}
#[derive(Clone, Copy, Debug)]
pub struct EntityDef {
    pub name: &'static str,
    pub class: EntityClass,
    pub fields: &'static [FieldDef],
}
pub trait Entity: Clone {
    const DEF: EntityDef;
    fn id(&self) -> &str;
    fn to_fields(&self) -> Result<Vec<pb::EntityField>>;
    fn from_fields(fields: &[pb::EntityField]) -> Result<Self>;
}
/// Scalar conversion models the store boundary, including NUL removal and the
/// current explicit fixed-point decimal transport restriction.
pub trait Scalar: Sized {
    fn encode(&self) -> Result<Kind>;
    fn decode(value: &Kind) -> Result<Self>;
}
impl Scalar for String {
    fn encode(&self) -> Result<Kind> {
        Ok(Kind::String(graph_store_string(self)))
    }
    fn decode(v: &Kind) -> Result<Self> {
        match v {
            Kind::String(s) => Ok(s.clone()),
            _ => Err(refuse("expected String")),
        }
    }
}
impl Scalar for i32 {
    fn encode(&self) -> Result<Kind> {
        Ok(Kind::Int(*self))
    }
    fn decode(v: &Kind) -> Result<Self> {
        match v {
            Kind::Int(n) => Ok(*n),
            _ => Err(refuse("expected Int")),
        }
    }
}
impl Scalar for BigInt {
    fn encode(&self) -> Result<Kind> {
        bigint::to_wire(self)
            .map(Kind::BigInt)
            .map_err(|e| refuse(e.to_string()))
    }
    fn decode(v: &Kind) -> Result<Self> {
        match v {
            Kind::BigInt(n) => bigint::from_wire(n).map_err(|e| refuse(e.to_string())),
            _ => Err(refuse("expected BigInt")),
        }
    }
}
impl Scalar for GraphDecimal {
    fn encode(&self) -> Result<Kind> {
        self.to_block_changes_wire()
            .map(Kind::BigDecimal)
            .map_err(|e| refuse(e.to_string()))
    }
    fn decode(v: &Kind) -> Result<Self> {
        match v {
            Kind::BigDecimal(n) => {
                Self::from_block_changes_wire(n).map_err(|e| refuse(e.to_string()))
            }
            _ => Err(refuse("expected BigDecimal")),
        }
    }
}
impl Scalar for Vec<u8> {
    fn encode(&self) -> Result<Kind> {
        Ok(Kind::Bytes(self.clone()))
    }
    fn decode(v: &Kind) -> Result<Self> {
        match v {
            Kind::Bytes(n) => Ok(n.clone()),
            _ => Err(refuse("expected Bytes")),
        }
    }
}
impl Scalar for Vec<String> {
    fn encode(&self) -> Result<Kind> {
        Ok(Kind::List(pb::ListValue {
            values: self
                .iter()
                .map(|v| v.encode().map(|kind| pb::GraphValue { kind: Some(kind) }))
                .collect::<Result<_>>()?,
        }))
    }
    fn decode(v: &Kind) -> Result<Self> {
        match v {
            Kind::List(v) => v
                .values
                .iter()
                .map(|v| {
                    String::decode(
                        v.kind
                            .as_ref()
                            .ok_or_else(|| refuse("missing list value"))?,
                    )
                })
                .collect(),
            _ => Err(refuse("expected relation list")),
        }
    }
}
pub trait FieldValue: Sized {
    fn encode_field(&self) -> Result<Option<Kind>>;
    fn decode_field(value: Option<&Kind>) -> Result<Self>;
}
impl<T: Scalar> FieldValue for T {
    fn encode_field(&self) -> Result<Option<Kind>> {
        self.encode().map(Some)
    }
    fn decode_field(value: Option<&Kind>) -> Result<Self> {
        T::decode(value.ok_or_else(|| refuse("missing required field"))?)
    }
}
impl<T: Scalar> FieldValue for Presence<T> {
    fn encode_field(&self) -> Result<Option<Kind>> {
        match self {
            Self::Absent => Ok(None),
            Self::Null => Ok(Some(Kind::Null(pb::NullValue {}))),
            Self::Set(v) => v.encode().map(Some),
        }
    }
    fn decode_field(value: Option<&Kind>) -> Result<Self> {
        match value {
            None => Ok(Self::Absent),
            Some(Kind::Null(_)) => Ok(Self::Null),
            Some(v) => T::decode(v).map(Self::Set),
        }
    }
}
fn field<'a>(fields: &'a [pb::EntityField], name: &str) -> Option<&'a Kind> {
    fields
        .binary_search_by(|f| f.name.as_str().cmp(name))
        .ok()
        .and_then(|i| fields[i].value.as_ref()?.kind.as_ref())
}
macro_rules! graph_entity {
    ($name:ident, $class:ident, {$($rust:ident : $ty:ty => $gql:literal : $gt:literal),* $(,)?})=>{
        #[derive(Clone,Debug,PartialEq)]
        pub struct $name {$(pub $rust:$ty),*}
        impl Entity for $name {
            const DEF:EntityDef=EntityDef{name:stringify!($name),class:EntityClass::$class,fields:&[$(FieldDef{name:$gql,graphql_type:$gt}),*]};
            fn id(&self)->&str{&self.id}
            fn to_fields(&self)->Result<Vec<pb::EntityField>>{
                let mut fields=Vec::new();
                $(if let Some(kind)=self.$rust.encode_field()?{fields.push(pb::EntityField{name:$gql.into(),value:Some(pb::GraphValue{kind:Some(kind)})});})*
                validate_fields(Self::DEF.name,&self.id,&fields,true)?;
                Ok(fields)
            }
            fn from_fields(fields:&[pb::EntityField])->Result<Self>{
                let id=String::decode_field(field(fields,"id"))?;
                validate_fields(Self::DEF.name,&id,fields,true)?;
                Ok(Self{$($rust:<$ty>::decode_field(field(fields,$gql))?),*})
            }
        }
    }
}
mod types;
pub use types::*;
pub fn definition(name: &str) -> Result<&'static EntityDef> {
    ALL_ENTITIES
        .binary_search_by_key(&name, |d| d.name)
        .map(|i| &ALL_ENTITIES[i])
        .map_err(|_| refuse(format!("unknown entity {name}")))
}
pub fn key(entity_type: &str, id: &str) -> pb::EntityKey {
    pb::EntityKey {
        entity_type: entity_type.into(),
        id: Some(pb::EntityId {
            value: Some(pb::entity_id::Value::String(id.into())),
        }),
        storage_causality_region: 0,
    }
}
/// Complete images require all non-null fields. Partial writes are checked
/// against their post-merge image by the journal before they can be accepted.
pub fn validate_fields(
    entity_type: &str,
    id: &str,
    fields: &[pb::EntityField],
    complete: bool,
) -> Result<()> {
    let def = definition(entity_type)?;
    require(!id.contains('\0'), "NUL in entity ID")?;
    backfill_common::block_changes::validate_materialized_entity(0, &key(entity_type, id), fields)
        .map_err(|e| refuse(e.to_string()))?;
    for f in fields {
        let fd = def
            .fields
            .binary_search_by_key(&f.name.as_str(), |d| d.name)
            .ok()
            .map(|i| &def.fields[i])
            .ok_or_else(|| refuse(format!("unknown or derived field {entity_type}.{}", f.name)))?;
        let kind = f
            .value
            .as_ref()
            .and_then(|v| v.kind.as_ref())
            .ok_or_else(|| refuse("missing GraphValue"))?;
        let nullable = !fd.graphql_type.ends_with('!');
        if matches!(kind, Kind::Null(_)) {
            require(nullable, "Null in non-null field")?;
            continue;
        }
        let ty = fd.graphql_type.trim_end_matches('!');
        let valid = match ty {
            "Int" => matches!(kind, Kind::Int(_)),
            "BigInt" => matches!(kind, Kind::BigInt(_)),
            "BigDecimal" => matches!(kind, Kind::BigDecimal(_)),
            "Bytes" => matches!(kind, Kind::Bytes(_)),
            "[Pool!]" => {
                matches!(kind,Kind::List(v) if v.values.iter().all(|v|matches!(v.kind,Some(Kind::String(_)))))
            }
            _ => matches!(kind, Kind::String(_)),
        };
        require(valid, &format!("wrong type for {entity_type}.{}", f.name))?;
    }
    if complete {
        for fd in def
            .fields
            .iter()
            .filter(|fd| fd.graphql_type.ends_with('!'))
        {
            require(
                field(fields, fd.name).is_some(),
                &format!("missing required {entity_type}.{}", fd.name),
            )?;
        }
    }
    Ok(())
}
/// Match host string normalization recursively, preserving top-level Null.
pub fn normalize_fields(fields: &[pb::EntityField]) -> Vec<pb::EntityField> {
    fn normalize(v: &mut pb::GraphValue) {
        match v.kind.as_mut() {
            Some(Kind::String(s)) => *s = graph_store_string(s),
            Some(Kind::List(l)) => l.values.iter_mut().for_each(normalize),
            _ => (),
        }
    }
    let mut out = fields.to_vec();
    for f in &mut out {
        if let Some(v) = &mut f.value {
            normalize(v);
        }
    }
    out.sort_by(|a, b| a.name.cmp(&b.name));
    out
}
