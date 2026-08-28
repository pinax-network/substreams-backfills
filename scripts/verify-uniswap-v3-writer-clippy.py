#!/usr/bin/env python3
"""Compare writer-runtime Clippy diagnostics with its ChainConfig baseline."""

from __future__ import annotations

import argparse
import collections
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT_PACKAGE = "substreams-uniswap-v3@0.1.0"
DEFAULT_CONTRACT = Path(__file__).resolve().parents[1] / "uniswap-v3/writer-runtime/clippy-baseline-v1.json"
NEW_RUNTIME_FILES = {
    "build.rs",
    "src/config.rs",
    "src/pb/uniswap.writer.v1.rs",
    "src/writer_runtime.rs",
}
ACKNOWLEDGED_HANDLER_LINT = (
    "src/lib.rs",
    "clippy::not_unsafe_ptr_arg_deref",
    "this public function might dereference a raw pointer but is not marked `unsafe`",
)
ACKNOWLEDGED_HANDLER_SOURCE = (
    "pub fn map_writer_events(params: String, block: Block) -> "
    "Result<crate::pb::writer::WriterEvents, Error> {"
)


class LintVerificationError(RuntimeError):
    pass


def warning_key(message: dict[str, object]) -> tuple[str, str, str, str] | None:
    diagnostic = message.get("message", {})
    if diagnostic.get("level") != "warning":
        return None
    code = diagnostic.get("code") or {}
    code_name = code.get("code")
    primary = [span for span in diagnostic.get("spans", []) if span.get("is_primary")]
    if not code_name or not primary:
        return None
    file_name = "|".join(sorted({span["file_name"] for span in primary}))
    source = "\n".join(
        line["text"]
        for span in primary
        for line in span.get("text", [])
    )
    return file_name, code_name, diagnostic["message"], source


def unclassified_root_warning(message: dict[str, object]) -> str | None:
    if message.get("reason") != "compiler-message" or ROOT_PACKAGE not in message.get("package_id", ""):
        return None
    diagnostic = message.get("message", {})
    if diagnostic.get("level") != "warning" or warning_key(message) is not None:
        return None
    if (
        not diagnostic.get("code")
        and not diagnostic.get("spans")
        and re.fullmatch(r"\d+ warnings? emitted", diagnostic.get("message", ""))
    ):
        return None
    return json.dumps(diagnostic, sort_keys=True)


def cargo_root_warnings(stderr: str) -> list[str]:
    return [
        line
        for line in stderr.splitlines()
        if line.startswith(f"warning: {ROOT_PACKAGE}:")
    ]


def collect_warnings(runtime: Path, cargo: str, target: str | None, target_dir: Path) -> collections.Counter:
    command = [cargo, "+1.79.0", "clippy", "--locked", "--all-targets", "--message-format=json"]
    if target:
        command.extend(("--target", target))
    # This macro-export lint is deny-by-default. Downgrade it to a reported
    # warning so the baseline comparison can inventory it instead of hiding it.
    command.extend(("--", "-W", "clippy::not_unsafe_ptr_arg_deref"))
    environment = {**os.environ, "CARGO_TARGET_DIR": str(target_dir)}
    process = subprocess.Popen(
        command,
        cwd=runtime,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    warnings: collections.Counter = collections.Counter()
    unclassified: list[str] = []
    assert process.stdout is not None
    for line in process.stdout:
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if message.get("reason") != "compiler-message" or ROOT_PACKAGE not in message.get("package_id", ""):
            continue
        key = warning_key(message)
        diagnostic = message.get("message", {})
        if diagnostic.get("level") != "warning":
            continue
        if key is None:
            payload = unclassified_root_warning(message)
            if payload is not None:
                unclassified.append(payload)
        else:
            warnings[key] += 1
    stderr = process.stderr.read() if process.stderr else ""
    returncode = process.wait()
    if returncode:
        raise LintVerificationError(f"Clippy failed for {runtime}:\n{stderr[-4000:]}")
    cargo_warnings = cargo_root_warnings(stderr)
    if unclassified or cargo_warnings:
        raise LintVerificationError(
            "unclassified root-package warning(s) escaped the exact Clippy inventory: "
            f"compiler={unclassified}, cargo={cargo_warnings}"
        )
    return warnings


def categories(warnings: collections.Counter) -> dict[str, int]:
    output: collections.Counter = collections.Counter()
    for (_, code, _, _), count in warnings.items():
        output[code] += count
    return dict(sorted(output.items()))


def inventory(warnings: collections.Counter) -> collections.Counter:
    output: collections.Counter = collections.Counter()
    for (file_name, code, message, _), count in warnings.items():
        output[(file_name, code, message)] += count
    return output


def file_lint_inventory(warnings: collections.Counter) -> collections.Counter:
    output: collections.Counter = collections.Counter()
    for (file_name, code, _, _), count in warnings.items():
        output[(file_name, code)] += count
    return output


def load_contract(path: Path) -> dict[str, object]:
    contract = json.loads(path.read_text())
    if contract["format_version"] != 1 or contract["contract_version"] != "uniswap-v3-writer-runtime-clippy-baseline/v1":
        raise LintVerificationError("unsupported Clippy baseline contract")
    if contract["rust_toolchain"] != "1.79.0":
        raise LintVerificationError("Clippy baseline toolchain drift")
    if set(contract["new_runtime_files_required_clean"]) != NEW_RUNTIME_FILES:
        raise LintVerificationError("strict-Clippy runtime file set drift")
    expected_acknowledgement = {
        "count": 2,
        "file": ACKNOWLEDGED_HANDLER_LINT[0],
        "lint": ACKNOWLEDGED_HANDLER_LINT[1],
        "origin": "Substreams handler macro host-ABI wrapper, once for lib and once for lib-test",
        "source": ACKNOWLEDGED_HANDLER_SOURCE,
    }
    if contract["acknowledged_runtime_only"] != expected_acknowledgement:
        raise LintVerificationError("diagnostic handler lint acknowledgement drift")
    expected_truth = {
        "broad_lint_suppression_added": False,
        "legacy_lint_debt_fixed": False,
        "new_handwritten_runtime_strict_clippy_clean": True,
    }
    if contract["truth_boundary"] != expected_truth:
        raise LintVerificationError("Clippy baseline truth boundary drift")
    return contract


def verify(
    baseline: Path,
    runtime: Path,
    contract: dict[str, object],
    cargo: str,
    target: str | None,
) -> tuple[collections.Counter, collections.Counter]:
    with tempfile.TemporaryDirectory(prefix="uniswap-v3-writer-clippy-") as temporary:
        temporary_path = Path(temporary)
        baseline_warnings = collect_warnings(baseline, cargo, target, temporary_path / "baseline")
        runtime_warnings = collect_warnings(runtime, cargo, target, temporary_path / "runtime")

    pinned_baseline = collections.Counter(
        {
            (item["file"], item["lint"]): item["count"]
            for item in contract["baseline_inventory"]
        }
    )
    if file_lint_inventory(baseline_warnings) != pinned_baseline:
        raise LintVerificationError("ChainConfig Clippy inventory drifted from the exact pinned baseline")
    if sum(baseline_warnings.values()) != contract["baseline_warning_count"]:
        raise LintVerificationError("ChainConfig Clippy warning count drift")

    baseline_inventory = inventory(baseline_warnings)
    runtime_inventory = inventory(runtime_warnings)
    missing = baseline_inventory - runtime_inventory
    if missing:
        raise LintVerificationError(f"legacy lint inventory unexpectedly changed or disappeared: {missing}")
    extra = runtime_inventory - baseline_inventory
    expected_extra = collections.Counter({ACKNOWLEDGED_HANDLER_LINT: contract["acknowledged_runtime_only"]["count"]})
    if extra != expected_extra:
        raise LintVerificationError(f"unacknowledged writer-runtime lint regression: {extra}")
    handwritten = {
        key: count
        for key, count in runtime_warnings.items()
        if key[0] in set(contract["new_runtime_files_required_clean"])
    }
    if handwritten:
        raise LintVerificationError(f"new handwritten/generated runtime files are not strict-Clippy clean: {handwritten}")
    handler_diagnostics = sum(
        count
        for (file_name, code, message, source), count in runtime_warnings.items()
        if (file_name, code, message) == ACKNOWLEDGED_HANDLER_LINT
        and source.strip() == ACKNOWLEDGED_HANDLER_SOURCE
    )
    if handler_diagnostics != contract["acknowledged_runtime_only"]["count"]:
        raise LintVerificationError(
            f"expected the map_writer_events macro lint once per lib target, found {handler_diagnostics}"
        )
    return baseline_warnings, runtime_warnings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--cargo", default="cargo")
    parser.add_argument("--target")
    args = parser.parse_args()
    try:
        contract = load_contract(args.contract.resolve())
        baseline, runtime = verify(
            args.baseline.resolve(),
            args.runtime.resolve(),
            contract,
            args.cargo,
            args.target,
        )
        print(
            json.dumps(
                {
                    "acknowledged_runtime_only": {
                        "count": 2,
                        "file": "src/lib.rs",
                        "lint": "clippy::not_unsafe_ptr_arg_deref",
                        "origin": "Substreams handler macro export for map_writer_events, once per lib target",
                    },
                    "baseline_categories": categories(baseline),
                    "baseline_warning_count": sum(baseline.values()),
                    "new_runtime_file_warning_count": 0,
                    "runtime_categories": categories(runtime),
                    "runtime_warning_count": sum(runtime.values()),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    except (LintVerificationError, OSError) as error:
        print(f"Uniswap V3 writer-runtime Clippy verification failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
