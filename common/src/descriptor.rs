//! Typed capabilities for descriptor v2. The frame contract remains v1; the
//! exact descriptor bytes still determine the compatibility ID.

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet};

/// V2 refuses duplicate object keys at every depth. Parsing straight into
/// `serde_json::Value` would silently keep the last value before typed
/// capability validation can see the conflict. V1 keeps its existing parser.
pub(crate) fn validate_unique_json(bytes: &[u8]) -> Result<(), String> {
    use serde::de::{DeserializeSeed, MapAccess, SeqAccess, Visitor};

    struct Unique;
    impl<'de> DeserializeSeed<'de> for Unique {
        type Value = ();
        fn deserialize<D: serde::Deserializer<'de>>(self, deserializer: D) -> Result<(), D::Error> {
            deserializer.deserialize_any(self)
        }
    }
    impl<'de> Visitor<'de> for Unique {
        type Value = ();
        fn expecting(&self, formatter: &mut std::fmt::Formatter) -> std::fmt::Result {
            formatter.write_str("JSON with unique object keys")
        }
        fn visit_unit<E>(self) -> Result<(), E> {
            Ok(())
        }
        fn visit_bool<E>(self, _: bool) -> Result<(), E> {
            Ok(())
        }
        fn visit_i64<E>(self, _: i64) -> Result<(), E> {
            Ok(())
        }
        fn visit_u64<E>(self, _: u64) -> Result<(), E> {
            Ok(())
        }
        fn visit_f64<E>(self, _: f64) -> Result<(), E> {
            Ok(())
        }
        fn visit_str<E>(self, _: &str) -> Result<(), E> {
            Ok(())
        }
        fn visit_string<E>(self, _: String) -> Result<(), E> {
            Ok(())
        }
        fn visit_seq<A: SeqAccess<'de>>(self, mut access: A) -> Result<(), A::Error> {
            while access.next_element_seed(Unique)?.is_some() {}
            Ok(())
        }
        fn visit_map<A: MapAccess<'de>>(self, mut access: A) -> Result<(), A::Error> {
            let mut keys = BTreeSet::new();
            while let Some(key) = access.next_key::<String>()? {
                if !keys.insert(key.clone()) {
                    return Err(serde::de::Error::custom(format!(
                        "duplicate JSON key: {key}"
                    )));
                }
                access.next_value_seed(Unique)?;
            }
            Ok(())
        }
    }
    let mut deserializer = serde_json::Deserializer::from_slice(bytes);
    Unique
        .deserialize(&mut deserializer)
        .map_err(|error| error.to_string())?;
    deserializer.end().map_err(|error| error.to_string())
}

pub const GRAPH_NODE_COMMIT: &str = "77823b5a7adc4eac4abf03202c8dd7cb00dea31d";

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RetentionPolicy {
    pub version: u32,
    pub default: PersistentDefault,
    pub types: BTreeMap<String, RetentionClass>,
    pub evidence: Vec<RetentionEvidence>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PersistentDefault {
    Persistent,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "class", rename_all = "snake_case", deny_unknown_fields)]
pub enum RetentionClass {
    Persistent,
    BlockLocal { proof: BlockLocalProof },
    PeriodScoped { period_id: PeriodId },
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum BlockLocalProof {
    DerivedFromTransaction,
    BlockNumberSuffix { separator: String },
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum PeriodId {
    WholeId,
    SuffixAfterLast { separator: String },
}

impl PeriodId {
    /// Parse unsigned decimal without accepting signs, whitespace or overflow.
    pub fn parse(&self, id: &str) -> Result<u64, String> {
        let digits = match self {
            Self::WholeId => id,
            Self::SuffixAfterLast { separator } => {
                valid_separator(separator)?;
                id.rsplit_once(separator)
                    .filter(|(prefix, _)| !prefix.is_empty())
                    .map(|(_, suffix)| suffix)
                    .ok_or_else(|| "period ID has no nonempty prefix and separator".to_owned())?
            }
        };
        if digits.is_empty() || !digits.bytes().all(|b| b.is_ascii_digit()) {
            return Err("period ID is not unsigned decimal".to_owned());
        }
        digits
            .parse()
            .map_err(|_| "period ID overflows u64".to_owned())
    }
}

impl BlockLocalProof {
    /// Transaction membership is a producer obligation, checked by differential
    /// oracles and loader overlap guards; it cannot be inferred from an ID.
    pub fn verify_block_suffix(&self, id: &str, block: u64) -> Result<(), String> {
        if let Self::BlockNumberSuffix { separator } = self {
            valid_separator(separator)?;
            let (prefix, suffix) = id
                .rsplit_once(separator)
                .ok_or_else(|| "block-local ID has no block suffix".to_owned())?;
            if prefix.is_empty() || suffix != block.to_string() {
                return Err("block-local ID does not name this block".to_owned());
            }
        }
        Ok(())
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RetentionEvidence {
    pub kind: RetentionEvidenceKind,
    pub reference: String,
    pub sha256: String,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RetentionEvidenceKind {
    StoreGetInventory,
    IdSchemeInventory,
}

impl Default for RetentionPolicy {
    fn default() -> Self {
        Self {
            version: 1,
            default: PersistentDefault::Persistent,
            types: BTreeMap::new(),
            evidence: Vec::new(),
        }
    }
}

impl RetentionPolicy {
    pub fn class(&self, entity_type: &str) -> &RetentionClass {
        self.types
            .get(entity_type)
            .unwrap_or(&RetentionClass::Persistent)
    }

    pub fn validate(&self, entity_types: &[String]) -> Result<(), String> {
        if self.version != 1 {
            return Err("entity_retention.version must be 1".to_owned());
        }
        let mut optimized = false;
        for (name, class) in &self.types {
            if entity_types.binary_search(name).is_err() {
                return Err(format!("retention names undeclared entity type {name}"));
            }
            match class {
                RetentionClass::Persistent => {}
                RetentionClass::BlockLocal { proof } => {
                    optimized = true;
                    if let BlockLocalProof::BlockNumberSuffix { separator } = proof {
                        valid_separator(separator)?;
                    }
                }
                RetentionClass::PeriodScoped { period_id } => {
                    optimized = true;
                    if let PeriodId::SuffixAfterLast { separator } = period_id {
                        valid_separator(separator)?;
                    }
                }
            }
        }
        let mut evidence_kinds = BTreeSet::new();
        for evidence in &self.evidence {
            nonempty_token(&evidence.reference, "retention evidence reference")?;
            require_hex(&evidence.sha256, 64, "retention evidence sha256")?;
            if !evidence_kinds.insert(evidence.kind) {
                return Err("duplicate retention evidence kind".to_owned());
            }
        }
        if optimized
            && !(evidence_kinds.contains(&RetentionEvidenceKind::StoreGetInventory)
                && evidence_kinds.contains(&RetentionEvidenceKind::IdSchemeInventory))
        {
            return Err(
                "non-persistent retention requires store-get and ID-scheme evidence".to_owned(),
            );
        }
        Ok(())
    }

    /// Object keys and evidence are sorted independently of JSON input order.
    /// This binds semantics, while the outer descriptor ID binds its raw bytes.
    pub fn canonical_bytes(&self) -> Vec<u8> {
        let mut canonical = self.clone();
        canonical.evidence.sort_by_key(|evidence| evidence.kind);
        canonical_json(&serde_json::to_value(canonical).expect("retention is serializable"))
    }

    pub fn sha256(&self) -> [u8; 32] {
        Sha256::digest(self.canonical_bytes()).into()
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct DescriptorCapabilities {
    pub deployment: String,
    pub spec_version: String,
    pub start_block: u64,
    pub graph_node: GraphNodeContract,
    pub storage_profile: DescriptorStorageProfile,
    pub data_sources: DataSourcesContract,
    pub entity_retention: RetentionPolicy,
    pub producer_contract: ProducerContract,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct GraphNodeContract {
    pub version: String,
    pub commit: String,
    pub poi_version: String,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DescriptorStorageProfile {
    /// Sorted, unique GraphQL entity names; their indexes are snapshot ordinals.
    pub entity_types: Vec<String>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DataSourcesContract {
    pub transport: DataSourceTransport,
    pub templates: Vec<TemplateContract>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DataSourceTransport {
    None,
    InBandV1,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TemplateContract {
    pub name: String,
    pub manifest_idx: u32,
    pub param: TemplateParameter,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum TemplateParameter {
    #[serde(rename = "address20")]
    Address20,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum ProducerContract {
    NativeBlockChangesReducer {
        reducer: ReducerIdentity,
        extractor: ExtractorIdentity,
    },
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReducerIdentity {
    pub repository: String,
    pub commit: String,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ExtractorIdentity {
    pub spkg_sha256: String,
    pub module: String,
    pub module_hash: String,
    pub output_type: String,
    pub initial_block: u64,
}

impl DescriptorCapabilities {
    pub(crate) fn from_descriptor(value: &serde_json::Value) -> Result<Self, String> {
        let result: Self = serde_json::from_value(value.clone()).map_err(|e| e.to_string())?;
        result.validate()?;
        Ok(result)
    }

    pub fn validate(&self) -> Result<(), String> {
        nonempty_token(&self.deployment, "deployment")?;
        let version: Vec<_> = self.spec_version.split('.').collect();
        if version.len() != 3
            || version.iter().any(|s| {
                s.is_empty() || !s.bytes().all(|b| b.is_ascii_digit()) || s.parse::<u32>().is_err()
            })
        {
            return Err("spec_version must be a three-component numeric version".to_owned());
        }
        if self.start_block > i32::MAX as u64 {
            return Err("start_block exceeds Graph Node's block-number domain".to_owned());
        }
        if self.graph_node.version != "0.44.0"
            || self.graph_node.commit != GRAPH_NODE_COMMIT
            || !matches!(self.graph_node.poi_version.as_str(), "fast" | "legacy")
        {
            return Err("unsupported Graph Node runtime or PoI contract".to_owned());
        }
        let types = &self.storage_profile.entity_types;
        if types.is_empty()
            || types.len() > u16::MAX as usize + 1
            || types.windows(2).any(|pair| pair[0] >= pair[1])
            || types.iter().any(|name| !graphql_name(name))
        {
            return Err(
                "entity_types must be sorted, unique GraphQL names fitting u16 ordinals".to_owned(),
            );
        }
        self.entity_retention.validate(types)?;
        let mut names = BTreeSet::new();
        let mut previous_index = None;
        for template in &self.data_sources.templates {
            if !graphql_name(&template.name)
                || !names.insert(&template.name)
                || previous_index.is_some_and(|index| index >= template.manifest_idx)
                || template.manifest_idx > i32::MAX as u32
            {
                return Err(
                    "templates require unique names and increasing manifest indexes".to_owned(),
                );
            }
            previous_index = Some(template.manifest_idx);
        }
        if self.data_sources.transport == DataSourceTransport::None && !names.is_empty() {
            return Err("data-source templates require in_band_v1 transport".to_owned());
        }
        let ProducerContract::NativeBlockChangesReducer { reducer, extractor } =
            &self.producer_contract;
        nonempty_token(&reducer.repository, "reducer repository")?;
        require_hex(&reducer.commit, 40, "reducer commit")?;
        require_hex(&extractor.spkg_sha256, 64, "extractor SPKG sha256")?;
        require_hex(&extractor.module_hash, 40, "extractor module hash")?;
        nonempty_token(&extractor.module, "extractor module")?;
        if !extractor.output_type.starts_with("proto:") || extractor.output_type.len() == 6 {
            return Err("extractor output_type must name a protobuf message".to_owned());
        }
        nonempty_token(&extractor.output_type, "extractor output type")?;
        if extractor.initial_block != self.start_block {
            return Err("extractor initial block must equal descriptor start_block".to_owned());
        }
        Ok(())
    }

    pub fn retention_sha256(&self) -> [u8; 32] {
        self.entity_retention.sha256()
    }
}

pub(crate) fn require_hex(value: &str, length: usize, field: &str) -> Result<(), String> {
    if value.len() != length
        || !value
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    {
        return Err(format!("{field} must be {length} lowercase hex characters"));
    }
    Ok(())
}

fn nonempty_token(value: &str, field: &str) -> Result<(), String> {
    if value.is_empty() || value.chars().any(|c| c.is_whitespace() || c.is_control()) {
        return Err(format!("{field} must be a nonempty token"));
    }
    Ok(())
}

fn graphql_name(value: &str) -> bool {
    let mut bytes = value.bytes();
    bytes
        .next()
        .is_some_and(|b| b.is_ascii_alphabetic() || b == b'_')
        && bytes.all(|b| b.is_ascii_alphanumeric() || b == b'_')
}

fn valid_separator(separator: &str) -> Result<(), String> {
    if separator.is_empty()
        || separator.len() > 16
        || separator
            .chars()
            .any(|c| c.is_ascii_digit() || c.is_whitespace() || c.is_control())
    {
        return Err(
            "ID separator must be 1..16 bytes without digits, whitespace or controls".to_owned(),
        );
    }
    Ok(())
}

pub(crate) fn canonical_json(value: &serde_json::Value) -> Vec<u8> {
    fn write(value: &serde_json::Value, out: &mut Vec<u8>) {
        match value {
            serde_json::Value::Object(map) => {
                out.push(b'{');
                let sorted: BTreeMap<_, _> = map.iter().collect();
                for (i, (key, value)) in sorted.into_iter().enumerate() {
                    if i > 0 {
                        out.push(b',');
                    }
                    serde_json::to_writer(&mut *out, key).expect("Vec write");
                    out.push(b':');
                    write(value, out);
                }
                out.push(b'}');
            }
            serde_json::Value::Array(array) => {
                out.push(b'[');
                for (i, value) in array.iter().enumerate() {
                    if i > 0 {
                        out.push(b',');
                    }
                    write(value, out);
                }
                out.push(b']');
            }
            _ => serde_json::to_writer(out, value).expect("Vec write"),
        }
    }
    let mut result = Vec::new();
    write(value, &mut result);
    result
}
