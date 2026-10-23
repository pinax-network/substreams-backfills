#![cfg(unix)]
use sha2::{Digest, Sha256};
use std::{
    path::Path,
    process::{Command, Stdio},
    time::{Duration, Instant},
};
fn run(mode: &str, path: &Path, pin: &str) -> std::process::Output {
    let mut child = Command::new(env!("CARGO_BIN_EXE_aerodrome-decimal-audit"))
        .args([mode, path.to_str().unwrap(), pin])
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    let start = Instant::now();
    while child.try_wait().unwrap().is_none() {
        if start.elapsed() > Duration::from_secs(5) {
            child.kill().unwrap();
            child.wait().unwrap();
            panic!("audit CLI blocked")
        }
        std::thread::sleep(Duration::from_millis(10));
    }
    child.wait_with_output().unwrap()
}
#[test]
fn actual_cli_reports_only_completed_pinned_input_and_refuses_special_files() {
    let dir = tempfile::tempdir().unwrap();
    let input = dir.path().join("rows.jsonl");
    let request = dir.path().join("request.json");
    let row=b"{\"vid\":1,\"id\":\"swap\",\"block_start\":13843704,\"amount0\":\"-85070591730234615865843651857942052000\",\"amount1\":\"1\"}\n";
    std::fs::write(&input, row).unwrap();
    let value = serde_json::json!({"format":"pinax.aerodrome.qn2-saved-request/v1","page":{"format":"pinax.aerodrome.qn2-sql-page/v1","schema":"sgd2","min_vid":0,"max_vid":10,"from_block":13843704,"to_block":13843704,"max_rows":10},"input":input,"input_sha256":hex::encode(Sha256::digest(row)),"input_bytes":row.len()});
    let bytes = serde_json::to_vec(&value).unwrap();
    let pin = hex::encode(Sha256::digest(&bytes));
    std::fs::write(&request, &bytes).unwrap();
    let out = run("saved", &request, &pin);
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    let report: serde_json::Value = serde_json::from_slice(&out.stdout).unwrap();
    assert_eq!(report["report"]["saved_non_fixed_points"], 1);
    assert_eq!(report["report"]["full_range_qn2_closed"], false);
    let out = run("saved", &request, &"00".repeat(32));
    assert!(!out.status.success() && out.stdout.is_empty());
    std::fs::write(&input, b"{}\n").unwrap();
    let out = run("saved", &request, &pin);
    assert!(!out.status.success() && out.stdout.is_empty());
    std::fs::remove_file(&input).unwrap();
    let path = std::ffi::CString::new(input.to_str().unwrap()).unwrap();
    assert_eq!(unsafe { libc::mkfifo(path.as_ptr(), 0o600) }, 0);
    let out = run("saved", &request, &pin);
    assert!(!out.status.success() && out.stdout.is_empty());
    let link = dir.path().join("request-link");
    std::os::unix::fs::symlink(&request, &link).unwrap();
    let out = run("saved", &link, &pin);
    assert!(!out.status.success() && out.stdout.is_empty());
}
