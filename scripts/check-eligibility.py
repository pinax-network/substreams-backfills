#!/usr/bin/env python3
"""Fail closed unless a target has fresh eligible evidence for an action."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from eligibility import (
    EligibilityError,
    check_fresh_gate,
    load_policy,
    load_yaml,
    parse_utc,
    validate_binding,
    validate_binding_evidence,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("binding", type=Path)
    parser.add_argument(
        "--purpose",
        required=True,
        choices=("implementation-start", "compute-or-load-start"),
    )
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--now", help="RFC3339 UTC override for deterministic tests")
    parser.add_argument("--json", action="store_true", dest="json_output")
    args = parser.parse_args()
    repository = args.repository.resolve()
    policy_path = args.policy or repository / "eligibility/policy-v1.yaml"
    try:
        policy = load_policy(policy_path)
        binding = load_yaml(args.binding)
        validate_binding(binding, policy, binding_path=args.binding)
        evidence = validate_binding_evidence(binding, policy, repository)
        now = parse_utc(args.now, "--now") if args.now else datetime.now(timezone.utc)
        allowed, message = check_fresh_gate(binding, evidence, policy, args.purpose, now)
        result = {
            "allowed": allowed,
            "deployment": binding["deployment"],
            "purpose": args.purpose,
            "message": message,
        }
        print(json.dumps(result, sort_keys=True) if args.json_output else message)
        return 0 if allowed else 2
    except EligibilityError as error:
        print(f"eligibility check failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
