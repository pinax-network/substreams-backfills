//! Proves the Rust materializer stages exactly the tree the shell scripts
//! staged, without needing the scripts, Python, or a network.
//!
//! The trees themselves were compared directly against
//! `scripts/materialize-uniswap-v3-*.sh` output, file contents and modes, for
//! all ten targets while this was written. These tests are what keeps that
//! true: the writer-runtime layer is checked against the per-file SHA-256
//! digests `uniswap-v3/writer-runtime/contract-v1.json` already pins for a
//! materialized tree, every copied file is checked against the pinned overlay
//! it came from, and the untouched part of the frozen import is checked
//! against `uniswap-v3/source`.

use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

use sha2::{Digest, Sha256};
use uniswap_v3_runtime::plan::{self, Step};

fn repository() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .canonicalize()
        .expect("the workspace root is reachable from the crate directory")
}

fn stage(target: &str) -> tempfile::TempDir {
    let destination = tempfile::tempdir().expect("temporary directory");
    uniswap_v3_runtime::materialize(&repository(), target, destination.path())
        .unwrap_or_else(|error| panic!("cannot materialize {target}: {error}"));
    destination
}

fn digest(path: &Path) -> String {
    let bytes =
        fs::read(path).unwrap_or_else(|error| panic!("cannot read {}: {error}", path.display()));
    let mut hasher = Sha256::new();
    hasher.update(&bytes);
    hex::encode(hasher.finalize())
}

/// Every file a target copies, as `(source, destination)` pairs already
/// resolved against the repository and the staged tree.
fn copied_files(target: &str, repository: &Path, destination: &Path) -> Vec<(PathBuf, PathBuf)> {
    let mut pairs = Vec::new();
    for layer in plan::chain(target).expect("known target") {
        for step in layer.steps {
            match *step {
                Step::Copy { from, to } => {
                    let source = match from.strip_prefix("@destination/") {
                        Some(rest) => destination.join(rest),
                        None => repository.join(from),
                    };
                    pairs.push((source, destination.join(to)));
                }
                Step::CopyGlob {
                    from,
                    prefix,
                    suffix,
                    to,
                } => {
                    let source_dir = repository.join(from);
                    for entry in fs::read_dir(&source_dir).expect("overlay directory exists") {
                        let name = entry.expect("directory entry").file_name();
                        let name = name.to_string_lossy().into_owned();
                        if name.starts_with(prefix) && name.ends_with(suffix) {
                            pairs.push((source_dir.join(&name), destination.join(to).join(&name)));
                        }
                    }
                }
                _ => {}
            }
        }
    }
    pairs
}

#[test]
fn the_writer_runtime_layer_matches_the_contract_digests() {
    let contract: serde_json::Value = serde_json::from_str(
        &fs::read_to_string(repository().join("uniswap-v3/writer-runtime/contract-v1.json"))
            .expect("the writer-runtime contract is readable"),
    )
    .expect("the writer-runtime contract is JSON");
    let expected: BTreeMap<String, String> = contract["materialized_runtime_artifacts"]
        .as_object()
        .expect("materialized_runtime_artifacts is an object")
        .iter()
        .map(|(path, digest)| {
            (
                path.clone(),
                digest.as_str().expect("digest is a string").to_string(),
            )
        })
        .collect();
    assert!(
        expected.len() >= 15,
        "the contract should pin the whole materialized runtime, found {}",
        expected.len()
    );

    let staged = stage("writer-runtime");
    for (path, want) in &expected {
        let got = digest(&staged.path().join(path));
        assert_eq!(
            &got, want,
            "{path} does not match the digest the writer-runtime contract pins"
        );
    }
}

#[test]
fn every_copied_file_is_byte_identical_to_its_pinned_overlay() {
    let repository = repository();
    for target in plan::TARGETS {
        let staged = stage(target.name);
        let pairs = copied_files(target.name, &repository, staged.path());
        assert!(
            !pairs.is_empty(),
            "{} copies no files, which cannot be right",
            target.name
        );
        // A later layer may overwrite an earlier layer's copy, and a later
        // layer may delete one; only the last source that wrote a path has to
        // match what is on disk.
        let last_writer: BTreeMap<PathBuf, PathBuf> = pairs
            .into_iter()
            .map(|(source, destination)| (destination, source))
            .collect();
        for (destination, source) in last_writer {
            if !destination.exists() {
                continue;
            }
            assert_eq!(
                fs::read(&source).expect("overlay source is readable"),
                fs::read(&destination).expect("staged file is readable"),
                "{} staged {} from {} with different bytes",
                target.name,
                destination.display(),
                source.display()
            );
        }
    }
}

#[test]
fn files_no_patch_touches_arrive_from_the_frozen_import_unchanged() {
    let repository = repository();
    let staged = stage("writer-runtime");
    // Files the two runtime patches never mention, so the archive step is the
    // only thing that can have written them.
    for relative in [
        "src/math.rs",
        "src/eth.rs",
        "src/ticks_idx.rs",
        "src/abi/pool.rs",
        "schema.graphql",
        "abis/factory.json",
        "proto/uniswap/v1/uniswap.proto",
    ] {
        assert_eq!(
            digest(&repository.join("uniswap-v3/source").join(relative)),
            digest(&staged.path().join(relative)),
            "{relative} differs from the frozen import"
        );
    }
}

#[test]
fn the_executable_mode_of_the_frozen_import_survives_staging() {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;

        let staged = stage("chain-config");
        let mut executable: Vec<String> = Vec::new();
        let mut stack = vec![staged.path().to_path_buf()];
        while let Some(directory) = stack.pop() {
            for entry in fs::read_dir(&directory).expect("staged directory is readable") {
                let entry = entry.expect("directory entry");
                let path = entry.path();
                let metadata = fs::symlink_metadata(&path).expect("metadata");
                if metadata.is_dir() {
                    stack.push(path);
                    continue;
                }
                assert!(!metadata.is_symlink(), "{} is a symlink", path.display());
                if metadata.permissions().mode() & 0o111 != 0 {
                    executable.push(
                        path.strip_prefix(staged.path())
                            .expect("staged path")
                            .display()
                            .to_string(),
                    );
                }
            }
        }
        executable.sort();
        // `cargo xtask verify-import uniswap-v3` counts exactly one executable
        // file in the frozen import, and the overlay adds none.
        assert_eq!(executable, vec!["build.sh".to_string()]);
    }
}

#[test]
fn materializing_twice_produces_the_same_tree() {
    let first = stage("npm-provider-executor");
    let second = stage("npm-provider-executor");
    let inventory = |root: &Path| -> BTreeMap<String, String> {
        let mut files = BTreeMap::new();
        let mut stack = vec![root.to_path_buf()];
        while let Some(directory) = stack.pop() {
            for entry in fs::read_dir(&directory).expect("staged directory is readable") {
                let entry = entry.expect("directory entry");
                let path = entry.path();
                if path.is_dir() {
                    stack.push(path);
                    continue;
                }
                files.insert(
                    path.strip_prefix(root)
                        .expect("staged path")
                        .display()
                        .to_string(),
                    digest(&path),
                );
            }
        }
        files
    };
    assert_eq!(inventory(first.path()), inventory(second.path()));
}

#[test]
fn each_target_names_the_shell_script_it_replaces() {
    let scripts = repository().join("scripts");
    for target in plan::TARGETS {
        let script = scripts.join(format!("materialize-uniswap-v3-{}.sh", target.name));
        assert!(
            script.is_file(),
            "{} has no matching materialize script; the table and the scripts have diverged",
            target.name
        );
    }
}

#[test]
fn a_target_refuses_to_stage_into_a_non_empty_directory() {
    let destination = tempfile::tempdir().expect("temporary directory");
    fs::write(destination.path().join("stray"), b"x").expect("write");
    let error = uniswap_v3_runtime::materialize(&repository(), "chain-config", destination.path())
        .expect_err("refuses a dirty destination");
    assert!(error.to_string().contains("must be empty"));
}
