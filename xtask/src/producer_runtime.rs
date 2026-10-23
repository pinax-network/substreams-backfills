//! Offline, non-final producer packaging. No registry push or release creation.
use aerodrome_slipstream_reducer::{
    identity,
    runtime::{
        self, ExtractorLock, FamilyContract, FilePin, RuntimeManifest, SourceManifest,
        VerifiedRuntime,
    },
};
use serde::{Deserialize, Serialize};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs::{self, File, OpenOptions},
    io::{Read, Write},
    path::Path,
    process::Command,
};

type Result<T> = std::result::Result<T, String>;
const SOURCE: &str = "source.json";
fn err(e: impl ToString) -> String {
    e.to_string()
}
fn need(ok: bool, msg: &str) -> Result<()> {
    if ok {
        Ok(())
    } else {
        Err(msg.into())
    }
}
fn read(path: &Path) -> Result<Vec<u8>> {
    let m = fs::symlink_metadata(path).map_err(err)?;
    need(
        m.is_file() && m.len() <= 256 * 1024 * 1024,
        "expected bounded regular file",
    )?;
    let mut bytes = Vec::new();
    File::open(path)
        .map_err(err)?
        .take(256 * 1024 * 1024 + 1)
        .read_to_end(&mut bytes)
        .map_err(err)?;
    need(
        bytes.len() <= 256 * 1024 * 1024,
        "file grew beyond size limit",
    )?;
    Ok(bytes)
}
fn write(path: &Path, bytes: &[u8]) -> Result<()> {
    let mut f = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .map_err(err)?;
    f.write_all(bytes).map_err(err)?;
    f.sync_all().map_err(err)
}
fn json<T: Serialize>(v: &T) -> Result<Vec<u8>> {
    runtime::json_bytes(v).map_err(err)
}
fn decode<T: for<'a> Deserialize<'a> + Serialize>(bytes: &[u8]) -> Result<T> {
    let v: T = serde_json::from_slice(bytes).map_err(err)?;
    need(json(&v)? == bytes, "noncanonical JSON")?;
    Ok(v)
}
fn safe(p: &str) -> bool {
    !p.contains(['\\', ':', '\0']) && p.split('/').all(|x| !x.is_empty() && x != "." && x != "..")
}
fn output(mut c: Command) -> Result<Vec<u8>> {
    let o = c.output().map_err(err)?;
    need(
        o.status.success(),
        &format!("command failed: {}", String::from_utf8_lossy(&o.stderr)),
    )?;
    Ok(o.stdout)
}
fn git(root: &Path, args: &[&str]) -> Result<Vec<u8>> {
    let mut c = Command::new("git");
    c.arg("-C").arg(root).args(args);
    output(c)
}
fn fresh(dest: &Path) -> Result<tempfile::TempDir> {
    need(
        fs::symlink_metadata(dest).is_err_and(|e| e.kind() == std::io::ErrorKind::NotFound),
        "output already exists or cannot be inspected",
    )?;
    let parent = dest
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
        .unwrap_or(Path::new("."));
    tempfile::Builder::new()
        .prefix(".producer-building-")
        .tempdir_in(parent)
        .map_err(err)
}
fn publish(temp: tempfile::TempDir, dest: &Path) -> Result<()> {
    sync_tree(temp.path())?;
    let building = temp.keep();
    if let Err(error) = backfill_rename(&building, dest) {
        let _ = fs::remove_dir_all(&building);
        return Err(error);
    }
    File::open(
        dest.parent()
            .filter(|p| !p.as_os_str().is_empty())
            .unwrap_or(Path::new(".")),
    )
    .map_err(err)?
    .sync_all()
    .map_err(err)
}
fn backfill_rename(from: &Path, to: &Path) -> Result<()> {
    // Same atomic no-replace primitive used by VerifiedRuntime::stage.
    backfill_common::dynamic_sources_v2::seal::rename_no_replace(from, to)
}
fn sync_tree(root: &Path) -> Result<()> {
    for entry in fs::read_dir(root).map_err(err)? {
        let e = entry.map_err(err)?;
        if e.file_type().map_err(err)?.is_dir() {
            sync_tree(&e.path())?;
        }
    }
    File::open(root).map_err(err)?.sync_all().map_err(err)
}
fn walk(root: &Path, allow_target: bool) -> Result<BTreeSet<String>> {
    fn visit(
        root: &Path,
        dir: &Path,
        out: &mut BTreeSet<String>,
        allow_target: bool,
    ) -> Result<()> {
        for e in fs::read_dir(dir).map_err(err)? {
            let e = e.map_err(err)?;
            let p = e.path();
            let r = p
                .strip_prefix(root)
                .map_err(err)?
                .to_str()
                .ok_or("non UTF-8 source path")?
                .to_owned();
            if allow_target && r == "target" {
                need(
                    e.file_type().map_err(err)?.is_dir(),
                    "target is not a real directory",
                )?;
                continue;
            }
            let k = e.file_type().map_err(err)?;
            if k.is_dir() {
                visit(root, &p, out, allow_target)?;
            } else {
                need(
                    k.is_file(),
                    "symlinks/special files refused in source closure",
                )?;
                out.insert(r);
            }
        }
        Ok(())
    }
    let mut out = BTreeSet::new();
    visit(root, root, &mut out, allow_target)?;
    Ok(out)
}
fn context(repo: &Path, revision: &str, dest: &Path) -> Result<()> {
    let commit = String::from_utf8(git(
        repo,
        &[
            "rev-parse",
            "--verify",
            "--end-of-options",
            &format!("{revision}^{{commit}}"),
        ],
    )?)
    .map_err(err)?
    .trim()
    .to_owned();
    need(
        commit.len() == 40 && commit.bytes().all(|c| c.is_ascii_hexdigit()),
        "invalid Git commit",
    )?;
    let listing = git(repo, &["ls-tree", "-rz", &commit])?;
    let mut blobs = Vec::new();
    for row in listing.split(|&b| b == 0).filter(|b| !b.is_empty()) {
        let (header, path) = row
            .split_once_byte(b'\t')
            .ok_or("invalid Git tree record")?;
        let header = std::str::from_utf8(header)
            .map_err(err)?
            .split(' ')
            .collect::<Vec<_>>();
        let path = std::str::from_utf8(path).map_err(err)?;
        need(
            header.len() == 3
                && ["100644", "100755"].contains(&header[0])
                && header[1] == "blob"
                && safe(path)
                && path != SOURCE
                && !path.starts_with("target/"),
            "unsupported Git source entry",
        )?;
        blobs.push((path.to_owned(), header[2].to_owned(), header[0] == "100755"));
    }
    need(!blobs.is_empty(), "empty Git source closure")?;
    let temp = fresh(dest)?;
    let mut files = BTreeMap::new();
    // Read exact blobs, never checkout bytes. A dirty workspace cannot enter.
    for (path, oid, execute) in blobs {
        let bytes = git(repo, &["cat-file", "blob", &oid])?;
        need(bytes.len() <= 256 * 1024 * 1024, "oversize Git blob")?;
        let to = temp.path().join(&path);
        fs::create_dir_all(to.parent().unwrap()).map_err(err)?;
        write(&to, &bytes)?;
        #[cfg(unix)]
        if execute {
            use std::os::unix::fs::PermissionsExt;
            fs::set_permissions(&to, fs::Permissions::from_mode(0o755)).map_err(err)?;
        }
        files.insert(path, runtime::pin(&bytes));
    }
    let manifest = SourceManifest {
        format: "pinax.backfill.producer-source/v1".into(),
        repository: "pinax-network/substreams-backfills".into(),
        source_commit: commit,
        files,
    };
    write(&temp.path().join(SOURCE), &json(&manifest)?)?;
    verify_source(temp.path())?;
    publish(temp, dest)
}
fn verify_source(root: &Path) -> Result<SourceManifest> {
    let m: SourceManifest = decode(&read(&root.join(SOURCE))?)?;
    need(
        m.format == "pinax.backfill.producer-source/v1"
            && m.repository == "pinax-network/substreams-backfills"
            && !m.files.is_empty(),
        "source identity mismatch",
    )?;
    let mut expected: BTreeSet<String> = m.files.keys().cloned().collect();
    expected.insert(SOURCE.into());
    need(
        walk(root, true)? == expected,
        "source context inventory changed",
    )?;
    for (path, pin) in &m.files {
        need(
            safe(path) && runtime::pin(&read(&root.join(path))?) == *pin,
            "source context digest changed",
        )?;
    }
    Ok(m)
}
fn build_bundle(root: &Path, spkg: &Path, lock: &Path, dest: &Path) -> Result<()> {
    let source = verify_source(root)?;
    let bytes = read(spkg)?;
    let lock_bytes = read(lock)?;
    let lock: ExtractorLock = decode(&lock_bytes)?;
    need(
        !lock.production_selectable,
        "this build path is non-final only",
    )?;
    runtime::verify_package(&bytes, &lock.identity).map_err(err)?;
    let target = root
        .canonicalize()
        .map_err(err)?
        .join("target/producer-runtime-build");
    // CARGO_TARGET_DIR is isolated from user cache and kept outside source pins.
    let status = Command::new("cargo")
        .current_dir(root)
        .args([
            "build",
            "--locked",
            "--release",
            "--package",
            "aerodrome-slipstream-reducer",
            "--bin",
            "producer",
        ])
        .env("CARGO_TARGET_DIR", &target)
        .status()
        .map_err(err)?;
    need(status.success(), "producer build failed")?;
    verify_source(root)?;
    seal_bundle(
        &source,
        &read(&root.join(SOURCE))?,
        &read(&target.join("release/producer"))?,
        &bytes,
        &lock_bytes,
        &lock,
        dest,
    )
}
fn seal_bundle(
    source: &SourceManifest,
    source_bytes: &[u8],
    binary: &[u8],
    spkg: &[u8],
    lock_bytes: &[u8],
    lock: &ExtractorLock,
    dest: &Path,
) -> Result<()> {
    let temp = fresh(dest)?;
    for d in ["bin", "contract", "spkg"] {
        fs::create_dir(temp.path().join(d)).map_err(err)?;
    }
    let descriptor =
        identity::build_descriptor(&lock.identity, &source.source_commit, true).map_err(err)?;
    let contents = BTreeMap::from([
        ("bin/producer", binary.to_vec()),
        ("source.json", source_bytes.to_vec()),
        (
            "contract/compatibility.json",
            json(&FamilyContract::aerodrome())?,
        ),
        (
            "contract/block-changes-descriptor.json.sha256",
            format!("{}\n", runtime::hash(&descriptor)).into_bytes(),
        ),
        ("contract/block-changes-descriptor.json", descriptor),
        ("spkg/extractor.spkg", spkg.to_vec()),
        ("spkg/extractor-lock.json", lock_bytes.to_vec()),
        ("spkg/extractor-identity.json", json(&lock.identity)?),
    ]);
    let files = contents
        .iter()
        .map(|(p, b)| ((*p).to_owned(), runtime::pin(b)))
        .collect();
    for (p, b) in contents {
        write(&temp.path().join(p), &b)?;
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(
            temp.path().join("bin/producer"),
            fs::Permissions::from_mode(0o755),
        )
        .map_err(err)?;
    }
    let m = RuntimeManifest {
        format: runtime::FORMAT.into(),
        protocol: runtime::PROTOCOL.into(),
        family: runtime::FAMILY.into(),
        production_selectable: false,
        source_commit: source.source_commit.clone(),
        files,
    };
    write(&temp.path().join("runtime.json"), &json(&m)?)?;
    VerifiedRuntime::load(temp.path(), None).map_err(err)?;
    publish(temp, dest)
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Smoke {
    format: String,
    production_selectable: bool,
    runtime_sha256: String,
    source_commit: String,
    checks: Vec<String>,
    process_exits: BTreeMap<String, i32>,
}
const SMOKE_CHECKS: [&str; 5] = [
    "version_identity",
    "stage_identity",
    "stage_no_clobber",
    "non_final_refusal",
    "empty_seed",
];
fn smoke_exits() -> BTreeMap<String, i32> {
    [
        ("version", 0),
        ("stage", 0),
        ("stage_existing", 4),
        ("non_final_seed", 5),
        ("seed", 0),
    ]
    .into_iter()
    .map(|(k, v)| (k.into(), v))
    .collect()
}
impl Smoke {
    fn validate(&self) -> Result<()> {
        need(
            self.format == "pinax.backfill.producer-smoke/v1"
                && !self.production_selectable
                && self.checks.iter().map(String::as_str).eq(SMOKE_CHECKS)
                && self.process_exits == smoke_exits(),
            "incomplete smoke checks or unexpected actual exits",
        )
    }
}

fn smoke(root: &Path, dest: &Path) -> Result<()> {
    let v = VerifiedRuntime::load(root, None).map_err(err)?;
    let root = root.canonicalize().map_err(err)?;
    let binary = root.join("bin/producer");
    let temp = fresh(dest)?;
    let invoke = |args: &[&str]| {
        let mut c = Command::new(&binary);
        c.arg("--runtime-root").arg(&root).args(args);
        c.output().map_err(err)
    };
    let version = invoke(&["version", "--json"])?;
    need(
        version.status.success() && version.stdout == v.manifest_bytes(),
        "version smoke failed",
    )?;
    let staged = temp.path().join("staged");
    let stage = invoke(&[
        "stage",
        "--dest",
        staged.to_str().ok_or("invalid stage path")?,
    ])?;
    need(stage.status.success(), "stage smoke failed")?;
    VerifiedRuntime::load(&staged, Some(&runtime::hash(v.manifest_bytes()))).map_err(err)?;
    let twice = invoke(&["stage", "--dest", staged.to_str().unwrap()])?;
    need(!twice.status.success(), "stage clobber guard failed")?;
    let state = temp.path().join("state");
    let state = state.to_str().ok_or("invalid state path")?;
    let refusal = invoke(&[
        "seed",
        "--empty",
        "--start-block",
        "13843704",
        "--out",
        state,
        "--engine-lineage",
        &"ab".repeat(32),
    ])?;
    need(
        !refusal.status.success() && !Path::new(state).exists(),
        "non-final execution gate failed",
    )?;
    let seeded = invoke(&[
        "--allow-non-final",
        "seed",
        "--empty",
        "--start-block",
        "13843704",
        "--out",
        state,
        "--engine-lineage",
        &"ab".repeat(32),
    ])?;
    need(
        seeded.status.success(),
        &format!(
            "empty seed smoke failed: {}",
            String::from_utf8_lossy(&seeded.stderr)
        ),
    )?;
    let m = Smoke {
        format: "pinax.backfill.producer-smoke/v1".into(),
        production_selectable: false,
        runtime_sha256: runtime::hash(v.manifest_bytes()),
        source_commit: v.manifest().source_commit.clone(),
        process_exits: [
            ("version", &version),
            ("stage", &stage),
            ("stage_existing", &twice),
            ("non_final_seed", &refusal),
            ("seed", &seeded),
        ]
        .into_iter()
        .map(|(name, output)| {
            Ok((
                name.into(),
                output
                    .status
                    .code()
                    .ok_or("smoke child terminated by signal")?,
            ))
        })
        .collect::<Result<_>>()?,
        checks: vec![
            "version_identity".into(),
            "stage_identity".into(),
            "stage_no_clobber".into(),
            "non_final_refusal".into(),
            "empty_seed".into(),
        ],
    };
    m.validate()?;
    write(&temp.path().join("smoke.json"), &json(&m)?)?;
    publish(temp, dest)
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Discovery {
    format: String,
    production_selectable: bool,
    source_commit: String,
    runtime_sha256: String,
    archive: FilePin,
    smoke: FilePin,
}
fn archive(root: &Path, smoke_path: &Path, dest: &Path) -> Result<()> {
    let runtime = VerifiedRuntime::load(root, None).map_err(err)?;
    let smoke_bytes = read(smoke_path)?;
    let smoke: Smoke = decode(&smoke_bytes)?;
    smoke.validate()?;
    need(
        smoke.format == "pinax.backfill.producer-smoke/v1"
            && !smoke.production_selectable
            && smoke.runtime_sha256 == runtime::hash(runtime.manifest_bytes())
            && smoke.source_commit == runtime.manifest().source_commit,
        "smoke runtime mismatch",
    )?;
    let temp = fresh(dest)?;
    let path = temp.path().join("producer-runtime.tar");
    write(&path, &archive_bytes(root)?)?;
    let d = Discovery {
        format: "pinax.backfill.producer-discovery/v1".into(),
        production_selectable: false,
        source_commit: runtime.manifest().source_commit.clone(),
        runtime_sha256: runtime::hash(runtime.manifest_bytes()),
        archive: runtime::pin(&read(&path)?),
        smoke: runtime::pin(&smoke_bytes),
    };
    write(&temp.path().join("smoke.json"), &smoke_bytes)?;
    write(&temp.path().join("discovery.json"), &json(&d)?)?;
    verify_discovery(temp.path())?;
    publish(temp, dest)
}
fn archive_bytes(root: &Path) -> Result<Vec<u8>> {
    let mut tar = tar::Builder::new(Vec::new());
    for p in runtime::FILES.into_iter().chain(["runtime.json"]) {
        let bytes = read(&root.join(p))?;
        let mut h = tar::Header::new_gnu();
        h.set_size(bytes.len() as u64);
        h.set_mode(if p == "bin/producer" { 0o755 } else { 0o644 });
        h.set_uid(0);
        h.set_gid(0);
        h.set_mtime(0);
        h.set_cksum();
        tar.append_data(&mut h, p, bytes.as_slice()).map_err(err)?;
    }
    tar.into_inner().map_err(err)
}

fn verify_discovery(root: &Path) -> Result<()> {
    need(
        walk(root, false)?
            == BTreeSet::from([
                "discovery.json".into(),
                "producer-runtime.tar".into(),
                "smoke.json".into(),
            ]),
        "discovery inventory mismatch",
    )?;
    let d: Discovery = decode(&read(&root.join("discovery.json"))?)?;
    need(
        d.format == "pinax.backfill.producer-discovery/v1" && !d.production_selectable,
        "unsupported discovery",
    )?;
    let archive = read(&root.join("producer-runtime.tar"))?;
    let smoke = read(&root.join("smoke.json"))?;
    need(
        runtime::pin(&archive) == d.archive && runtime::pin(&smoke) == d.smoke,
        "discovery payload hash mismatch",
    )?;
    let tmp = tempfile::tempdir().map_err(err)?;
    let mut seen = BTreeSet::new();
    let expected: BTreeSet<String> = runtime::FILES
        .into_iter()
        .chain(["runtime.json"])
        .map(str::to_owned)
        .collect();
    for entry in tar::Archive::new(archive.as_slice())
        .entries()
        .map_err(err)?
    {
        let mut entry = entry.map_err(err)?;
        let p = entry
            .path()
            .map_err(err)?
            .to_str()
            .ok_or("non UTF-8 archive path")?
            .to_owned();
        need(
            expected.contains(&p)
                && seen.insert(p.clone())
                && entry.header().entry_type().is_file(),
            "archive traversal/duplicate/unknown/special entry",
        )?;
        let target = tmp.path().join(&p);
        fs::create_dir_all(target.parent().unwrap()).map_err(err)?;
        let mut bytes = Vec::new();
        need(entry.size() <= 256 * 1024 * 1024, "oversize archive entry")?;
        entry.read_to_end(&mut bytes).map_err(err)?;
        write(&target, &bytes)?;
        #[cfg(unix)]
        if p == "bin/producer" {
            use std::os::unix::fs::PermissionsExt;
            fs::set_permissions(target, fs::Permissions::from_mode(0o755)).map_err(err)?;
        }
    }
    need(seen == expected, "archive incomplete")?;
    need(
        archive_bytes(tmp.path())? == archive,
        "archive is not canonical or has trailing bytes",
    )?;
    let v = VerifiedRuntime::load(tmp.path(), Some(&d.runtime_sha256)).map_err(err)?;
    let s: Smoke = decode(&smoke)?;
    s.validate()?;
    need(
        v.manifest().source_commit == d.source_commit
            && s.format == "pinax.backfill.producer-smoke/v1"
            && s.runtime_sha256 == d.runtime_sha256
            && s.source_commit == d.source_commit
            && !s.production_selectable,
        "discovery identity mismatch",
    )
}
trait SplitByte {
    fn split_once_byte(&self, b: u8) -> Option<(&[u8], &[u8])>;
}
impl SplitByte for [u8] {
    fn split_once_byte(&self, b: u8) -> Option<(&[u8], &[u8])> {
        let n = self.iter().position(|&x| x == b)?;
        Some((&self[..n], &self[n + 1..]))
    }
}

pub fn run(args: &[String]) -> Result<()> {
    let command=args.first().ok_or("producer-runtime requires context|verify-source|build-bundle|smoke|archive|verify-discovery")?;
    let mut opts = BTreeMap::new();
    let (pairs, remainder) = args[1..].as_chunks::<2>();
    for pair in pairs {
        need(
            pair[0].starts_with("--") && opts.insert(pair[0].as_str(), pair[1].as_str()).is_none(),
            "invalid/duplicate packaging option",
        )?;
    }
    need(remainder.is_empty(), "missing packaging option value")?;
    let allowed = match command.as_str() {
        "context" => vec!["--root", "--revision", "--output"],
        "verify-source" => vec!["--root", "--revision"],
        "verify-discovery" => vec!["--root"],
        "build-bundle" => vec!["--root", "--spkg", "--extractor-lock", "--output"],
        "smoke" => vec!["--root", "--output"],
        "archive" => vec!["--root", "--smoke", "--output"],
        _ => return Err("unknown producer-runtime command".into()),
    };
    need(
        opts.keys().all(|k| allowed.contains(k)),
        "unknown packaging option",
    )?;
    let get = |k| opts.get(k).copied().ok_or_else(|| format!("missing {k}"));
    let root = Path::new(get("--root")?);
    match command.as_str() {
        "context" => context(root, get("--revision")?, Path::new(get("--output")?)),
        "verify-source" => {
            let source = verify_source(root)?;
            if let Some(expected) = opts.get("--revision") {
                need(
                    source.source_commit == *expected,
                    "source commit differs from external revision",
                )?;
            }
            Ok(())
        }
        "build-bundle" => build_bundle(
            root,
            Path::new(get("--spkg")?),
            Path::new(get("--extractor-lock")?),
            Path::new(get("--output")?),
        ),
        "smoke" => smoke(root, Path::new(get("--output")?)),
        "archive" => archive(
            root,
            Path::new(get("--smoke")?),
            Path::new(get("--output")?),
        ),
        "verify-discovery" => verify_discovery(root),
        _ => unreachable!(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn repo() -> tempfile::TempDir {
        let t = tempfile::tempdir().unwrap();
        git(t.path(), &["init", "--quiet"]).unwrap();
        fs::write(t.path().join("Cargo.toml"), b"tracked committed source").unwrap();
        fs::create_dir(t.path().join("include")).unwrap();
        fs::write(t.path().join("include/abi.json"), b"{\"locked\":true}\n").unwrap();
        git(t.path(), &["add", "."]).unwrap();
        git(
            t.path(),
            &[
                "-c",
                "user.name=Runtime Test",
                "-c",
                "user.email=runtime@example.invalid",
                "commit",
                "--quiet",
                "-m",
                "fixture",
            ],
        )
        .unwrap();
        t
    }
    #[test]
    fn context_reads_committed_objects_and_refuses_mutation_or_extra_files() {
        let r = repo();
        let out = tempfile::tempdir().unwrap();
        let target = out.path().join("context");
        fs::write(r.path().join("Cargo.toml"), b"dirty replacement").unwrap();
        fs::write(r.path().join("untracked-secret"), b"not a build input").unwrap();
        context(r.path(), "HEAD", &target).unwrap();
        assert_eq!(
            read(&target.join("Cargo.toml")).unwrap(),
            b"tracked committed source"
        );
        assert!(!target.join("untracked-secret").exists());
        assert!(context(r.path(), "HEAD", &target).is_err());
        verify_source(&target).unwrap();
        fs::write(target.join("include/abi.json"), b"changed").unwrap();
        assert!(verify_source(&target).is_err());
        fs::write(target.join("include/abi.json"), b"{\"locked\":true}\n").unwrap();
        fs::write(target.join("unexpected.rs"), b"extra").unwrap();
        assert!(verify_source(&target).is_err());
    }
    #[cfg(unix)]
    #[test]
    fn context_refuses_tracked_symlinks_without_publishing() {
        let r = repo();
        std::os::unix::fs::symlink("Cargo.toml", r.path().join("linked")).unwrap();
        git(r.path(), &["add", "linked"]).unwrap();
        git(
            r.path(),
            &[
                "-c",
                "user.name=Runtime Test",
                "-c",
                "user.email=runtime@example.invalid",
                "commit",
                "--quiet",
                "-m",
                "symlink",
            ],
        )
        .unwrap();
        let out = tempfile::tempdir().unwrap();
        let target = out.path().join("context");
        assert!(context(r.path(), "HEAD", &target).is_err());
        assert!(!target.exists());
    }
    fn bundle(dest: &Path) {
        let source = SourceManifest {
            format: "pinax.backfill.producer-source/v1".into(),
            repository: "pinax-network/substreams-backfills".into(),
            source_commit: "ab".repeat(20),
            files: BTreeMap::from([("Cargo.toml".into(), runtime::pin(b"fixture"))]),
        };
        let spkg = include_bytes!(
            "../../crates/aerodrome-slipstream-reducer/fixtures/runtime/synthetic-extractor.spkg"
        );
        let identity=serde_json::from_slice(include_bytes!("../../crates/aerodrome-slipstream-reducer/fixtures/runtime/synthetic-extractor-identity.json")).unwrap();
        let lock = ExtractorLock {
            format: "pinax.backfill.extractor-lock/v1".into(),
            source_commit: "cd".repeat(20),
            production_selectable: false,
            identity,
        };
        seal_bundle(
            &source,
            &json(&source).unwrap(),
            b"synthetic binary",
            spkg,
            &json(&lock).unwrap(),
            &lock,
            dest,
        )
        .unwrap();
    }
    #[test]
    fn archive_roundtrip_is_closed_and_tampering_refuses() {
        let t = tempfile::tempdir().unwrap();
        let b = t.path().join("bundle");
        bundle(&b);
        let v = VerifiedRuntime::load(&b, None).unwrap();
        // Unit fixture manifest is a declaration, never evidence of subprocess execution.
        let s = Smoke {
            format: "pinax.backfill.producer-smoke/v1".into(),
            production_selectable: false,
            runtime_sha256: runtime::hash(v.manifest_bytes()),
            source_commit: v.manifest().source_commit.clone(),
            checks: SMOKE_CHECKS.into_iter().map(str::to_owned).collect(),
            process_exits: smoke_exits(),
        };
        let smoke = t.path().join("smoke.json");
        write(&smoke, &json(&s).unwrap()).unwrap();
        let out = t.path().join("archive");
        archive(&b, &smoke, &out).unwrap();
        verify_discovery(&out).unwrap();
        assert!(archive(&b, &smoke, &out).is_err());
        let tar = out.join("producer-runtime.tar");
        let mut bytes = read(&tar).unwrap();
        bytes[0] ^= 1;
        fs::write(tar, bytes).unwrap();
        assert!(verify_discovery(&out).is_err());
    }
    #[test]
    fn archive_rehashed_trailing_bytes_and_symlink_entries_refuse() {
        let t = tempfile::tempdir().unwrap();
        let b = t.path().join("bundle");
        bundle(&b);
        let v = VerifiedRuntime::load(&b, None).unwrap();
        let smoke = Smoke {
            format: "pinax.backfill.producer-smoke/v1".into(),
            production_selectable: false,
            runtime_sha256: runtime::hash(v.manifest_bytes()),
            source_commit: v.manifest().source_commit.clone(),
            checks: SMOKE_CHECKS.into_iter().map(str::to_owned).collect(),
            process_exits: smoke_exits(),
        };
        let p = t.path().join("smoke.json");
        write(&p, &json(&smoke).unwrap()).unwrap();
        let out = t.path().join("archive");
        archive(&b, &p, &out).unwrap();
        let path = out.join("producer-runtime.tar");
        let mut bytes = read(&path).unwrap();
        bytes.extend(b"hidden payload");
        fs::write(&path, &bytes).unwrap();
        let dp = out.join("discovery.json");
        let mut d: Discovery = decode(&read(&dp).unwrap()).unwrap();
        d.archive = runtime::pin(&bytes);
        fs::write(&dp, json(&d).unwrap()).unwrap();
        assert!(verify_discovery(&out)
            .unwrap_err()
            .contains("trailing bytes"));
        let mut writer = tar::Builder::new(Vec::new());
        let mut h = tar::Header::new_gnu();
        h.set_size(0);
        h.set_mode(0o644);
        h.set_entry_type(tar::EntryType::Symlink);
        h.set_link_name("/outside").unwrap();
        h.set_cksum();
        writer.append_data(&mut h, "bin/producer", &[][..]).unwrap();
        let bytes = writer.into_inner().unwrap();
        fs::write(&path, &bytes).unwrap();
        d.archive = runtime::pin(&bytes);
        fs::write(&dp, json(&d).unwrap()).unwrap();
        assert!(verify_discovery(&out)
            .unwrap_err()
            .contains("special entry"));
    }
    #[test]
    fn workflow_separates_read_only_candidate_from_explicit_main_publication() {
        let value: serde_yaml::Value =
            serde_yaml::from_str(include_str!("../../.github/workflows/producer-runtime.yml"))
                .unwrap();
        assert_eq!(value["permissions"]["contents"].as_str(), Some("read"));
        assert_eq!(
            value["jobs"]["candidate"]["if"].as_str(),
            Some("github.event_name == 'workflow_dispatch'")
        );
        for job in ["candidate", "publish"] {
            let steps = value["jobs"][job]["steps"].as_sequence().unwrap();
            let setup = steps
                .iter()
                .position(|s| s["name"].as_str() == Some("Enable OCI-capable Docker image store"))
                .unwrap();
            assert_eq!(
                steps[setup]["uses"].as_str(),
                Some("docker/setup-docker-action@7ec28a010822b4626af4874f9448a4b05ac6f3e5")
            );
            let config: serde_json::Value =
                serde_json::from_str(steps[setup]["with"]["daemon-config"].as_str().unwrap())
                    .unwrap();
            assert_eq!(
                config,
                serde_json::json!({"features":{"containerd-snapshotter":true}})
            );
            let first_load = steps
                .iter()
                .position(|s| {
                    s["run"]
                        .as_str()
                        .unwrap_or("")
                        .contains("docker load --input")
                })
                .unwrap();
            assert!(setup < first_load);
        }
        let steps = value["jobs"]["candidate"]["steps"].as_sequence().unwrap();
        let build = steps
            .iter()
            .find(|s| s["uses"].as_str() == Some("docker/build-push-action@v6"))
            .unwrap();
        assert_eq!(build["with"]["push"].as_bool(), Some(false));
        assert!(build["with"]["outputs"]
            .as_str()
            .unwrap()
            .starts_with("type=oci,"));
        assert_eq!(build["with"]["provenance"].as_bool(), Some(false));
        assert_eq!(build["with"]["sbom"].as_bool(), Some(false));
        let smoke = steps
            .iter()
            .find(|s| {
                s["name"].as_str() == Some("Inspect and smoke the actual candidate image offline")
            })
            .unwrap()["run"]
            .as_str()
            .unwrap();
        assert!(
            smoke.find("docker load --input").unwrap()
                < smoke.find("docker image inspect").unwrap()
        );
        assert!(steps
            .iter()
            .all(|s| !s["run"].as_str().unwrap_or("").contains("docker-daemon:")));
        let upload = steps
            .iter()
            .find(|s| s["id"].as_str() == Some("upload"))
            .unwrap();
        assert_eq!(upload["if"].as_str(), Some("always()"));
        assert!(steps
            .iter()
            .all(|s| !s["run"].as_str().unwrap_or("").contains("docker push")));
        assert!(value["jobs"]["candidate"]["permissions"].is_null());
        assert_eq!(
            value["on"]["workflow_dispatch"]["inputs"]["publish_candidate"]["default"].as_bool(),
            Some(false)
        );
        let publish = &value["jobs"]["publish"];
        assert_eq!(publish["if"].as_str(), Some("github.event_name == 'workflow_dispatch' && inputs.publish_candidate && github.ref == 'refs/heads/main'"));
        assert_eq!(publish["needs"].as_str(), Some("candidate"));
        assert_eq!(publish["permissions"]["contents"].as_str(), Some("write"));
        assert_eq!(publish["permissions"]["packages"].as_str(), Some("write"));
        let steps = publish["steps"].as_sequence().unwrap();
        let checks = steps
            .iter()
            .position(|s| {
                s["name"].as_str()
                    == Some("Verify retained image and require unchanged canonical main")
            })
            .unwrap();
        let registry = steps
            .iter()
            .position(|s| {
                s["name"].as_str()
                    == Some("Publish candidate and independently retrieve its exact OCI manifest")
            })
            .unwrap();
        let release = steps
            .iter()
            .position(|s| {
                s["name"].as_str() == Some("Publish retained non-final evidence as a prerelease")
            })
            .unwrap();
        assert!(checks < registry && registry < release);
        let check = steps[checks]["run"].as_str().unwrap();
        assert!(check.contains("git ls-remote origin refs/heads/main"));
        assert!(check.contains("EXPECTED_SOURCE") && check.contains("GITHUB_SHA"));
        let registry = steps[registry]["run"].as_str().unwrap();
        assert!(registry.contains("--preserve-digests"));
        assert!(registry.contains("docker load --input"));
        assert!(!registry.contains("docker-daemon:"));
        assert!(registry.contains("--expected-manifest"));
        assert!(registry.contains("docker run --rm --network none"));
        assert!(registry.contains("--password-stdin"));
        assert!(steps[release]["run"]
            .as_str()
            .unwrap()
            .contains("--prerelease --latest=false"));
    }
    #[test]
    fn parser_refuses_unknown_and_duplicate_options() {
        for args in [
            vec!["context", "--root", "a", "--root", "b"],
            vec!["verify-source", "--root", "a", "--unknown", "b"],
            vec!["context", "--root"],
        ] {
            assert!(run(&args.into_iter().map(str::to_owned).collect::<Vec<_>>()).is_err());
        }
    }
}
