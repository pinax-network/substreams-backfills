//! Frozen source-import verification (port of `verify-uniswap-v4-import.sh`,
//! `verify-uniswap-v3-import.sh`, `build-uniswap-v{3,4}-import-inventory.py`,
//! and `verify-uniswap-v3-logical-contract.py`, #110).
//!
//! Each import has an isolated upstream history mirror ref, an exact source
//! commit and tree, a subtree in this repository that must equal that tree
//! byte for byte, a complete SHA-256 file inventory, and a provenance lock
//! binding the inventory. Nothing here modifies the frozen bytes.

use std::collections::{BTreeMap, BTreeSet};
use std::fmt;
use std::path::{Path, PathBuf};
use std::process::Command;

use serde_json::{json, Value};
use sha2::{Digest, Sha256};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ImportError(pub String);

impl fmt::Display for ImportError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for ImportError {}

pub type Result<T> = std::result::Result<T, ImportError>;

fn fail<T>(message: impl Into<String>) -> Result<T> {
    Err(ImportError(message.into()))
}

/// One frozen import contract.
pub struct ImportContract {
    pub label: &'static str,
    pub source_commit: &'static str,
    pub source_tree: &'static str,
    pub source_ref: &'static str,
    pub import_path: &'static str,
    pub tracked_files: usize,
    pub executable_files: usize,
    pub inventory_path: &'static str,
    /// V3 only: provenance lock that binds the inventory digest.
    pub provenance_path: Option<&'static str>,
    /// Frozen packages inside the import that must keep exact digests.
    pub frozen_packages: &'static [(&'static str, &'static str)],
}

pub const UNISWAP_V4: ImportContract = ImportContract {
    label: "Uniswap V4",
    source_commit: "6812a4deaa5a520020e8d727e17f6d0b7113d0a9",
    source_tree: "2d60d30242443adc2c021a5b609c27edcb75128a",
    source_ref: "refs/remotes/origin/upstream/uniswap-v4-v0.4.1",
    import_path: "uniswap-v4",
    tracked_files: 98,
    executable_files: 13,
    inventory_path: "docs/provenance/uniswap-v4-v0.4.1-files.json",
    provenance_path: None,
    frozen_packages: &[
        (
            "ac3b295591e68949881509379aa99d8460134873f895187746a35ece003fa440",
            "uniswap-v4/release/v0.4.0/uniswap-v4-base-state-stores-v0.1.0.spkg",
        ),
        (
            "7cf06bb4b73c1409c581a7f878fb832c3e15c1d82193103d8bc7609dce8b58f3",
            "uniswap-v4/release/v0.4.0/uniswap-v4-base-store-fed-reducer-v0.1.0.spkg",
        ),
        (
            "bc8a841dbb74f9bbc7d90826251ab766ad350170a4832fc3e9b084664d22254a",
            "uniswap-v4/release/v0.4.0/uniswap-v4-base-store-state-reducer-v0.4.0.spkg",
        ),
    ],
};

pub const UNISWAP_V3: ImportContract = ImportContract {
    label: "Uniswap V3",
    source_commit: "42c7b15345e6df80561b694e52a0eb622b374b96",
    source_tree: "a00e882e92d07b46550b74dea279c114d57631ac",
    source_ref: "refs/remotes/origin/upstream/uniswap-v3-qma8a81t-parity",
    import_path: "uniswap-v3/source",
    tracked_files: 75,
    executable_files: 1,
    inventory_path: "docs/provenance/uniswap-v3-qma8a81t-parity-files.json",
    provenance_path: Some("docs/provenance/uniswap-v3-qma8a81t-parity.json"),
    frozen_packages: &[],
};

fn git(root: &Path, args: &[&str]) -> Result<Vec<u8>> {
    let output = Command::new("git")
        .arg("-C")
        .arg(root)
        .args(args)
        .output()
        .map_err(|e| ImportError(format!("git {}: {e}", args.join(" "))))?;
    if !output.status.success() {
        return fail(format!(
            "git {} failed: {}",
            args.join(" "),
            String::from_utf8_lossy(&output.stderr).trim()
        ));
    }
    Ok(output.stdout)
}

fn git_text(root: &Path, args: &[&str]) -> Result<String> {
    Ok(String::from_utf8_lossy(&git(root, args)?)
        .trim()
        .to_string())
}

/// `git ls-tree -r -z --long <revision>` as (path, mode, size, blob) records.
pub fn ls_tree(root: &Path, revision: &str) -> Result<Vec<(String, String, u64, String)>> {
    let raw = git(root, &["ls-tree", "-r", "-z", "--long", revision])?;
    let mut records = Vec::new();
    for record in raw.split(|b| *b == 0) {
        if record.is_empty() {
            continue;
        }
        let tab = record
            .iter()
            .position(|b| *b == b'\t')
            .ok_or_else(|| ImportError("malformed ls-tree record".into()))?;
        let metadata = String::from_utf8_lossy(&record[..tab]).to_string();
        let path = String::from_utf8(record[tab + 1..].to_vec())
            .map_err(|_| ImportError("non-UTF-8 path in ls-tree".into()))?;
        let parts: Vec<&str> = metadata.split_whitespace().collect();
        if parts.len() != 4 {
            return fail(format!("malformed ls-tree metadata: {metadata}"));
        }
        if parts[1] != "blob" {
            return fail(format!("unexpected Git object type {}", parts[1]));
        }
        let size: u64 = parts[3]
            .parse()
            .map_err(|_| ImportError(format!("bad size in ls-tree: {metadata}")))?;
        records.push((path, parts[0].to_string(), size, parts[2].to_string()));
    }
    Ok(records)
}

/// Complete SHA-256 inventory of the pinned source commit, in ls-tree order.
pub fn build_inventory(root: &Path, contract: &ImportContract) -> Result<Value> {
    let actual_tree = git_text(
        root,
        &["rev-parse", &format!("{}^{{tree}}", contract.source_commit)],
    )?;
    if actual_tree != contract.source_tree {
        return fail(format!("source tree is {actual_tree}"));
    }
    let mut files = Vec::new();
    let mut executables = 0usize;
    for (path, mode, size, blob) in ls_tree(root, contract.source_commit)? {
        let payload = git(root, &["cat-file", "blob", &blob])?;
        if payload.len() as u64 != size {
            return fail(format!("Git size mismatch for {path:?}"));
        }
        if mode == "100755" {
            executables += 1;
        }
        files.push(json!({
            "path": path,
            "mode": mode,
            "size": size,
            "git_blob": blob,
            "sha256": hex::encode(Sha256::digest(&payload)),
        }));
    }
    Ok(json!({
        "format_version": 1,
        "source_commit": contract.source_commit,
        "source_tree": contract.source_tree,
        "file_count": files.len(),
        "executable_count": executables,
        "files": files,
    }))
}

fn read_json(path: &Path) -> Result<Value> {
    let text = std::fs::read_to_string(path)
        .map_err(|e| ImportError(format!("cannot read {}: {e}", path.display())))?;
    serde_json::from_str(&text)
        .map_err(|e| ImportError(format!("cannot parse {}: {e}", path.display())))
}

/// Verify the live filesystem subtree that a materializer would copy: exact
/// file and directory sets, no symlinks, executable bits, sizes, digests.
/// A real top-level `target` directory is tolerated and never inspected.
pub fn verify_live_source_tree(source_dir: &Path, inventory: &Value) -> Result<()> {
    let files = inventory["files"]
        .as_array()
        .ok_or_else(|| ImportError("inventory.files must be an array".into()))?;
    let mut expected: BTreeMap<String, &Value> = BTreeMap::new();
    let mut expected_dirs: BTreeSet<String> = BTreeSet::new();
    for item in files {
        let path = item["path"].as_str().unwrap_or_default().to_string();
        let mut parent = Path::new(&path).parent();
        while let Some(p) = parent {
            if p.as_os_str().is_empty() {
                break;
            }
            expected_dirs.insert(p.to_string_lossy().replace('\\', "/"));
            parent = p.parent();
        }
        expected.insert(path, item);
    }
    let mut actual: BTreeMap<String, PathBuf> = BTreeMap::new();
    let mut actual_dirs: BTreeSet<String> = BTreeSet::new();
    fn walk(
        dir: &Path,
        relative: &str,
        actual: &mut BTreeMap<String, PathBuf>,
        actual_dirs: &mut BTreeSet<String>,
    ) -> Result<()> {
        let entries = std::fs::read_dir(dir)
            .map_err(|e| ImportError(format!("cannot list {}: {e}", dir.display())))?;
        for entry in entries {
            let entry = entry.map_err(|e| ImportError(e.to_string()))?;
            let name = entry.file_name().to_string_lossy().to_string();
            let rel = if relative.is_empty() {
                name.clone()
            } else {
                format!("{relative}/{name}")
            };
            let meta = entry
                .path()
                .symlink_metadata()
                .map_err(|e| ImportError(e.to_string()))?;
            if relative.is_empty() && name == "target" {
                if meta.file_type().is_symlink() || !meta.is_dir() {
                    return fail("live source target must be a real directory when present");
                }
                continue;
            }
            if meta.file_type().is_symlink() {
                return fail(format!("live source contains symlink {rel}"));
            }
            if meta.is_dir() {
                actual_dirs.insert(rel.clone());
                walk(&entry.path(), &rel, actual, actual_dirs)?;
                continue;
            }
            if !meta.is_file() {
                return fail(format!("live source contains non-regular entry {rel}"));
            }
            actual.insert(rel, entry.path());
        }
        Ok(())
    }
    walk(source_dir, "", &mut actual, &mut actual_dirs)?;
    let expected_paths: BTreeSet<&String> = expected.keys().collect();
    let actual_paths: BTreeSet<&String> = actual.keys().collect();
    if expected_paths != actual_paths {
        let missing: Vec<_> = expected_paths.difference(&actual_paths).collect();
        let extra: Vec<_> = actual_paths.difference(&expected_paths).collect();
        return fail(format!(
            "live source file set drift; missing={missing:?}, extra={extra:?}"
        ));
    }
    if expected_dirs != actual_dirs {
        let missing: Vec<_> = expected_dirs.difference(&actual_dirs).collect();
        let extra: Vec<_> = actual_dirs.difference(&expected_dirs).collect();
        return fail(format!(
            "live source directory set drift; missing={missing:?}, extra={extra:?}"
        ));
    }
    for (relative, item) in &expected {
        let path = &actual[relative];
        let meta = path.metadata().map_err(|e| ImportError(e.to_string()))?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let executable = meta.permissions().mode() & 0o111 != 0;
            if executable != (item["mode"].as_str() == Some("100755")) {
                return fail(format!("live source executable mode drift: {relative}"));
            }
        }
        if meta.len() != item["size"].as_u64().unwrap_or_default() {
            return fail(format!("live source size drift: {relative}"));
        }
        let bytes = std::fs::read(path).map_err(|e| ImportError(e.to_string()))?;
        if hex::encode(Sha256::digest(&bytes)) != item["sha256"].as_str().unwrap_or_default() {
            return fail(format!("live source content drift: {relative}"));
        }
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Uniswap V3 logical schema and source-level parity boundaries.

pub const EXPECTED_LOGICAL_SHA256: &str =
    "6c801fc4c141c0ae12dbb937652f0dd49c9be5bd3b1b3c8e38bdb92fe6efec5d";
pub const EXPECTED_ENTITIES: &[&str] = &[
    "Bundle",
    "Burn",
    "Collect",
    "Factory",
    "Flash",
    "Mint",
    "Pool",
    "PoolDayData",
    "PoolHourData",
    "Position",
    "PositionSnapshot",
    "Swap",
    "Tick",
    "TickDayData",
    "TickHourData",
    "Token",
    "TokenDayData",
    "TokenHourData",
    "Transaction",
    "UniswapDayData",
];
pub const EXPECTED_SOURCE_IMMUTABLE: &[&str] = &["Burn", "Mint", "Swap", "Transaction"];

fn is_ident_start(c: char) -> bool {
    c == '_' || c.is_ascii_alphabetic()
}

fn is_ident(c: char) -> bool {
    c == '_' || c.is_ascii_alphanumeric()
}

fn take_ident(s: &str) -> Option<(&str, &str)> {
    let mut chars = s.char_indices();
    let (_, first) = chars.next()?;
    if !is_ident_start(first) {
        return None;
    }
    let end = s
        .char_indices()
        .find(|(_, c)| !is_ident(*c))
        .map(|(i, _)| i)
        .unwrap_or(s.len());
    Some((&s[..end], &s[end..]))
}

/// Parse `type X @entity(...) { field: Type ... }` declarations the way the
/// Python verifier did: comments stripped, one declaration per line, fields
/// captured as `name: Type` where the type token is `[\[\]!_A-Za-z0-9]+`.
pub fn parse_schema(text: &str) -> (BTreeMap<String, BTreeMap<String, String>>, BTreeSet<String>) {
    let mut entities: BTreeMap<String, BTreeMap<String, String>> = BTreeMap::new();
    let mut immutable = BTreeSet::new();
    let mut current: Option<String> = None;
    for raw in text.lines() {
        let line = raw.split('#').next().unwrap_or_default().trim();
        if let Some(rest) = line.strip_prefix("type") {
            if rest.starts_with(char::is_whitespace) {
                let rest = rest.trim_start();
                if let Some((name, after)) = take_ident(rest) {
                    let after = after.trim_start();
                    if let Some(after) = after.strip_prefix("@entity") {
                        let after = after.trim_start();
                        let (directive, tail) = if let Some(stripped) = after.strip_prefix('(') {
                            match stripped.find(')') {
                                Some(end) => {
                                    (Some(&stripped[..end]), stripped[end + 1..].trim_start())
                                }
                                None => (None, after),
                            }
                        } else {
                            (None, after)
                        };
                        if tail.starts_with('{') {
                            current = Some(name.to_string());
                            entities.insert(name.to_string(), BTreeMap::new());
                            if directive.is_some_and(|d| d.contains("immutable")) {
                                immutable.insert(name.to_string());
                            }
                            continue;
                        }
                    }
                }
            }
        }
        if let Some(name) = current.clone() {
            if line == "}" {
                current = None;
                continue;
            }
            if let Some((field, after)) = take_ident(line) {
                let after = after.trim_start();
                if let Some(after) = after.strip_prefix(':') {
                    let after = after.trim_start();
                    let end = after
                        .char_indices()
                        .find(|(_, c)| {
                            !(c.is_ascii_alphanumeric() || matches!(c, '[' | ']' | '!' | '_'))
                        })
                        .map(|(i, _)| i)
                        .unwrap_or(after.len());
                    if end > 0 {
                        entities
                            .get_mut(&name)
                            .expect("current entity exists")
                            .insert(field.to_string(), after[..end].to_string());
                    }
                }
            }
        }
    }
    (entities, immutable)
}

/// `hashlib.sha256(json.dumps(entities, sort_keys=True, separators=(",", ":")))`.
pub fn logical_hash(entities: &BTreeMap<String, BTreeMap<String, String>>) -> String {
    let payload = serde_json::to_string(entities).expect("map serializes");
    hex::encode(Sha256::digest(payload.as_bytes()))
}

fn function_body<'a>(source: &'a str, name: &str) -> Result<&'a str> {
    let needle = format!("fn {name}");
    let mut search = 0usize;
    let start = loop {
        let Some(idx) = source[search..].find(&needle) else {
            return fail(format!("missing function {name}"));
        };
        let abs = search + idx;
        let after = &source[abs + needle.len()..];
        // `\b` after the name: next char must not be an identifier char.
        if after.chars().next().is_none_or(|c| !is_ident(c)) {
            // include a preceding `pub ` if present
            let prefix = &source[..abs];
            let start = if prefix.ends_with("pub ") {
                abs - 4
            } else {
                abs
            };
            break start;
        }
        search = abs + needle.len();
    };
    let body_start = start;
    let rest = &source[start + needle.len()..];
    // next "\n(pub )?fn \w+\b"
    let mut end = source.len();
    let mut offset = 0usize;
    while let Some(nl) = rest[offset..]
        .find("\nfn ")
        .or_else(|| rest[offset..].find("\npub fn "))
    {
        let candidate = offset + nl;
        let line = &rest[candidate + 1..];
        let line = line.strip_prefix("pub ").unwrap_or(line);
        if let Some(after) = line.strip_prefix("fn ") {
            if take_ident(after).is_some() {
                end = start + needle.len() + candidate;
                break;
            }
        }
        offset = candidate + 1;
    }
    Ok(&source[body_start..end])
}

pub fn verify_source_contract(source_root: &Path) -> Result<()> {
    let schema_text = std::fs::read_to_string(source_root.join("schema.graphql"))
        .map_err(|e| ImportError(format!("cannot read schema.graphql: {e}")))?;
    let (schema, immutable) = parse_schema(&schema_text);
    let expected: BTreeSet<String> = EXPECTED_ENTITIES.iter().map(|s| s.to_string()).collect();
    let actual: BTreeSet<String> = schema.keys().cloned().collect();
    if actual != expected {
        let missing: Vec<_> = expected.difference(&actual).collect();
        let extra: Vec<_> = actual.difference(&expected).collect();
        return fail(format!(
            "entity set drift: missing={missing:?}, extra={extra:?}"
        ));
    }
    let hash = logical_hash(&schema);
    if hash != EXPECTED_LOGICAL_SHA256 {
        return fail(format!("logical schema drift: {hash}"));
    }
    let expected_immutable: BTreeSet<String> = EXPECTED_SOURCE_IMMUTABLE
        .iter()
        .map(|s| s.to_string())
        .collect();
    if immutable != expected_immutable {
        return fail(format!(
            "source immutable entities drift: {:?}",
            immutable.iter().collect::<Vec<_>>()
        ));
    }

    let db = std::fs::read_to_string(source_root.join("src/db.rs"))
        .map_err(|e| ImportError(format!("cannot read src/db.rs: {e}")))?;
    let lib = std::fs::read_to_string(source_root.join("src/lib.rs"))
        .map_err(|e| ImportError(format!("cannot read src/lib.rs: {e}")))?;

    let create_pool = function_body(&db, "create_pool")?;
    let pool_tvl = function_body(&db, "total_value_locked_pool_entity_change")?;
    if create_pool.contains("\"totalValueLockedETHUntracked\"")
        || pool_tvl.contains("\"totalValueLockedETHUntracked\"")
    {
        return fail("Pool reintroduced target-absent totalValueLockedETHUntracked");
    }
    let pool_window_tvl = function_body(&db, "total_value_locked_usd_pool_windows")?;
    for required in [
        ".key_last_segment_eq(\"totalValueLockedUSD\")",
        ".set(\"tvlUSD\",",
    ] {
        if !pool_window_tvl.contains(required) {
            return fail(format!(
                "Pool window output/store-key boundary missing {required}"
            ));
        }
    }
    let token_window_volume = function_body(&db, "swap_volume_token_windows")?;
    if !token_window_volume.contains("\"untrackedUSD\" => \"untrackedVolumeUSD\"") {
        return fail("Token window untracked-volume output/store-key boundary drifted");
    }
    if !function_body(&db, "create_pool_windows_entity")?.contains(".set(\"tvlUSD\",") {
        return fail("Pool window create output field tvlUSD drifted");
    }
    if !function_body(&db, "create_token_windows_entity")?.contains(".set(\"untrackedVolumeUSD\",")
    {
        return fail("Token window create output field untrackedVolumeUSD drifted");
    }
    let tick_create = function_body(&db, "tick_windows_create")?;
    let tick_update = function_body(&db, "liquidities_tick_windows")?;
    for required in [
        "\"TickDayData\"",
        "\"TickHourData\"",
        "format!(\"0x{pool_address}#{tick_idx}-{time_id}\")",
        ".set(\"liquidityGross\",",
        ".set(\"liquidityNet\",",
        ".set(\"volumeToken0\",",
        ".set(\"volumeToken1\",",
        ".set(\"volumeUSD\",",
        ".set(\"feesUSD\",",
    ] {
        if !tick_create.contains(required) {
            return fail(format!("tick-window create contract missing {required}"));
        }
    }
    for required in ["\"liquidityGross\"", "\"liquidityNet\""] {
        if !tick_update.contains(required) {
            return fail(format!("tick-window update contract missing {required}"));
        }
    }
    for required in [
        "db::tick_windows_create(&mut tables, &ticks_liquidities_deltas);",
        "db::liquidities_tick_windows(&mut tables, &ticks_liquidities_deltas);",
    ] {
        if !lib.contains(required) {
            return fail(format!("graph_out wiring missing {required}"));
        }
    }
    for (relative, marker) in [
        ("src/utils.rs", "1f98431c8ad98523631ae4a59f267346ea31f984"),
        ("src/price.rs", "8ad599c3a0ff1de082011efddc58f1908eb6e6d8"),
        ("substreams.yaml", "initialblock: 12369621"),
    ] {
        let text = std::fs::read_to_string(source_root.join(relative))
            .map_err(|e| ImportError(format!("cannot read {relative}: {e}")))?;
        if !text.to_lowercase().contains(marker) {
            return fail(format!(
                "mainnet-only marker changed in {relative}; version the import contract"
            ));
        }
    }
    Ok(())
}

// ---------------------------------------------------------------------------

pub fn verify_import(root: &Path, contract: &ImportContract) -> Result<Vec<String>> {
    let mut report = Vec::new();
    let actual_commit = git_text(
        root,
        &[
            "rev-parse",
            "--verify",
            &format!("{}^{{commit}}", contract.source_ref),
        ],
    )?;
    if actual_commit != contract.source_commit {
        return fail(format!("{} points to {actual_commit}", contract.source_ref));
    }
    let actual_tree = git_text(
        root,
        &["rev-parse", &format!("{}^{{tree}}", contract.source_ref)],
    )?;
    if actual_tree != contract.source_tree {
        return fail(format!("source tree is {actual_tree}"));
    }
    let ancestor = Command::new("git")
        .arg("-C")
        .arg(root)
        .args([
            "merge-base",
            "--is-ancestor",
            contract.source_commit,
            "HEAD",
        ])
        .status()
        .map_err(|e| ImportError(format!("git merge-base: {e}")))?;
    if ancestor.success() {
        return fail(
            "upstream history entered the default-branch lineage instead of its isolated mirror",
        );
    }
    let import_tree = git_text(
        root,
        &["rev-parse", &format!("HEAD:{}", contract.import_path)],
    )?;
    if import_tree != contract.source_tree {
        return fail(format!("import tree is {import_tree}"));
    }
    let source_records = ls_tree(root, contract.source_commit)?;
    let import_records = ls_tree(root, &format!("HEAD:{}", contract.import_path))?;
    if source_records.len() != contract.tracked_files {
        return fail(format!(
            "source contains {} tracked files",
            source_records.len()
        ));
    }
    if import_records.len() != contract.tracked_files {
        return fail(format!(
            "import contains {} tracked files",
            import_records.len()
        ));
    }
    let count_exec = |records: &[(String, String, u64, String)]| {
        records.iter().filter(|r| r.1 == "100755").count()
    };
    if count_exec(&source_records) != contract.executable_files {
        return fail(format!(
            "source contains {} executable files",
            count_exec(&source_records)
        ));
    }
    if count_exec(&import_records) != contract.executable_files {
        return fail(format!(
            "import contains {} executable files",
            count_exec(&import_records)
        ));
    }
    for args in [
        vec!["diff", "--quiet", "--", contract.import_path],
        vec!["diff", "--cached", "--quiet", "--", contract.import_path],
    ] {
        let status = Command::new("git")
            .arg("-C")
            .arg(root)
            .args(&args)
            .status()
            .map_err(|e| ImportError(e.to_string()))?;
        if !status.success() {
            return fail(if args.contains(&"--cached") {
                "index modifies the imported source"
            } else {
                "working tree modifies the imported source"
            });
        }
    }
    let inventory = build_inventory(root, contract)?;
    let expected_inventory = read_json(&root.join(contract.inventory_path))?;
    if inventory != expected_inventory {
        return fail(format!(
            "inventory drift: regenerate {}",
            contract.inventory_path
        ));
    }
    report.push(format!(
        "verified {} {} files and {} executable modes",
        inventory["file_count"],
        contract.label.split(' ').next_back().unwrap_or_default(),
        inventory["executable_count"]
    ));
    if let Some(provenance_path) = contract.provenance_path {
        let provenance = read_json(&root.join(provenance_path))?;
        let inventory_bytes = std::fs::read(root.join(contract.inventory_path))
            .map_err(|e| ImportError(e.to_string()))?;
        if provenance["source"]["commit"].as_str() != Some(contract.source_commit) {
            return fail("provenance source commit drift");
        }
        if provenance["source"]["tree"].as_str() != Some(contract.source_tree) {
            return fail("provenance source tree drift");
        }
        let expected_binding = json!({
            "path": contract.inventory_path,
            "sha256": hex::encode(Sha256::digest(&inventory_bytes)),
            "format_version": inventory["format_version"],
            "records": inventory["file_count"],
        });
        if provenance["file_inventory"] != expected_binding {
            return fail("provenance file inventory binding drift");
        }
        verify_live_source_tree(&root.join(contract.import_path), &inventory)
            .map_err(|e| ImportError(format!("live source verification failed: {e}")))?;
        verify_source_contract(&root.join(contract.import_path))
            .map_err(|e| ImportError(format!("logical contract verification failed: {e}")))?;
        report.push("verified 20 logical entities, target field/type hash, renamed output/Store boundaries, tick-window wiring, and the explicit mainnet-only configuration marker".into());
    }
    for (digest, relative) in contract.frozen_packages {
        let bytes = std::fs::read(root.join(relative))
            .map_err(|e| ImportError(format!("cannot read {relative}: {e}")))?;
        let actual = hex::encode(Sha256::digest(&bytes));
        if actual != *digest {
            return fail(format!("{relative} has SHA-256 {actual}"));
        }
    }
    Ok(report)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    fn repository() -> PathBuf {
        Path::new(env!("CARGO_MANIFEST_DIR")).join("..")
    }

    fn source_root() -> PathBuf {
        repository().join("uniswap-v3/source")
    }

    fn copy_source() -> tempfile::TempDir {
        let dir = tempfile::tempdir().unwrap();
        for relative in [
            "schema.graphql",
            "src/db.rs",
            "src/lib.rs",
            "src/utils.rs",
            "src/price.rs",
            "substreams.yaml",
        ] {
            let destination = dir.path().join(relative);
            fs::create_dir_all(destination.parent().unwrap()).unwrap();
            fs::copy(source_root().join(relative), destination).unwrap();
        }
        dir
    }

    fn rewrite(dir: &Path, relative: &str, from: &str, to: &str) {
        let path = dir.join(relative);
        let text = fs::read_to_string(&path).unwrap();
        assert!(text.contains(from), "{relative} lacks {from}");
        fs::write(path, text.replacen(from, to, 1)).unwrap();
    }

    fn rewrite_last(dir: &Path, relative: &str, from: &str, to: &str) {
        let path = dir.join(relative);
        let text = fs::read_to_string(&path).unwrap();
        let idx = text
            .rfind(from)
            .unwrap_or_else(|| panic!("{relative} lacks {from}"));
        let mut out = String::with_capacity(text.len());
        out.push_str(&text[..idx]);
        out.push_str(to);
        out.push_str(&text[idx + from.len()..]);
        fs::write(path, out).unwrap();
    }

    fn error(dir: &Path) -> String {
        verify_source_contract(dir).unwrap_err().to_string()
    }

    #[test]
    fn exact_import_passes() {
        verify_source_contract(&source_root()).unwrap();
        let (schema, immutable) =
            parse_schema(&fs::read_to_string(source_root().join("schema.graphql")).unwrap());
        assert_eq!(schema.len(), 20);
        assert_eq!(logical_hash(&schema), EXPECTED_LOGICAL_SHA256);
        assert_eq!(immutable.len(), 4);
    }

    #[test]
    fn schema_field_drift_is_rejected() {
        let dir = copy_source();
        rewrite(
            dir.path(),
            "schema.graphql",
            "txCount: BigInt!",
            "txCount: BigDecimal!",
        );
        assert!(error(dir.path()).contains("logical schema drift"));
    }

    #[test]
    fn tick_window_wiring_drift_is_rejected() {
        let dir = copy_source();
        rewrite(
            dir.path(),
            "src/lib.rs",
            "db::tick_windows_create(&mut tables, &ticks_liquidities_deltas);",
            "// removed",
        );
        assert!(error(dir.path()).contains("graph_out wiring missing"));
    }

    #[test]
    fn pool_window_store_key_rename_is_rejected() {
        let dir = copy_source();
        rewrite_last(
            dir.path(),
            "src/db.rs",
            ".key_last_segment_eq(\"totalValueLockedUSD\")",
            ".key_last_segment_eq(\"tvlUSD\")",
        );
        assert!(error(dir.path()).contains("Pool window output/store-key boundary"));
    }

    #[test]
    fn token_window_store_key_rename_is_rejected() {
        let dir = copy_source();
        rewrite_last(
            dir.path(),
            "src/db.rs",
            "\"untrackedUSD\" => \"untrackedVolumeUSD\"",
            "\"untrackedVolumeUSD\" => \"untrackedVolumeUSD\"",
        );
        assert!(error(dir.path()).contains("Token window untracked-volume"));
    }

    #[test]
    fn target_absent_pool_field_is_rejected() {
        let dir = copy_source();
        rewrite(
            dir.path(),
            "src/db.rs",
            ".set(\"liquidityProviderCount\", &bigint0);",
            ".set(\"totalValueLockedETHUntracked\", &bigdecimal0)\n        .set(\"liquidityProviderCount\", &bigint0);",
        );
        assert!(error(dir.path()).contains("totalValueLockedETHUntracked"));
    }

    #[test]
    fn mainnet_marker_drift_requires_a_versioned_contract() {
        let dir = copy_source();
        let path = dir.path().join("src/utils.rs");
        let text = fs::read_to_string(&path).unwrap();
        fs::write(
            &path,
            text.replace(
                "1f98431c8ad98523631ae4a59f267346ea31f984",
                "0000000000000000000000000000000000000000",
            ),
        )
        .unwrap();
        assert!(error(dir.path()).contains("mainnet-only marker changed in src/utils.rs"));
    }

    #[test]
    fn repository_inventories_match_committed_files() {
        let root = repository();
        for contract in [&UNISWAP_V3, &UNISWAP_V4] {
            let inventory = build_inventory(&root, contract).unwrap();
            let expected = read_json(&root.join(contract.inventory_path)).unwrap();
            assert_eq!(inventory, expected, "{}", contract.label);
        }
    }

    #[test]
    fn live_source_tree_rejects_symlinks_and_extra_files() {
        let root = repository();
        let inventory = build_inventory(&root, &UNISWAP_V3).unwrap();
        verify_live_source_tree(&root.join("uniswap-v3/source"), &inventory).unwrap();
        let dir = tempfile::tempdir().unwrap();
        let copy = dir.path().join("source");
        fn copy_dir(from: &Path, to: &Path) {
            fs::create_dir_all(to).unwrap();
            for entry in fs::read_dir(from).unwrap() {
                let entry = entry.unwrap();
                let target = to.join(entry.file_name());
                if entry.file_name() == "target" {
                    continue;
                }
                if entry.path().is_dir() {
                    copy_dir(&entry.path(), &target);
                } else {
                    fs::copy(entry.path(), target).unwrap();
                }
            }
        }
        copy_dir(&root.join("uniswap-v3/source"), &copy);
        verify_live_source_tree(&copy, &inventory).unwrap();
        fs::write(copy.join("extra.toml"), b"x").unwrap();
        assert!(verify_live_source_tree(&copy, &inventory)
            .unwrap_err()
            .to_string()
            .contains("file set drift"));
        fs::remove_file(copy.join("extra.toml")).unwrap();
        std::os::unix::fs::symlink(copy.join("Cargo.toml"), copy.join("link.toml")).unwrap();
        assert!(verify_live_source_tree(&copy, &inventory)
            .unwrap_err()
            .to_string()
            .contains("symlink"));
    }
}
