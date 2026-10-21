//! Offline tooling for the separately pinned Aerodrome extractor workspace.
use sha2::{Digest, Sha256};
use std::{
    env, fs,
    path::{Path, PathBuf},
    process::Command,
};
const FAMILY: &str = "aerodrome-slipstream-base/substreams";
const WASMS: [&str; 2] = [
    "aerodrome_extractor_extract.wasm",
    "aerodrome_extractor_stores.wasm",
];
fn cargo(root: &Path, args: &[&str]) -> Result<(), String> {
    let status = Command::new("cargo")
        .arg("+1.90.0")
        .args(args)
        .current_dir(root)
        .status()
        .map_err(|e| e.to_string())?;
    if !status.success() {
        return Err(format!("cargo {} failed: {status}", args.join(" ")));
    }
    Ok(())
}
pub fn run(repo: &Path, command: &str, check: bool, twice: bool) -> Result<(), String> {
    let repo = repo.canonicalize().map_err(|e| e.to_string())?;
    let root = repo.join(FAMILY);
    match command {
        "protogen" => {
            let mut args = vec![
                "run",
                "--locked",
                "-p",
                "aerodrome-extractor-protogen",
                "--",
            ];
            if check {
                args.push("--check");
            }
            cargo(&root, &args)
        }
        "check" => {
            cargo(&root, &["fmt", "--all", "--check"])?;
            cargo(
                &root,
                &[
                    "clippy",
                    "--locked",
                    "--workspace",
                    "--all-targets",
                    "--",
                    "-D",
                    "warnings",
                ],
            )?;
            cargo(&root, &["test", "--locked", "--workspace"])?;
            cargo(
                &root,
                &[
                    "run",
                    "--locked",
                    "-p",
                    "aerodrome-extractor-protogen",
                    "--",
                    "--check",
                ],
            )?;
            pure_dependency_check(&root)
        }
        "build" => {
            if twice {
                let a = tempfile::tempdir().map_err(|e| e.to_string())?;
                let b = tempfile::tempdir().map_err(|e| e.to_string())?;
                let a = stage(&repo, a.path())?;
                let b = stage(&repo, b.path())?;
                let left = build(&a)?;
                let right = build(&b)?;
                if left != right {
                    return Err(format!(
                        "WASM build differs across roots: {left:?} != {right:?}"
                    ));
                }
                println!("two independent source/target roots produced identical WASM bytes");
            } else {
                build(&root)?;
            }
            Ok(())
        }
        _ => Err(
            "usage: cargo xtask aerodrome-substreams <check|protogen [--check]|build [--twice]>"
                .into(),
        ),
    }
}
fn pure_dependency_check(root: &Path) -> Result<(), String> {
    let output = Command::new("cargo")
        .args([
            "+1.90.0",
            "tree",
            "--locked",
            "--edges",
            "normal",
            "--prefix",
            "none",
            "-p",
            "aerodrome-extractor-core",
        ])
        .current_dir(root)
        .output()
        .map_err(|e| e.to_string())?;
    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).into());
    }
    if String::from_utf8_lossy(&output.stdout)
        .lines()
        .any(|l| l.starts_with("substreams"))
    {
        return Err("native core must not depend on the Substreams runtime".into());
    }
    println!("native core has no Substreams runtime dependency");
    Ok(())
}
fn build(root: &Path) -> Result<Vec<String>, String> {
    // macOS exposes temporary roots through /var -> /private/var. Rust emits
    // canonical source paths, so remapping the unresolved alias is insufficient.
    let root = root.canonicalize().map_err(|e| e.to_string())?;
    let mut flags = format!("--remap-path-prefix={}=/src/substreams", root.display());
    for (name, destination, fallback) in [
        ("CARGO_HOME", "/cargo", ".cargo"),
        ("RUSTUP_HOME", "/rustup", ".rustup"),
    ] {
        let path = env::var_os(name)
            .map(PathBuf::from)
            .or_else(|| env::var_os("HOME").map(|h| PathBuf::from(h).join(fallback)))
            .ok_or_else(|| format!("cannot locate {name}"))?;
        flags.push_str(&format!(
            " --remap-path-prefix={}={destination}",
            path.display()
        ));
    }
    let status = Command::new("cargo")
        .args([
            "+1.90.0",
            "build",
            "--locked",
            "--release",
            "--target",
            "wasm32-unknown-unknown",
            "-p",
            "aerodrome-extractor-extract",
            "-p",
            "aerodrome-extractor-stores",
        ])
        .env("RUSTFLAGS", flags)
        .env("CARGO_TARGET_DIR", root.join("target"))
        .current_dir(&root)
        .status()
        .map_err(|e| e.to_string())?;
    if !status.success() {
        return Err(format!("extractor WASM build failed: {status}"));
    }
    WASMS
        .iter()
        .map(|name| {
            let bytes = fs::read(
                root.join("target/wasm32-unknown-unknown/release")
                    .join(name),
            )
            .map_err(|e| e.to_string())?;
            let digest = format!("{:x}", Sha256::digest(bytes));
            println!("{digest}  {name}");
            Ok(digest)
        })
        .collect()
}
fn stage(repo: &Path, tmp: &Path) -> Result<PathBuf, String> {
    let family = tmp.join("aerodrome-slipstream-base");
    copy_tree(&repo.join(FAMILY), &family.join("substreams"))?;
    copy_tree(
        &repo.join("aerodrome-slipstream-base/reference/abis"),
        &family.join("reference/abis"),
    )?;
    Ok(family.join("substreams"))
}
fn copy_tree(source: &Path, dest: &Path) -> Result<(), String> {
    fs::create_dir_all(dest).map_err(|e| e.to_string())?;
    for entry in fs::read_dir(source).map_err(|e| e.to_string())? {
        let entry = entry.map_err(|e| e.to_string())?;
        if entry.file_name() == "target" || entry.file_name() == ".git" {
            continue;
        }
        let typ = entry.file_type().map_err(|e| e.to_string())?;
        if typ.is_dir() {
            copy_tree(&entry.path(), &dest.join(entry.file_name()))?;
        } else if typ.is_file() {
            fs::copy(entry.path(), dest.join(entry.file_name())).map_err(|e| e.to_string())?;
        } else {
            return Err(format!(
                "unsupported staged file {}",
                entry.path().display()
            ));
        }
    }
    Ok(())
}
