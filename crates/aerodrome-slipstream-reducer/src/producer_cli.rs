//! Staged producer/v1 entry. Bundle identity is never accepted from replay argv.
use crate::{cli, runtime::VerifiedRuntime};
use std::{collections::BTreeMap, io::Write, path::PathBuf};

#[derive(Debug)]
pub struct Failure {
    pub exit_code: u8,
    pub message: String,
}
fn usage(message: impl ToString) -> Failure {
    Failure {
        exit_code: 2,
        message: message.to_string(),
    }
}
fn data(message: impl ToString) -> Failure {
    Failure {
        exit_code: 4,
        message: message.to_string(),
    }
}

pub fn run(args: Vec<String>) -> Result<(), Failure> {
    let mut args = args.into_iter();
    let mut remaining = Vec::new();
    let mut globals = BTreeMap::new();
    let mut allow_non_final = false;
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--runtime-root" | "--runtime-sha256" => {
                let value = args
                    .next()
                    .filter(|v| !v.is_empty() && !v.starts_with("--"))
                    .ok_or_else(|| usage(format!("missing {arg} value")))?;
                if globals.insert(arg, value).is_some() {
                    return Err(usage("duplicate runtime option"));
                }
            }
            "--allow-non-final" => {
                if allow_non_final {
                    return Err(usage("duplicate --allow-non-final"));
                }
                allow_non_final = true;
            }
            _ => remaining.push(arg),
        }
    }
    let Some(command) = remaining.first() else {
        return Err(usage("expected stage|version|seed|reduce|rewind|inspect"));
    };
    if !["stage", "version", "seed", "reduce", "rewind", "inspect"].contains(&command.as_str()) {
        return Err(usage("expected stage|version|seed|reduce|rewind|inspect"));
    }
    let root = if let Some(root) = globals.get("--runtime-root") {
        PathBuf::from(root)
    } else {
        std::env::current_exe()
            .map_err(data)?
            .parent()
            .and_then(|p| p.parent())
            .ok_or_else(|| usage("cannot infer runtime root from executable"))?
            .to_path_buf()
    };
    let runtime = VerifiedRuntime::load(&root, globals.get("--runtime-sha256").map(String::as_str))
        .map_err(data)?;
    runtime.verify_running_executable().map_err(data)?;
    let options = &remaining[1..];
    match command.as_str() {
        "version" => {
            if options != ["--json"] {
                return Err(usage("version requires --json"));
            }
            let mut out = std::io::stdout().lock();
            out.write_all(runtime.manifest_bytes()).map_err(data)?;
            out.flush().map_err(data)?;
            return Ok(());
        }
        "stage" => {
            if options.len() != 2 || options[0] != "--dest" {
                return Err(usage("stage requires --dest DIR"));
            }
            runtime.stage(&PathBuf::from(&options[1])).map_err(data)?;
            return Ok(());
        }
        _ => {}
    }
    if !runtime.manifest().production_selectable && !allow_non_final {
        return Err(Failure {
            exit_code: 5,
            message: "non-final producer execution requires --allow-non-final".into(),
        });
    }
    let input = runtime.input_binding();
    let translated = match command.as_str() {
        "seed" => seed_args(
            options,
            input.compatibility().capabilities().unwrap().start_block,
        )?,
        "reduce" => std::iter::once("stream".into())
            .chain(options.iter().cloned())
            .collect(),
        "rewind" | "inspect" => remaining,
        _ => unreachable!(),
    };
    cli::validate_pinned_arguments(&translated).map_err(usage)?;
    cli::run_pinned(translated, input, runtime.producer_binding()).map_err(data)
}

fn seed_args(args: &[String], root_start: u64) -> Result<Vec<String>, Failure> {
    let mut args = args.iter();
    let mut options = BTreeMap::new();
    let mut empty = false;
    while let Some(arg) = args.next() {
        if arg == "--empty" {
            if empty {
                return Err(usage("duplicate --empty"));
            }
            empty = true;
        } else {
            if ![
                "--from",
                "--out",
                "--start-block",
                "--engine-lineage",
                "--seed-manifest",
                "--seed-pins",
                "--cache-mib",
            ]
            .contains(&arg.as_str())
            {
                return Err(usage(format!("unknown seed option {arg}")));
            }
            let value = args
                .next()
                .ok_or_else(|| usage(format!("missing {arg} value")))?;
            if options.insert(arg.as_str(), value.as_str()).is_some() {
                return Err(usage("duplicate seed option"));
            }
        }
    }
    let required = |key| {
        options
            .get(key)
            .copied()
            .ok_or_else(|| usage(format!("missing {key}")))
    };
    let mut result = vec![
        if empty { "init" } else { "seed-captured" }.into(),
        "--state-dir".into(),
        required("--out")?.into(),
    ];
    if empty {
        if ["--from", "--seed-manifest", "--seed-pins"]
            .iter()
            .any(|k| options.contains_key(k))
        {
            return Err(usage("empty seed cannot include capture options"));
        }
        let start = required("--start-block")?.parse::<u64>().map_err(usage)?;
        if start != root_start {
            return Err(usage("empty seed must start at the deployment root"));
        }
        result.extend([
            "--engine-lineage".into(),
            required("--engine-lineage")?.into(),
        ]);
    } else {
        if ["--start-block", "--engine-lineage"]
            .iter()
            .any(|k| options.contains_key(k))
        {
            return Err(usage(
                "captured seed takes its boundary and lineage from explicit capture pins",
            ));
        }
        for key in ["--from", "--seed-manifest", "--seed-pins"] {
            result.extend([key.into(), required(key)?.into()]);
        }
    }
    if let Some(cache) = options.get("--cache-mib") {
        result.extend(["--cache-mib".into(), (*cache).into()]);
    }
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;
    fn args(s: &[&str]) -> Vec<String> {
        s.iter().map(|s| (*s).into()).collect()
    }
    #[test]
    fn empty_seed_cannot_skip_history_or_silently_select_another_origin() {
        let good = args(&[
            "--empty",
            "--start-block",
            "13843704",
            "--out",
            "state",
            "--engine-lineage",
            "pin",
        ]);
        assert_eq!(
            seed_args(&good, 13843704).unwrap(),
            args(&["init", "--state-dir", "state", "--engine-lineage", "pin"])
        );
        assert!(seed_args(&good, 13843705).is_err());
        for extra in [
            args(&["--empty"]),
            args(&["--from", "seed"]),
            args(&["--seed-pins", "pins"]),
            args(&["--out", "other"]),
            args(&["--producer-binding", "override"]),
        ] {
            let mut bad = good.clone();
            bad.extend(extra);
            assert!(seed_args(&bad, 13843704).is_err());
        }
    }
    #[test]
    fn imported_seed_always_uses_typed_capture_entry_and_all_external_pins() {
        let good = args(&[
            "--from",
            "seed",
            "--out",
            "state",
            "--seed-manifest",
            "manifest",
            "--seed-pins",
            "pins",
        ]);
        assert_eq!(seed_args(&good, 13843704).unwrap()[0], "seed-captured");
        for extra in [
            args(&["--empty"]),
            args(&["--start-block", "13843704"]),
            args(&["--engine-lineage", "override"]),
        ] {
            let mut bad = good.clone();
            bad.extend(extra);
            assert!(seed_args(&bad, 13843704).is_err());
        }
        for missing in (0..good.len()).step_by(2) {
            let mut bad = good.clone();
            bad.drain(missing..missing + 2);
            assert!(seed_args(&bad, 13843704).is_err());
        }
    }
}
