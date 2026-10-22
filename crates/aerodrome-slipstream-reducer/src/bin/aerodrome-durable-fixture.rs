//! Digest-pinned durable development replay, including a supervised stream.
//! This does not implement runtime staging or manufacture the engine receipt.
use aerodrome_slipstream_reducer::{
    durable::{run_segment, run_segment_streaming, DurableStore, SeedImportPins},
    identity::InputBinding,
    input::InputStream,
    runner::{AbortMode, InputCompletion, Runner},
    ReducerError,
};
use backfill_common::{
    descriptor::ExtractorIdentity, producer_checkpoint::Binding, state_snapshot::Boundary,
    upstream_completion,
};
use sha2::{Digest, Sha256};
use std::{
    cell::{Cell, RefCell},
    collections::BTreeMap,
    fs,
    io::{self, BufReader, Read, Write},
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
    count: Rc<Cell<u64>>,
}
impl<R: Read> Read for HashReader<R> {
    fn read(&mut self, b: &mut [u8]) -> io::Result<usize> {
        let n = self.input.read(b)?;
        self.count.set(
            self.count
                .get()
                .checked_add(n as u64)
                .ok_or_else(|| io::Error::other("input byte counter overflow"))?,
        );
        self.hash.borrow_mut().update(&b[..n]);
        Ok(n)
    }
}
fn run() -> Result<()> {
    let mut args = std::env::args().skip(1);
    let command = args
        .next()
        .ok_or("expected init|seed|inspect|reduce|stream|rewind")?;
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
        "seed" => &["--from", "--seed-manifest", "--seed-pins"],
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
        "stream" => &[
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
            "--attempt-nonce",
            "--substreams-native-sha256",
            "--upstream-completion-fd",
        ],
        _ => return Err("expected init|seed|inspect|reduce|stream|rewind".into()),
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
    } else if command == "seed" {
        let read_small = |path: &str| -> Result<Vec<u8>> {
            let mut f = fs::File::open(path)?;
            if !f.metadata()?.is_file() || f.metadata()?.len() > 1024 * 1024 {
                return Err("seed pins/manifest must be regular files at most 1 MiB".into());
            }
            let mut bytes = Vec::new();
            f.by_ref().take(1024 * 1024 + 1).read_to_end(&mut bytes)?;
            if bytes.len() > 1024 * 1024 {
                return Err("seed pins/manifest grew beyond 1 MiB".into());
            }
            Ok(bytes)
        };
        let pins: SeedImportPins = serde_json::from_slice(&read_small(option("--seed-pins")?)?)?;
        let manifest = read_small(option("--seed-manifest")?)?;
        let snapshot = fs::File::open(option("--from")?)?;
        if !snapshot.metadata()?.is_file() {
            return Err("seed snapshot must be a regular file".into());
        }
        DurableStore::import_snapshot(
            state,
            &binding,
            pin,
            BufReader::new(snapshot),
            &manifest,
            pins,
            cache,
        )?
    } else {
        DurableStore::open(state, &binding, pin, cache)?
    };
    match command.as_str() {
        "stream" => stream_reduce(binding, &store, &options)?,
        "init" | "inspect" => println!("{}", String::from_utf8(store.manifest()?.encode()?)?),
        "seed" => println!(
            "{}",
            serde_json::json!({
                "format":"pinax.aerodrome.development-seed-import-result/v1",
                "production_selectable":false,
                "capture_manifest_verified":false,
                "checkpoint":store.manifest()?,
            })
        ),
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
                    count: Rc::default(),
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

#[cfg(unix)]
fn control_pipe(fd: &str) -> Result<fs::File> {
    use std::os::unix::fs::FileTypeExt;
    let number = fd.parse::<u32>()?;
    if number < 3 || number > i32::MAX as u32 {
        return Err("completion fd must be a private inherited descriptor".into());
    }
    // /dev/fd duplicates the inherited handle using safe std APIs. Reusable
    // regular files and sockets are not the private EOF-delimited pipe protocol.
    let file = fs::File::open(format!("/dev/fd/{number}"))?;
    if !file.metadata()?.file_type().is_fifo() {
        return Err("upstream completion must use an inherited pipe".into());
    }
    Ok(file)
}
#[cfg(not(unix))]
fn control_pipe(_: &str) -> Result<fs::File> {
    Err("supervised streaming requires a Unix control pipe".into())
}

fn stream_reduce(
    binding: InputBinding,
    store: &DurableStore,
    options: &BTreeMap<String, String>,
) -> Result<()> {
    let option = |key: &str| {
        options
            .get(key)
            .map(String::as_str)
            .ok_or_else(|| format!("missing {key}"))
    };
    let before = store.manifest()?;
    let request = upstream_completion::Request {
        binding: before.binding.clone(),
        attempt_nonce: option("--attempt-nonce")?.into(),
        substreams_native_sha256: option("--substreams-native-sha256")?.into(),
        from: option("--from")?.parse()?,
        stop_exclusive: option("--stop-exclusive")?.parse()?,
        predecessor: Boundary {
            block_number: option("--expected-head-block")?.parse()?,
            block_hash: hash(option("--expected-head-hash")?)?,
        },
        observed_parent_hash: option("--expected-parent-hash")?.into(),
        reducer_lineage_before: option("--expected-reducer-lineage")?.into(),
        engine_lineage_before: option("--engine-lineage")?.into(),
    };
    request.validate()?;
    let control = control_pipe(option("--upstream-completion-fd")?)?;
    let parent = hash(&request.observed_parent_hash)?;
    let segment = store.begin_segment(
        &request.predecessor,
        &request.reducer_lineage_before,
        &request.engine_lineage_before,
        (request.predecessor.block_hash == [0; 32]).then_some(parent),
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
    let observed = Rc::new(RefCell::new(Sha256::new()));
    let count = Rc::new(Cell::new(0));
    let input = InputStream::new(
        HashReader {
            input: io::stdin().lock(),
            hash: Rc::clone(&observed),
            count: Rc::clone(&count),
        },
        binding.clone(),
        request.from,
        request.stop_exclusive - 1,
        parent,
    )?;
    let runner = Runner::with_abort_mode(binding, segment, mode)?;
    let output = Path::new(option("--output")?);
    let checkpoint = run_segment_streaming(
        runner,
        input,
        output,
        50_000,
        full,
        &mut io::stdout().lock(),
        |head| {
            let head = head.ok_or_else(|| {
                ReducerError("input or output refused; supervisor must cancel upstream".into())
            })?;
            let digest = hex::encode(observed.borrow().clone().finalize());
            let (_, bytes) = upstream_completion::Completion::read_verified(
                control,
                &request,
                &digest,
                count.get(),
                head,
            )
            .map_err(ReducerError)?;
            let mut file = fs::OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(output.join("upstream-completion.json"))
                .map_err(|e| ReducerError(e.to_string()))?;
            file.write_all(&bytes)
                .and_then(|()| file.sync_all())
                .map_err(|e| ReducerError(e.to_string()))?;
            Ok(())
        },
    )?;
    // stdout contains only provisional BCF1. Success still requires the actual
    // process exit and this checkpoint; the supervisor builds receipt v2 later.
    eprintln!(
        "{}",
        serde_json::json!({
            "format":"pinax.aerodrome.supervised-stream-result/v1",
            "from":request.from,"stop_exclusive":request.stop_exclusive,
            "input_sha256":hex::encode(observed.borrow().clone().finalize()),"input_bytes":count.get(),
            "checkpoint_sha256":hex::encode(Sha256::digest(checkpoint.encode()?)),
            "boundary":checkpoint.boundary,"production_qualified":false,"producer_supervisor_receipt":false
        })
    );
    Ok(())
}
fn main() {
    if let Err(e) = run() {
        eprintln!("aerodrome-durable-fixture refused: {e}");
        std::process::exit(4);
    }
}
