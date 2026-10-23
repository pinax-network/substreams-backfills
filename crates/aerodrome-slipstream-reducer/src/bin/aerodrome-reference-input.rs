//! Offline development M1 reference input. No RPC or live producer is started.
use aerodrome_slipstream_reducer::{
    reference::{capture::CaptureSet, Cassette, ReferenceExtractor},
    ReducerError,
};
use backfill_common::clock;
use serde_json::json;
use sha2::{Digest, Sha256};
use std::{
    fs::{self, OpenOptions},
    io::{BufWriter, Write},
    path::{Path, PathBuf},
    time::Instant,
};
fn run() -> Result<(), Box<dyn std::error::Error>> {
    let args = std::env::args().skip(1).collect::<Vec<_>>();
    if args.len() < 7 {
        return Err("usage: aerodrome-reference-input NEW_OUTPUT_DIRECTORY CASSETTE_JSON CASSETTE_SHA256 CAPTURE_SOURCE_COMMIT CAPTURE_BINARY_SHA256 REFERENCE_SOURCE_COMMIT CAPTURE_DIR...".into());
    }
    let source = &args[5];
    if source.len() != 40 || !source.bytes().all(|b| b.is_ascii_hexdigit()) {
        return Err("invalid reference source commit".into());
    }
    let paths = args[6..].iter().map(PathBuf::from).collect::<Vec<_>>();
    let captures = CaptureSet::open(&paths, &args[3], &args[4])?;
    let cassette = Cassette::from_json(&fs::read(&args[1])?)?;
    if cassette.sha256() != args[2] {
        return Err("cassette digest mismatch".into());
    }
    let mut reference = ReferenceExtractor::new(cassette, captures.to_exclusive)?;
    let mut receipt = json!({"schema":"aerodrome-reference-input/v1","scope":"development-native-M1; not live Substreams WASM","source_commit":source,"binary_sha256":hex::encode(Sha256::digest(fs::read(std::env::current_exe()?)?)),"from":captures.from,"to_exclusive":captures.to_exclusive,"blocks":captures.to_exclusive-captures.from,"raw_bcf1_sha256":captures.raw_sha256,"raw_bcf1_bytes":captures.raw_bytes,"capture_receipts":captures.receipts,"cassette_sha256":reference.cassette_sha256()});
    let root = PathBuf::from(&args[0]);
    fs::create_dir(&root)?;
    let create = |name: &str| {
        OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(root.join(name))
    };
    let mut output = BufWriter::new(create("extractor.bcf1")?);
    let mut digest = Sha256::new();
    let mut bytes = 0_u64;
    let mut progress = Instant::now();
    captures.for_each(|frame| {
        let number = frame.block_number;
        let frame = reference
            .process(frame)
            .map_err(|e| ReducerError(format!("block {number}: {e}")))?;
        let mut encoded = Vec::new();
        clock::write_frame(&mut encoded, &frame).map_err(|e| ReducerError(e.to_string()))?;
        digest.update(&encoded);
        bytes += encoded.len() as u64;
        output
            .write_all(&encoded)
            .map_err(|e| ReducerError(e.to_string()))?;
        if progress.elapsed().as_secs() >= 30 {
            eprintln!("reference extracted through {number}");
            progress = Instant::now();
        }
        Ok(())
    })?;
    reference.finish()?;
    output.flush()?;
    output.get_ref().sync_all()?;
    receipt["extractor_bcf1_sha256"] = json!(hex::encode(digest.finalize()));
    receipt["extractor_bcf1_bytes"] = json!(bytes);
    receipt["compared_cassette_calls"] = json!(reference.compared_calls());
    receipt["all_capture_receipts_and_eof_verified"] = json!(true);
    publish_complete(&root, &receipt)?;
    eprintln!(
        "reference input complete: {} cassette calls compared",
        reference.compared_calls()
    );
    Ok(())
}
fn publish_complete(
    root: &Path,
    receipt: &impl serde::Serialize,
) -> Result<(), Box<dyn std::error::Error>> {
    // Persist the raw output directory before any completion marker exists.
    fs::File::open(root)?.sync_all()?;
    let partial = root.join("complete.json.partial");
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&partial)?;
    serde_json::to_writer_pretty(&mut file, receipt)?;
    file.write_all(b"\n")?;
    file.flush()?;
    file.sync_all()?;
    fs::File::open(root)?.sync_all()?;
    // Publication is the final fallible operation. A partial write/sync error
    // leaves only .partial, which is never a success marker.
    fs::rename(partial, root.join("complete.json"))?;
    Ok(())
}

fn main() {
    if let Err(e) = run() {
        eprintln!("reference input refused: {e}");
        std::process::exit(4)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    struct Failed;
    impl serde::Serialize for Failed {
        fn serialize<S: serde::Serializer>(&self, _: S) -> Result<S::Ok, S::Error> {
            Err(serde::ser::Error::custom(
                "injected receipt serialization failure",
            ))
        }
    }
    #[test]
    fn failed_receipt_write_never_publishes_completion() {
        let dir = tempfile::tempdir().unwrap();
        assert!(publish_complete(dir.path(), &Failed).is_err());
        assert!(!dir.path().join("complete.json").exists());
        assert!(dir.path().join("complete.json.partial").exists());
        assert!(publish_complete(dir.path(), &json!({"complete":true})).is_err());
        assert!(!dir.path().join("complete.json").exists());
    }
    #[test]
    fn complete_receipt_appears_only_after_successful_publication() {
        let dir = tempfile::tempdir().unwrap();
        let receipt = json!({"complete":true});
        publish_complete(dir.path(), &receipt).unwrap();
        assert!(!dir.path().join("complete.json.partial").exists());
        assert_eq!(
            serde_json::from_slice::<serde_json::Value>(
                &fs::read(dir.path().join("complete.json")).unwrap()
            )
            .unwrap(),
            receipt
        );
    }
}
