// The overlay staging manifest, shared by `build.rs` and `tests/staging.rs`
// through `include!` so the test checks the same table the build uses.

/// How a staged file is derived from its overlay original.
#[allow(dead_code)]
#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Staging {
    /// Byte-for-byte.
    Verbatim,
    /// Byte-for-byte except that the leading `//!` block becomes `//`.
    HarnessRoot,
}

/// `(staged path, path under `uniswap-v3/`, staging)`, mirroring a
/// materialized runtime.
#[allow(dead_code)]
pub const STAGED: &[(&str, &str, Staging)] = &[
    // Reducer sources, in overlay application order.
    (
        "src/position_reducer.rs",
        "position-reducer/src/position_reducer.rs",
        Staging::Verbatim,
    ),
    (
        "src/flash_reducer.rs",
        "flash-reducer/src/flash_reducer.rs",
        Staging::Verbatim,
    ),
    (
        "src/transaction_reducer.rs",
        "transaction-reducer/src/transaction_reducer.rs",
        Staging::Verbatim,
    ),
    (
        "src/npm_source_block.rs",
        "npm-source-block/runtime/src/npm_source_block.rs",
        Staging::Verbatim,
    ),
    (
        "src/npm_handler_reducer.rs",
        "npm-handler-reducer/src/npm_handler_reducer.rs",
        Staging::Verbatim,
    ),
    (
        "src/npm_resolved_inputs.rs",
        "npm-resolved-inputs/src/npm_resolved_inputs.rs",
        Staging::Verbatim,
    ),
    (
        "src/npm_observation_plan.rs",
        "npm-observation-plan/src/npm_observation_plan.rs",
        Staging::Verbatim,
    ),
    (
        "src/npm_provider_executor.rs",
        "npm-provider-executor/v1/src/npm_provider_executor.rs",
        Staging::Verbatim,
    ),
    // Checked-in prost bindings the harnesses `include!` beside the sources.
    (
        "src/uniswap.npm.source.v1.rs",
        "npm-source-block/runtime/src/pb/uniswap.npm.source.v1.rs",
        Staging::Verbatim,
    ),
    (
        "src/uniswap.npm.inputs.v1.rs",
        "npm-resolved-inputs/src/uniswap.npm.inputs.v1.rs",
        Staging::Verbatim,
    ),
    (
        "src/uniswap.npm.plan.v1.rs",
        "npm-observation-plan/src/uniswap.npm.plan.v1.rs",
        Staging::Verbatim,
    ),
    // Contract documents the sources `include_str!` and hash at run time.
    (
        "configs/position-reducer-v1.json",
        "position-reducer/position-reducer-v1.json",
        Staging::Verbatim,
    ),
    (
        "configs/flash-reducer-v1.json",
        "flash-reducer/flash-reducer-v1.json",
        Staging::Verbatim,
    ),
    (
        "configs/transaction-reducer-v1.json",
        "transaction-reducer/transaction-reducer-v1.json",
        Staging::Verbatim,
    ),
    (
        "configs/segment-profiles-v1.json",
        "writer-runtime/segment-profiles-v1.json",
        Staging::Verbatim,
    ),
    (
        "configs/npm-source-block-v1.json",
        "npm-source-block/npm-source-block-v1.json",
        Staging::Verbatim,
    ),
    (
        "configs/npm-handler-reducer-v1.json",
        "npm-handler-reducer/npm-handler-reducer-v1.json",
        Staging::Verbatim,
    ),
    (
        "configs/npm-resolved-inputs-v1.json",
        "npm-resolved-inputs/npm-resolved-inputs-v1.json",
        Staging::Verbatim,
    ),
    (
        "configs/npm-observation-plan-v1.json",
        "npm-observation-plan/npm-observation-plan-v1.json",
        Staging::Verbatim,
    ),
    (
        "configs/npm-provider-executor-v1.json",
        "npm-provider-executor/v1/npm-provider-executor-v1.json",
        Staging::Verbatim,
    ),
    // Integration harnesses, each its own test-crate root.
    (
        "tests/transaction_reducer.rs",
        "transaction-reducer/tests/transaction_reducer.rs",
        Staging::HarnessRoot,
    ),
    (
        "tests/npm_handler_reducer.rs",
        "npm-handler-reducer/tests/npm_handler_reducer.rs",
        Staging::HarnessRoot,
    ),
    (
        "tests/npm_resolved_inputs.rs",
        "npm-resolved-inputs/tests/npm_resolved_inputs.rs",
        Staging::HarnessRoot,
    ),
    (
        "tests/npm_observation_plan.rs",
        "npm-observation-plan/tests/npm_observation_plan.rs",
        Staging::HarnessRoot,
    ),
    (
        "tests/npm_provider_executor.rs",
        "npm-provider-executor/v1/tests/npm_provider_executor.rs",
        Staging::HarnessRoot,
    ),
];

/// `(module, doc comment, extra lint allowances)` for the library's view of
/// the staged reducers.
///
/// Declared out of line from a generated file rather than written in
/// `src/lib.rs`, because `#[path]` takes a literal and `OUT_DIR` is not known
/// until the build runs.
#[allow(dead_code)]
const REDUCER_MODULES: &[(&str, &str, &[&str])] = &[
    (
        "position_reducer",
        "Sequential Position and PositionSnapshot state transitions.",
        &[],
    ),
    (
        "flash_reducer",
        "Pool Flash state transitions behind a hermetic contract-call trait.",
        &[],
    ),
    (
        "transaction_reducer",
        "NonfungiblePositionManager Transaction side effects.",
        &[],
    ),
    (
        "npm_source_block",
        "Deterministic, provider-free NPM source frames.",
        &[],
    ),
    (
        "npm_handler_reducer",
        "Joint Transaction, Position, and PositionSnapshot reduction.",
        &[],
    ),
    (
        "npm_resolved_inputs",
        "Resolved-observation adapter into the joint reducer.",
        &[],
    ),
    (
        "npm_observation_plan",
        "Conservative observation planner over the resolved-input identities.",
        // `coverage_audit_for_test` is reached only from the overlay harness.
        &["dead_code"],
    ),
    (
        "npm_provider_executor",
        "Hermetic host executor for the planned observations.",
        &[],
    ),
];

#[allow(dead_code)]
pub const OVERLAY_ROOT: &str = "../../uniswap-v3";

/// Applies a staging mode to one overlay file's bytes.
#[allow(dead_code)]
pub fn stage(bytes: &[u8], mode: Staging) -> Vec<u8> {
    match mode {
        Staging::Verbatim => bytes.to_vec(),
        Staging::HarnessRoot => demote_leading_inner_doc(bytes),
    }
}

/// Rewrites the `//!` prefix to `//` on the run of lines that opens a file.
///
/// Only the leading block is touched, and only its comment marker, so the
/// harness keeps its text and every byte of code.
#[allow(dead_code)]
pub fn demote_leading_inner_doc(bytes: &[u8]) -> Vec<u8> {
    let mut out = Vec::with_capacity(bytes.len());
    let mut rest = bytes;
    while let Some(line) = rest.strip_prefix(b"//!") {
        let end = line
            .iter()
            .position(|byte| *byte == b'\n')
            .map_or(line.len(), |at| at + 1);
        out.extend_from_slice(b"//");
        out.extend_from_slice(&line[..end]);
        rest = &line[end..];
    }
    out.extend_from_slice(rest);
    out
}
