use aerodrome_decimal_audit::{digest, saved, scan, Request, MAX_BYTES};
use sha2::{Digest, Sha256};
use std::{
    fs::File,
    io::{Read, Write},
    path::Path,
};

#[cfg(unix)]
fn regular(path: &Path, limit: u64) -> Result<File, String> {
    use std::os::unix::fs::OpenOptionsExt;
    let file = std::fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK | libc::O_CLOEXEC)
        .open(path)
        .map_err(|_| "cannot open regular audit input".to_string())?;
    let meta = file.metadata().map_err(|_| "cannot inspect audit input")?;
    if !meta.is_file() || meta.len() > limit {
        return Err("audit input is not a bounded regular file".into());
    }
    Ok(file)
}
#[cfg(not(unix))]
fn regular(_path: &Path, _limit: u64) -> Result<File, String> {
    Err("this diagnostic CLI requires Unix no-follow/nonblocking file admission".into())
}
fn run() -> Result<(), String> {
    let args: Vec<_> = std::env::args_os().skip(1).collect();
    if args.len() != 3 {
        return Err(
            "usage: aerodrome-decimal-audit <extractor|saved|sql> REQUEST.json REQUEST_SHA256"
                .into(),
        );
    }
    let mode = args[0].to_str().ok_or("mode is not UTF-8")?;
    let pin = args[2].to_str().ok_or("request pin is not UTF-8")?;
    digest(pin)?;
    let mut bytes = Vec::new();
    regular(Path::new(&args[1]), 65536)?
        .take(65537)
        .read_to_end(&mut bytes)
        .map_err(|_| "cannot read audit request")?;
    if bytes.len() > 65536 || hex::encode(Sha256::digest(&bytes)) != pin {
        return Err("request byte limit or external digest mismatch".into());
    }
    let report = match mode {
        "extractor" => {
            let request: Request = serde_json::from_slice(&bytes).map_err(|e| e.to_string())?;
            request.validate()?;
            serde_json::to_value(scan(regular(&request.input, MAX_BYTES)?, request)?)
                .map_err(|e| e.to_string())?
        }
        "saved" => {
            let request: saved::Request =
                serde_json::from_slice(&bytes).map_err(|e| e.to_string())?;
            request.page.validate()?;
            serde_json::to_value(saved::scan(
                regular(&request.input, saved::MAX_SAVED_BYTES)?,
                request,
            )?)
            .map_err(|e| e.to_string())?
        }
        "sql" => {
            let request: saved::SqlPage =
                serde_json::from_slice(&bytes).map_err(|e| e.to_string())?;
            return std::io::stdout()
                .lock()
                .write_all(request.sql()?.as_bytes())
                .map_err(|_| "cannot write SQL plan".into());
        }
        _ => return Err("unknown audit mode".into()),
    };
    let mut bytes =
        serde_json::to_vec_pretty(&serde_json::json!({"request_sha256":pin,"report":report}))
            .map_err(|e| e.to_string())?;
    bytes.push(b'\n');
    std::io::stdout()
        .lock()
        .write_all(&bytes)
        .map_err(|_| "cannot write completed audit report".into())
}
fn main() {
    if let Err(error) = run() {
        eprintln!("decimal audit refused: {error}");
        std::process::exit(1);
    }
}
