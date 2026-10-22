//! Local digest-pinned durable replay. This is not the live producer/v1 driver
//! and never manufactures a successful subprocess receipt for the engine.
use aerodrome_slipstream_reducer::{
    durable::{run_segment, DurableStore},
    identity::InputBinding,
    input::InputStream,
    runner::{AbortMode, InputCompletion, Runner},
    ReducerError,
};
use backfill_common::{
    descriptor::ExtractorIdentity, producer_checkpoint::Binding, state_snapshot::Boundary,
};
use sha2::{Digest, Sha256};
use std::{
    cell::RefCell,
    collections::BTreeMap,
    fs,
    io::{self, BufReader, Read},
    path::Path,
    rc::Rc,
};
type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;
fn hash(value: &str) -> Result<[u8; 32]> {
    let bytes: [u8; 32] = hex::decode(value)?
        .try_into()
        .map_err(|_| "hash must be 32 bytes")?;
    if hex::encode(bytes) != value {
        return Err("hash must use lowercase hex".into());
    }
    Ok(bytes)
}
fn file_hash(path: &Path) -> Result<String> {
    let mut file = fs::File::open(path)?;
    let mut h = Sha256::new();
    let mut buffer = [0; 65536];
    loop {
        let n = file.read(&mut buffer)?;
        if n == 0 {
            break;
        }
        h.update(&buffer[..n]);
    }
    Ok(hex::encode(h.finalize()))
}
struct HashReader<R> {
    input: R,
    hash: Rc<RefCell<Sha256>>,
}
impl<R: Read> Read for HashReader<R> {
    fn read(&mut self, b: &mut [u8]) -> io::Result<usize> {
        let n = self.input.read(b)?;
        self.hash.borrow_mut().update(&b[..n]);
        Ok(n)
    }
}
fn run() -> Result<()> {
    let mut args = std::env::args().skip(1);
    let command = args.next().ok_or("expected init|inspect|reduce|rewind")?;
    let common = [
        "--state-dir",
        "--descriptor",
        "--descriptor-sha256",
        "--extractor-identity",
        "--producer-binding",
        "--cache-mib",
    ];
    let specific: &[&str] = match command.as_str() {
        "init" => &["--engine-lineage"],
        "inspect" => &[],
        "reduce" => &[
            "--input",
            "--input-sha256",
            "--from",
            "--stop-exclusive",
            "--expected-parent-hash",
            "--expected-head-block",
            "--expected-head-hash",
            "--expected-reducer-lineage",
            "--engine-lineage",
            "--output",
            "--error-mode",
            "--full-state-digest",
        ],
        "rewind" => &["--expected-checkpoint-sha256", "--to-block", "--to-hash"],
        _ => return Err("expected init|inspect|reduce|rewind".into()),
    };
    let mut options = BTreeMap::new();
    while let Some(key) = args.next() {
        if !common.contains(&key.as_str()) && !specific.contains(&key.as_str()) {
            return Err(format!("unknown option {key}").into());
        }
        let value = args.next().ok_or("missing option value")?;
        if options.insert(key, value).is_some() {
            return Err("duplicate option".into());
        }
    }
    let option = |key: &str| {
        options
            .get(key)
            .map(String::as_str)
            .ok_or_else(|| format!("missing {key}"))
    };
    let descriptor = fs::read(option("--descriptor")?)?;
    let identity: ExtractorIdentity =
        serde_json::from_slice(&fs::read(option("--extractor-identity")?)?)?;
    let binding = InputBinding::new(
        &descriptor,
        hash(option("--descriptor-sha256")?)?,
        &identity,
    )?;
    let pin: Binding = serde_json::from_slice(&fs::read(option("--producer-binding")?)?)?;
    pin.validate()?;
    if pin.reducer_binary_sha256 != file_hash(&std::env::current_exe()?)? {
        return Err("producer binding does not pin this executable".into());
    }
    let mib = options
        .get("--cache-mib")
        .map(|v| v.parse::<usize>())
        .transpose()?
        .unwrap_or(64);
    let cache = mib
        .checked_mul(1024 * 1024)
        .filter(|n| *n > 0)
        .ok_or("invalid cache size")?;
    let state = Path::new(option("--state-dir")?);
    let store = if command == "init" {
        DurableStore::init_empty(state, &binding, pin, option("--engine-lineage")?, cache)?
    } else {
        DurableStore::open(state, &binding, pin, cache)?
    };
    match command.as_str() {
        "init" | "inspect" => println!("{}", String::from_utf8(store.manifest()?.encode()?)?),
        "rewind" => {
            let current = store.manifest()?;
            let expected = hash(option("--expected-checkpoint-sha256")?)?;
            if <[u8; 32]>::from(Sha256::digest(current.encode()?)) != expected {
                return Err("rewind checkpoint pin differs".into());
            }
            let target = Boundary {
                block_number: option("--to-block")?.parse()?,
                block_hash: hash(option("--to-hash")?)?,
            };
            if current.transition.as_ref().map(|t| &t.from) != Some(&target) {
                return Err("rewind requires exact immediate predecessor".into());
            }
            let previous = store.rewind_one(&current)?;
            println!("{}", String::from_utf8(previous.encode()?)?);
        }
        "reduce" => {
            let from = option("--from")?.parse::<u64>()?;
            let stop = option("--stop-exclusive")?.parse::<u64>()?;
            let head = Boundary {
                block_number: option("--expected-head-block")?.parse()?,
                block_hash: hash(option("--expected-head-hash")?)?,
            };
            let parent = hash(option("--expected-parent-hash")?)?;
            if from >= stop
                || head.block_number.checked_add(1) != Some(from)
                || (head.block_hash != [0; 32] && head.block_hash != parent)
            {
                return Err("invalid segment boundary/range".into());
            }
            let expected = hash(option("--input-sha256")?)?;
            let file = fs::File::open(option("--input")?)?;
            if !file.metadata()?.is_file() {
                return Err("offline input must be regular file".into());
            }
            let observed = Rc::new(RefCell::new(Sha256::new()));
            let input = InputStream::new(
                HashReader {
                    input: BufReader::new(file),
                    hash: Rc::clone(&observed),
                },
                binding.clone(),
                from,
                stop - 1,
                parent,
            )?;
            let segment = store.begin_segment(
                &head,
                option("--expected-reducer-lineage")?,
                option("--engine-lineage")?,
                (head.block_hash == [0; 32]).then_some(parent),
            )?;
            let mode = match options
                .get("--error-mode")
                .map(String::as_str)
                .unwrap_or("fail-closed")
            {
                "fail-closed" => AbortMode::FailClosed,
                "emit-non-fatal" => AbortMode::EmitNonFatal,
                _ => return Err("invalid error-mode".into()),
            };
            let full = match options
                .get("--full-state-digest")
                .map(String::as_str)
                .unwrap_or("false")
            {
                "false" => false,
                "true" => true,
                _ => return Err("full-state-digest must be true|false".into()),
            };
            let runner = Runner::with_abort_mode(binding, segment, mode)?;
            let checkpoint = run_segment(
                runner,
                input,
                Path::new(option("--output")?),
                50_000,
                full,
                |status| {
                    if status != InputCompletion::Complete {
                        return Err(ReducerError("input refused".into()));
                    }
                    let digest: [u8; 32] = observed.borrow().clone().finalize().into();
                    if digest != expected {
                        return Err(ReducerError("input artifact digest mismatch".into()));
                    }
                    Ok(())
                },
            )?;
            println!(
                "{}",
                serde_json::json!({"format":"pinax.aerodrome.durable-fixture-result/v1",
                "input_sha256":hex::encode(expected),"from":from,"stop_exclusive":stop,
                "checkpoint_sha256":hex::encode(Sha256::digest(checkpoint.encode()?)),
                "boundary":checkpoint.boundary,"reducer_lineage":checkpoint.reducer_lineage,
                "production_qualified":false,"producer_supervisor_receipt":false})
            );
        }
        _ => unreachable!(),
    }
    Ok(())
}
fn main() {
    if let Err(e) = run() {
        eprintln!("aerodrome-durable-fixture refused: {e}");
        std::process::exit(4);
    }
}
