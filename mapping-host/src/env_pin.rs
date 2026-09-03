//! Pin the `GRAPH_*` environment variables that `graph::env::ENV_VARS` reads.
//!
//! `ENV_VARS` is a process-global `Lazy` that reads the environment on first
//! use. Anything that touches it before we pin would freeze whatever the ambient
//! environment happened to hold, so [`pin`] must run before the first use — it is
//! called from `main` and from every test entry point.
//!
//! Every value below is Graph Node v0.44.0's own default for that variable, taken
//! from `graph/src/env/mod.rs` and `graph/src/env/mappings.rs`. We set them
//! explicitly rather than relying on the defaults so that a stray `GRAPH_*` in the
//! ambient environment cannot change a report or a PoI digest.

use std::sync::Once;

/// The variables we pin, with the value each is pinned to.
///
/// Keep this table in sync with `README.md`.
pub const PINNED: &[(&str, &str)] = &[
    // graph/src/env/mod.rs
    ("GRAPH_MAX_SPEC_VERSION", "1.5.0"),
    ("GRAPH_MAX_GAS_PER_HANDLER", "1_000_000_000_000_000"),
    ("GRAPH_LOG_POI_EVENTS", "false"),
    ("GRAPH_ENABLE_DIPS_METRICS", "false"),
    ("GRAPH_SUBGRAPH_MAX_DATA_SOURCES", "1000000"),
    // graph/src/env/mappings.rs
    ("GRAPH_MAX_API_VERSION", "0.0.9"),
    ("GRAPH_ENTITY_CACHE_SIZE", "10000"),
    ("GRAPH_WASM_OPT_LEVEL", "speed"),
    ("GRAPH_ALLOW_NON_DETERMINISTIC_IPFS", "false"),
    ("GRAPH_DISABLE_DECLARED_CALLS", "false"),
    ("GRAPH_STORE_ERRORS_ARE_NON_DETERMINISTIC", "false"),
    ("GRAPH_IPFS_REQUEST_LIMIT", "100"),
];

/// Variables that must be *absent*, because Graph Node's default for them is
/// "unset" and any value at all changes behaviour.
pub const UNSET: &[&str] = &[
    // No mapping timeout: a timeout turns a slow handler into a non-deterministic
    // failure, which would make a report irreproducible.
    "GRAPH_MAPPING_HANDLER_TIMEOUT",
    // Empty means "wasmtime default stack"; a value changes where a deep
    // AssemblyScript recursion traps.
    "GRAPH_RUNTIME_MAX_STACK_SIZE",
];

static ONCE: Once = Once::new();

/// Pin the environment. Idempotent, and safe to call from several tests.
pub fn pin() {
    ONCE.call_once(|| {
        // Called once, before any thread that reads `ENV_VARS` has started.
        for (key, value) in PINNED {
            std::env::set_var(key, value);
        }
        for key in UNSET {
            std::env::remove_var(key);
        }
    });
}
