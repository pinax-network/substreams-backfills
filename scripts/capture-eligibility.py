#!/usr/bin/env python3
"""Build immutable eligibility evidence from reviewed raw measurements."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from eligibility import (
    EligibilityError,
    build_evidence,
    canonical_json,
    load_json,
    load_policy,
    load_yaml,
    parse_utc,
    resolve_evidence_path,
    sha256_file,
    validate_binding,
    validate_evidence,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binding", required=True, type=Path)
    parser.add_argument("--measurements", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--policy", type=Path, default=Path("eligibility/policy-v1.yaml"))
    args = parser.parse_args()
    try:
        policy = load_policy(args.policy)
        binding = load_yaml(args.binding)
        validate_binding(binding, policy, binding_path=args.binding)
        measurements = load_json(args.measurements)
        evidence = build_evidence(measurements, binding, policy)
        validate_evidence(evidence, binding, policy)
        repository = Path.cwd().resolve()
        output = args.output.resolve() if args.output.is_absolute() else (repository / args.output).resolve()
        relative = output.relative_to(repository)
        resolve_evidence_path(repository, relative.as_posix())
        expected_directory = repository / "evidence" / "eligibility" / binding["deployment"]
        expected_name = parse_utc(evidence["measured_at"], "evidence.measured_at").strftime("%Y%m%dT%H%M%SZ.json")
        if output.parent != expected_directory or output.name != expected_name:
            raise EligibilityError(
                f"output must be {expected_directory.relative_to(repository)}/{expected_name}"
            )
        if output.exists():
            raise EligibilityError(f"refusing to overwrite immutable evidence file {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(canonical_json(evidence))
        latest = {
            "decision": evidence["summary"]["decision"],
            "reason": evidence["summary"]["reason"],
            "measured_at": evidence["measured_at"],
            "evidence": relative.as_posix(),
            "sha256": sha256_file(output),
        }
        print("Captured immutable evidence. Review it, then update eligibility.latest to:")
        print(yaml.safe_dump(latest, sort_keys=False).rstrip())
        return 0
    except (EligibilityError, OSError, ValueError) as error:
        print(f"eligibility capture failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
