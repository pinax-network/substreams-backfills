//! Read-only validator for the S-R2 input foundation. No handlers are run.
use aerodrome_slipstream_reducer::{identity::InputBinding, input::InputStream};
use backfill_common::descriptor::ExtractorIdentity;
use serde_json::json;
use std::{collections::BTreeMap, fs, io::BufReader};
fn run() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = std::env::args().skip(1);
    if args.next().as_deref() != Some("validate-input") {
        return Err("usage: aerodrome-reducer validate-input --input FILE --descriptor FILE --descriptor-sha256 HEX --extractor-identity FILE --from BLOCK --to BLOCK --expected-parent-hash HEX".into());
    }
    let mut options = BTreeMap::new();
    while let Some(key) = args.next() {
        if ![
            "--input",
            "--descriptor",
            "--descriptor-sha256",
            "--extractor-identity",
            "--from",
            "--to",
            "--expected-parent-hash",
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
    let option = |key: &str| {
        options
            .get(key)
            .map(String::as_str)
            .ok_or_else(|| format!("missing {key}"))
    };
    let hash = |value: &str| -> Result<[u8; 32], Box<dyn std::error::Error>> {
        Ok(hex::decode(value)?
            .try_into()
            .map_err(|_| "hash must be 32 bytes")?)
    };
    let descriptor = fs::read(option("--descriptor")?)?;
    let extractor: ExtractorIdentity =
        serde_json::from_slice(&fs::read(option("--extractor-identity")?)?)?;
    let binding = InputBinding::new(
        &descriptor,
        hash(option("--descriptor-sha256")?)?,
        &extractor,
    )?;
    let mut stream = InputStream::new(
        BufReader::new(fs::File::open(option("--input")?)?),
        binding,
        option("--from")?.parse()?,
        option("--to")?.parse()?,
        hash(option("--expected-parent-hash")?)?,
    )?;
    let mut blocks = 0u64;
    let mut candidates = 0u64;
    let mut decoded = 0u64;
    let mut unused_answers = 0u64;
    while let Some(block) = stream.next_block()? {
        blocks += 1;
        candidates += block.block().candidates.len() as u64;
        decoded += block
            .decoded()
            .iter()
            .filter(|event| event.is_some())
            .count() as u64;
        unused_answers += block.calls().unused_answer_count() as u64;
    }
    let end_hash = stream.finish()?;
    println!(
        "{}",
        json!({"contract":"pinax.aerodrome.reducer-input-validation/v1","blocks":blocks,"candidates":candidates,"abi_decoded":decoded,"unused_answers":unused_answers,"end_hash":hex::encode(end_hash),"handlers_executed":0,"production_qualified":false})
    );
    Ok(())
}
fn main() {
    if let Err(error) = run() {
        eprintln!("aerodrome-reducer: {error}");
        std::process::exit(4)
    }
}
