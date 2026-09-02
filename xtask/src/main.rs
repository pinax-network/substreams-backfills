//! `cargo xtask` — repository automation for substreams-backfills.
//!
//! Commands:
//!   evidence check   [--lock PATH] [--root DIR]
//!   evidence fetch   [--lock PATH] [--root DIR] [--cache-dir DIR] [--offline] [--mirror DIR]
//!   evidence lock    --release-tag TAG [--repository OWNER/NAME] [--lock PATH] [--root DIR] [--write] PATH...
//!   evidence audit-release [--lock PATH]

mod evidence;
mod github;
mod verify_all;

use std::path::{Path, PathBuf};
use std::process::ExitCode;

use evidence::{DirectoryFetcher, FetchOptions, Fetcher, Lock, Outcome, Status, DEFAULT_LOCK_PATH};

const USAGE: &str = "usage: cargo xtask <evidence|verify-all> ...
  evidence <check|fetch|lock|audit-release> [options]
  verify-all [--list] [--family core|targets|uniswap-v3|uniswap-v4] [--keep-going]

evidence subcommands:
  check          verify every locked blob in the working tree (offline)
  fetch          place missing or mismatched blobs from the checksum-keyed cache or the release
  lock           regenerate the lock from in-tree files (review before committing)
  audit-release  compare the published release asset set with the lock (exact match required)
options:
  --lock PATH        lock file (default evidence-assets.lock.json)
  --root DIR         repository root (default: current directory)
  --cache-dir DIR    fetch cache (default $XDG_CACHE_HOME or ~/.cache, then substreams-backfills/evidence-assets)
  --offline          fetch: never contact the release; fail on anything not in tree or cache
  --mirror DIR       fetch: read assets from a local directory instead of GitHub
  --release-tag TAG  lock: immutable release tag the assets live on
  --repository O/N   lock: GitHub repository (default pinax-network/substreams-backfills)
  --track PATH       lock: also pin an in-tree contract file (repeatable)
  --write            lock: write the lock file instead of printing it";

struct Args {
    positional: Vec<String>,
    flags: std::collections::BTreeMap<String, Option<String>>,
    tracked: Vec<String>,
}

fn parse_args(raw: Vec<String>) -> Result<Args, String> {
    let mut positional = Vec::new();
    let mut flags = std::collections::BTreeMap::new();
    let mut tracked = Vec::new();
    let mut iter = raw.into_iter();
    while let Some(arg) = iter.next() {
        if let Some(name) = arg.strip_prefix("--") {
            match name {
                "offline" | "write" | "list" | "keep-going" => {
                    flags.insert(name.to_string(), None);
                }
                "track" => {
                    let value = iter
                        .next()
                        .ok_or_else(|| "--track requires a value".to_string())?;
                    tracked.push(value);
                }
                "lock" | "root" | "cache-dir" | "mirror" | "release-tag" | "repository"
                | "family" => {
                    let value = iter
                        .next()
                        .ok_or_else(|| format!("--{name} requires a value"))?;
                    flags.insert(name.to_string(), Some(value));
                }
                other => return Err(format!("unknown option --{other}")),
            }
        } else {
            positional.push(arg);
        }
    }
    Ok(Args {
        positional,
        flags,
        tracked,
    })
}

impl Args {
    fn value(&self, name: &str) -> Option<&str> {
        self.flags.get(name).and_then(|v| v.as_deref())
    }
    fn has(&self, name: &str) -> bool {
        self.flags.contains_key(name)
    }
}

fn default_cache_dir() -> PathBuf {
    let base = std::env::var_os("XDG_CACHE_HOME")
        .map(PathBuf::from)
        .or_else(|| std::env::var_os("HOME").map(|h| PathBuf::from(h).join(".cache")))
        .unwrap_or_else(|| PathBuf::from(".cache"));
    base.join("substreams-backfills").join("evidence-assets")
}

fn run() -> Result<(), String> {
    let raw: Vec<String> = std::env::args().skip(1).collect();
    let args = parse_args(raw)?;
    let mut positional = args.positional.iter();
    match (
        positional.next().map(String::as_str),
        positional.next().map(String::as_str),
    ) {
        (Some("verify-all"), _) => verify_all_command(&args),
        (Some("evidence"), Some(sub)) => {
            let root = PathBuf::from(args.value("root").unwrap_or("."));
            let lock_path = root.join(args.value("lock").unwrap_or(DEFAULT_LOCK_PATH));
            let rest: Vec<String> = positional.cloned().collect();
            match sub {
                "check" => evidence_check(&lock_path, &root),
                "fetch" => evidence_fetch(&args, &lock_path, &root),
                "lock" => evidence_lock(&args, &lock_path, &root, rest),
                "audit-release" => evidence_audit(&lock_path),
                other => Err(format!("unknown evidence subcommand {other}\n{USAGE}")),
            }
        }
        _ => Err(USAGE.to_string()),
    }
}

fn evidence_check(lock_path: &Path, root: &Path) -> Result<(), String> {
    let lock = Lock::load(lock_path).map_err(|e| e.to_string())?;
    let report = evidence::check(&lock, root);
    for (path, status, detail) in &report.rows {
        let tag = match status {
            Status::Verified => "ok      ",
            Status::Missing => "MISSING ",
            Status::Mismatch => "MISMATCH",
        };
        println!("{tag} {path}  {detail}");
    }
    if report.ok() {
        println!(
            "evidence check: {} locked blobs verified",
            report.rows.len()
        );
        Ok(())
    } else {
        Err("evidence check failed: one or more locked blobs are missing or mismatched".into())
    }
}

fn evidence_fetch(args: &Args, lock_path: &Path, root: &Path) -> Result<(), String> {
    let lock = Lock::load(lock_path).map_err(|e| e.to_string())?;
    let cache_dir = args
        .value("cache-dir")
        .map(PathBuf::from)
        .unwrap_or_else(default_cache_dir);
    let options = FetchOptions {
        cache_dir: &cache_dir,
        offline: args.has("offline"),
    };
    let fetcher: Box<dyn Fetcher> = if let Some(mirror) = args.value("mirror") {
        Box::new(DirectoryFetcher {
            directory: PathBuf::from(mirror),
        })
    } else if options.offline {
        Box::new(NoNetwork)
    } else {
        Box::new(github::GithubFetcher::from_environment().map_err(|e| e.to_string())?)
    };
    let outcomes =
        evidence::fetch_all(&lock, root, fetcher.as_ref(), &options).map_err(|e| e.to_string())?;
    for (path, outcome) in &outcomes {
        let tag = match outcome {
            Outcome::AlreadyPresent => "present   ",
            Outcome::FromCache => "cache     ",
            Outcome::Downloaded => "downloaded",
        };
        println!("{tag} {path}");
    }
    let report = evidence::check(&lock, root);
    if !report.ok() {
        return Err("post-fetch verification failed".into());
    }
    println!(
        "evidence fetch: {} locked blobs verified (cache {})",
        outcomes.len(),
        cache_dir.display()
    );
    Ok(())
}

struct NoNetwork;
impl Fetcher for NoNetwork {
    fn fetch(
        &self,
        _lock: &Lock,
        asset: &evidence::Asset,
        _dest: &mut dyn std::io::Write,
    ) -> evidence::Result<()> {
        Err(evidence::EvidenceError::NotFetched {
            path: PathBuf::from(&asset.path),
        })
    }
}

fn evidence_lock(
    args: &Args,
    lock_path: &Path,
    root: &Path,
    paths: Vec<String>,
) -> Result<(), String> {
    let release_tag = args
        .value("release-tag")
        .ok_or("--release-tag is required")?;
    let repository = args
        .value("repository")
        .unwrap_or("pinax-network/substreams-backfills");
    if paths.is_empty() {
        return Err("at least one externalized path is required (positional); use --track PATH for in-tree pins".into());
    }
    let lock = evidence::lock_from_tree(root, repository, release_tag, paths, args.tracked.clone())
        .map_err(|e| e.to_string())?;
    let rendered = lock.render();
    if args.has("write") {
        std::fs::write(lock_path, rendered)
            .map_err(|e| format!("write {}: {e}", lock_path.display()))?;
        println!(
            "wrote {} ({} assets)",
            lock_path.display(),
            lock.assets.len()
        );
    } else {
        print!("{rendered}");
    }
    Ok(())
}

fn evidence_audit(lock_path: &Path) -> Result<(), String> {
    let lock = Lock::load(lock_path).map_err(|e| e.to_string())?;
    let fetcher = github::GithubFetcher::from_environment().map_err(|e| e.to_string())?;
    let published = fetcher.published_assets(&lock).map_err(|e| e.to_string())?;
    evidence::audit_release_assets(&lock, &published).map_err(|e| e.to_string())?;
    println!(
        "release audit: {} assets on {}@{} match the lock exactly",
        published.len(),
        lock.repository,
        lock.release_tag
    );
    Ok(())
}

fn main() -> ExitCode {
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(message) => {
            eprintln!("{message}");
            ExitCode::FAILURE
        }
    }
}

fn verify_all_command(args: &Args) -> Result<(), String> {
    let family = match args.value("family") {
        Some(value) => Some(
            verify_all::Family::parse(value).ok_or_else(|| format!("unknown family {value}"))?,
        ),
        None => None,
    };
    if args.has("list") {
        for check in verify_all::list(family) {
            println!(
                "{:<12} {:<40} {}",
                check.family.label(),
                check.name,
                check.argv.join(" ")
            );
        }
        return Ok(());
    }
    let root = PathBuf::from(args.value("root").unwrap_or("."));
    let lock_path = root.join(args.value("lock").unwrap_or(DEFAULT_LOCK_PATH));
    let evidence_ok = Lock::load(&lock_path)
        .map(|lock| evidence::check(&lock, &root).ok())
        .unwrap_or(false);
    let (outcomes, all_ok) = verify_all::run(family, args.has("keep-going"), evidence_ok);
    for outcome in &outcomes {
        let tag = if outcome.ok { "ok  " } else { "FAIL" };
        println!(
            "{tag} {:<40} {:>8.1}s  {}",
            outcome.name, outcome.seconds, outcome.detail
        );
    }
    let passed = outcomes.iter().filter(|o| o.ok).count();
    println!("verify-all: {passed}/{} checks passed", outcomes.len());
    if all_ok {
        Ok(())
    } else {
        Err("verify-all failed".into())
    }
}
