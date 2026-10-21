//! Per-segment BlockChanges compatibility descriptors.
//!
//! `BlockChanges.compatibility_id` is the SHA-256 of the descriptor bytes, so a
//! frame is only interpretable against the exact artifacts that produced it.
//! Each segment gets `segments/<cid>/block-changes-descriptor.json` and a
//! `.sha256` sidecar; the engine's `--block-changes-descriptor` requires that
//! sidecar and refuses a descriptor whose digest disagrees with it.
//!
//! These are **not** fixture descriptors. `fixture_only` is absent, so the
//! engine replays them without `--allow-fixture-descriptor`.
//!
//! What the descriptor binds, beyond the four fields
//! `BlockChangesCompatibility::from_descriptor` itself checks:
//!
//! * the deployment CID, and the CID and SHA-256 of the manifest, schema, every
//!   mapping module and every ABI, taken from the segment's `bundle.lock.json`;
//! * the canonical proto and its prost binding, so a wire-format change
//!   invalidates every frame produced before it;
//! * the Graph Node revision and the PoI version that revision selects for this
//!   deployment's spec version;
//! * the entity types the resolved schema defines.
//!
//! Descriptors are generated rather than hand-written, so they cannot drift from
//! the bundle they describe: `graph-mapping-host build-descriptors`.

use std::path::Path;

use anyhow::{anyhow, Context, Result};
use backfill_common::BlockChangesCompatibility;
use graph::prelude::Logger;
use serde_json::{json, Map, Value};

use crate::bundle::{sha256_hex, SegmentBundle};
use crate::poi;
use crate::runner::GRAPH_NODE_REV;

pub const DESCRIPTOR_FILE: &str = "block-changes-descriptor.json";
pub const DESCRIPTOR_SIDECAR: &str = "block-changes-descriptor.json.sha256";
pub const IN_BAND_DESCRIPTOR_FILE: &str = "block-changes-in-band-descriptor.json";
pub const IN_BAND_DESCRIPTOR_SIDECAR: &str = "block-changes-in-band-descriptor.json.sha256";
pub const SOURCE_CLOSURE_SHA256: &str = env!("MAPPING_HOST_SOURCE_CLOSURE_SHA256");
pub const SOURCE_CLOSURE_INVENTORY: &str =
    include_str!(concat!(env!("OUT_DIR"), "/source-closure.txt"));
const GRAPH_NODE_VERSION: &str = "0.44.0";

/// Read a segment's descriptor, verify its sidecar, and derive the
/// compatibility identity the frames must carry.
pub fn load(segment_dir: &Path) -> Result<(BlockChangesCompatibility, String)> {
    load_named(segment_dir, DESCRIPTOR_FILE, DESCRIPTOR_SIDECAR)
}

pub fn load_in_band(segment_dir: &Path) -> Result<(BlockChangesCompatibility, String)> {
    let (compatibility, digest) = load_named(
        segment_dir,
        IN_BAND_DESCRIPTOR_FILE,
        IN_BAND_DESCRIPTOR_SIDECAR,
    )?;
    let capabilities = compatibility
        .capabilities()
        .context("in-band mode requires descriptor v2")?;
    if capabilities.data_sources.transport
        != backfill_common::descriptor::DataSourceTransport::InBandV1
    {
        anyhow::bail!("in-band descriptor does not enable in_band_v1");
    }
    match &capabilities.producer_contract {
        backfill_common::descriptor::ProducerContract::MappingHostOracle {
            repository,
            source_closure_sha256,
            bundle_lock_sha256,
        } if repository == "pinax-network/substreams-backfills"
            && source_closure_sha256 == SOURCE_CLOSURE_SHA256
            && bundle_lock_sha256 == SegmentBundle::load(segment_dir)?.lock_sha256() => {}
        _ => anyhow::bail!(
            "in-band descriptor does not bind this mapping-host source closure and bundle"
        ),
    }
    Ok((compatibility, digest))
}

fn load_named(
    segment_dir: &Path,
    file: &str,
    sidecar: &str,
) -> Result<(BlockChangesCompatibility, String)> {
    let path = segment_dir.join(file);
    let bytes = std::fs::read(&path)
        .with_context(|| format!("reading BlockChanges descriptor {}", path.display()))?;
    let digest = sha256_hex(&bytes);

    let sidecar_path = segment_dir.join(sidecar);
    let sidecar = std::fs::read_to_string(&sidecar_path)
        .with_context(|| format!("reading descriptor sidecar {}", sidecar_path.display()))?;
    let sidecar = sidecar.trim();
    if sidecar.len() != 64 || !sidecar.bytes().all(|b| b.is_ascii_hexdigit()) {
        return Err(anyhow!(
            "{} is not a bare 64-character SHA-256 digest",
            sidecar_path.display()
        ));
    }
    if sidecar != digest {
        return Err(anyhow!(
            "descriptor digest drift: {} declares {sidecar}, but {} hashes to {digest}",
            sidecar_path.display(),
            path.display()
        ));
    }

    let compatibility = BlockChangesCompatibility::from_descriptor(&bytes)
        .map_err(|error| anyhow!("{}: {error}", path.display()))?;
    if file == IN_BAND_DESCRIPTOR_FILE {
        let descriptor: Value = serde_json::from_slice(&bytes)?;
        anyhow::ensure!(
            descriptor["message_type"] == "proto:pinax.graph.backfill.v2.BlockChanges",
            "in-band descriptor message_type differs from extended envelope"
        );
    }
    Ok((compatibility, digest))
}

/// Build the descriptor for one bundle and write it with its sidecar.
pub async fn write(segment_dir: &Path, repo_root: &Path, logger: &Logger) -> Result<String> {
    write_mode(segment_dir, repo_root, logger, false).await
}

pub async fn write_in_band(
    segment_dir: &Path,
    repo_root: &Path,
    logger: &Logger,
) -> Result<String> {
    write_mode(segment_dir, repo_root, logger, true).await
}

async fn write_mode(
    segment_dir: &Path,
    repo_root: &Path,
    logger: &Logger,
    in_band: bool,
) -> Result<String> {
    if in_band {
        verify_compiled_source_closure(repo_root)?;
    }
    let bundle = SegmentBundle::load(segment_dir)?;
    let manifest = bundle.manifest(logger).await?;
    let lock = bundle.lock();

    let spec_version = manifest.spec_version.clone();
    let poi_version = match poi::version_for_spec(&spec_version) {
        graph::components::subgraph::ProofOfIndexingVersion::Fast => "fast",
        graph::components::subgraph::ProofOfIndexingVersion::Legacy => "legacy",
    };
    let policy = if lock
        .features
        .iter()
        .any(|feature| feature == "nonFatalErrors")
    {
        "non_fatal"
    } else {
        "fatal"
    };

    let artifact = |predicate: &dyn Fn(&str) -> bool| -> Vec<Value> {
        let mut out: Vec<Value> = lock
            .files
            .iter()
            .filter(|file| predicate(&file.path))
            .map(|file| {
                json!({
                    "path": format!("mapping-host/segments/{}/{}", lock.deployment, file.path),
                    "cid": file.cid,
                    "sha256": file.sha256,
                    "bytes": file.bytes,
                })
            })
            .collect();
        out.sort_by(|a, b| a["path"].as_str().cmp(&b["path"].as_str()));
        out
    };

    let proto_path = repo_root.join("common/proto/block_changes.proto");
    let binding_path = repo_root.join("common/src/pb/pinax.graph.backfill.v1.rs");

    let mut entity_types: Vec<String> = manifest
        .schema
        .entity_types()
        .iter()
        .map(|entity_type| entity_type.typename().to_string())
        .collect();
    entity_types.sort();
    entity_types.dedup();

    let mut root = Map::new();
    root.insert(
        "adapter".into(),
        json!(format!(
            "pinax-network/substreams-backfills::mapping-host/segments/{}",
            lock.deployment
        )),
    );
    root.insert(
        "artifacts".into(),
        json!({
            "abis": artifact(&|path| path.starts_with("abis/")),
            "block_changes_proto": digest_of(&proto_path, "common/proto/block_changes.proto")?,
            "mappings": artifact(&|path| path.starts_with("mappings/")),
            "manifest": artifact(&|path| path == "manifest.yaml").first().cloned()
                .ok_or_else(|| anyhow!("bundle has no manifest.yaml"))?,
            "prost_binding": digest_of(&binding_path, "common/src/pb/pinax.graph.backfill.v1.rs")?,
            "schema": artifact(&|path| path == "schema.graphql").first().cloned()
                .ok_or_else(|| anyhow!("bundle has no schema.graphql"))?,
        }),
    );
    root.insert(
        "contract".into(),
        json!(backfill_common::BLOCK_CHANGES_V1_CONTRACT),
    );
    root.insert("deployment".into(), json!(lock.deployment));
    root.insert("descriptor_version".into(), json!(1));
    root.insert("deterministic_error_policy".into(), json!(policy));
    root.insert(
        "expected_poi_causality_region".into(),
        json!(format!("ethereum/{}", lock.network)),
    );
    root.insert(
        "graph_node".into(),
        json!({
            "commit": GRAPH_NODE_REV,
            "poi_version": poi_version,
            "version": GRAPH_NODE_VERSION,
        }),
    );
    root.insert("manifest_features".into(), json!(lock.features));
    root.insert("network".into(), json!(lock.network));
    root.insert(
        "producer".into(),
        json!("pinax-network/substreams-backfills"),
    );
    root.insert("spec_version".into(), json!(spec_version.to_string()));
    root.insert(
        "storage_profile".into(),
        json!({
            "entity_types": entity_types,
            "id": format!("deployed-subgraph-schema/{}", lock.deployment),
            "mutability": "deployed",
        }),
    );

    let (file, sidecar) = if in_band {
        root.insert("descriptor_version".into(), json!(2));
        root.insert(
            "message_type".into(),
            json!("proto:pinax.graph.backfill.v2.BlockChanges"),
        );
        let start = manifest
            .start_blocks()
            .into_iter()
            .min()
            .context("manifest has no start block")?;
        if start < 0 {
            anyhow::bail!("negative manifest start block");
        }
        root.insert("start_block".into(), json!(start));
        root.insert(
            "storage_profile".into(),
            json!({"entity_types": root["storage_profile"]["entity_types"].clone()}),
        );
        let mut templates = Vec::new();
        for template in &manifest.templates {
            templates.push(json!({"name": template.name(), "manifest_idx": template.manifest_idx(), "param": "address20"}));
        }
        templates.sort_by_key(|t| t["manifest_idx"].as_u64());
        root.insert(
            "data_sources".into(),
            json!({"transport":"in_band_v1", "templates": templates}),
        );
        root.insert(
            "entity_retention".into(),
            serde_json::to_value(backfill_common::descriptor::RetentionPolicy::default())?,
        );
        root.insert("producer_contract".into(), json!({"kind":"mapping_host_oracle", "repository":"pinax-network/substreams-backfills", "source_closure_sha256":SOURCE_CLOSURE_SHA256, "bundle_lock_sha256":bundle.lock_sha256()}));
        let artifacts = root.get_mut("artifacts").unwrap().as_object_mut().unwrap();
        artifacts.insert(
            "in_band_proto".into(),
            digest_of(
                &repo_root.join("common/proto/block_changes_in_band.proto"),
                "common/proto/block_changes_in_band.proto",
            )?,
        );
        artifacts.insert(
            "in_band_binding".into(),
            digest_of(
                &repo_root.join("common/src/pb/pinax.graph.backfill.v2.rs"),
                "common/src/pb/pinax.graph.backfill.v2.rs",
            )?,
        );
        (IN_BAND_DESCRIPTOR_FILE, IN_BAND_DESCRIPTOR_SIDECAR)
    } else {
        (DESCRIPTOR_FILE, DESCRIPTOR_SIDECAR)
    };

    // `serde_json::Map` is a `BTreeMap` here, so keys serialise sorted and the
    // digest is stable.
    let mut json_text = serde_json::to_string_pretty(&Value::Object(root))?;
    json_text.push('\n');
    let digest = sha256_hex(json_text.as_bytes());

    // Refuse an invalid descriptor before replacing either output.
    BlockChangesCompatibility::from_descriptor(json_text.as_bytes())
        .map_err(|error| anyhow!("generated descriptor is invalid: {error}"))?;
    std::fs::write(segment_dir.join(file), &json_text)?;
    std::fs::write(segment_dir.join(sidecar), format!("{digest}\n"))?;
    Ok(digest)
}

fn digest_of(path: &Path, label: &str) -> Result<Value> {
    let bytes = std::fs::read(path)
        .with_context(|| format!("reading {} for the descriptor", path.display()))?;
    Ok(json!({
        "path": label,
        "sha256": sha256_hex(&bytes),
        "bytes": bytes.len(),
    }))
}

/// Refuse mixing a compiled producer identity with artifacts from a different
/// checkout. Descriptor generation is a source operation; image loading does
/// not need the source tree and checks the compiled closure plus bundle lock.
pub fn verify_compiled_source_closure(repo_root: &Path) -> Result<()> {
    use std::collections::BTreeSet;
    fn collect(root: &Path, path: &Path, names: &mut BTreeSet<String>) -> Result<()> {
        let meta = std::fs::symlink_metadata(path)?;
        anyhow::ensure!(
            !meta.file_type().is_symlink(),
            "source closure refuses symlinks"
        );
        if meta.is_dir() {
            for entry in std::fs::read_dir(path)? {
                collect(root, &entry?.path(), names)?;
            }
        } else {
            anyhow::ensure!(meta.is_file(), "source closure requires regular files");
            names.insert(
                path.strip_prefix(root)?
                    .to_str()
                    .context("non-UTF-8 source path")?
                    .to_string(),
            );
        }
        Ok(())
    }
    let mut expected = BTreeSet::new();
    for line in SOURCE_CLOSURE_INVENTORY.lines() {
        let mut parts = line.splitn(3, "  ");
        let digest = parts.next().context("compiled source inventory digest")?;
        let size: usize = parts
            .next()
            .context("compiled source inventory size")?
            .parse()?;
        let path = parts.next().context("compiled source inventory path")?;
        let bytes = std::fs::read(repo_root.join(path))
            .with_context(|| format!("reading compiled source closure input {path}"))?;
        anyhow::ensure!(
            bytes.len() == size && sha256_hex(&bytes) == digest,
            "source closure differs from compiled producer at {path}"
        );
        expected.insert(path.to_owned());
    }
    let mut actual = BTreeSet::new();
    for path in [
        "Cargo.toml",
        "common/Cargo.toml",
        "common/src",
        "common/proto",
        "mapping-host/Cargo.toml",
        "mapping-host/Cargo.lock",
        "mapping-host/build.rs",
        "mapping-host/src",
        "mapping-host/vendor",
    ] {
        collect(repo_root, &repo_root.join(path), &mut actual)?;
    }
    anyhow::ensure!(
        actual == expected,
        "source closure file set differs from compiled producer"
    );
    Ok(())
}
