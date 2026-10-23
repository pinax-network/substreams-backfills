//! Deterministic transport fixtures. Historical return bytes come from the
//! retained independent first-pool audit; these tests make no network requests.
use aerodrome_call_cassette::{prepare, read_request, FilePin, Request, Rpc, MAX_RESPONSE};
use aerodrome_extractor_core::config::{CONTRACT, INITIAL_BLOCK};
use aerodrome_slipstream_reducer::{
    identity::{build_descriptor, OUTPUT_MODULE, OUTPUT_TYPE},
    pb,
};
use backfill_common::{
    clock::{self, Frame, FrameKind},
    descriptor::ExtractorIdentity,
};
use prost::Message;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeMap,
    fs,
    path::{Path, PathBuf},
    time::Duration,
};
fn sha(b: &[u8]) -> String {
    hex::encode(Sha256::digest(b))
}
fn original() -> pb::ExtractorBlock {
    pb::ExtractorBlock::decode(
        include_bytes!("../../aerodrome-slipstream-reducer/fixtures/first-pool-extractor.pb")
            .as_slice(),
    )
    .unwrap()
}
fn frame(b: &pb::ExtractorBlock) -> Frame {
    Frame {
        kind: FrameKind::Observed,
        block_number: b.number,
        block_hash: b.hash.clone().try_into().unwrap(),
        payload: b.encode_to_vec(),
    }
}
fn pin(path: &Path) -> FilePin {
    let b = fs::read(path).unwrap();
    FilePin {
        path: path.into(),
        bytes: b.len() as u64,
        sha256: sha(&b),
    }
}
struct Fixture {
    _dir: tempfile::TempDir,
    root: PathBuf,
    request: Request,
    block: pb::ExtractorBlock,
}
impl Fixture {
    fn new() -> Self {
        let dir = tempfile::tempdir().unwrap();
        let root = dir.path().canonicalize().unwrap();
        let extractor = ExtractorIdentity {
            spkg_sha256: "11".repeat(32),
            module: OUTPUT_MODULE.into(),
            module_hash: "22".repeat(20),
            output_type: OUTPUT_TYPE.into(),
            initial_block: INITIAL_BLOCK,
        };
        let descriptor = build_descriptor(&extractor, &"33".repeat(20), true).unwrap();
        fs::write(root.join("descriptor.json"), descriptor).unwrap();
        let b = original();
        let mut bytes = Vec::new();
        clock::write_frame(&mut bytes, &frame(&b)).unwrap();
        fs::write(root.join("input.bcf1"), bytes).unwrap();
        let request = Request {
            format: "pinax.aerodrome.call-cassette-request/v1".into(),
            input: pin(&root.join("input.bcf1")),
            descriptor: pin(&root.join("descriptor.json")),
            extractor,
            from_block: b.number,
            to_exclusive: b.number + 1,
            parent_hash: hex::encode(&b.parent_hash),
            head_hash: hex::encode(&b.hash),
            rpc_timeout_seconds: 1,
            total_timeout_seconds: 2,
            minimum_interval_ms: 1,
        };
        Self {
            _dir: dir,
            root,
            request,
            block: b,
        }
    }
    fn replace(&mut self, blocks: &[Frame]) {
        let mut bytes = Vec::new();
        for b in blocks {
            clock::write_frame(&mut bytes, b).unwrap();
        }
        fs::write(&self.request.input.path, bytes).unwrap();
        self.request.input = pin(&self.request.input.path);
    }
    fn run(&self, rpc: &mut Fake) -> Result<(), String> {
        self.run_to(rpc, "output")
    }
    fn run_to(&self, rpc: &mut Fake, name: &str) -> Result<(), String> {
        prepare(
            &self.request,
            &serde_json::to_vec(&self.request).unwrap(),
            &self.root.join(name),
            rpc,
        )
    }
    fn failed(&self, rpc: &mut Fake) {
        assert!(self.run(rpc).is_err());
        assert!(!self.root.join("output/complete.json").exists());
        assert!(!self.root.join("output/cassette.json").exists());
        assert!(self.root.join("output/failure.json").exists());
    }
}
struct Fake {
    block: pb::ExtractorBlock,
    answers: BTreeMap<(String, String), String>,
    seen: usize,
    headers: usize,
    fault: &'static str,
    requests: Vec<Value>,
}
impl Fake {
    fn new(block: pb::ExtractorBlock) -> Self {
        let mut answers = BTreeMap::new();
        for line in include_str!("../../../aerodrome-slipstream-base/substreams/fixtures/archive-audit-13899663/observations.jsonl").lines(){
            let v:Value=serde_json::from_str(line).unwrap();assert_eq!(v["actual"]["kind"],"value");
            answers.insert((v["request"]["params"][0]["to"].as_str().unwrap().into(),v["request"]["params"][0]["data"].as_str().unwrap().into()),format!("0x{}",v["actual"]["data"].as_str().unwrap()));
        }
        Self {
            block,
            answers,
            seen: 0,
            headers: 0,
            fault: "",
            requests: vec![],
        }
    }
}
impl Rpc for Fake {
    fn request(&mut self, body: &Value, timeout: Duration) -> Result<Vec<u8>, String> {
        assert!(timeout <= Duration::from_secs(1));
        self.seen += 1;
        self.requests.push(body.clone());
        if self.fault == "deadline" {
            std::thread::sleep(Duration::from_millis(2100));
        }
        if self.fault == "transport" && self.seen == 5 {
            return Err("synthetic transport refused".into());
        }
        if self.fault == "oversize" {
            return Ok(vec![b' '; MAX_RESPONSE + 1]);
        }
        if self.fault == "duplicate" {
            return Ok(format!(
                "{{\"jsonrpc\":\"2.0\",\"id\":{},\"id\":{},\"result\":\"0x2105\"}}",
                body["id"], body["id"]
            )
            .into_bytes());
        }
        if self.fault == "truncated_json" {
            return Ok(b"{\"jsonrpc\":".to_vec());
        }
        if self.fault == "wrong_id" {
            return Ok(
                serde_json::to_vec(&json!({"jsonrpc":"2.0","id":9999,"result":"0x2105"})).unwrap(),
            );
        }
        let result = match body["method"].as_str().unwrap() {
            "eth_chainId" => json!(if self.fault == "wrong_chain" {
                "0x1"
            } else {
                "0x2105"
            }),
            "eth_getBlockByNumber" => {
                self.headers += 1;
                let number = u64::from_str_radix(
                    body["params"][0].as_str().unwrap().trim_start_matches("0x"),
                    16,
                )
                .unwrap();
                let hash = if self.fault == "wrong_header"
                    || (self.fault == "reorg_after" && self.headers == 2)
                {
                    "ff".repeat(32)
                } else {
                    hex::encode(&self.block.hash)
                };
                json!({"hash":format!("0x{hash}"),"parentHash":format!("0x{}",hex::encode(&self.block.parent_hash)),"number":format!("0x{number:x}")})
            }
            "eth_call" => {
                assert_eq!(body["params"][0]["gas"], "0x2faf080");
                assert_eq!(body["params"][1]["requireCanonical"], true);
                assert_eq!(
                    body["params"][1]["blockHash"],
                    format!("0x{}", hex::encode(&self.block.hash))
                );
                if self.fault == "null_result_with_error" {
                    return Ok(serde_json::to_vec(&json!({"jsonrpc":"2.0","id":body["id"],"result":null,"error":{"code":3,"message":"execution reverted"}})).unwrap());
                }
                if self.fault == "result_with_null_error" {
                    return Ok(serde_json::to_vec(
                        &json!({"jsonrpc":"2.0","id":body["id"],"result":"0x","error":null}),
                    )
                    .unwrap());
                }
                if body["params"][0]["data"] == "0x95d89b41" {
                    if self.fault == "explicit_revert" {
                        return Ok(serde_json::to_vec(&json!({"jsonrpc":"2.0","id":body["id"],"error":{"code":3,"message":"execution reverted: synthetic","data":"redacted"}})).unwrap());
                    }
                    if self.fault == "empty_return" {
                        return Ok(serde_json::to_vec(
                            &json!({"jsonrpc":"2.0","id":body["id"],"result":"0x"}),
                        )
                        .unwrap());
                    }
                }
                if self.fault == "missing_response" {
                    return Ok(
                        serde_json::to_vec(&json!({"jsonrpc":"2.0","id":body["id"]})).unwrap(),
                    );
                }
                if self.fault == "archive_error" {
                    return Ok(serde_json::to_vec(&json!({"jsonrpc":"2.0","id":body["id"],"error":{"code":-32000,"message":"missing trie node SECRET_ENDPOINT"}})).unwrap());
                }
                let k = (
                    body["params"][0]["to"].as_str().unwrap().into(),
                    body["params"][0]["data"].as_str().unwrap().into(),
                );
                let answer = self
                    .answers
                    .get(&k)
                    .ok_or("fake has no retained RPC answer")?;
                json!(if self.fault == "wrong_value" {
                    "0x01"
                } else {
                    answer
                })
            }
            _ => panic!("unplanned RPC method"),
        };
        Ok(serde_json::to_vec(&json!({"jsonrpc":"2.0","id":body["id"],"result":result})).unwrap())
    }
}
#[test]
fn retained_independent_returns_round_trip_to_full_cassette_and_stable_order() {
    let f = Fixture::new();
    let mut rpc = Fake::new(f.block.clone());
    f.run(&mut rpc).unwrap();
    use std::os::unix::fs::PermissionsExt;
    assert_eq!(
        fs::metadata(f.root.join("output"))
            .unwrap()
            .permissions()
            .mode()
            & 0o777,
        0o700
    );
    for entry in fs::read_dir(f.root.join("output")).unwrap() {
        assert_eq!(
            entry.unwrap().metadata().unwrap().permissions().mode() & 0o777,
            0o600
        );
    }
    let raw = fs::read(f.root.join("output/cassette.json")).unwrap();
    let v: Value = serde_json::from_slice(&raw).unwrap();
    assert_eq!(
        v["schema"],
        "pinax.substreams-backfills.mapping-host.cassette/v1"
    );
    assert_eq!(v["entries"].as_array().unwrap().len(), 12);
    for e in v["entries"].as_array().unwrap() {
        let key = (
            e["address"].as_str().unwrap().into(),
            e["calldata"].as_str().unwrap().into(),
        );
        assert_eq!(e["retval"]["data"], rpc.answers[&key]);
    }
    // Positions' full12words retain fields the extractor comparison never consumes.
    let pos = v["entries"]
        .as_array()
        .unwrap()
        .iter()
        .find(|e| e["function"] == "positions(uint256)")
        .unwrap();
    assert_eq!(pos["retval"]["data"].as_str().unwrap().len(), 2 + 12 * 64);
    let complete: Value =
        serde_json::from_slice(&fs::read(f.root.join("output/complete.json")).unwrap()).unwrap();
    assert_eq!(complete["cassette"]["sha256"], sha(&raw));
    assert_eq!(complete["proves_completeness"], false);
    assert_eq!(complete["native_process_exit_verified"], false);
    let mut second = Fake::new(f.block.clone());
    f.run_to(&mut second, "repeat").unwrap();
    assert_eq!(raw, fs::read(f.root.join("repeat/cassette.json")).unwrap());
    let proofs: Value =
        serde_json::from_slice(&fs::read(f.root.join("output/archive-blocks.json")).unwrap())
            .unwrap();
    assert_eq!(proofs.as_array().unwrap().len(), 1);
    assert_eq!(
        proofs[0]["before"]["result"]["hash"],
        format!("0x{}", hex::encode(&f.block.hash))
    );
    let seen = rpc.seen;
    assert!(f.run(&mut rpc).is_err());
    assert_eq!(rpc.seen, seen);
}
#[test]
fn rpc_faults_never_publish_cassette_or_completion() {
    for fault in [
        "transport",
        "oversize",
        "duplicate",
        "truncated_json",
        "wrong_id",
        "wrong_chain",
        "wrong_header",
        "reorg_after",
        "missing_response",
        "archive_error",
        "wrong_value",
        "null_result_with_error",
        "result_with_null_error",
    ] {
        let f = Fixture::new();
        let mut rpc = Fake::new(f.block.clone());
        rpc.fault = fault;
        f.failed(&mut rpc);
        let failure = fs::read_to_string(f.root.join("output/failure.json")).unwrap();
        assert!(!failure.contains("SECRET_ENDPOINT"));
    }
}
#[test]
fn deadline_is_checked_even_with_complete_looking_transport_output() {
    let f = Fixture::new();
    let mut rpc = Fake::new(f.block.clone());
    rpc.fault = "deadline";
    f.failed(&mut rpc);
    assert_eq!(rpc.seen, 1);
}
#[test]
fn malformed_incomplete_duplicate_and_unpinned_inputs_refuse_before_rpc() {
    for fault in 0..11 {
        let mut f = Fixture::new();
        let mut b = f.block.clone();
        match fault {
            0 => {
                let mut bytes = fs::read(&f.request.input.path).unwrap();
                bytes.pop();
                fs::write(&f.request.input.path, bytes).unwrap();
                f.request.input = pin(&f.request.input.path);
            }
            1 => f.request.input.sha256 = "ff".repeat(32),
            2 => f.request.to_exclusive += 1,
            3 => f.replace(&[frame(&b), frame(&b)]),
            4 => {
                b.hash = vec![0; 32];
                let mut fr = frame(&f.block);
                fr.payload = b.encode_to_vec();
                f.replace(&[fr]);
            }
            5 => {
                b.calls = None;
                f.replace(&[frame(&b)]);
            }
            6 => {
                let calls = b.calls.as_mut().unwrap();
                calls.erc20.push(calls.erc20[0].clone());
                f.replace(&[frame(&b)]);
            }
            7 => {
                b.calls.as_mut().unwrap().erc20.pop();
                f.replace(&[frame(&b)]);
            }
            8 => {
                b.parent_hash = vec![0x42; 32];
                f.replace(&[frame(&b)]);
            }
            9 => {
                let mut fr = frame(&b);
                fr.payload.extend([0xf8, 0x07, 1]);
                f.replace(&[fr]);
            }
            10 => {
                let fr = Frame {
                    kind: FrameKind::SyntheticRangeFill,
                    block_number: b.number,
                    block_hash: [0; 32],
                    payload: vec![],
                };
                f.replace(&[fr]);
            }
            _ => unreachable!(),
        }
        let mut rpc = Fake::new(f.block.clone());
        f.failed(&mut rpc);
        assert_eq!(rpc.seen, 0, "fault{fault}");
    }
}
#[test]
fn request_duplicate_unknown_range_pin_and_symlink_refusals() {
    let mut f = Fixture::new();
    let bytes = serde_json::to_vec(&f.request).unwrap();
    let path = f.root.join("request.json");
    fs::write(&path, &bytes).unwrap();
    assert!(read_request(&path, &sha(&bytes)).is_ok());
    assert!(read_request(&path, &"ff".repeat(32)).is_err());
    for prefix in ["\"format\":\"x\",", "\"unexpected\":true,"] {
        let b = format!("{{{}{}", prefix, std::str::from_utf8(&bytes[1..]).unwrap()).into_bytes();
        fs::write(&path, &b).unwrap();
        assert!(read_request(&path, &sha(&b)).is_err());
    }
    f.request.to_exclusive = f.request.from_block + 1001;
    assert!(f.request.validate().is_err());
    use std::os::unix::fs::symlink;
    let link = f.root.join("link");
    symlink(&path, &link).unwrap();
    assert!(read_request(&link, &sha(&bytes)).is_err());
}
#[test]
fn empty_observed_block_still_has_two_canonical_archive_identity_checks() {
    let mut f = Fixture::new();
    let b = pb::ExtractorBlock {
        contract: CONTRACT.into(),
        number: f.block.number,
        hash: f.block.hash.clone(),
        parent_hash: f.block.parent_hash.clone(),
        timestamp: f.block.timestamp,
        firehose_block_version: 4,
        audit: Some(pb::ExtractorAudit::default()),
        calls: Some(pb::CallAnswers::default()),
        ..Default::default()
    };
    f.replace(&[frame(&b)]);
    let mut rpc = Fake::new(b);
    f.run(&mut rpc).unwrap();
    assert_eq!(rpc.headers, 2);
    assert_eq!(rpc.seen, 3);
    let cassette: Value =
        serde_json::from_slice(&fs::read(f.root.join("output/cassette.json")).unwrap()).unwrap();
    assert!(cassette["entries"].as_array().unwrap().is_empty());
}
#[test]
fn actual_cli_refuses_changed_request_without_leaking_endpoint() {
    let f = Fixture::new();
    let bytes = serde_json::to_vec(&f.request).unwrap();
    let path = f.root.join("request.json");
    fs::write(&path, bytes).unwrap();
    let out = std::process::Command::new(env!("CARGO_BIN_EXE_aerodrome-call-cassette"))
        .args([
            "--request",
            path.to_str().unwrap(),
            "--request-sha256",
            &"ff".repeat(32),
            "--output",
            f.root.join("out").to_str().unwrap(),
        ])
        .env(
            "BASE_ARCHIVE_RPC_URL",
            "https://SECRET_ENDPOINT.invalid/private-token",
        )
        .output()
        .unwrap();
    assert_eq!(out.status.code(), Some(4));
    assert!(!String::from_utf8_lossy(&out.stderr).contains("SECRET_ENDPOINT"));
    assert!(!f.root.join("out").exists());
}

#[test]
fn explicit_revert_and_empty_return_preserve_mapping_null_without_inventing_words() {
    for fault in ["explicit_revert", "empty_return"] {
        let mut f = Fixture::new();
        let mut b = f.block.clone();
        for token in &mut b.calls.as_mut().unwrap().erc20 {
            token.symbol = Some(pb::RawRetval {
                kind: Some(pb::raw_retval::Kind::Reverted(pb::raw_retval::Null {})),
            });
            if fault == "explicit_revert" {
                token.rpc_failed_mask |= 1;
            } else {
                token.rpc_empty_mask |= 1;
            }
        }
        f.replace(&[frame(&b)]);
        let mut rpc = Fake::new(b);
        rpc.fault = fault;
        f.run(&mut rpc).unwrap();
        let cassette: Value =
            serde_json::from_slice(&fs::read(f.root.join("output/cassette.json")).unwrap())
                .unwrap();
        let symbols: Vec<_> = cassette["entries"]
            .as_array()
            .unwrap()
            .iter()
            .filter(|e| e["function"] == "symbol()")
            .collect();
        assert_eq!(symbols.len(), 2);
        for symbol in symbols {
            assert_eq!(symbol["retval"], json!({"kind":"null"}));
        }
        if fault == "explicit_revert" {
            let observations =
                fs::read_to_string(f.root.join("output/observations.jsonl")).unwrap();
            let observation: Value = observations
                .lines()
                .map(|line| serde_json::from_str::<Value>(line).unwrap())
                .find(|v| v["actual"]["kind"] == "reverted")
                .unwrap();
            let raw = hex::decode(observation["rpc_response_hex"].as_str().unwrap()).unwrap();
            let response: Value = serde_json::from_slice(&raw).unwrap();
            assert_eq!(response["error"]["data"], "redacted");
        }
    }
}

#[test]
fn fifo_and_ancestor_symlink_are_refused_without_reading() {
    let f = Fixture::new();
    let fifo = f.root.join("request.fifo");
    use std::ffi::CString;
    let name = CString::new(fifo.to_str().unwrap()).unwrap();
    assert_eq!(unsafe { libc::mkfifo(name.as_ptr(), 0o600) }, 0);
    let started = std::time::Instant::now();
    assert!(read_request(&fifo, &"11".repeat(32)).is_err());
    assert!(started.elapsed() < Duration::from_secs(1));
    fs::create_dir(f.root.join("real")).unwrap();
    std::os::unix::fs::symlink(f.root.join("real"), f.root.join("alias")).unwrap();
    fs::write(f.root.join("real/request.json"), b"{}").unwrap();
    assert!(read_request(&f.root.join("alias/request.json"), &sha(b"{}")).is_err());
}
