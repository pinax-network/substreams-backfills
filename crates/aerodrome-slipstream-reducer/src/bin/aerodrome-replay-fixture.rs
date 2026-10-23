//! Offline bounded replay of a digest-pinned artifact. No live producer or resume.
use aerodrome_slipstream_reducer::{
    identity::InputBinding,
    input::InputStream,
    runner::{run_stream, AbortMode, InputCompletion, MemoryLimits, MemoryRunner},
    state::MemoryBackend,
    ReducerError,
};
use backfill_common::{clock, descriptor::ExtractorIdentity};
use serde_json::json;
use sha2::{Digest, Sha256};
use std::{
    cell::RefCell,
    collections::BTreeMap,
    fs,
    io::{self, BufReader, BufWriter, Read, Write},
    path::{Path, PathBuf},
    rc::Rc,
};
type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;

struct HashReader<R> {
    inner: R,
    digest: Rc<RefCell<Sha256>>,
}
impl<R: Read> Read for HashReader<R> {
    fn read(&mut self, output: &mut [u8]) -> io::Result<usize> {
        let n = self.inner.read(output)?;
        self.digest.borrow_mut().update(&output[..n]);
        Ok(n)
    }
}
fn hash(value: &str) -> Result<[u8; 32]> {
    let bytes: [u8; 32] = hex::decode(value)?
        .try_into()
        .map_err(|_| "hash must be 32 bytes")?;
    if hex::encode(bytes) != value {
        return Err("hash must use canonical lowercase hex".into());
    }
    Ok(bytes)
}
fn digest_file(path: &Path) -> Result<String> {
    let mut file = fs::File::open(path)?;
    let mut digest = Sha256::new();
    let mut buffer = [0; 65536];
    loop {
        let n = file.read(&mut buffer)?;
        if n == 0 {
            break;
        }
        digest.update(&buffer[..n]);
    }
    Ok(hex::encode(digest.finalize()))
}
fn write_json_new(path: &Path, value: &serde_json::Value) -> Result<()> {
    let mut file = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)?;
    serde_json::to_writer_pretty(&mut file, value)?;
    file.write_all(b"\n")?;
    file.sync_all()?;
    Ok(())
}
fn replay(options: &BTreeMap<String, String>, output: &Path) -> Result<()> {
    let option = |key: &str| {
        options
            .get(key)
            .map(String::as_str)
            .ok_or_else(|| format!("missing {key}"))
    };
    let descriptor = fs::read(option("--descriptor")?)?;
    let descriptor_sha = hash(option("--descriptor-sha256")?)?;
    let identity: ExtractorIdentity =
        serde_json::from_slice(&fs::read(option("--extractor-identity")?)?)?;
    let binding = InputBinding::new(&descriptor, descriptor_sha, &identity)?;
    let from = option("--from")?.parse::<u64>()?;
    let stop = option("--stop-exclusive")?.parse::<u64>()?;
    if from >= stop || from != identity.initial_block {
        return Err("fixture replay requires a nonempty range from the deployment root".into());
    }
    let parent = hash(option("--expected-parent-hash")?)?;
    let expected_input = hash(option("--input-sha256")?)?;
    let mode = match options
        .get("--error-mode")
        .map(String::as_str)
        .unwrap_or("fail-closed")
    {
        "fail-closed" => AbortMode::FailClosed,
        "emit-non-fatal" => AbortMode::EmitNonFatal,
        _ => return Err("invalid error mode".into()),
    };
    let limit = |key: &str, default: usize| -> Result<usize> {
        Ok(options
            .get(key)
            .map(|v| v.parse())
            .transpose()?
            .unwrap_or(default))
    };
    let limits = MemoryLimits {
        max_blocks: limit("--max-blocks", 100000)?,
        max_candidates: limit("--max-candidates", 2000000)?,
        max_output_payload_bytes: limit("--max-output-bytes", 256 * 1024 * 1024)?,
    };
    let file = fs::File::open(option("--input")?)?;
    if !file.metadata()?.is_file() {
        return Err("offline replay input must be a regular file".into());
    }
    let digest = Rc::new(RefCell::new(Sha256::new()));
    let reader = HashReader {
        inner: BufReader::new(file),
        digest: digest.clone(),
    };
    let input = InputStream::new(reader, binding.clone(), from, stop - 1, parent)?;
    let backend = MemoryBackend::root(&binding, parent)?;
    let runner = MemoryRunner::with_abort_mode(binding, backend, mode)?;
    // For this offline command, the supervisor gate is the exact bytes of the
    // supplied artifact. This is not a live-process exit or producer receipt.
    let completed = run_stream(runner, input, limits, |status| {
        if status != InputCompletion::Complete {
            return Err(ReducerError("input was refused".into()));
        }
        let observed: [u8; 32] = digest.borrow().clone().finalize().into();
        if observed != expected_input {
            return Err(ReducerError("input artifact digest mismatch".into()));
        }
        Ok(())
    })?;
    let frames_part = output.join("frames.bcf1.partial");
    let outcomes_part = output.join("block-outcomes.jsonl.partial");
    let mut frames = BufWriter::new(
        fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&frames_part)?,
    );
    let mut outcomes = BufWriter::new(
        fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&outcomes_part)?,
    );
    let mut handlers = 0usize;
    for block in completed.blocks() {
        clock::write_frame(&mut frames, block.frame())?;
        handlers += block
            .candidates()
            .iter()
            .filter(|c| {
                !matches!(
                    c.outcome,
                    aerodrome_slipstream_reducer::runner::CandidateOutcome::NotMatched
                )
            })
            .count();
        serde_json::to_writer(
            &mut outcomes,
            &json!({"block":block.frame().block_number,"hash":hex::encode(block.frame().block_hash),"candidates":block.candidates()}),
        )?;
        outcomes.write_all(b"\n")?;
    }
    frames.flush()?;
    frames.get_ref().sync_all()?;
    outcomes.flush()?;
    outcomes.get_ref().sync_all()?;
    drop(frames);
    drop(outcomes);
    fs::rename(frames_part, output.join("frames.bcf1"))?;
    fs::rename(outcomes_part, output.join("block-outcomes.jsonl"))?;
    fs::File::open(output)?.sync_all()?;
    let receipt = json!({"contract":"pinax.aerodrome.fixture-replay/v1","from":from,"stop_exclusive":stop,"blocks":completed.blocks().len(),"handlers":handlers,"entities":completed.backend().rows().len(),"sources":completed.backend().sources().len(),"head_hash":hex::encode(completed.boundary().block_hash),"input_sha256":hex::encode(expected_input),"descriptor_sha256":hex::encode(descriptor_sha),"extractor_identity":identity,"frames_sha256":digest_file(&output.join("frames.bcf1"))?,"outcomes_sha256":digest_file(&output.join("block-outcomes.jsonl"))?,"error_mode":format!("{mode:?}"),"production_qualified":false,"producer_receipt":false,"durable_checkpoint":false});
    // Keep even a fully written but unsynced receipt out of the success path.
    // Rename is the final fallible publication step; a crash can lose the marker
    // (this is not a recovery checkpoint), never expose a partial JSON receipt.
    write_json_new(&output.join("complete.json.partial"), &receipt)?;
    fs::File::open(output)?.sync_all()?;
    fs::rename(
        output.join("complete.json.partial"),
        output.join("complete.json"),
    )?;
    println!("{}", receipt);
    Ok(())
}
fn run() -> Result<()> {
    let mut options = BTreeMap::new();
    let mut args = std::env::args().skip(1);
    while let Some(key) = args.next() {
        if ![
            "--input",
            "--input-sha256",
            "--descriptor",
            "--descriptor-sha256",
            "--extractor-identity",
            "--from",
            "--stop-exclusive",
            "--expected-parent-hash",
            "--output",
            "--error-mode",
            "--max-blocks",
            "--max-candidates",
            "--max-output-bytes",
        ]
        .contains(&key.as_str())
        {
            return Err(format!("unknown option {key}").into());
        }
        let value = args.next().ok_or("missing option value")?;
        if options.insert(key, value).is_some() {
            return Err("duplicate option".into());
        }
    }
    let output = PathBuf::from(options.get("--output").ok_or("missing --output")?);
    fs::create_dir(&output)?; // no clobber, including partial failed attempts
    write_json_new(
        &output.join("attempt.json"),
        &json!({"contract":"pinax.aerodrome.fixture-replay-attempt/v1","options":options}),
    )?;
    let result = replay(&options, &output);
    if let Err(error) = &result {
        let _ = write_json_new(
            &output.join("failure.json"),
            &json!({"error":error.to_string(),"complete":false}),
        );
    }
    result
}
fn main() {
    if let Err(error) = run() {
        eprintln!("aerodrome-replay-fixture: {error}");
        std::process::exit(4)
    }
}
