use sha2::{Digest, Sha256};
use std::{
    fs,
    path::{Path, PathBuf},
};

fn collect(path: &Path, files: &mut Vec<PathBuf>) {
    let meta = fs::symlink_metadata(path).expect("source closure metadata");
    assert!(
        !meta.file_type().is_symlink(),
        "source closure refuses symlinks"
    );
    if meta.is_dir() {
        println!("cargo:rerun-if-changed={}", path.display());
        for entry in fs::read_dir(path).expect("source closure directory") {
            collect(&entry.expect("source closure entry").path(), files);
        }
    } else if meta.is_file() {
        files.push(path.to_owned());
    }
}

fn main() {
    let root = PathBuf::from(std::env::var_os("CARGO_MANIFEST_DIR").unwrap())
        .parent()
        .unwrap()
        .to_owned();
    let mut files = Vec::new();
    for path in [
        "Cargo.toml",
        "common/Cargo.toml",
        "common/src",
        "common/proto",
        "mapping-host/Cargo.toml",
        "mapping-host/Cargo.lock",
        "mapping-host/build.rs",
        "mapping-host/src",
        "mapping-host/vendor",
    ] {
        collect(&root.join(path), &mut files);
    }
    files.sort();
    let mut hash = Sha256::new();
    hash.update(b"pinax.mapping-host.source-closure/v1\0");
    let mut inventory = String::new();
    for path in files {
        println!("cargo:rerun-if-changed={}", path.display());
        let name = path
            .strip_prefix(&root)
            .unwrap()
            .to_str()
            .expect("UTF-8 source path");
        let bytes = fs::read(&path).expect("read source closure file");
        let digest = Sha256::digest(&bytes);
        hash.update((name.len() as u64).to_be_bytes());
        hash.update(name.as_bytes());
        hash.update((bytes.len() as u64).to_be_bytes());
        hash.update(digest);
        inventory.push_str(&format!("{digest:x}  {}  {name}\n", bytes.len()));
    }
    let digest = format!("{:x}", hash.finalize());
    fs::write(
        PathBuf::from(std::env::var_os("OUT_DIR").unwrap()).join("source-closure.txt"),
        inventory,
    )
    .unwrap();
    println!("cargo:rustc-env=MAPPING_HOST_SOURCE_CLOSURE_SHA256={digest}");
}
