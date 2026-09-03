//! Proves the staged overlay tree in `OUT_DIR` still matches `uniswap-v3/`.
//!
//! `build.rs` copies the overlay reducers, bindings, contract documents, and
//! harnesses into the materialized layout they expect. That copy is the one
//! place drift could enter, so this test re-reads both sides and compares them.

use std::fs;
use std::path::PathBuf;

include!("../overlay_manifest.rs");

#[test]
fn staged_files_match_their_overlay_originals() {
    let staging = PathBuf::from(env!("OUT_DIR")).join("overlay");

    for (staged_path, overlay_path, mode) in STAGED {
        let overlay = read_overlay(overlay_path);
        let staged = fs::read(staging.join(staged_path)).expect("staged file is readable");
        assert_eq!(
            staged,
            stage(&overlay, *mode),
            "{staged_path} drifted from {overlay_path}"
        );
    }
}

#[test]
fn staging_rewrites_nothing_but_a_harness_root_leading_comment_marker() {
    for (staged_path, overlay_path, mode) in STAGED {
        let overlay = read_overlay(overlay_path);
        let staged = stage(&overlay, *mode);
        if *mode == Staging::Verbatim {
            assert_eq!(staged, overlay, "{staged_path} is not a byte copy");
            continue;
        }

        let staged = String::from_utf8(staged).expect("a harness root is UTF-8");
        let original = String::from_utf8(overlay).expect("a harness root is UTF-8");
        let leading = original
            .lines()
            .take_while(|line| line.starts_with("//!"))
            .count();
        assert!(
            leading > 0,
            "{staged_path} has no leading inner doc comment"
        );
        assert_eq!(
            staged.lines().count(),
            original.lines().count(),
            "{staged_path} changed its line count"
        );
        for (index, (staged_line, original_line)) in
            staged.lines().zip(original.lines()).enumerate()
        {
            let expected = if index < leading {
                format!("//{}", &original_line["//!".len()..])
            } else {
                original_line.to_owned()
            };
            assert_eq!(
                staged_line,
                expected,
                "{staged_path} line {} changed",
                index + 1
            );
        }
    }
}

#[test]
fn every_module_the_library_declares_is_staged() {
    for (module, _, _) in REDUCER_MODULES {
        let staged = format!("src/{module}.rs");
        assert!(
            STAGED.iter().any(|(path, _, _)| *path == staged),
            "{module} is declared by the library but never staged"
        );
    }
}

fn read_overlay(overlay_path: &str) -> Vec<u8> {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join(OVERLAY_ROOT)
        .join(overlay_path);
    fs::read(&path).unwrap_or_else(|error| panic!("cannot read {}: {error}", path.display()))
}
