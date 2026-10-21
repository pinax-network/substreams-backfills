//! Bind exact descriptor bytes and the extractor identity supplied by the
//! package verification layer. BCF1 itself carries neither SPKG nor module hash.
use crate::{refuse, require, Result};
use aerodrome_extractor_core::config::{DEPLOYMENT, INITIAL_BLOCK};
use backfill_common::{
    descriptor::{
        DataSourceTransport, ExtractorIdentity, ProducerContract, TemplateContract,
        TemplateParameter,
    },
    BlockChangesCompatibility,
};
use sha2::{Digest, Sha256};
pub const OUTPUT_TYPE: &str = "proto:pinax.aerodrome.slipstream.base.v1.ExtractorBlock";
pub const OUTPUT_MODULE: &str = "map_extractor_block";

#[derive(Debug, Clone)]
pub struct InputBinding {
    compatibility: BlockChangesCompatibility,
}
impl InputBinding {
    /// `verified_extractor` must come from package verification, not a claim
    /// embedded in a frame. This validates the identity link, not the package.
    pub fn new(
        descriptor: &[u8],
        expected_descriptor_sha256: [u8; 32],
        verified_extractor: &ExtractorIdentity,
    ) -> Result<Self> {
        let compatibility = BlockChangesCompatibility::from_descriptor(descriptor)
            .map_err(|e| refuse(e.to_string()))?;
        let document: serde_json::Value =
            serde_json::from_slice(descriptor).map_err(|e| refuse(e.to_string()))?;
        let mut features: Vec<String> = serde_json::from_value(
            document
                .get("manifest_features")
                .cloned()
                .ok_or_else(|| refuse("missing manifest features"))?,
        )
        .map_err(|e| refuse(e.to_string()))?;
        features.sort();
        require(
            features == ["grafting", "nonFatalErrors"],
            "wrong deployed manifest features",
        )?;
        require(
            compatibility.id() == &expected_descriptor_sha256,
            "descriptor digest mismatch",
        )?;
        require(
            compatibility.expected_poi_causality_region() == "ethereum/base"
                && document.get("network").and_then(serde_json::Value::as_str) == Some("base"),
            "wrong target network",
        )?;
        // The locked deployment declares the grafting feature but has no graft.
        // Accept absent/null metadata only; never silently accept a grafted seed.
        for field in ["graft", "concrete_graft"] {
            require(
                document.get(field).is_none_or(serde_json::Value::is_null),
                "locked deployment has no concrete graft",
            )?;
        }
        let cap = compatibility
            .capabilities()
            .ok_or_else(|| refuse("Aerodrome reducer requires descriptor v2"))?;
        require(
            cap.deployment == DEPLOYMENT
                && cap.spec_version == "1.2.0"
                && cap.start_block == INITIAL_BLOCK,
            "wrong Aerodrome deployment/start/spec",
        )?;
        require(
            cap.graph_node.poi_version == "fast",
            "Aerodrome spec 1.2.0 requires Fast PoI",
        )?;
        require(
            cap.storage_profile.entity_types == entity_types(),
            "descriptor entity types differ from locked schema",
        )?;
        require(
            cap.data_sources.transport == DataSourceTransport::InBandV1
                && cap.data_sources.templates
                    == vec![TemplateContract {
                        name: "Pool".into(),
                        manifest_idx: 2,
                        param: TemplateParameter::Address20,
                    }],
            "wrong Pool template contract",
        )?;
        let ProducerContract::NativeBlockChangesReducer { reducer, extractor } =
            &cap.producer_contract
        else {
            return Err(refuse("reducer input requires a native reducer producer contract"));
        };
        require(
            reducer.repository == "pinax-network/substreams-backfills",
            "wrong reducer repository",
        )?;
        require(
            extractor == verified_extractor,
            "extractor identity mismatch",
        )?;
        require(
            extractor.module == OUTPUT_MODULE
                && extractor.output_type == OUTPUT_TYPE
                && extractor.initial_block == INITIAL_BLOCK,
            "wrong extractor module/output/start (candidate modules are not supported)",
        )?;
        Ok(Self { compatibility })
    }
    pub fn compatibility(&self) -> &BlockChangesCompatibility {
        &self.compatibility
    }
}
pub fn entity_types() -> Vec<String> {
    let schema = include_str!("../../../aerodrome-slipstream-base/reference/schema.graphql");
    assert_eq!(
        hex::encode(Sha256::digest(schema.as_bytes())),
        "09d7c40167fc27c3aa2de0ec003fe7b0b469e132943cc26dcd4db6064769d0e8",
        "locked schema changed"
    );
    let mut names = schema
        .lines()
        .filter(|line| line.starts_with("type ") && line.contains("@entity"))
        .map(|line| line.split_whitespace().nth(1).unwrap().to_owned())
        .collect::<Vec<_>>();
    names.sort();
    names
}

/// Build a v2 descriptor with conservative persistent retention. S-R6 may add
/// reviewed retention evidence; that intentionally changes compatibility ID.
/// Real release/source pins are mandatory inputs; this does not certify them.
pub fn build_descriptor(
    extractor: &ExtractorIdentity,
    reducer_commit: &str,
    emit_non_fatal: bool,
) -> Result<Vec<u8>> {
    let value = serde_json::json!({
        "contract":"pinax.graph.backfill.block-changes/v1","descriptor_version":2,
        "producer":"pinax-network/substreams-backfills",
        "deterministic_error_policy":if emit_non_fatal {"non_fatal"} else {"fatal"},
        "network":"base","expected_poi_causality_region":"ethereum/base",
        "deployment":DEPLOYMENT,"spec_version":"1.2.0","start_block":INITIAL_BLOCK,
        "manifest_features":["nonFatalErrors","grafting"],"graft":null,
        "graph_node":{"version":"0.44.0","commit":graph_numerics::GRAPH_NODE_COMMIT,"poi_version":"fast"},
        "storage_profile":{"entity_types":entity_types()},
        "data_sources":{"transport":"in_band_v1","templates":[{"name":"Pool","manifest_idx":2,"param":"address20"}]},
        "entity_retention":{"version":1,"default":"persistent","types":{},"evidence":[]},
        "producer_contract":{"kind":"native_block_changes_reducer","reducer":{"repository":"pinax-network/substreams-backfills","commit":reducer_commit},"extractor":extractor}
    });
    let mut bytes = serde_json::to_vec_pretty(&value).map_err(|e| refuse(e.to_string()))?;
    bytes.push(b'\n');
    InputBinding::new(&bytes, Sha256::digest(&bytes).into(), extractor)?;
    Ok(bytes)
}
