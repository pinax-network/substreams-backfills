//! Extracts the `uniswap.writer.v1` prost bindings out of the writer-runtime
//! overlay patch.
//!
//! The bindings are checked in only as added lines of
//! `uniswap-v3/writer-runtime/runtime.patch`. Materializing the overlay applies
//! that patch to a copy of the frozen source; this build script performs the
//! same extraction into `OUT_DIR` so the workspace can compile the reducers
//! against the identical bytes without a second checked-in copy that could
//! drift.

use std::env;
use std::fs;
use std::path::{Path, PathBuf};

const WRITER_PATCH: &str = "../../uniswap-v3/writer-runtime/runtime.patch";
const BINDINGS_TARGET: &str = "+++ b/src/pb/uniswap.writer.v1.rs";

fn main() {
    println!("cargo:rerun-if-changed=build.rs");
    println!("cargo:rerun-if-changed={WRITER_PATCH}");

    let patch = fs::read_to_string(WRITER_PATCH)
        .unwrap_or_else(|error| panic!("cannot read {WRITER_PATCH}: {error}"));
    let bindings = extract_added_file(&patch, BINDINGS_TARGET);

    let out = PathBuf::from(env::var_os("OUT_DIR").expect("OUT_DIR is set by cargo"));
    write_if_changed(&out.join("uniswap.writer.v1.rs"), &bindings);
}

/// Returns the full contents of a file the unified diff adds, reconstructed
/// from the single `@@ -0,0 +1,N @@` hunk that introduces it.
fn extract_added_file(patch: &str, target: &str) -> String {
    let mut lines = patch.lines();
    while let Some(line) = lines.next() {
        if line != target {
            continue;
        }
        let header = lines
            .next()
            .unwrap_or_else(|| panic!("{target} has no hunk header"));
        let count = added_line_count(header).unwrap_or_else(|| {
            panic!("{target} hunk header is not a whole-file addition: {header}")
        });
        let mut body = String::new();
        for index in 0..count {
            let hunk_line = lines
                .next()
                .unwrap_or_else(|| panic!("{target} hunk ends after {index} of {count} lines"));
            let content = hunk_line.strip_prefix('+').unwrap_or_else(|| {
                panic!("{target} hunk line {index} is not an addition: {hunk_line}")
            });
            body.push_str(content);
            body.push('\n');
        }
        return body;
    }
    panic!("{target} is not added by {WRITER_PATCH}");
}

/// Parses `@@ -0,0 +1,N @@`, rejecting any hunk that is not a whole-file add.
fn added_line_count(header: &str) -> Option<usize> {
    let rest = header.strip_prefix("@@ -0,0 +1,")?;
    let (count, _) = rest.split_once(" @@")?;
    count.parse().ok()
}

fn write_if_changed(path: &Path, contents: &str) {
    if fs::read_to_string(path).is_ok_and(|existing| existing == contents) {
        return;
    }
    fs::write(path, contents)
        .unwrap_or_else(|error| panic!("cannot write {}: {error}", path.display()));
}
