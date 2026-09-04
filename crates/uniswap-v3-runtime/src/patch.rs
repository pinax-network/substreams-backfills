//! A unified-diff applier for the overlay `runtime.patch` files.
//!
//! The overlay patches are `git diff -U0` output: whole-file additions and
//! zero-context edits, no deletions, renames, or mode changes. Zero context
//! means the recorded line numbers are the whole of the addressing
//! information, so application is exact rather than a search, and this applier
//! refuses anything it cannot place exactly. That is stricter than the
//! `patch --forward --batch` the shell scripts run, and it fails loudly rather
//! than silently reordering or fuzzing a hunk into the wrong place.

use std::fmt;
use std::path::{Component, Path, PathBuf};

/// One `@@ -a,b +c,d @@` hunk and the lines that follow it.
#[derive(Debug)]
struct Hunk {
    /// 1-based first old line the hunk replaces, or the line it inserts after
    /// when `old_count` is zero.
    old_start: usize,
    old_count: usize,
    body: Vec<BodyLine>,
}

#[derive(Debug)]
enum BodyLine {
    Context(String),
    Removed(String),
    Added(String),
}

/// Every edit one unified diff makes to one file.
#[derive(Debug)]
pub struct FilePatch {
    /// Path relative to the tree root, with the `a/` or `b/` prefix stripped.
    pub path: PathBuf,
    /// True when the diff creates the file rather than editing it.
    pub creates: bool,
    hunks: Vec<Hunk>,
}

#[derive(Debug)]
pub struct PatchError(String);

impl fmt::Display for PatchError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.0)
    }
}

impl std::error::Error for PatchError {}

fn fail<T>(message: impl Into<String>) -> Result<T, PatchError> {
    Err(PatchError(message.into()))
}

/// Parses a unified diff into its per-file edits.
pub fn parse(diff: &str) -> Result<Vec<FilePatch>, PatchError> {
    let mut files: Vec<FilePatch> = Vec::new();
    let mut creates = false;
    let mut lines = diff.lines().peekable();
    while let Some(line) = lines.next() {
        if line.starts_with("diff --git ") {
            creates = false;
            continue;
        }
        if line == "new file mode 100644" {
            creates = true;
            continue;
        }
        if line.starts_with("deleted file mode")
            || line.starts_with("rename ")
            || line.starts_with("old mode ")
            || line.starts_with("new mode ")
            || line.starts_with("Binary files ")
        {
            return fail(format!("unsupported diff directive: {line}"));
        }
        if !line.starts_with("+++ ") {
            continue;
        }
        let path = strip_prefix_component(line.trim_start_matches("+++ "))?;
        let mut hunks = Vec::new();
        while let Some(header) = lines.peek() {
            if !header.starts_with("@@ ") {
                break;
            }
            let header = lines.next().expect("peeked");
            let (old_start, old_count) = parse_hunk_header(header)?;
            let mut body = Vec::new();
            while let Some(candidate) = lines.peek() {
                let Some(first) = candidate.chars().next() else {
                    // A bare empty line is a context line whose content is empty.
                    body.push(BodyLine::Context(String::new()));
                    lines.next();
                    continue;
                };
                match first {
                    ' ' => body.push(BodyLine::Context(candidate[1..].to_string())),
                    '-' => body.push(BodyLine::Removed(candidate[1..].to_string())),
                    '+' => body.push(BodyLine::Added(candidate[1..].to_string())),
                    '\\' => return fail(format!("unsupported no-newline marker: {candidate}")),
                    _ => break,
                }
                lines.next();
            }
            hunks.push(Hunk {
                old_start,
                old_count,
                body,
            });
        }
        if hunks.is_empty() {
            return fail(format!("{} has no hunks", path.display()));
        }
        files.push(FilePatch {
            path,
            creates,
            hunks,
        });
        creates = false;
    }
    if files.is_empty() {
        return fail("diff contains no file sections");
    }
    Ok(files)
}

/// Parses `@@ -start[,count] +start[,count] @@ [heading]`, returning the old side.
fn parse_hunk_header(header: &str) -> Result<(usize, usize), PatchError> {
    let rest = match header.strip_prefix("@@ -") {
        Some(rest) => rest,
        None => return fail(format!("malformed hunk header: {header}")),
    };
    let Some((old, _)) = rest.split_once(" +") else {
        return fail(format!("malformed hunk header: {header}"));
    };
    let (start, count) = match old.split_once(',') {
        Some((start, count)) => (start, count),
        None => (old, "1"),
    };
    match (start.parse(), count.parse()) {
        (Ok(start), Ok(count)) => Ok((start, count)),
        _ => fail(format!("malformed hunk header: {header}")),
    }
}

/// Strips the leading `a/` or `b/` component a `-p1` patch carries, and
/// refuses any path that could escape the tree root.
fn strip_prefix_component(raw: &str) -> Result<PathBuf, PatchError> {
    let Some((_, rest)) = raw.split_once('/') else {
        return fail(format!("path has no strippable component: {raw}"));
    };
    let path = Path::new(rest);
    for component in path.components() {
        match component {
            Component::Normal(_) => {}
            _ => return fail(format!("unsafe path in diff: {raw}")),
        }
    }
    Ok(path.to_path_buf())
}

/// Splits file contents into lines, requiring a trailing newline.
///
/// Every overlay source ends with a newline and no patch carries a
/// `\ No newline at end of file` marker, so a file without one would mean the
/// tree is not what the patch was cut against.
pub fn split_lines(contents: &str, what: &dyn fmt::Display) -> Result<Vec<String>, PatchError> {
    if contents.is_empty() {
        return Ok(Vec::new());
    }
    let Some(body) = contents.strip_suffix('\n') else {
        return fail(format!("{what} does not end with a newline"));
    };
    Ok(body.split('\n').map(str::to_string).collect())
}

/// Rejoins lines into file contents, restoring the trailing newline.
pub fn join_lines(lines: &[String]) -> String {
    if lines.is_empty() {
        return String::new();
    }
    let mut joined = lines.join("\n");
    joined.push('\n');
    joined
}

impl FilePatch {
    /// Applies every hunk to `old`, returning the patched lines.
    pub fn apply(&self, old: &[String]) -> Result<Vec<String>, PatchError> {
        let path = self.path.display();
        let mut out: Vec<String> = Vec::with_capacity(old.len());
        let mut cursor = 0usize;
        for hunk in &self.hunks {
            // A zero-length old side is an insertion *after* `old_start`;
            // otherwise `old_start` is the 1-based first replaced line.
            let start = if hunk.old_count == 0 {
                hunk.old_start
            } else {
                match hunk.old_start.checked_sub(1) {
                    Some(start) => start,
                    None => return fail(format!("{path}: hunk starts at line 0")),
                }
            };
            if start < cursor {
                return fail(format!(
                    "{path}: hunk at line {start} overlaps an earlier hunk"
                ));
            }
            if start > old.len() {
                return fail(format!(
                    "{path}: hunk starts past the end of the file ({start} > {})",
                    old.len()
                ));
            }
            out.extend_from_slice(&old[cursor..start]);
            cursor = start;
            for line in &hunk.body {
                match line {
                    BodyLine::Added(content) => out.push(content.clone()),
                    BodyLine::Context(content) | BodyLine::Removed(content) => {
                        let Some(actual) = old.get(cursor) else {
                            return fail(format!("{path}: hunk reads past the end of the file"));
                        };
                        if actual != content {
                            return fail(format!(
                                "{path}: line {} does not match the patch\n  expected: {content}\n  actual:   {actual}",
                                cursor + 1
                            ));
                        }
                        if matches!(line, BodyLine::Context(_)) {
                            out.push(content.clone());
                        }
                        cursor += 1;
                    }
                }
            }
        }
        out.extend_from_slice(&old[cursor..]);
        Ok(out)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn lines(raw: &[&str]) -> Vec<String> {
        raw.iter().map(|line| (*line).to_string()).collect()
    }

    #[test]
    fn applies_a_zero_context_replacement() {
        let diff = "diff --git a/src/lib.rs b/src/lib.rs\n\
                    --- a/src/lib.rs\n\
                    +++ b/src/lib.rs\n\
                    @@ -2 +2 @@ heading\n\
                    -second\n\
                    +patched\n";
        let files = parse(diff).expect("parses");
        assert_eq!(files.len(), 1);
        assert_eq!(files[0].path, Path::new("src/lib.rs"));
        assert!(!files[0].creates);
        let out = files[0]
            .apply(&lines(&["first", "second", "third"]))
            .expect("applies");
        assert_eq!(out, lines(&["first", "patched", "third"]));
    }

    #[test]
    fn inserts_after_the_named_line_when_the_old_side_is_empty() {
        let diff = "--- a/x\n+++ b/x\n@@ -1,0 +2 @@ heading\n+inserted\n";
        let files = parse(diff).expect("parses");
        let out = files[0]
            .apply(&lines(&["first", "second"]))
            .expect("applies");
        assert_eq!(out, lines(&["first", "inserted", "second"]));
    }

    #[test]
    fn reconstructs_a_whole_file_addition() {
        let diff = "diff --git a/src/new.rs b/src/new.rs\n\
                    new file mode 100644\n\
                    --- /dev/null\n\
                    +++ b/src/new.rs\n\
                    @@ -0,0 +1,2 @@\n\
                    +one\n\
                    +two\n";
        let files = parse(diff).expect("parses");
        assert!(files[0].creates);
        assert_eq!(
            files[0].apply(&[]).expect("applies"),
            lines(&["one", "two"])
        );
    }

    #[test]
    fn applies_several_hunks_in_one_file() {
        let diff = "--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+A\n@@ -3 +3,2 @@\n-c\n+C\n+D\n";
        let files = parse(diff).expect("parses");
        let out = files[0].apply(&lines(&["a", "b", "c"])).expect("applies");
        assert_eq!(out, lines(&["A", "b", "C", "D"]));
    }

    #[test]
    fn refuses_a_hunk_whose_removed_line_does_not_match() {
        let diff = "--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+A\n";
        let files = parse(diff).expect("parses");
        let error = files[0].apply(&lines(&["different"])).expect_err("refuses");
        assert!(error.to_string().contains("does not match the patch"));
    }

    #[test]
    fn refuses_a_path_that_escapes_the_tree() {
        let diff = "--- a/x\n+++ b/../escape\n@@ -0,0 +1 @@\n+x\n";
        let error = parse(diff).expect_err("refuses");
        assert!(error.to_string().contains("unsafe path"));
    }

    #[test]
    fn refuses_an_unsupported_directive() {
        let diff = "diff --git a/x b/x\ndeleted file mode 100644\n--- a/x\n+++ /dev/null\n";
        let error = parse(diff).expect_err("refuses");
        assert!(error.to_string().contains("unsupported diff directive"));
    }

    #[test]
    fn requires_a_trailing_newline() {
        let what = "x";
        let error = split_lines("no newline", &what).expect_err("refuses");
        assert!(error.to_string().contains("does not end with a newline"));
        assert_eq!(
            split_lines("", &what).expect("empty is fine"),
            Vec::<String>::new()
        );
    }
}
