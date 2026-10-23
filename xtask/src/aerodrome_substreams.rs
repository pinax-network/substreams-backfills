//! Offline tooling for the separately pinned Aerodrome extractor workspace.
use sha2::{Digest, Sha256};
use std::{
    env, fs,
    path::{Path, PathBuf},
    process::Command,
};
const FAMILY: &str = "aerodrome-slipstream-base/substreams";
const WASMS: [&str; 4] = [
    "aerodrome_extractor_extract.wasm",
    "aerodrome_extractor_stores.wasm",
    "aerodrome_extractor_rpc.wasm",
    "aerodrome_extractor_answers.wasm",
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
pub fn audit(repo: &Path, input: &str, output: &str, erc20_only: bool) -> Result<(), String> {
    // Resolve user paths before changing the child working directory.
    let cwd = env::current_dir().map_err(|e| e.to_string())?;
    let input = cwd.join(input);
    let output = cwd.join(output);
    let mut command = Command::new("cargo");
    command
        .args([
            "+1.90.0",
            "run",
            "--locked",
            "-p",
            "aerodrome-extractor-audit",
            "--",
            "--input",
        ])
        .arg(input)
        .arg("--output")
        .arg(output)
        .current_dir(repo.join(FAMILY));
    if erc20_only {
        command.arg("--erc20-only");
    }
    let status = command.status().map_err(|e| e.to_string())?;
    if !status.success() {
        return Err(format!("archive call audit refused: {status}"));
    }
    Ok(())
}
pub fn run(repo: &Path, command: &str, check: bool, twice: bool) -> Result<(), String> {
    let repo = repo.canonicalize().map_err(|e| e.to_string())?;
    let root = repo.join(FAMILY);
    match command {
        "cache-boundary" => cache_boundary(&repo, &root),
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
            "usage: cargo xtask aerodrome-substreams <check|protogen [--check]|build [--twice]|cache-boundary>"
                .into(),
        ),
    }
}

fn module_hashes(root: &Path) -> Result<std::collections::BTreeMap<String, String>, String> {
    let output = Command::new("substreams")
        .args(["info", "substreams.yaml", "map_extractor_block", "--json"])
        .current_dir(root)
        .output()
        .map_err(|e| e.to_string())?;
    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).into());
    }
    let value: serde_json::Value =
        serde_json::from_slice(&output.stdout).map_err(|e| e.to_string())?;
    let modules = value["modules"]
        .as_array()
        .ok_or("missing module inventory")?;
    if modules.len() != 34 {
        return Err("expected the exact 34-module extractor graph".into());
    }
    let mut hashes = std::collections::BTreeMap::new();
    for module in modules {
        let name = module["name"].as_str().ok_or("module name missing")?;
        if module["initial_block"].as_u64() != Some(13_843_704) {
            return Err(format!("wrong initial block for {name}"));
        }
        if name == "map_extractor_block"
            && module["output_type"].as_str()
                != Some("proto:pinax.aerodrome.slipstream.base.v1.ExtractorBlock")
        {
            return Err("wrong final output type".into());
        }
        let hash = module["hash"].as_str().ok_or("module hash missing")?;
        if hashes.insert(name.into(), hash.into()).is_some() {
            return Err("duplicate module".into());
        }
    }
    if !hashes.contains_key("map_extractor_block") {
        return Err("missing final extractor module".into());
    }
    Ok(hashes)
}

/// Mutate valid WASM custom sections in a temporary package to exercise the
/// actual CLI's transitive module hashes, without altering source artifacts.
fn cache_boundary(repo: &Path, root: &Path) -> Result<(), String> {
    let temporary = tempfile::tempdir().map_err(|e| e.to_string())?;
    let staged = stage(repo, temporary.path())?;
    let release = "target/wasm32-unknown-unknown/release";
    fs::create_dir_all(staged.join(release)).map_err(|e| e.to_string())?;
    for wasm in WASMS {
        let source = root.join(release).join(wasm);
        let output = Command::new("wasm-objdump")
            .arg("-x")
            .arg(&source)
            .output()
            .map_err(|e| format!("wasm-objdump (wabt) is required: {e}"))?;
        if !output.status.success() {
            return Err(format!("invalid WASM: {wasm}"));
        }
        let imports: Vec<_> = String::from_utf8_lossy(&output.stdout)
            .lines()
            .filter_map(|line| line.split_once(" <- ").map(|(_, import)| import.to_owned()))
            .filter(|import| import.starts_with("rpc."))
            .collect();
        let expected: Vec<&str> = if wasm == "aerodrome_extractor_rpc.wasm" {
            vec!["rpc.eth_call"]
        } else {
            vec![]
        };
        if imports != expected {
            return Err(format!("wrong RPC import boundary for {wasm}: {imports:?}"));
        }
        fs::copy(source, staged.join(release).join(wasm)).map_err(|e| e.to_string())?;
    }
    let baseline = module_hashes(&staged)?;
    for (wasm, expected) in [
        (
            "aerodrome_extractor_rpc.wasm",
            vec!["map_extractor_block", "map_token_metadata"],
        ),
        (
            "aerodrome_extractor_answers.wasm",
            vec![
                "map_extractor_block",
                "map_position_answers",
                "map_tick_answers",
            ],
        ),
    ] {
        let path = staged.join(release).join(wasm);
        let original = fs::read(&path).map_err(|e| e.to_string())?;
        let mut changed = original.clone();
        changed.extend([0, 6, 4, b't', b'e', b's', b't', 0x42]);
        fs::write(&path, changed).map_err(|e| e.to_string())?;
        let hashes = module_hashes(&staged)?;
        let changed: Vec<_> = hashes
            .iter()
            .filter(|(name, hash)| baseline.get(*name) != Some(*hash))
            .map(|(name, _)| name.as_str())
            .collect();
        if changed != expected {
            return Err(format!(
                "cache boundary drift for {wasm}: {changed:?} != {expected:?}"
            ));
        }
        fs::write(&path, original).map_err(|e| e.to_string())?;
        println!("{wasm} changes exactly {}", changed.join(", "));
    }
    if module_hashes(&staged)? != baseline {
        return Err("restored hashes differ".into());
    }
    println!("34-module graph, output type, initial blocks, isolated RPC import, and cache boundaries verified");
    Ok(())
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
            "-p",
            "aerodrome-extractor-rpc",
            "-p",
            "aerodrome-extractor-answers",
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
