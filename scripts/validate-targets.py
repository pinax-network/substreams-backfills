#!/usr/bin/env python3
"""Validate every target binding and its pinned eligibility evidence offline."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from eligibility import (
    EligibilityError,
    load_json,
    load_policy,
    load_yaml,
    validate_binding,
    validate_binding_evidence,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--policy", type=Path)
    args = parser.parse_args()
    repository = args.repository.resolve()
    policy_path = args.policy or repository / "eligibility/policy-v1.yaml"
    try:
        policy = load_policy(policy_path)
        for schema_name in ("target-binding-v1.schema.json", "eligibility-evidence-v1.schema.json"):
            schema = load_json(repository / "schemas" / schema_name)
            if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
                raise EligibilityError(f"{schema_name} is not a draft 2020-12 schema")
            if not schema.get("$id"):
                raise EligibilityError(f"{schema_name} is missing $id")
        bindings = sorted(repository.glob("*/Qm*.yaml"))
        if not bindings:
            raise EligibilityError("no target bindings found")
        for binding_path in bindings:
            binding = load_yaml(binding_path)
            validate_binding(binding, policy, binding_path=binding_path)
            validate_binding_evidence(binding, policy, repository)
            latest = binding["eligibility"]["latest"]
            print(
                f"{binding['deployment']} {binding['chain']} "
                f"decision={latest['decision']} reason={latest['reason']}"
            )
        print(f"validated {len(bindings)} target bindings")
        return 0
    except EligibilityError as error:
        print(f"target validation failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
