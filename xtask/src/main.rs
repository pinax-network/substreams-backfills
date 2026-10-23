//! `cargo xtask` — repository automation for substreams-backfills.
//!
//! Commands:
//!   evidence check   [--lock PATH] [--root DIR]
//!   evidence fetch   [--lock PATH] [--root DIR] [--cache-dir DIR] [--offline] [--mirror DIR]
//!   evidence lock    --release-tag TAG [--repository OWNER/NAME] [--lock PATH] [--root DIR] [--write] PATH...
//!   evidence audit-release [--lock PATH]

mod aerodrome_substreams;
mod diagnostic_package;
mod eligibility;
mod evidence;
mod fixtures;
mod github;
mod import_verify;
mod logical_oracle;
mod producer_runtime;
mod target_common;
mod targets;
mod v4_engine_reference;
mod v4_q8_reference;
mod v4_release_assets;
mod verify_all;

use std::path::{Path, PathBuf};
use std::process::ExitCode;

use evidence::{DirectoryFetcher, FetchOptions, Fetcher, Lock, Outcome, Status, DEFAULT_LOCK_PATH};

const USAGE: &str = "usage: cargo xtask <evidence|verify-all|verify-targets|eligibility|producer-runtime> ...
  producer-runtime <context|verify-source|build-bundle|smoke|archive|verify-discovery> [options]
  aerodrome-substreams <check|protogen [--check]|build [--twice]|cache-boundary> [--root DIR]   offline Aerodrome extractor tooling
  aerodrome-substreams <audit-calls|audit-erc20> --input EXTRACTOR.pb --output NEW_DIR [--root DIR]
  eligibility capture --binding FILE --measurements FILE --output FILE [--policy PATH] [--root DIR]
  eligibility check --binding FILE --purpose implementation-start|compute-or-load-start [--now RFC3339] [--json] [--policy PATH] [--root DIR]
  verify-targets [--root DIR] [--policy PATH]   validate every target binding and pinned evidence (offline)
  verify-v4-release-assets [--root DIR] [--manifest PATH]   verify the immutable Uniswap V4 release-asset mirror
  verify-v4-engine-reference [--root DIR]   verify the engine v0.5.0 reference capsule (offline)
  verify-v4-q8-reference [--root DIR]   verify the q8 declared-metadata capsule (offline)
  verify-diagnostic-package PATH   verify the evidence-only Uniswap V3 package structure (needs the substreams CLI)
  materialize-uniswap-v3 <target> DIR [--root DIR]   stage a configured Uniswap V3 runtime tree
                 targets: chain-config writer-runtime npm-source-block position-reducer flash-reducer
                          transaction-reducer npm-handler-reducer npm-resolved-inputs npm-observation-plan
                          npm-provider-executor
  verify-logical-oracle [--root DIR]   verify the retained Uniswap V3 logical-oracle snapshot (offline)
  verify-import <uniswap-v3|uniswap-v4> [--root DIR]   verify a frozen source import against its mirror, inventory, and contracts
  fixtures check [--root DIR]   verify hydrated Uniswap V3 block fixtures and module goldens (offline)
  fixtures normalize [--root DIR] [--lock PATH] [--write]   re-cut locked block fixtures to their first Block message (offline)
  verify-target <family> [--root DIR] [--lock PATH] [--exact-source-root DIR] [--write-contract]   verify a pinned target baseline (offline)
                 uniswap-v2-base source mode: --source-root DIR --generic-source-root DIR; messari-v3: --write-contract
                 families: uniswap-v3-matic uniswap-v2-base pancakeswap-infinity-cl-bsc exchange-v3-bsc aerodrome-slipstream-base messari-v3
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
                "offline" | "write" | "list" | "keep-going" | "json" | "write-contract"
                | "check" | "twice" => {
                    flags.insert(name.to_string(), None);
                }
                "track" => {
                    let value = iter
                        .next()
                        .ok_or_else(|| "--track requires a value".to_string())?;
                    tracked.push(value);
                }
                "lock"
                | "root"
                | "cache-dir"
                | "mirror"
                | "release-tag"
                | "repository"
                | "family"
                | "policy"
                | "binding"
                | "measurements"
                | "output"
                | "input"
                | "purpose"
                | "now"
                | "exact-source-root"
                | "source-root"
                | "generic-source-root" => {
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
    if raw.first().is_some_and(|s| s == "producer-runtime") {
        return producer_runtime::run(&raw[1..]);
    }
    let args = parse_args(raw)?;
    let mut positional = args.positional.iter();
    match (
        positional.next().map(String::as_str),
        positional.next().map(String::as_str),
    ) {
        (Some("aerodrome-substreams"), Some(command)) => {
            let root = PathBuf::from(args.value("root").unwrap_or("."));
            if matches!(command, "audit-calls" | "audit-erc20") {
                return aerodrome_substreams::audit(
                    &root,
                    args.value("input").ok_or("--input is required")?,
                    args.value("output").ok_or("--output is required")?,
                    command == "audit-erc20",
                );
            }
            aerodrome_substreams::run(&root, command, args.has("check"), args.has("twice"))
        }
        (Some("verify-all"), _) => verify_all_command(&args),
        (Some("verify-targets"), _) => verify_targets_command(&args),
        (Some("fixtures"), Some(sub @ ("check" | "normalize"))) => {
            let root = PathBuf::from(args.value("root").unwrap_or("."));
            let report = if sub == "check" {
                fixtures::check(&root)
            } else {
                let lock_path = root.join(args.value("lock").unwrap_or(fixtures::BLOCKS_LOCK));
                fixtures::normalize(&root, &lock_path, args.has("write"))
            }
            .map_err(|e| e.to_string())?;
            for line in report.lines {
                println!("{line}");
            }
            Ok(())
        }
        (Some("verify-import"), Some(family)) => {
            let root = PathBuf::from(args.value("root").unwrap_or("."));
            let contract = match family {
                "uniswap-v3" | "v3" => &import_verify::UNISWAP_V3,
                "uniswap-v4" | "v4" => &import_verify::UNISWAP_V4,
                other => return Err(format!("unknown import {other}")),
            };
            let report = import_verify::verify_import(&root, contract)
                .map_err(|e| format!("{} import verification failed: {e}", contract.label))?;
            for line in report {
                println!("{line}");
            }
            if contract.label == "Uniswap V4" {
                v4_release_assets::verify(&root, &v4_release_assets::default_manifest_path())
                    .map_err(|e| e.to_string())?;
                println!("verified mirrored Uniswap V4 history, exact imported tree, 98 files, 13 executable modes, frozen v0.4.0 packages, and external release assets");
            } else {
                println!("verified mirrored Uniswap V3 history, exact imported tree and inventory, 75 files, one executable mode, and the 20-entity logical contract");
            }
            Ok(())
        }
        (Some("materialize-uniswap-v3"), Some(target)) => {
            let root = PathBuf::from(args.value("root").unwrap_or("."));
            let Some(destination) = positional.next() else {
                return Err("materialize-uniswap-v3 needs a destination directory".to_string());
            };
            let destination = PathBuf::from(destination);
            uniswap_v3_runtime::materialize(&root, target, &destination)
                .map_err(|e| format!("Uniswap V3 {target} materialization failed: {e}"))?;
            let summary = uniswap_v3_runtime::summary(target).unwrap_or(target);
            println!("materialized {summary} at {}", destination.display());
            Ok(())
        }
        (Some("verify-target"), Some(family)) => verify_target_command(family, &args),
        (Some("verify-diagnostic-package"), Some(package)) => {
            let package = PathBuf::from(package);
            let inspected = diagnostic_package::inspect(&package)
                .map_err(|e| format!("Uniswap V3 diagnostic package verification failed: {e}"))?;
            diagnostic_package::verify(&inspected)
                .map_err(|e| format!("Uniswap V3 diagnostic package verification failed: {e}"))?;
            println!("{}", diagnostic_package::SUCCESS_LINE);
            Ok(())
        }
        (Some("verify-v4-q8-reference"), _) => {
            let root = PathBuf::from(args.value("root").unwrap_or("."));
            v4_q8_reference::verify(&root).map_err(|e| format!("ERROR: {e}"))?;
            println!("{}", v4_q8_reference::success_json());
            Ok(())
        }
        (Some("verify-logical-oracle"), _) => {
            let root = PathBuf::from(args.value("root").unwrap_or("."));
            let line = logical_oracle::verify(&root)
                .map_err(|e| format!("Uniswap V3 logical-oracle verification failed: {e}"))?;
            println!("{line}");
            Ok(())
        }
        (Some("verify-v4-engine-reference"), _) => {
            let root = PathBuf::from(args.value("root").unwrap_or("."));
            v4_engine_reference::verify(&root)
                .map_err(|e| format!("Uniswap V4 engine reference verification failed: {e}"))?;
            println!("{}", v4_engine_reference::success_line());
            Ok(())
        }
        (Some("verify-v4-release-assets"), _) => {
            let root = PathBuf::from(args.value("root").unwrap_or("."));
            let manifest = args
                .value("manifest")
                .map(PathBuf::from)
                .unwrap_or_else(v4_release_assets::default_manifest_path);
            v4_release_assets::verify(&root, &manifest).map_err(|e| e.to_string())?;
            println!("verified 2 immutable Uniswap V4 historical release assets");
            Ok(())
        }
        (Some("eligibility"), Some(sub)) => eligibility_command(sub, &args),
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

fn verify_targets_command(args: &Args) -> Result<(), String> {
    let root = PathBuf::from(args.value("root").unwrap_or("."));
    let policy = args
        .value("policy")
        .map(PathBuf::from)
        .unwrap_or_else(|| root.join("eligibility/policy-v1.yaml"));
    match eligibility::validate_targets(&root, &policy) {
        Ok(lines) => {
            for line in lines {
                println!("{line}");
            }
            Ok(())
        }
        Err(error) => Err(format!("target validation failed: {error}")),
    }
}

fn eligibility_command(sub: &str, args: &Args) -> Result<(), String> {
    use serde_json::Value;
    let root = PathBuf::from(args.value("root").unwrap_or("."));
    let root = root
        .canonicalize()
        .map_err(|e| format!("cannot resolve root {}: {e}", root.display()))?;
    let policy_path = args
        .value("policy")
        .map(PathBuf::from)
        .unwrap_or_else(|| root.join("eligibility/policy-v1.yaml"));
    let binding_path = PathBuf::from(args.value("binding").ok_or("--binding is required")?);
    let policy = eligibility::load_policy(&policy_path).map_err(|e| e.to_string())?;
    let binding = eligibility::load_yaml(&binding_path).map_err(|e| e.to_string())?;
    eligibility::validate_binding(&binding, &policy, Some(&binding_path))
        .map_err(|e| format!("eligibility {sub} failed: {e}"))?;
    match sub {
        "capture" => {
            let measurements_path = PathBuf::from(
                args.value("measurements")
                    .ok_or("--measurements is required")?,
            );
            let output_arg = PathBuf::from(args.value("output").ok_or("--output is required")?);
            let measurements =
                eligibility::load_json(&measurements_path).map_err(|e| e.to_string())?;
            let evidence = eligibility::build_evidence(&measurements, &binding, &policy)
                .map_err(|e| format!("eligibility capture failed: {e}"))?;
            eligibility::validate_evidence(&evidence, &binding, &policy)
                .map_err(|e| format!("eligibility capture failed: {e}"))?;
            let output = if output_arg.is_absolute() {
                output_arg
            } else {
                root.join(output_arg)
            };
            let relative = output
                .strip_prefix(&root)
                .map_err(|_| {
                    "eligibility capture failed: output must be inside the repository".to_string()
                })?
                .to_string_lossy()
                .replace('\\', "/");
            eligibility::resolve_evidence_path(&root, &relative)
                .map_err(|e| format!("eligibility capture failed: {e}"))?;
            let deployment = binding
                .get("deployment")
                .and_then(Value::as_str)
                .unwrap_or_default();
            let expected_directory = root.join("evidence").join("eligibility").join(deployment);
            let measured_at =
                eligibility::parse_utc(evidence.get("measured_at"), "evidence.measured_at")
                    .map_err(|e| e.to_string())?;
            let expected_name = measured_at.format("%Y%m%dT%H%M%SZ.json").to_string();
            if output.parent() != Some(expected_directory.as_path())
                || output.file_name().and_then(|n| n.to_str()) != Some(expected_name.as_str())
            {
                return Err(format!(
                    "eligibility capture failed: output must be evidence/eligibility/{deployment}/{expected_name}"
                ));
            }
            if output.exists() {
                return Err(format!(
                    "eligibility capture failed: refusing to overwrite immutable evidence file {}",
                    output.display()
                ));
            }
            std::fs::create_dir_all(&expected_directory).map_err(|e| e.to_string())?;
            std::fs::write(&output, eligibility::canonical_json(&evidence))
                .map_err(|e| e.to_string())?;
            let summary = evidence
                .get("summary")
                .and_then(Value::as_object)
                .expect("validated");
            println!("Captured immutable evidence. Review it, then update eligibility.latest to:");
            println!(
                "decision: {}",
                summary
                    .get("decision")
                    .and_then(Value::as_str)
                    .unwrap_or_default()
            );
            println!(
                "reason: {}",
                summary
                    .get("reason")
                    .and_then(Value::as_str)
                    .unwrap_or_default()
            );
            println!(
                "measured_at: '{}'",
                evidence
                    .get("measured_at")
                    .and_then(Value::as_str)
                    .unwrap_or_default()
            );
            println!("evidence: {relative}");
            println!(
                "sha256: {}",
                eligibility::sha256_file(&output).map_err(|e| e.to_string())?
            );
            Ok(())
        }
        "check" => {
            let purpose = args.value("purpose").ok_or("--purpose is required")?;
            if !matches!(purpose, "implementation-start" | "compute-or-load-start") {
                return Err(format!(
                    "eligibility check failed: unsupported purpose {purpose:?}"
                ));
            }
            let evidence = eligibility::validate_binding_evidence(&binding, &policy, &root)
                .map_err(|e| format!("eligibility check failed: {e}"))?;
            let now = match args.value("now") {
                Some(text) => {
                    eligibility::parse_utc(Some(&Value::String(text.to_string())), "--now")
                        .map_err(|e| format!("eligibility check failed: {e}"))?
                }
                None => eligibility::now_utc(),
            };
            let (allowed, message) =
                eligibility::check_fresh_gate(&binding, evidence.as_ref(), &policy, purpose, now)
                    .map_err(|e| format!("eligibility check failed: {e}"))?;
            if args.has("json") {
                let mut result = serde_json::Map::new();
                result.insert("allowed".into(), Value::Bool(allowed));
                result.insert(
                    "deployment".into(),
                    binding.get("deployment").cloned().unwrap_or(Value::Null),
                );
                result.insert("message".into(), Value::String(message.clone()));
                result.insert("purpose".into(), Value::String(purpose.into()));
                println!("{}", serde_json::to_string(&result).expect("serializes"));
            } else {
                println!("{message}");
            }
            if allowed {
                Ok(())
            } else {
                // Exit status 2 mirrors check-eligibility.py: a closed gate is not an error.
                std::process::exit(2);
            }
        }
        other => Err(format!("unknown eligibility subcommand {other}\n{USAGE}")),
    }
}

fn verify_target_command(family: &str, args: &Args) -> Result<(), String> {
    use targets::{
        aerodrome_slipstream_base, exchange_v3_bsc, messari_v3, pancakeswap_infinity_cl_bsc,
        uniswap_v2_base, uniswap_v3_matic,
    };
    let root = PathBuf::from(args.value("root").unwrap_or("."));
    let exact_source_root = args.value("exact-source-root").map(PathBuf::from);
    let lock = |default: &str| PathBuf::from(args.value("lock").unwrap_or(default));
    let (label, outcome) = match family {
        "uniswap-v3-matic" => (
            "Uniswap V3 Matic target",
            uniswap_v3_matic::verify(
                &root,
                &lock(uniswap_v3_matic::LOCK_PATH),
                exact_source_root.as_deref(),
            ),
        ),
        "uniswap-v2-base" => {
            let sources =
                match (args.value("source-root"), args.value("generic-source-root")) {
                    (None, None) => None,
                    (Some(behavioral), Some(generic)) => {
                        Some((PathBuf::from(behavioral), PathBuf::from(generic)))
                    }
                    _ => return Err(
                        "uniswap-v2-base needs --source-root and --generic-source-root together"
                            .into(),
                    ),
                };
            if exact_source_root.is_some() {
                return Err("uniswap-v2-base takes --source-root and --generic-source-root, not --exact-source-root".into());
            }
            (
                "Uniswap V2 Base target",
                uniswap_v2_base::verify(
                    &root,
                    &lock(uniswap_v2_base::LOCK_PATH),
                    sources.as_ref().map(|(b, g)| (b.as_path(), g.as_path())),
                ),
            )
        }
        "pancakeswap-infinity-cl-bsc" => (
            "Pancake Infinity CL BSC target",
            pancakeswap_infinity_cl_bsc::verify(
                &root,
                &lock(pancakeswap_infinity_cl_bsc::LOCK_PATH),
                exact_source_root.as_deref(),
            ),
        ),
        "exchange-v3-bsc" => (
            "Exchange V3 BSC target",
            exchange_v3_bsc::verify(
                &root,
                &lock(exchange_v3_bsc::LOCK_PATH),
                exact_source_root.as_deref(),
            ),
        ),
        "aerodrome-slipstream-base" => (
            "Aerodrome Slipstream Base target",
            aerodrome_slipstream_base::verify(
                &root,
                &lock(aerodrome_slipstream_base::LOCK_PATH),
                exact_source_root.as_deref(),
            ),
        ),
        "messari-v3" => (
            "Messari V3 targets",
            messari_v3::verify(&root, args.has("write-contract")),
        ),
        other => return Err(format!("unknown target family {other}\n{USAGE}")),
    };
    let line = outcome.map_err(|e| format!("{label} verification failed: {e}"))?;
    println!("{line}");
    Ok(())
}
