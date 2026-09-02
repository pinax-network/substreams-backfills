//! `cargo xtask verify-all` — the single driver for every retained repository
//! check. Each entry names the check, the family it belongs to, and the exact
//! command that CI runs today. Entries are replaced by native Rust
//! implementations as #110 ports them; until then the driver spawns the
//! retained command unchanged so the interface is stable for CI.

use std::process::Command;
use std::time::Instant;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Family {
    Core,
    Targets,
    UniswapV3,
    UniswapV4,
}

impl Family {
    pub fn parse(value: &str) -> Option<Family> {
        match value {
            "core" => Some(Family::Core),
            "targets" => Some(Family::Targets),
            "uniswap-v3" | "v3" => Some(Family::UniswapV3),
            "uniswap-v4" | "v4" => Some(Family::UniswapV4),
            _ => None,
        }
    }
    pub fn label(self) -> &'static str {
        match self {
            Family::Core => "core",
            Family::Targets => "targets",
            Family::UniswapV3 => "uniswap-v3",
            Family::UniswapV4 => "uniswap-v4",
        }
    }
}

/// Environment a check needs before it can run. `verify-all` refuses to run a
/// check whose requirement is absent instead of letting it fail obscurely.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Requires {
    Nothing,
    /// Externalized evidence blobs must be hydrated (`cargo xtask evidence fetch`).
    EvidenceAssets,
}

pub struct Check {
    pub name: &'static str,
    pub family: Family,
    pub requires: &'static [Requires],
    /// argv; `$WASM2WAT` is substituted from the environment.
    pub argv: &'static [&'static str],
}

pub const CHECKS: &[Check] = &[
    Check {
        name: "evidence-check",
        family: Family::Core,
        requires: &[Requires::EvidenceAssets],
        argv: &["cargo", "xtask", "evidence", "check"],
    },
    Check {
        name: "validate-targets",
        family: Family::Core,
        requires: &[Requires::Nothing],
        argv: &["python3", "scripts/validate-targets.py"],
    },
    Check {
        name: "eligibility-tests",
        family: Family::Core,
        requires: &[Requires::Nothing],
        argv: &[
            "python3",
            "-m",
            "unittest",
            "scripts.tests.test_eligibility",
            "scripts.tests.test_target_market_snapshots",
        ],
    },
    Check {
        name: "uniswap-v3-matic-target",
        family: Family::Targets,
        requires: &[Requires::EvidenceAssets],
        argv: &["python3", "scripts/verify-uniswap-v3-matic-target.py"],
    },
    Check {
        name: "uniswap-v2-base-target",
        family: Family::Targets,
        requires: &[Requires::Nothing],
        argv: &["python3", "scripts/verify-uniswap-v2-base-target.py"],
    },
    Check {
        name: "pancakeswap-infinity-cl-bsc-target",
        family: Family::Targets,
        requires: &[Requires::Nothing],
        argv: &[
            "python3",
            "scripts/verify-pancakeswap-infinity-cl-bsc-target.py",
        ],
    },
    Check {
        name: "exchange-v3-bsc-target",
        family: Family::Targets,
        requires: &[Requires::Nothing],
        argv: &["python3", "scripts/verify-exchange-v3-bsc-target.py"],
    },
    Check {
        name: "aerodrome-slipstream-base-target",
        family: Family::Targets,
        requires: &[Requires::Nothing],
        argv: &[
            "python3",
            "scripts/verify-aerodrome-slipstream-base-target.py",
        ],
    },
    Check {
        name: "messari-v3-targets",
        family: Family::Targets,
        requires: &[Requires::EvidenceAssets],
        argv: &["python3", "scripts/verify-messari-v3-targets.py"],
    },
    Check {
        name: "uniswap-v4-engine-reference",
        family: Family::UniswapV4,
        requires: &[Requires::Nothing],
        argv: &["python3", "scripts/verify-uniswap-v4-engine-reference.py"],
    },
    Check {
        name: "uniswap-v4-q8-reference",
        family: Family::UniswapV4,
        requires: &[Requires::Nothing],
        argv: &["python3", "scripts/verify-uniswap-v4-q8-reference.py"],
    },
    Check {
        name: "uniswap-v4-release-assets",
        family: Family::UniswapV4,
        requires: &[Requires::Nothing],
        argv: &["python3", "scripts/verify-uniswap-v4-release-assets.py"],
    },
];

pub struct Outcome {
    pub name: &'static str,
    pub ok: bool,
    pub seconds: f64,
    pub detail: String,
}

fn requirement_missing(requires: Requires, evidence_ok: bool) -> Option<String> {
    match requires {
        Requires::Nothing => None,
        Requires::EvidenceAssets => (!evidence_ok)
            .then(|| "evidence blobs not hydrated (run `cargo xtask evidence fetch`)".to_string()),
    }
}

pub fn list(family: Option<Family>) -> Vec<&'static Check> {
    CHECKS
        .iter()
        .filter(|c| family.is_none_or(|f| c.family == f))
        .collect()
}

/// Run the selected checks in registry order, stopping at the first failure
/// unless `keep_going`. `evidence_ok` is the result of an up-front
/// `evidence::check`, so a check that needs hydrated blobs is refused early.
pub fn run(family: Option<Family>, keep_going: bool, evidence_ok: bool) -> (Vec<Outcome>, bool) {
    let mut outcomes = Vec::new();
    let mut all_ok = true;
    for check in list(family) {
        if let Some(missing) = check
            .requires
            .iter()
            .find_map(|r| requirement_missing(*r, evidence_ok))
        {
            outcomes.push(Outcome {
                name: check.name,
                ok: false,
                seconds: 0.0,
                detail: format!("refused: {missing}"),
            });
            all_ok = false;
            if !keep_going {
                break;
            }
            continue;
        }
        let started = Instant::now();
        let wasm2wat = std::env::var("WASM2WAT").unwrap_or_default();
        let argv: Vec<String> = check
            .argv
            .iter()
            .map(|a| a.replace("$WASM2WAT", &wasm2wat))
            .collect();
        let status = Command::new(&argv[0]).args(&argv[1..]).status();
        let seconds = started.elapsed().as_secs_f64();
        let (ok, detail) = match status {
            Ok(s) if s.success() => (true, String::new()),
            Ok(s) => (
                false,
                format!(
                    "exit {}",
                    s.code().map_or("signal".to_string(), |c| c.to_string())
                ),
            ),
            Err(e) => (false, format!("spawn failed: {e}")),
        };
        all_ok &= ok;
        outcomes.push(Outcome {
            name: check.name,
            ok,
            seconds,
            detail,
        });
        if !ok && !keep_going {
            break;
        }
    }
    (outcomes, all_ok)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn registry_names_are_unique_and_families_parse() {
        let mut names: Vec<&str> = CHECKS.iter().map(|c| c.name).collect();
        let total = names.len();
        names.sort_unstable();
        names.dedup();
        assert_eq!(names.len(), total, "duplicate check names");
        for c in CHECKS {
            assert!(!c.argv.is_empty());
            assert_eq!(Family::parse(c.family.label()), Some(c.family));
        }
        assert!(Family::parse("nope").is_none());
    }

    #[test]
    fn refuses_checks_whose_requirements_are_missing() {
        let (outcomes, ok) = run(Some(Family::Targets), true, false);
        assert!(!ok);
        let refused: Vec<_> = outcomes
            .iter()
            .filter(|o| o.detail.starts_with("refused"))
            .map(|o| o.name)
            .collect();
        assert!(refused.contains(&"uniswap-v3-matic-target"));
        assert!(refused.contains(&"messari-v3-targets"));
    }

    #[test]
    fn list_filters_by_family() {
        assert!(list(Some(Family::UniswapV4))
            .iter()
            .all(|c| c.family == Family::UniswapV4));
        assert_eq!(list(None).len(), CHECKS.len());
    }
}
