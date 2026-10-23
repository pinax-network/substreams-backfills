//! Compare a fresh in-band oracle range with retained v1 oracle evidence.
//! Usage: legacy-descriptor in-band-descriptor old.bcf1 new.bcf1
//!        old.report.jsonl new.report.jsonl new.checkpoint.jsonl [old.checkpoint.jsonl]
//! The range must begin with an empty dynamic-source inventory (R0 and R1 do).
use anyhow::{ensure, Context, Result};
use backfill_common::{
    clock::{read_frame, ObservedRange, MAX_PAYLOAD_LEN},
    decode_canonical_block_changes, decode_canonical_in_band_block_changes,
    dynamic_sources::DataSource,
    dynamic_sources_v2::{Creation, FilePin, SourceOrder},
    encode_canonical_in_band_block_changes, BlockChangesCompatibility,
};
use graph_mapping_host::{checkpoint::HostCheckpoint, report::RunHeader};
use serde_json::{json, Value};
use std::{
    fs::File,
    io::{BufRead, BufReader},
    path::Path,
};

fn line(reader: &mut impl BufRead) -> Result<Option<Value>> {
    let mut s = String::new();
    if reader.read_line(&mut s)? == 0 {
        return Ok(None);
    }
    ensure!(s.ends_with('\n'), "truncated report line");
    Ok(Some(serde_json::from_str(&s)?))
}

fn main() -> Result<()> {
    let paths = std::env::args().skip(1).collect::<Vec<_>>();
    ensure!(
        (7..=8).contains(&paths.len()),
        "expected seven or eight paths; see example source usage"
    );
    let legacy = BlockChangesCompatibility::from_descriptor(&std::fs::read(&paths[0])?)?;
    let extended = BlockChangesCompatibility::from_descriptor(&std::fs::read(&paths[1])?)?;
    let descriptor: Value = serde_json::from_slice(&std::fs::read(&paths[1])?)?;
    ensure!(
        descriptor["data_sources"]["transport"] == "in_band_v1",
        "not an in-band descriptor"
    );
    let mut old = BufReader::new(File::open(&paths[2])?);
    let mut new = BufReader::new(File::open(&paths[3])?);
    let mut old_reports = BufReader::new(File::open(&paths[4])?);
    let mut new_reports = BufReader::new(File::open(&paths[5])?);
    let old_header: RunHeader =
        serde_json::from_value(line(&mut old_reports)?.context("missing old header")?)?;
    let new_header: RunHeader =
        serde_json::from_value(line(&mut new_reports)?.context("missing new header")?)?;
    ensure!(old_header == new_header, "report headers differ");
    ensure!(
        descriptor["deployment"] == new_header.deployment
            && descriptor["network"] == new_header.network,
        "report/descriptor deployment mismatch"
    );
    let from = u64::try_from(new_header.from.context("missing from")?)?;
    let to = u64::try_from(new_header.to.context("missing to")?)?;
    let mut old_range = ObservedRange::new(from, to)?;
    let mut new_range = ObservedRange::new(from, to)?;
    let mut creations = Vec::new();
    let mut order = SourceOrder::empty();
    let mut count = 0u64;
    let mut last_hash = None;
    let mut last_poi = None;
    while let Some(new_frame) = read_frame(&mut new, MAX_PAYLOAD_LEN)? {
        new_range.accept(&new_frame)?;
        let old_frame =
            read_frame(&mut old, MAX_PAYLOAD_LEN)?.context("legacy stream ended early")?;
        old_range.accept(&old_frame)?;
        ensure!(
            old_frame.block_hash == new_frame.block_hash,
            "clock hash differs at {}",
            new_frame.block_number
        );
        let old_changes = decode_canonical_block_changes(&old_frame.payload, &legacy)?;
        let mut changes = decode_canonical_in_band_block_changes(&new_frame.payload, &extended)?;
        ensure!(
            old_changes.block_number == old_frame.block_number
                && old_changes.block_hash == old_frame.block_hash,
            "legacy payload/clock identity differs"
        );
        ensure!(
            changes.block_number == new_frame.block_number
                && changes.block_hash == new_frame.block_hash,
            "in-band payload/clock identity differs"
        );
        for creation in std::mem::take(&mut changes.created_data_sources) {
            let source = DataSource {
                creation_block: i32::try_from(changes.block_number)?,
                manifest_idx: i32::try_from(creation.manifest_idx)?,
                causality_region: 0,
                param: hex::encode(creation.param),
                context: None,
                done_at: None,
            };
            order
                .append(&Creation {
                    ordinal: order.count,
                    source: source.clone(),
                })
                .map_err(anyhow::Error::msg)?;
            creations.push((creation.template, source));
        }
        changes.compatibility_id = legacy.to_vec();
        ensure!(
            encode_canonical_in_band_block_changes(&changes, &legacy)? == old_frame.payload,
            "v1 projection differs at {}",
            new_frame.block_number
        );
        let mut old_report = line(&mut old_reports)?.context("legacy report ended early")?;
        let mut new_report = line(&mut new_reports)?.context("in-band report ended early")?;
        ensure!(
            old_report["number"] == new_frame.block_number
                && new_report["number"] == new_frame.block_number,
            "report block number mismatch"
        );
        for (report, payload) in [
            (&old_report, &old_frame.payload),
            (&new_report, &new_frame.payload),
        ] {
            let pin = FilePin::for_bytes(payload);
            ensure!(
                report["block_changes"]["frame_sha256"] == pin.sha256
                    && report["block_changes"]["frame_bytes"] == pin.bytes,
                "report does not bind payload"
            );
        }
        last_hash = Some(format!("0x{}", hex::encode(new_frame.block_hash)));
        if !new_report["poi"].is_null() {
            last_poi = Some(new_report["poi"].clone());
        }
        // Only the encoded envelope length and digest change. Every other
        // report field, including handler grouping, entity modifications and
        // public PoI, must be exactly equal as structured JSON.
        for report in [&mut old_report, &mut new_report] {
            let summary = report["block_changes"]
                .as_object_mut()
                .context("missing frame summary")?;
            summary.remove("frame_sha256");
            summary.remove("frame_bytes");
        }
        ensure!(
            old_report == new_report,
            "semantic report differs at {}",
            new_frame.block_number
        );
        count += 1;
    }
    ensure!(
        read_frame(&mut old, MAX_PAYLOAD_LEN)?.is_none(),
        "extra legacy frame"
    );
    ensure!(
        line(&mut old_reports)?.is_none() && line(&mut new_reports)?.is_none(),
        "extra report line"
    );
    old_range.finish()?;
    new_range.finish()?;
    let (checkpoint, checkpoint_sha256) = HostCheckpoint::read(Path::new(&paths[6]))?;
    ensure!(
        checkpoint.header.boundary.block as u64 + 1 == to
            && checkpoint.header.boundary.chunk_from == Some(from as i32)
            && checkpoint.header.boundary.chunk_to == Some(to as i32)
            && checkpoint.header.boundary.blocks_in_chunk as u64 == count,
        "checkpoint range differs"
    );
    ensure!(
        Some(&checkpoint.header.boundary.block_hash) == last_hash.as_ref(),
        "checkpoint boundary hash differs"
    );
    ensure!(
        checkpoint.header.identity.descriptor_sha256 == hex::encode(extended.to_vec()),
        "checkpoint descriptor differs"
    );
    ensure!(
        checkpoint.data_sources.len() == creations.len(),
        "checkpoint source inventory differs (range must start with empty source inventory)"
    );
    for (stored, (template, source)) in checkpoint.data_sources.iter().zip(&creations) {
        ensure!(
            stored.template == *template
                && stored.manifest_idx as i32 == source.manifest_idx
                && stored.creation_block == source.creation_block
                && stored.context.is_none()
                && stored.params == vec![format!("0x{}", source.param)],
            "checkpoint source order/content differs"
        );
    }
    if let Some(path) = paths.get(7) {
        let (old_checkpoint, _) = HostCheckpoint::read(Path::new(path))?;
        ensure!(
            old_checkpoint.rows == checkpoint.rows,
            "closing materialized entity/PoI rows differ"
        );
        ensure!(
            old_checkpoint.cached_absent == checkpoint.cached_absent,
            "closing absent cache differs"
        );
        ensure!(
            old_checkpoint.data_sources == checkpoint.data_sources,
            "closing legacy runtime source inventory differs"
        );
        ensure!(
            old_checkpoint.header.poi == checkpoint.header.poi
                && old_checkpoint.header.counts_by_type == checkpoint.header.counts_by_type,
            "closing PoI/counts differ"
        );
    }
    let pins = paths
        .iter()
        .map(|p| FilePin::read(Path::new(p)).map_err(anyhow::Error::msg))
        .collect::<Result<Vec<_>>>()?;
    println!(
        "{}",
        serde_json::to_string_pretty(
            &json!({"schema":"pinax.mapping-host.in-band-oracle-comparison/v1", "claim":"oracle v1 projection and semantic replay equivalence; no deployed indexer parity claim", "range":{"from":from,"to":to,"blocks":count}, "compatibility_id":hex::encode(extended.to_vec()), "producer_contract":descriptor["producer_contract"], "source_order":order, "legacy_checkpoint_state_compared":paths.len() == 8, "accepted_creations":creations.iter().map(|(template,source)| json!({"template":template,"source":source})).collect::<Vec<_>>(), "last_poi":last_poi, "checkpoint_sha256":checkpoint_sha256, "input_pins_in_argument_order":pins})
        )?
    );
    Ok(())
}
