use anyhow::{ensure, Result};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::{env, fs, path::PathBuf};
fn main() -> Result<()> {
    let out = PathBuf::from(env::var("OUT_DIR")?);
    let abis: [(&str, &str, &str, &[&str]); 3] = [
        (
            "factory",
            "Factory.json",
            "7dac7fd7c4ff807498cb7dcbf503474d13b1207852bb8b2b3687a7e8cfb6d979",
            &["PoolCreated"],
        ),
        (
            "pool",
            "Pool.json",
            "46588c2f4ad0b91f64e7b43b03190c5422d3f46f2759c53412a3f3279f816760",
            &["Initialize", "Swap", "Mint", "Burn", "Flash"],
        ),
        (
            "npm",
            "NonfungiblePositionManager.json",
            "6109c87c3dfd051c5fa283e71463d29d4c31a40339223ea3015ea0bcdd602c00",
            &[
                "IncreaseLiquidity",
                "DecreaseLiquidity",
                "Collect",
                "Transfer",
            ],
        ),
    ];
    for (module, file, sha, names) in abis {
        let path = PathBuf::from("../../../reference/abis").join(file);
        println!("cargo:rerun-if-changed={}", path.display());
        let bytes = fs::read(&path)?;
        ensure!(
            format!("{:x}", Sha256::digest(&bytes)) == sha,
            "pinned ABI digest mismatch: {file}"
        );
        let all: Vec<Value> = serde_json::from_slice(&bytes)?;
        let events: Vec<_> = all
            .into_iter()
            .filter(|e| {
                e["type"] == "event" && e["name"].as_str().is_some_and(|n| names.contains(&n))
            })
            .collect();
        for name in names {
            ensure!(
                events.iter().filter(|e| e["name"] == *name).count() == 1,
                "event count mismatch {file}::{name}"
            );
        }
        let filtered = out.join(format!("{module}.json"));
        fs::write(&filtered, serde_json::to_vec(&events)?)?;
        substreams_ethereum::Abigen::new(module, filtered.to_str().unwrap())?
            .generate()?
            .write_to_file(out.join(format!("{module}.rs")))?;
        // Abigen keeps TOPIC_ID private. Expose its generated value for raw candidate
        // matching, which must retain malformed payloads that match_and_decode rejects.
        let generated = out.join(format!("{module}.rs"));
        let text = fs::read_to_string(&generated)?;
        ensure!(
            text.matches("const TOPIC_ID:").count() == names.len(),
            "Abigen topic visibility shim drift"
        );
        fs::write(
            generated,
            text.replace("const TOPIC_ID:", "pub const TOPIC_ID:"),
        )?;
    }
    Ok(())
}
