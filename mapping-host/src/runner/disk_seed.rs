use super::*;
use crate::{
    checkpoint::{
        CassettePin, CheckpointHeader, CheckpointLine, CheckpointTotals, CHECKPOINT_SCHEMA,
    },
    disk_store::{DiskStore, OverlayLimits},
};
use backfill_common::{
    seed_manifest::Binding,
    state_snapshot::{Limits, StoredEntity},
};
use std::io::{Read, Write};
use std::os::unix::fs::OpenOptionsExt;

impl SegmentHost {
    /// Load the exact deployed Aerodrome bundle over a complete, externally
    /// pinned physical seed. The immutable base stays open for this whole host;
    /// callers must not cold-reset it between report partitions.
    #[allow(clippy::too_many_arguments)]
    pub async fn load_disk_seed<R: Read>(
        config: SegmentHostConfig<'_>,
        database: &Path,
        input: R,
        manifest: &[u8],
        manifest_sha256: &str,
        expected: &Binding,
        overlay_limits: OverlayLimits,
        limits: DiskRunLimits,
        snapshot_limits: Limits,
    ) -> Result<Self> {
        const AERODROME: &str = "QmasYjypV6nTLp4iNH4Vjf7fksRNxAkAskqDdKf2DCsQkV";
        if expected.snapshot.deployment != AERODROME || expected.snapshot.network != "base" {
            bail!("disk oracle currently admits only the pinned Aerodrome Base deployment");
        }
        if limits.sources == 0
            || limits.cache_keys == 0
            || limits.blocks == 0
            || limits.blocks > 1000
        {
            bail!("disk oracle requires positive budgets and at most 1000 blocks");
        }
        // Replay cassettes are bounded before the existing loader parses them.
        // Recording needs its own bounded admission and is deliberately refused.
        if config.record {
            bail!("disk oracle requires a pre-recorded bounded cassette");
        }
        let file = std::fs::OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
            .open(config.cassette_path)?;
        if !file.metadata()?.is_file() {
            bail!("disk oracle cassette requires a regular file");
        }
        let mut cassette_bytes = Vec::new();
        file.take(64 * 1024 * 1024 + 1)
            .read_to_end(&mut cassette_bytes)?;
        let cassette = Arc::new(Cassette::replay_bytes(&cassette_bytes)?);
        let bundle = SegmentBundle::load(config.bundle_dir)?;
        let lock = bundle.lock();
        for (path, want) in [
            ("schema.graphql", &expected.schema_sha256),
            ("manifest.yaml", &expected.raw_manifest_sha256),
        ] {
            if lock
                .files
                .iter()
                .find(|f| f.path == path)
                .map(|f| &f.sha256)
                != Some(want)
            {
                bail!("disk seed {path} differs from exact deployed bundle");
            }
        }
        let mut host = Self::load_mode(config, true, Some(cassette)).await?;
        if expected.spec_version != host.spec_version
            || expected.start_block != host.bounds.start as u64
        {
            bail!("disk seed manifest specification/start differs from deployed bundle");
        }
        let disk = DiskStore::import(
            database,
            input,
            manifest,
            manifest_sha256,
            expected,
            host.store.schema().clone(),
            overlay_limits,
            snapshot_limits,
        )?;
        if disk.header().sources.rows.len() > limits.sources {
            bail!("seed exceeds dynamic source budget");
        }
        let mut sources = Vec::with_capacity(disk.header().sources.rows.len());
        for source in &disk.header().sources.rows {
            let template = host
                .templates
                .iter()
                .find(|t| t.manifest_idx() as i32 == source.manifest_idx)
                .ok_or_else(|| anyhow!("seed names unknown template"))?;
            if source.param.len() != 20 {
                bail!("Aerodrome source parameter must contain exactly one address");
            }
            sources.push(CheckpointDataSource {
                template: template.name().to_string(),
                manifest_idx: source.manifest_idx.try_into()?,
                params: vec![format!("0x{}", hex::encode(&source.param))],
                context: None,
                creation_block: source.creation_block,
            });
        }
        if let Some(active) = &disk.header().poi.active {
            if active.id != host.causality_region
                || disk.header().poi.region_digest.as_ref() != Some(&active.digest)
            {
                bail!("seed PoI causality region/digest differs");
            }
            let schema = disk.schema();
            let key = schema.poi_type().parse_key(active.id.as_str())?;
            let mut entity = schema.make_entity(vec![
                ("id".into(), Value::String(active.id.clone())),
                (
                    schema.poi_digest(),
                    Value::Bytes(active.digest.clone().into()),
                ),
            ])?;
            entity
                .set_vid(active.vid)
                .map_err(|e| anyhow!("seed PoI VID: {e:?}"))?;
            disk.insert_poi(key, entity)?;
        }
        host.disk_boundary = Some((
            disk.header().boundary.block_number.try_into()?,
            format!("0x{}", hex::encode(disk.header().boundary.block_hash)),
        ));
        host.disk_limits = Some(limits);
        host.disk_cassette_sha256 = Some(crate::bundle::sha256_hex(&cassette_bytes));
        host.store = Arc::new(HostStore::Disk(Box::new(disk)));
        host.restore_sources(&sources)?;
        // The cold cache is empty by construction. No invented present/absent
        // keys, and the ordinary Graph Node LFU is retained across all blocks.
        Ok(host)
    }

    /// Write the initial full cold checkpoint in the existing v2 wire format,
    /// with bounded per-record encoding and no collected historical row Vec.
    pub fn write_cold_seed_checkpoint(&self, sink: &mut impl Write) -> Result<()> {
        if self.blocks_processed != 0 || self.disk_failed {
            bail!("cold seed checkpoint is available only before replay");
        }
        let HostStore::Disk(disk) = self.store.as_ref() else {
            bail!("streamed cold checkpoint requires a disk seed");
        };
        let header = disk.header();
        let mut poi_row = header
            .poi
            .active
            .as_ref()
            .map(|active| {
                let key = disk.schema().poi_type().parse_key(active.id.as_str())?;
                let entity = disk
                    .lookup(&key)?
                    .ok_or_else(|| anyhow!("seed PoI row missing"))?;
                let wire = convert_key(&key);
                checkpoint_row(
                    &wire,
                    &StoredEntity {
                        vid: active.vid,
                        block_range_start: active.block_range_start,
                        fields: convert_entity(&entity),
                    },
                )
            })
            .transpose()?;
        let poi = if let Some(active) = &header.poi.active {
            let block = header.boundary.block_number.try_into()?;
            let ptr = BlockPtr::from((header.boundary.block_hash.to_vec(), block));
            let finished = poi::finish(
                &ptr,
                &self.deployment,
                self.poi_version,
                &BTreeMap::from([(active.id.clone(), active.digest.clone())]),
            );
            Some(StorePoi {
                block,
                version: self.poi_version_name().into(),
                causality_regions: finished.causality_regions,
                public_digest: finished.public_digest,
            })
        } else {
            None
        };
        let checkpoint = CheckpointHeader {
            schema: CHECKPOINT_SCHEMA.into(),
            identity: self.checkpoint_identity(),
            cassette: CassettePin::Exact {
                sha256: self
                    .disk_cassette_sha256
                    .clone()
                    .ok_or_else(|| anyhow!("verified disk cassette pin missing"))?,
            },
            boundary: CheckpointBoundary {
                block: header.boundary.block_number.try_into()?,
                block_hash: format!("0x{}", hex::encode(header.boundary.block_hash)),
                source: "verified BCGSNAP1 seed".into(),
                chunk_from: None,
                chunk_to: None,
                blocks_in_chunk: 0,
                blocks_total: 0,
                chunk_index: 0,
                previous_checkpoint_sha256: None,
            },
            poi,
            totals: CheckpointTotals {
                dynamic_data_sources: self.dynamic.len(),
                rows: header.records.try_into()?,
                poi_rows: usize::from(poi_row.is_some()),
                fields: disk
                    .seed_fields()
                    .checked_add(poi_row.as_ref().map_or(0, |r| r.fields.len()))
                    .ok_or_else(|| anyhow!("seed field count overflow"))?,
                ..CheckpointTotals::default()
            },
            counts_by_type: disk.counts_by_type(),
        };
        crate::disk_oracle::write_json_line(sink, &checkpoint)?;
        for source in &self.dynamic {
            crate::disk_oracle::write_json_line(sink, &CheckpointLine::DataSource(source.clone()))?;
        }
        disk.visit_seed(|key, value| {
            let row = checkpoint_row(key, value)?;
            if poi_row
                .as_ref()
                .is_some_and(|poi| poi.entity_type < row.entity_type)
            {
                write_row(sink, poi_row.take().unwrap())?;
            }
            write_row(sink, row)
        })?;
        if let Some(row) = poi_row {
            write_row(sink, row)?;
        }
        sink.flush()?;
        Ok(())
    }
}

fn checkpoint_row(key: &pb::EntityKey, value: &StoredEntity) -> Result<CheckpointRow> {
    let Some(pb::entity_id::Value::String(id)) = key.id.as_ref().and_then(|id| id.value.as_ref())
    else {
        bail!("cold oracle checkpoint requires a String ID");
    };
    Ok(CheckpointRow {
        entity_type: key.entity_type.clone(),
        id: crate::store_state::StoreEntityId::String(id.clone()),
        storage_causality_region: key.storage_causality_region,
        vid: value.vid,
        cached: false,
        fields: value
            .fields
            .iter()
            .map(|field| {
                Ok((
                    field.name.clone(),
                    StoreValue::from_wire(
                        field
                            .value
                            .as_ref()
                            .ok_or_else(|| anyhow!("seed field value missing"))?,
                    )?,
                ))
            })
            .collect::<Result<_>>()?,
    })
}
fn write_row(sink: &mut impl Write, row: CheckpointRow) -> Result<()> {
    crate::disk_oracle::write_json_line(sink, &CheckpointLine::Row(row))
}
