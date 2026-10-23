use aerodrome_extractor_audit::{call_retval, checks, compare, request};
use aerodrome_extractor_core::config::{Config, PARAMS};
use aerodrome_extractor_pb::v1::ExtractorBlock;
use prost::Message;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    fs::{self, File, OpenOptions},
    io::Write,
    path::PathBuf,
    time::Duration,
};

fn rpc(agent: &ureq::Agent, url: &str, body: &Value) -> Result<Value, String> {
    // Never include a URL, transport error or provider error text in output:
    // URLs may carry credentials and JSON-RPC error data is untrusted.
    let response = agent
        .post(url)
        .send_json(body.clone())
        .map_err(|_| "archive RPC transport/HTTP failure")?;
    let value: Value = response
        .into_json()
        .map_err(|_| "archive RPC invalid JSON")?;
    if value["jsonrpc"] != "2.0" || value["id"] != body["id"] {
        return Err("archive RPC response identity mismatch".into());
    }
    Ok(value)
}
fn block_identity(agent: &ureq::Agent, url: &str, block: &ExtractorBlock) -> Result<(), String> {
    let body = json!({"jsonrpc":"2.0","id":2,"method":"eth_getBlockByHash","params":[format!("0x{}",hex::encode(&block.hash)), false]});
    let response = rpc(agent, url, &body)?;
    let value = &response["result"];
    if response.get("error").is_some()
        || value["hash"] != format!("0x{}", hex::encode(&block.hash))
        || value["parentHash"] != format!("0x{}", hex::encode(&block.parent_hash))
        || value["number"] != format!("0x{:x}", block.number)
    {
        return Err("archive block identity differs from extractor".into());
    }
    Ok(())
}
fn write_json(path: PathBuf, value: &Value) -> Result<(), String> {
    let mut f = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .map_err(|e| e.to_string())?;
    serde_json::to_writer_pretty(&mut f, value).map_err(|e| e.to_string())?;
    f.write_all(b"\n").map_err(|e| e.to_string())?;
    f.sync_all().map_err(|e| e.to_string())
}
fn run() -> Result<(), String> {
    let mut args = std::env::args().skip(1);
    let mut input = None;
    let mut output = None;
    let mut erc20_only = false;
    while let Some(flag) = args.next() {
        match flag.as_str() {
            "--input" if input.is_none() => input = Some(PathBuf::from(args.next().ok_or("--input requires a path")?)),
            "--output" if output.is_none() => output = Some(PathBuf::from(args.next().ok_or("--output requires a new directory")?)),
            "--erc20-only" if !erc20_only => erc20_only = true,
            _ => return Err("usage: aerodrome-extractor-audit --input EXTRACTOR.pb --output NEW_DIR [--erc20-only]; BASE_ARCHIVE_RPC_URL supplies the read-only archive".into()),
        }
    }
    let input = input.ok_or("--input is required")?;
    let output = output.ok_or("--output is required")?;
    let url =
        std::env::var("BASE_ARCHIVE_RPC_URL").map_err(|_| "BASE_ARCHIVE_RPC_URL is required")?;
    if !url.starts_with("https://") {
        return Err("archive RPC must use HTTPS".into());
    }
    let bytes = fs::read(input).map_err(|e| e.to_string())?;
    let block = ExtractorBlock::decode(bytes.as_slice()).map_err(|e| e.to_string())?;
    if block.encode_to_vec() != bytes {
        return Err("input must be canonical ExtractorBlock protobuf".into());
    }
    let checks = checks(
        &block,
        &Config::parse(PARAMS).map_err(|e| e.to_string())?,
        erc20_only,
    )?;
    fs::create_dir(&output)
        .map_err(|_| "output must be a new directory with an existing parent")?;
    write_json(
        output.join("attempt.json"),
        &json!({
            "schema":"pinax.aerodrome.archive-call-audit/v1", "status":"incomplete",
            "scope":if erc20_only {"erc20"} else {"all_supplied_answers"},
            "input_sha256":hex::encode(Sha256::digest(&bytes)), "block_number":block.number,
            "block_hash":hex::encode(&block.hash), "expected_calls":checks.len(),
            "auditor_binary_sha256":hex::encode(Sha256::digest(fs::read(std::env::current_exe().map_err(|e|e.to_string())?).map_err(|e|e.to_string())?)),
            "proves_completeness":false, "production_qualified":false
        }),
    )?;
    let mut observations = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(output.join("observations.jsonl"))
        .map_err(|e| e.to_string())?;
    let agent = ureq::AgentBuilder::new()
        .timeout(Duration::from_secs(30))
        .redirects(0)
        .build();
    let outcome = (|| -> Result<(), String> {
        let chain = rpc(
            &agent,
            &url,
            &json!({"jsonrpc":"2.0","id":1,"method":"eth_chainId","params":[]}),
        )?;
        if chain.get("error").is_some() || chain["result"] != "0x2105" {
            return Err("archive is not Base chain 8453".into());
        }
        block_identity(&agent, &url, &block)?;
        for (index, check) in checks.iter().enumerate() {
            let id = 3 + index as u64;
            let body = request(check, &block.hash, id);
            let response = rpc(&agent, &url, &body)?;
            let actual = call_retval(&response, id)?;
            let comparison = compare(check, &actual);
            // Store only normalized call output, not provider errors/URLs.
            serde_json::to_writer(
                &mut observations,
                &json!({"request":body,"actual":actual,"matched":comparison.is_ok()}),
            )
            .map_err(|e| e.to_string())?;
            observations.write_all(b"\n").map_err(|e| e.to_string())?;
            observations.sync_all().map_err(|e| e.to_string())?;
            comparison.map_err(|reason| format!("call {index}: {reason}"))?;
        }
        block_identity(&agent, &url, &block)?;
        Ok(())
    })();
    match outcome {
        Ok(()) => {
            write_json(
                output.join("success.json"),
                &json!({"schema":"pinax.aerodrome.archive-call-audit-success/v1", "calls_checked":checks.len(),
                "nonempty":!checks.is_empty(), "input_sha256":hex::encode(Sha256::digest(&bytes)),
                "attempt_sha256":hex::encode(Sha256::digest(fs::read(output.join("attempt.json")).map_err(|e|e.to_string())?)),
                "observations_sha256":hex::encode(Sha256::digest(fs::read(output.join("observations.jsonl")).map_err(|e|e.to_string())?)),
                "proves_completeness":false, "production_qualified":false}),
            )?;
            File::open(&output)
                .and_then(|f| f.sync_all())
                .map_err(|e| e.to_string())?;
            println!(
                "verified {} supplied answers at Base block {}; receipt {}",
                checks.len(),
                block.number,
                output.display()
            );
            Ok(())
        }
        Err(reason) => {
            write_json(
                output.join("failure.json"),
                &json!({"reason":reason,"production_qualified":false}),
            )?;
            Err(reason)
        }
    }
}
fn main() {
    if let Err(error) = run() {
        eprintln!("audit refused: {error}");
        std::process::exit(4);
    }
}
