//! Offline artifact equality; does not certify either producer's provenance.
use aerodrome_slipstream_reducer::differential::compare_frames;
use backfill_common::BlockChangesCompatibility;
use std::{collections::BTreeMap, fs, io::BufReader};

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = std::env::args().skip(1);
    let mut options = BTreeMap::new();
    while let Some(key) = args.next() {
        if ![
            "--expected",
            "--actual",
            "--expected-descriptor",
            "--actual-descriptor",
            "--expected-descriptor-sha256",
            "--actual-descriptor-sha256",
            "--from",
            "--stop-exclusive",
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
    let binding = |side: &str| -> Result<BlockChangesCompatibility, Box<dyn std::error::Error>> {
        let bytes = fs::read(option(&format!("--{side}-descriptor"))?)?;
        let binding = BlockChangesCompatibility::from_descriptor(&bytes)?;
        if hex::encode(binding.id()) != option(&format!("--{side}-descriptor-sha256"))? {
            return Err(format!("{side} descriptor digest mismatch").into());
        }
        Ok(binding)
    };
    let report = compare_frames(
        BufReader::new(fs::File::open(option("--expected")?)?),
        BufReader::new(fs::File::open(option("--actual")?)?),
        &binding("expected")?,
        &binding("actual")?,
        option("--from")?.parse()?,
        option("--stop-exclusive")?.parse()?,
    )?;
    println!("{}", serde_json::to_string(&report)?);
    Ok(())
}
fn main() {
    if let Err(e) = run() {
        eprintln!("aerodrome-diff-frames: {e}");
        std::process::exit(4);
    }
}
