//! Public CLI refusals stop before seed import or network access.
use sha2::{Digest, Sha256};
use std::{
    process::Command,
    time::{Duration, Instant},
};

fn refuse(path: &std::path::Path, sha: &str) -> std::process::Output {
    let mut child = Command::new(env!("CARGO_BIN_EXE_graph-mapping-host"))
        .args(["disk-oracle", "--request"])
        .arg(path)
        .args(["--request-sha256", sha])
        .env_remove("FIREHOSE_ENDPOINT")
        .env_remove("FIREHOSE_API_TOKEN")
        .env_remove("ETHEREUM_RPC_URL")
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .spawn()
        .unwrap();
    let deadline = Instant::now() + Duration::from_secs(5);
    loop {
        if child.try_wait().unwrap().is_some() {
            break;
        }
        if Instant::now() >= deadline {
            child.kill().unwrap();
            let _ = child.wait();
            panic!("request refusal blocked");
        }
        std::thread::sleep(Duration::from_millis(10));
    }
    let result = child.wait_with_output().unwrap();
    assert_eq!(result.status.code(), Some(1));
    assert!(result.stdout.is_empty());
    result
}

#[test]
fn request_sha_shape_and_nonregular_inputs_refuse_without_output() {
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("request.json");
    std::fs::write(&path, b"{}\n").unwrap();
    let error = refuse(&path, &"00".repeat(32));
    assert!(String::from_utf8_lossy(&error.stderr).contains("request pin/bound mismatch"));
    let error = refuse(&path, &hex::encode(Sha256::digest(b"{}\n")));
    assert!(String::from_utf8_lossy(&error.stderr).contains("missing field"));
    let link = temp.path().join("symlink.json");
    std::os::unix::fs::symlink(&path, &link).unwrap();
    refuse(&link, &"00".repeat(32));
    let fifo = temp.path().join("fifo.json");
    assert!(Command::new("mkfifo")
        .arg(&fifo)
        .status()
        .unwrap()
        .success());
    let error = refuse(&fifo, &"00".repeat(32));
    assert!(String::from_utf8_lossy(&error.stderr).contains("regular file"));
    assert_eq!(std::fs::read_dir(temp.path()).unwrap().count(), 3);
}
