//! Materializes the configured Uniswap V3 runtime trees in Rust.
//!
//! The overlay sources under `uniswap-v3/` are digest-pinned and cannot be
//! edited or copied into the workspace. They are also not, on their own, a
//! buildable tree: the runtime is the frozen import at `uniswap-v3/source`
//! with two `runtime.patch` files applied and a set of configs, manifests and
//! fixtures laid over it. `scripts/materialize-uniswap-v3-*.sh` built that
//! tree with `git archive`, `patch(1)` and `cp`; this crate performs the same
//! steps from Rust so continuous integration needs no shell.
//!
//! Nothing here reproduces the bytes of a pinned file. [`plan::TARGETS`] is a
//! table of paths, and every byte written comes from reading a pinned file or
//! from applying a pinned patch to one.
//!
//! ```no_run
//! # use std::path::Path;
//! uniswap_v3_runtime::materialize(
//!     Path::new("."),
//!     "writer-runtime",
//!     Path::new("/tmp/uniswap-v3-writer-runtime"),
//! )
//! .expect("materializes");
//! ```

pub mod patch;
pub mod plan;

use std::fmt;
use std::fs;
use std::io;
use std::path::{Component, Path, PathBuf};
use std::process::Command;

use plan::{Step, Target};

/// Marks a [`plan::Step::Copy`] source that lives in the destination tree
/// rather than the repository, as `cp "$destination/x" "$destination/y"` does.
const DESTINATION_PREFIX: &str = "@destination/";

#[derive(Debug)]
pub struct Error(String);

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.0)
    }
}

impl std::error::Error for Error {}

impl From<patch::PatchError> for Error {
    fn from(error: patch::PatchError) -> Self {
        Error(error.to_string())
    }
}

fn fail<T>(message: impl Into<String>) -> Result<T, Error> {
    Err(Error(message.into()))
}

fn io_error(what: &dyn fmt::Display, error: io::Error) -> Error {
    Error(format!("{what}: {error}"))
}

/// Materializes `target` and every layer below it into `destination`.
///
/// `destination` must not exist, or must be an empty directory.
pub fn materialize(repository: &Path, target: &str, destination: &Path) -> Result<(), Error> {
    let Some(chain) = plan::chain(target) else {
        let known: Vec<&str> = plan::TARGETS.iter().map(|entry| entry.name).collect();
        return fail(format!(
            "unknown materialization target {target}; known targets: {}",
            known.join(", ")
        ));
    };
    prepare_destination(destination)?;
    for layer in chain {
        run(repository, layer, destination)?;
    }
    Ok(())
}

/// The one-line summary the shell script printed for `target`.
pub fn summary(target: &str) -> Option<&'static str> {
    plan::target(target).map(|entry| entry.summary)
}

fn prepare_destination(destination: &Path) -> Result<(), Error> {
    match fs::symlink_metadata(destination) {
        Ok(metadata) => {
            if !metadata.is_dir() {
                return fail(format!(
                    "destination exists and is not a directory: {}",
                    destination.display()
                ));
            }
            let mut entries = fs::read_dir(destination)
                .map_err(|error| io_error(&destination.display(), error))?;
            if entries.next().is_some() {
                return fail(format!(
                    "destination must be empty: {}",
                    destination.display()
                ));
            }
        }
        Err(error) if error.kind() == io::ErrorKind::NotFound => {
            fs::create_dir_all(destination)
                .map_err(|error| io_error(&destination.display(), error))?;
        }
        Err(error) => return Err(io_error(&destination.display(), error)),
    }
    Ok(())
}

fn run(repository: &Path, target: &Target, destination: &Path) -> Result<(), Error> {
    for step in target.steps {
        match *step {
            Step::Archive { tree } => archive(repository, tree, destination)?,
            Step::ApplyPatch { patch } => apply_patch(repository, patch, destination)?,
            Step::MakeDir { dir } => {
                let path = resolve(destination, dir)?;
                fs::create_dir_all(&path).map_err(|error| io_error(&path.display(), error))?;
                require_real_dir(&path)?;
            }
            Step::Copy { from, to } => {
                let source = match from.strip_prefix(DESTINATION_PREFIX) {
                    Some(rest) => resolve(destination, rest)?,
                    None => resolve(repository, from)?,
                };
                copy(&source, &resolve(destination, to)?)?;
            }
            Step::CopyGlob {
                from,
                prefix,
                suffix,
                to,
            } => {
                let source_dir = resolve(repository, from)?;
                let target_dir = resolve(destination, to)?;
                let matches = glob(&source_dir, prefix, suffix)?;
                if matches.is_empty() {
                    return fail(format!(
                        "no file in {} matches {prefix}*{suffix}",
                        source_dir.display()
                    ));
                }
                for name in matches {
                    copy(&source_dir.join(&name), &target_dir.join(&name))?;
                }
            }
            Step::Remove { path } => {
                let path = resolve(destination, path)?;
                let metadata = fs::symlink_metadata(&path)
                    .map_err(|error| io_error(&path.display(), error))?;
                if !metadata.is_file() {
                    return fail(format!("refusing to remove a non-file: {}", path.display()));
                }
                fs::remove_file(&path).map_err(|error| io_error(&path.display(), error))?;
            }
        }
    }
    Ok(())
}

/// Extracts `HEAD:<tree>` from the repository, as `git archive | tar -x` does.
fn archive(repository: &Path, tree: &str, destination: &Path) -> Result<(), Error> {
    let output = Command::new("git")
        .arg("-C")
        .arg(repository)
        .args(["archive", "--format=tar", &format!("HEAD:{tree}")])
        .output()
        .map_err(|error| Error(format!("cannot run git archive: {error}")))?;
    if !output.status.success() {
        return fail(format!(
            "git archive HEAD:{tree} failed: {}",
            String::from_utf8_lossy(&output.stderr).trim()
        ));
    }
    let mut archive = tar::Archive::new(output.stdout.as_slice());
    archive.set_preserve_permissions(true);
    archive.set_preserve_mtime(false);
    archive
        .unpack(destination)
        .map_err(|error| Error(format!("cannot unpack HEAD:{tree}: {error}")))?;
    // `git archive` records group-writable modes, and `tar -x` clears whatever
    // the process umask covers before creating each entry. Preserving the
    // recorded mode and then masking reaches the same modes the shell pipeline
    // produced, which the import verifiers count.
    umask::apply(destination)?;
    Ok(())
}

/// Reproduces the umask `tar -x` applies to the modes it restores.
mod umask {
    use super::{io_error, Error};
    use std::fs;
    use std::path::Path;

    /// Clears the process umask bits from every file and directory under `root`.
    pub fn apply(root: &Path) -> Result<(), Error> {
        let mask = match probe(root)? {
            0 => return Ok(()),
            mask => mask,
        };
        walk(root, mask)
    }

    #[cfg(unix)]
    fn probe(scratch: &Path) -> Result<u32, Error> {
        use std::fs::OpenOptions;
        use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};

        let path = scratch.join(".umask-probe");
        let _ = fs::remove_file(&path);
        OpenOptions::new()
            .create_new(true)
            .write(true)
            .mode(0o666)
            .open(&path)
            .map_err(|error| io_error(&path.display(), error))?;
        let granted = fs::metadata(&path)
            .map_err(|error| io_error(&path.display(), error))?
            .permissions()
            .mode()
            & 0o777;
        fs::remove_file(&path).map_err(|error| io_error(&path.display(), error))?;
        Ok(0o666 & !granted)
    }

    #[cfg(not(unix))]
    fn probe(_scratch: &Path) -> Result<u32, Error> {
        Ok(0)
    }

    #[cfg(unix)]
    fn walk(root: &Path, mask: u32) -> Result<(), Error> {
        use std::os::unix::fs::PermissionsExt;

        let metadata =
            fs::symlink_metadata(root).map_err(|error| io_error(&root.display(), error))?;
        let mode = metadata.permissions().mode();
        let masked = mode & !mask;
        if masked != mode {
            fs::set_permissions(root, fs::Permissions::from_mode(masked))
                .map_err(|error| io_error(&root.display(), error))?;
        }
        if !metadata.is_dir() {
            return Ok(());
        }
        for entry in fs::read_dir(root).map_err(|error| io_error(&root.display(), error))? {
            let entry = entry.map_err(|error| io_error(&root.display(), error))?;
            walk(&entry.path(), mask)?;
        }
        Ok(())
    }

    #[cfg(not(unix))]
    fn walk(_root: &Path, _mask: u32) -> Result<(), Error> {
        Ok(())
    }
}

/// Applies a unified diff to the destination tree.
fn apply_patch(repository: &Path, relative: &str, destination: &Path) -> Result<(), Error> {
    let patch_path = resolve(repository, relative)?;
    let diff =
        fs::read_to_string(&patch_path).map_err(|error| io_error(&patch_path.display(), error))?;
    for file in patch::parse(&diff)? {
        let path = resolve(destination, &file.path.to_string_lossy())?;
        let old = if file.creates {
            if path.exists() {
                return fail(format!(
                    "{relative} creates a file that already exists: {}",
                    path.display()
                ));
            }
            Vec::new()
        } else {
            let existing =
                fs::read_to_string(&path).map_err(|error| io_error(&path.display(), error))?;
            patch::split_lines(&existing, &path.display())?
        };
        let patched = file
            .apply(&old)
            .map_err(|error| Error(format!("{relative}: {error}")))?;
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).map_err(|error| io_error(&parent.display(), error))?;
        }
        fs::write(&path, patch::join_lines(&patched))
            .map_err(|error| io_error(&path.display(), error))?;
    }
    Ok(())
}

fn copy(source: &Path, target: &Path) -> Result<(), Error> {
    if let Some(parent) = target.parent() {
        require_real_dir(parent)?;
    }
    fs::copy(source, target).map_err(|error| {
        Error(format!(
            "cannot copy {} to {}: {error}",
            source.display(),
            target.display()
        ))
    })?;
    Ok(())
}

/// Lists the names in `dir` matching `prefix*suffix`, sorted, as a shell glob
/// expands them.
fn glob(dir: &Path, prefix: &str, suffix: &str) -> Result<Vec<String>, Error> {
    let mut matches = Vec::new();
    for entry in fs::read_dir(dir).map_err(|error| io_error(&dir.display(), error))? {
        let entry = entry.map_err(|error| io_error(&dir.display(), error))?;
        let name = entry.file_name().to_string_lossy().into_owned();
        if name.len() >= prefix.len() + suffix.len()
            && name.starts_with(prefix)
            && name.ends_with(suffix)
        {
            matches.push(name);
        }
    }
    matches.sort();
    Ok(matches)
}

fn require_real_dir(path: &Path) -> Result<(), Error> {
    let metadata = fs::symlink_metadata(path).map_err(|error| io_error(&path.display(), error))?;
    if !metadata.is_dir() {
        return fail(format!(
            "materialization target must be a real directory: {}",
            path.display()
        ));
    }
    Ok(())
}

/// Joins a table-declared relative path onto a root, refusing anything that
/// could leave it.
fn resolve(root: &Path, relative: &str) -> Result<PathBuf, Error> {
    if relative.is_empty() {
        return Ok(root.to_path_buf());
    }
    let candidate = Path::new(relative);
    if candidate.is_absolute() {
        return fail(format!("path must be relative: {relative}"));
    }
    for component in candidate.components() {
        match component {
            Component::Normal(_) => {}
            _ => return fail(format!("path must not leave the tree: {relative}")),
        }
    }
    Ok(root.join(candidate))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn resolve_refuses_paths_that_leave_the_tree() {
        let root = Path::new("/tmp/root");
        assert!(resolve(root, "../escape").is_err());
        assert!(resolve(root, "/etc/passwd").is_err());
        assert_eq!(resolve(root, "").expect("empty is the root"), root);
        assert_eq!(
            resolve(root, "src/lib.rs").expect("normal"),
            root.join("src/lib.rs")
        );
    }

    #[test]
    fn unknown_targets_are_named_in_the_error() {
        let error = materialize(Path::new("."), "not-a-target", Path::new("/tmp/unused"))
            .expect_err("refuses");
        assert!(error.to_string().contains("known targets: chain-config"));
    }

    #[test]
    fn a_non_empty_destination_is_refused() {
        let destination = tempfile::tempdir().expect("temp dir");
        fs::write(destination.path().join("stray"), "x").expect("write");
        let error = prepare_destination(destination.path()).expect_err("refuses");
        assert!(error.to_string().contains("must be empty"));
    }

    #[test]
    fn glob_matches_a_prefix_and_suffix() {
        let dir = tempfile::tempdir().expect("temp dir");
        for name in [
            "substreams.base.yaml",
            "substreams.mainnet.yaml",
            "other.json",
        ] {
            fs::write(dir.path().join(name), "x").expect("write");
        }
        let matches = glob(dir.path(), "substreams.", ".yaml").expect("globs");
        assert_eq!(
            matches,
            vec!["substreams.base.yaml", "substreams.mainnet.yaml"]
        );
    }
}
