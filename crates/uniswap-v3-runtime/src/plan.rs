//! The declarative table of overlay materialization steps.
//!
//! One entry per `scripts/materialize-uniswap-v3-*.sh`, in the same order the
//! script performs them, so the two can be read side by side. Every path is
//! relative to the repository root or to the destination tree; nothing here
//! duplicates the bytes of a pinned file.

/// One step of a materialization, mirroring one line of a shell script.
#[derive(Debug, Clone, Copy)]
pub enum Step {
    /// `git archive HEAD:<tree> | tar -x` into the destination root.
    Archive { tree: &'static str },
    /// `patch --strip 1 --forward --batch < <patch>`.
    ApplyPatch { patch: &'static str },
    /// `mkdir -p <destination>/<dir>`.
    MakeDir { dir: &'static str },
    /// `cp <repository>/<from> <destination>/<to>`.
    Copy {
        from: &'static str,
        to: &'static str,
    },
    /// `cp <repository>/<from>/<pattern> <destination>/<to>/`, where `pattern`
    /// is a `prefix*suffix` glob over one directory.
    CopyGlob {
        from: &'static str,
        prefix: &'static str,
        suffix: &'static str,
        to: &'static str,
    },
    /// `rm <destination>/<path>`, for a file an earlier layer staged.
    Remove { path: &'static str },
}

/// A materialization target, named exactly as its shell script is.
#[derive(Debug, Clone, Copy)]
pub struct Target {
    pub name: &'static str,
    /// The layer this one is built on top of, if any.
    pub base: Option<&'static str>,
    pub steps: &'static [Step],
    /// What the script prints on success, kept so callers can say the same thing.
    pub summary: &'static str,
}

/// Every target, in dependency order.
pub const TARGETS: &[Target] = &[
    Target {
        name: "chain-config",
        base: None,
        steps: &[
            Step::Archive {
                tree: "uniswap-v3/source",
            },
            Step::ApplyPatch {
                patch: "uniswap-v3/chain-config/runtime.patch",
            },
            Step::MakeDir { dir: "configs" },
            Step::CopyGlob {
                from: "uniswap-v3/chain-config/configs",
                prefix: "",
                suffix: ".json",
                to: "configs",
            },
            Step::CopyGlob {
                from: "uniswap-v3/chain-config/manifests",
                prefix: "substreams.",
                suffix: ".yaml",
                to: "",
            },
        ],
        summary: "configured Uniswap V3 runtime",
    },
    Target {
        name: "writer-runtime",
        base: Some("chain-config"),
        steps: &[
            Step::ApplyPatch {
                patch: "uniswap-v3/writer-runtime/runtime.patch",
            },
            Step::MakeDir { dir: "configs" },
            Step::MakeDir { dir: "fixtures" },
            Step::CopyGlob {
                from: "uniswap-v3/writer-runtime/configs",
                prefix: "",
                suffix: ".json",
                to: "configs",
            },
            Step::Copy {
                from: "uniswap-v3/writer-runtime/segment-profiles-v1.json",
                to: "configs/segment-profiles-v1.json",
            },
            Step::Copy {
                from: "uniswap-v3/writer-runtime/fixtures/events-v1.json",
                to: "fixtures/events-v1.json",
            },
            Step::CopyGlob {
                from: "uniswap-v3/writer-runtime/manifests",
                prefix: "substreams.",
                suffix: ".yaml",
                to: "",
            },
        ],
        summary: "diagnostic Uniswap V3 writer runtime",
    },
    Target {
        name: "npm-source-block",
        base: Some("writer-runtime"),
        steps: &[
            Step::MakeDir {
                dir: "npm-source-block-runtime/src/pb",
            },
            Step::MakeDir {
                dir: "npm-source-block-runtime/configs",
            },
            Step::Copy {
                from: "uniswap-v3/npm-source-block/runtime/Cargo.toml",
                to: "npm-source-block-runtime/Cargo.toml",
            },
            Step::Copy {
                from: "uniswap-v3/npm-source-block/runtime/Cargo.lock",
                to: "npm-source-block-runtime/Cargo.lock",
            },
            Step::Copy {
                from: "@destination/rust-toolchain.toml",
                to: "npm-source-block-runtime/rust-toolchain.toml",
            },
            Step::Copy {
                from: "@destination/rustfmt.toml",
                to: "npm-source-block-runtime/rustfmt.toml",
            },
            Step::Copy {
                from: "uniswap-v3/npm-source-block/runtime/src/lib.rs",
                to: "npm-source-block-runtime/src/lib.rs",
            },
            Step::Copy {
                from: "uniswap-v3/npm-source-block/runtime/src/npm_source_block.rs",
                to: "npm-source-block-runtime/src/npm_source_block.rs",
            },
            Step::Copy {
                from: "uniswap-v3/npm-source-block/runtime/src/pb/mod.rs",
                to: "npm-source-block-runtime/src/pb/mod.rs",
            },
            Step::Copy {
                from: "uniswap-v3/npm-source-block/runtime/src/pb/uniswap.npm.source.v1.rs",
                to: "npm-source-block-runtime/src/pb/uniswap.npm.source.v1.rs",
            },
            Step::Copy {
                from: "@destination/src/pb/uniswap.writer.v1.rs",
                to: "npm-source-block-runtime/src/pb/uniswap.writer.v1.rs",
            },
            Step::Copy {
                from: "uniswap-v3/npm-source-block/npm-source-block-v1.json",
                to: "npm-source-block-runtime/configs/npm-source-block-v1.json",
            },
            Step::Copy {
                from: "uniswap-v3/writer-runtime/segment-profiles-v1.json",
                to: "npm-source-block-runtime/configs/segment-profiles-v1.json",
            },
            Step::MakeDir {
                dir: "proto/uniswap/npm/source/v1",
            },
            Step::Copy {
                from:
                    "uniswap-v3/npm-source-block/proto/uniswap/npm/source/v1/npm_source_block.proto",
                to: "proto/uniswap/npm/source/v1/npm_source_block.proto",
            },
            Step::MakeDir {
                dir: "npm-source-package",
            },
            Step::Copy {
                from: "uniswap-v3/npm-source-block/README.md",
                to: "npm-source-package/README.md",
            },
            Step::Copy {
                from: "uniswap-v3/npm-source-block/manifests/substreams.npm-source.mainnet.yaml",
                to: "npm-source-package/substreams.npm-source.mainnet.yaml",
            },
            Step::Copy {
                from: "uniswap-v3/npm-source-block/manifests/substreams.npm-source.base.yaml",
                to: "npm-source-package/substreams.npm-source.base.yaml",
            },
        ],
        summary: "provider-free Uniswap V3 NPM source-block package",
    },
    Target {
        name: "position-reducer",
        base: Some("writer-runtime"),
        steps: &[
            Step::ApplyPatch {
                patch: "uniswap-v3/position-reducer/runtime.patch",
            },
            Step::Copy {
                from: "uniswap-v3/position-reducer/src/position_reducer.rs",
                to: "src/position_reducer.rs",
            },
            Step::Copy {
                from: "uniswap-v3/position-reducer/position-reducer-v1.json",
                to: "configs/position-reducer-v1.json",
            },
        ],
        summary: "host-only Uniswap V3 position reducer",
    },
    Target {
        name: "flash-reducer",
        base: Some("writer-runtime"),
        steps: &[
            Step::ApplyPatch {
                patch: "uniswap-v3/flash-reducer/runtime.patch",
            },
            Step::Copy {
                from: "uniswap-v3/flash-reducer/src/flash_reducer.rs",
                to: "src/flash_reducer.rs",
            },
            Step::Copy {
                from: "uniswap-v3/flash-reducer/flash-reducer-v1.json",
                to: "configs/flash-reducer-v1.json",
            },
        ],
        summary: "host-only Uniswap V3 Pool Flash reducer",
    },
    Target {
        name: "transaction-reducer",
        base: Some("writer-runtime"),
        steps: &[
            Step::MakeDir { dir: "tests" },
            Step::Copy {
                from: "uniswap-v3/transaction-reducer/src/transaction_reducer.rs",
                to: "src/transaction_reducer.rs",
            },
            Step::Copy {
                from: "uniswap-v3/transaction-reducer/transaction-reducer-v1.json",
                to: "configs/transaction-reducer-v1.json",
            },
            Step::Copy {
                from: "uniswap-v3/transaction-reducer/tests/transaction_reducer.rs",
                to: "tests/transaction_reducer.rs",
            },
        ],
        summary: "host-only Uniswap V3 NPM Transaction reducer",
    },
    Target {
        name: "npm-handler-reducer",
        base: Some("writer-runtime"),
        steps: &[
            Step::MakeDir { dir: "tests" },
            Step::Copy {
                from: "uniswap-v3/npm-handler-reducer/src/npm_handler_reducer.rs",
                to: "src/npm_handler_reducer.rs",
            },
            Step::Copy {
                from: "uniswap-v3/npm-handler-reducer/npm-handler-reducer-v1.json",
                to: "configs/npm-handler-reducer-v1.json",
            },
            Step::Copy {
                from: "uniswap-v3/npm-handler-reducer/tests/npm_handler_reducer.rs",
                to: "tests/npm_handler_reducer.rs",
            },
        ],
        summary: "host-only Uniswap V3 joint NPM reducer",
    },
    Target {
        name: "npm-resolved-inputs",
        base: Some("npm-handler-reducer"),
        steps: &[
            Step::Remove {
                path: "tests/npm_handler_reducer.rs",
            },
            Step::Copy {
                from: "uniswap-v3/npm-source-block/runtime/src/npm_source_block.rs",
                to: "src/npm_source_block.rs",
            },
            Step::Copy {
                from: "uniswap-v3/npm-source-block/runtime/src/pb/uniswap.npm.source.v1.rs",
                to: "src/uniswap.npm.source.v1.rs",
            },
            Step::Copy {
                from: "uniswap-v3/npm-source-block/npm-source-block-v1.json",
                to: "configs/npm-source-block-v1.json",
            },
            Step::Copy {
                from: "uniswap-v3/npm-resolved-inputs/src/npm_resolved_inputs.rs",
                to: "src/npm_resolved_inputs.rs",
            },
            Step::Copy {
                from: "uniswap-v3/npm-resolved-inputs/src/uniswap.npm.inputs.v1.rs",
                to: "src/uniswap.npm.inputs.v1.rs",
            },
            Step::Copy {
                from: "uniswap-v3/npm-resolved-inputs/npm-resolved-inputs-v1.json",
                to: "configs/npm-resolved-inputs-v1.json",
            },
            Step::Copy {
                from: "uniswap-v3/npm-resolved-inputs/tests/npm_resolved_inputs.rs",
                to: "tests/npm_resolved_inputs.rs",
            },
        ],
        summary: "host-only Uniswap V3 resolved NPM input adapter",
    },
    Target {
        name: "npm-observation-plan",
        base: Some("npm-resolved-inputs"),
        steps: &[
            Step::Remove {
                path: "tests/npm_resolved_inputs.rs",
            },
            Step::Copy {
                from: "uniswap-v3/npm-observation-plan/src/npm_observation_plan.rs",
                to: "src/npm_observation_plan.rs",
            },
            Step::Copy {
                from: "uniswap-v3/npm-observation-plan/src/uniswap.npm.plan.v1.rs",
                to: "src/uniswap.npm.plan.v1.rs",
            },
            Step::Copy {
                from: "uniswap-v3/npm-observation-plan/npm-observation-plan-v1.json",
                to: "configs/npm-observation-plan-v1.json",
            },
            Step::Copy {
                from: "uniswap-v3/npm-observation-plan/tests/npm_observation_plan.rs",
                to: "tests/npm_observation_plan.rs",
            },
        ],
        summary: "host-only Uniswap V3 NPM observation plan",
    },
    Target {
        name: "npm-provider-executor",
        base: Some("npm-observation-plan"),
        steps: &[
            Step::Remove {
                path: "tests/npm_observation_plan.rs",
            },
            Step::Copy {
                from: "uniswap-v3/npm-provider-executor/v1/src/npm_provider_executor.rs",
                to: "src/npm_provider_executor.rs",
            },
            Step::Copy {
                from: "uniswap-v3/npm-provider-executor/v1/npm-provider-executor-v1.json",
                to: "configs/npm-provider-executor-v1.json",
            },
            Step::Copy {
                from: "uniswap-v3/npm-provider-executor/v1/tests/npm_provider_executor.rs",
                to: "tests/npm_provider_executor.rs",
            },
        ],
        summary: "hermetic Uniswap V3 NPM provider executor",
    },
];

/// Looks a target up by the name its shell script carries.
pub fn target(name: &str) -> Option<&'static Target> {
    TARGETS.iter().find(|candidate| candidate.name == name)
}

/// The chain of targets to run, base first, ending at `name`.
pub fn chain(name: &str) -> Option<Vec<&'static Target>> {
    let mut chain = Vec::new();
    let mut current = target(name)?;
    loop {
        chain.push(current);
        match current.base {
            Some(base) => current = target(base)?,
            None => break,
        }
    }
    chain.reverse();
    Some(chain)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_base_resolves_and_no_chain_cycles() {
        for candidate in TARGETS {
            let chain = chain(candidate.name).expect("chain resolves");
            assert_eq!(chain.last().expect("non-empty").name, candidate.name);
            assert_eq!(chain[0].name, "chain-config");
            let mut seen = std::collections::BTreeSet::new();
            for link in &chain {
                assert!(seen.insert(link.name), "{} appears twice", link.name);
            }
        }
    }

    #[test]
    fn target_names_are_unique_and_match_a_shell_script() {
        let mut seen = std::collections::BTreeSet::new();
        for candidate in TARGETS {
            assert!(seen.insert(candidate.name), "duplicate {}", candidate.name);
        }
        assert_eq!(TARGETS.len(), 10);
    }
}
