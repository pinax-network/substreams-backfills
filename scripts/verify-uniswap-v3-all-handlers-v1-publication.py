#!/usr/bin/env python3
"""Verify the post-merge publication seal for Uniswap V3 all-handlers v1.

The immutable all-handlers contract deliberately leaves its own canonical
publication flag false.  This separate seal binds that exact contract to the
tested PR candidate, the byte-identical canonical squash tree, and the exact
successful ``main`` push workflow at the canonical aggregate commit.  It
promotes only the effective aggregate publication root; it does not modify or
reinterpret any semantic, runtime, parity, backfill, delivery, or issue gate.

The four values marked ``None`` below must be filled from the real PR #100
squash merge and its completed canonical workflow before a seal can verify.
Leaving any one unset is an intentional fail-closed preparation state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[1]
SEAL_PATH = Path("uniswap-v3/all-handlers/v1/publication-seal.json")
SEAL_VERSION = "uniswap-v3-all-handlers/v1/publication-seal/v1"

CANDIDATE_PR_NUMBER = 100
CANDIDATE_HEAD = "ebac0f4c72cf564aee21a34c54e90bc0b0777145"
CANDIDATE_TREE = "e96f0956e76d136664db58e0d210851af38c2c87"
CONTRACT_PATH = "uniswap-v3/all-handlers/v1/contract.json"
CONTRACT_BLOB = "d34393070324970f758b38b2cc80e4e533f6f1ae"
CONTRACT_BYTE_LENGTH = 14_769_915
CONTRACT_RAW_SHA256 = "04d0608da305bcd6575a9f9e02711d21cc3aaa7362701d85763d23afe9881fd0"
CONTRACT_CANONICAL_SHA256 = "9184573f56492131e803bfaf77f5e42ecaccb9fe388f5b71bc78ff35b992976f"
CONTRACT_TRUTH_BOUNDARY_SHA256 = "d45d3bf272471a7ebe28840317e2b51e4fa464a92b85b7f8c5672555227280fb"

# Fill only after the tested PR #100 head is squash-merged and its exact
# canonical main-push workflow has completed successfully.
EXPECTED_CANONICAL_AGGREGATE_COMMIT: str | None = None
EXPECTED_CANONICAL_AGGREGATE_PARENT: str | None = None
EXPECTED_CANONICAL_MAIN_PUSH_RUN_ID: int | None = None
EXPECTED_PAYLOAD_CANONICAL_SHA256: str | None = None

EXPECTED_REPOSITORY = "pinax-network/substreams-backfills"
EXPECTED_WORKFLOW_NAME = "ci"
EXPECTED_WORKFLOW_PATH = ".github/workflows/ci.yaml"
EXPECTED_JOB_NAMES = tuple(
    sorted(
        (
            "build",
            "exchange-v3-bsc-reference",
            "pancakeswap-infinity-cl-bsc-reference",
            "uniswap-v3-matic-reference",
            "uniswap-v3-reference",
            "uniswap-v4-reference",
        )
    )
)
EXPECTED_AGGREGATE_STEP_NAME = "Verify candidate complete Uniswap V3 all-handlers v1 matrix"
MAIN_REF = "refs/remotes/origin/main"
PUBLICATION_DOC_PATHS = (
    Path("README.md"),
    Path("uniswap-v3/README.md"),
    Path("uniswap-v3/all-handlers/v1/README.md"),
    Path("uniswap-v3/all-handlers/v1/docs/eligibility.md"),
    Path("uniswap-v3/all-handlers/v1/docs/provenance.md"),
)
PROVENANCE_DOC_PATH = Path("uniswap-v3/all-handlers/v1/docs/provenance.md")
PUBLICATION_RECORD_START = "<!-- publication-seal-record:start -->"
PUBLICATION_RECORD_END = "<!-- publication-seal-record:end -->"
PRODUCTION_PLACEHOLDERS = (
    "{{EXPECTED_CANONICAL_AGGREGATE_COMMIT}}",
    "{{EXPECTED_CANONICAL_AGGREGATE_PARENT}}",
    "{{EXPECTED_CANONICAL_MAIN_PUSH_RUN_ID}}",
    "{{EXPECTED_PAYLOAD_CANONICAL_SHA256}}",
)
STALE_PRESENT_TENSE_PUBLICATION_WORDING = (
    "not presently a canonical aggregate publication",
    "currently not a canonical aggregate publication",
    "not currently a canonical aggregate publication",
)

UNCHANGED_FALSE_GATES = (
    "source_package_identity_proven",
    "imported_host_semantics_rederived",
    "imported_numeric_or_comparator_semantics_rederived",
    "arbitrary_alias_safety_complete",
    "uniform_setter_to_matching_store_path_proven",
    "uniform_setter_store_common_execution_path_proven",
    "uniform_setter_store_branch_correlation_proven",
    "uniform_setter_store_receiver_must_alias_proven",
    "no_setter_means_preserved_or_unchanged",
    "graph_store_visibility_or_version_proven",
    "graph_store_persistence_proven",
    "graph_store_rollback_proven",
    "post_fatal_execution_complete",
    "complete_entity_histories",
    "runtime_population_complete",
    "required_nonempty_certified",
    "target_runtime_identity_proven",
    "combined_handler_scheduler_implemented",
    "global_flattened_event_order_proven",
    "shared_entity_last_writer_complete",
    "transaction_last_writer_complete",
    "query_visibility_complete",
    "output_or_graph_out_complete",
    "store_consumer_complete",
    "package_consumer_complete",
    "boundary_continuity_proven",
    "provider_or_graph_oracle_compared",
    "logical_parity_proven",
    "physical_or_poi_parity_proven",
    "checkpoint_authority_complete",
    "backfill_ready",
    "deployment_ready",
    "production_ready",
    "readiness_complete",
    "issue_37_acceptance_criterion_completed",
    "issue_38_acceptance_criterion_completed",
    "issue_checkbox_completed",
    "issue_closed",
)

SHA1_RE = re.compile(r"[0-9a-f]{40}\Z")
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
UTC_TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")


class VerificationError(RuntimeError):
    """Raised when the publication seal does not reproduce exactly."""


@dataclass(frozen=True)
class Expectations:
    candidate_pr_number: int
    candidate_head: str
    candidate_tree: str
    canonical_commit: str
    canonical_parent: str
    canonical_tree: str
    contract_path: str
    contract_blob: str
    contract_byte_length: int
    contract_raw_sha256: str
    contract_canonical_sha256: str
    contract_truth_boundary_sha256: str
    main_push_run_id: int
    payload_canonical_sha256: str
    main_ref: str = MAIN_REF


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def raw_sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def render(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json_bytes(value: bytes, source: str) -> dict[str, Any]:
    try:
        result = json.loads(value, object_pairs_hook=reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise VerificationError(f"invalid JSON at {source}: {error}") from error
    require(isinstance(result, dict), f"JSON root is not an object: {source}")
    return result


def require_exact_keys(value: Any, expected: set[str], context: str) -> dict[str, Any]:
    require(isinstance(value, dict), f"{context} must be an object")
    actual = set(value)
    require(actual == expected, f"{context} keys differ: missing={sorted(expected - actual)}, unexpected={sorted(actual - expected)}")
    return value


def require_int(value: Any, context: str, *, positive: bool = False) -> int:
    require(type(value) is int, f"{context} must be an integer")
    if positive:
        require(value > 0, f"{context} must be positive")
    else:
        require(value >= 0, f"{context} must be non-negative")
    return value


def parse_timestamp(value: Any, context: str) -> datetime:
    require(isinstance(value, str) and UTC_TIMESTAMP_RE.fullmatch(value) is not None, f"{context} must be a strict UTC RFC3339 timestamp")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as error:
        raise VerificationError(f"{context} is not a valid timestamp: {value}") from error
    return parsed


def git_output(root: Path, *arguments: str) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(root), *arguments],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    require(completed.returncode == 0, f"git {' '.join(arguments)} failed: {completed.stderr.decode(errors='replace').strip()}")
    return completed.stdout


def git_text(root: Path, *arguments: str) -> str:
    return git_output(root, *arguments).decode().strip()


def is_ancestor(root: Path, ancestor: str, descendant: str) -> bool:
    completed = subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", ancestor, descendant],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    require(completed.returncode in (0, 1), f"cannot test ancestry {ancestor}..{descendant}")
    return completed.returncode == 0


def safe_repository_file(root: Path, relative: str | Path, context: str) -> Path:
    raw = str(relative)
    require("\\" not in raw, f"{context} must use repository-relative POSIX syntax")
    pure = PurePosixPath(raw)
    require(not pure.is_absolute() and pure.parts and all(part not in ("", ".", "..") for part in pure.parts), f"{context} escapes the repository")
    candidate = root
    for part in pure.parts:
        candidate /= part
        require(not candidate.is_symlink(), f"{context} uses a symlinked path component")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root.resolve())
    except (OSError, ValueError) as error:
        raise VerificationError(f"{context} is missing or escapes the repository: {raw}") from error
    require(resolved.is_file(), f"{context} is not a regular file: {raw}")
    return resolved


def production_expectations() -> Expectations:
    missing = [
        name
        for name, value in (
            ("EXPECTED_CANONICAL_AGGREGATE_COMMIT", EXPECTED_CANONICAL_AGGREGATE_COMMIT),
            ("EXPECTED_CANONICAL_AGGREGATE_PARENT", EXPECTED_CANONICAL_AGGREGATE_PARENT),
            ("EXPECTED_CANONICAL_MAIN_PUSH_RUN_ID", EXPECTED_CANONICAL_MAIN_PUSH_RUN_ID),
            ("EXPECTED_PAYLOAD_CANONICAL_SHA256", EXPECTED_PAYLOAD_CANONICAL_SHA256),
        )
        if value is None
    ]
    require(not missing, f"publication seal production facts are not configured: {', '.join(missing)}")
    assert EXPECTED_CANONICAL_AGGREGATE_COMMIT is not None
    assert EXPECTED_CANONICAL_AGGREGATE_PARENT is not None
    assert EXPECTED_CANONICAL_MAIN_PUSH_RUN_ID is not None
    assert EXPECTED_PAYLOAD_CANONICAL_SHA256 is not None
    return Expectations(
        candidate_pr_number=CANDIDATE_PR_NUMBER,
        candidate_head=CANDIDATE_HEAD,
        candidate_tree=CANDIDATE_TREE,
        canonical_commit=EXPECTED_CANONICAL_AGGREGATE_COMMIT,
        canonical_parent=EXPECTED_CANONICAL_AGGREGATE_PARENT,
        canonical_tree=CANDIDATE_TREE,
        contract_path=CONTRACT_PATH,
        contract_blob=CONTRACT_BLOB,
        contract_byte_length=CONTRACT_BYTE_LENGTH,
        contract_raw_sha256=CONTRACT_RAW_SHA256,
        contract_canonical_sha256=CONTRACT_CANONICAL_SHA256,
        contract_truth_boundary_sha256=CONTRACT_TRUTH_BOUNDARY_SHA256,
        main_push_run_id=EXPECTED_CANONICAL_MAIN_PUSH_RUN_ID,
        payload_canonical_sha256=EXPECTED_PAYLOAD_CANONICAL_SHA256,
    )


def publication_record_markdown(expectations: Expectations) -> str:
    repository_url = f"https://github.com/{EXPECTED_REPOSITORY}"
    return "\n".join(
        (
            PUBLICATION_RECORD_START,
            f"- tested PR #{expectations.candidate_pr_number} candidate commit: "
            f"[`{expectations.candidate_head}`]({repository_url}/commit/{expectations.candidate_head})",
            f"- tested candidate tree: [`{expectations.candidate_tree}`]"
            f"({repository_url}/tree/{expectations.candidate_head})",
            f"- canonical aggregate squash commit: [`{expectations.canonical_commit}`]"
            f"({repository_url}/commit/{expectations.canonical_commit})",
            f"- canonical aggregate parent: [`{expectations.canonical_parent}`]"
            f"({repository_url}/commit/{expectations.canonical_parent})",
            f"- canonical aggregate tree: [`{expectations.canonical_tree}`]"
            f"({repository_url}/tree/{expectations.canonical_commit}) "
            "(byte-identical to the tested candidate tree)",
            f"- canonical exact-head `main` push run: [`{expectations.main_push_run_id}`]"
            f"({repository_url}/actions/runs/{expectations.main_push_run_id})",
            f"- seal payload canonical SHA-256: `{expectations.payload_canonical_sha256}`",
            PUBLICATION_RECORD_END,
        )
    )


def replace_publication_record(document: str, record: str) -> str:
    require(
        document.count(PUBLICATION_RECORD_START) == 1,
        "provenance document must contain exactly one publication record start marker",
    )
    require(
        document.count(PUBLICATION_RECORD_END) == 1,
        "provenance document must contain exactly one publication record end marker",
    )
    start = document.index(PUBLICATION_RECORD_START)
    end = document.index(PUBLICATION_RECORD_END, start) + len(PUBLICATION_RECORD_END)
    return document[:start] + record + document[end:]


def verify_publication_docs(root: Path, expectations: Expectations) -> None:
    documents: dict[Path, str] = {}
    for relative in PUBLICATION_DOC_PATHS:
        retained = safe_repository_file(root, relative, f"publication status document {relative}")
        text = retained.read_text(encoding="utf-8")
        documents[relative] = text
        normalized = " ".join(text.lower().split())
        for stale in STALE_PRESENT_TENSE_PUBLICATION_WORDING:
            require(
                stale not in normalized,
                f"stale present-tense publication wording in {relative}: {stale}",
            )

    provenance = documents[PROVENANCE_DOC_PATH]
    for placeholder in PRODUCTION_PLACEHOLDERS:
        require(placeholder not in provenance, f"unresolved production provenance placeholder: {placeholder}")
    expected_record = publication_record_markdown(expectations)
    require(
        replace_publication_record(provenance, expected_record) == provenance,
        "canonical aggregate publication provenance record differs from the configured production pins",
    )


def expected_publication_truth() -> dict[str, Any]:
    return {
        "sealed_contract_canonical_publication_root_complete": False,
        "sealed_contract_post_merge_publication_seal_required": True,
        "post_merge_aggregate_publication_seal_complete": True,
        "effective_canonical_aggregate_publication_root_complete": True,
        "third_order_publication_seal_required": False,
        "semantic_promotions": [],
        "unchanged_false_gates": {name: False for name in UNCHANGED_FALSE_GATES},
        "issue_effect": {
            "37": {"checkboxes_completed_by_this_seal": [], "issue_closed": False},
            "38": {"checkboxes_completed_by_this_seal": [], "issue_closed": False},
        },
    }


def build_seal(expectations: Expectations, canonical_main_push_ci: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "candidate_anchor": {
            "pull_request_number": expectations.candidate_pr_number,
            "head": expectations.candidate_head,
            "tree": expectations.candidate_tree,
        },
        "canonical_aggregate": {
            "squash_commit": expectations.canonical_commit,
            "parent": expectations.canonical_parent,
            "tree": expectations.canonical_tree,
            "candidate_tree_identical": True,
        },
        "sealed_contract": {
            "path": expectations.contract_path,
            "git_blob": expectations.contract_blob,
            "byte_length": expectations.contract_byte_length,
            "raw_sha256": expectations.contract_raw_sha256,
            "canonical_json_sha256": expectations.contract_canonical_sha256,
            "truth_boundary_canonical_sha256": expectations.contract_truth_boundary_sha256,
        },
        "canonical_main_push_ci": canonical_main_push_ci,
        "publication_truth": expected_publication_truth(),
    }
    return {
        "format_version": 1,
        "seal_version": SEAL_VERSION,
        "payload": payload,
        "payload_canonical_sha256": canonical_sha256(payload),
    }


def verify_git_and_contract(root: Path, payload: dict[str, Any], expectations: Expectations) -> None:
    candidate = require_exact_keys(payload["candidate_anchor"], {"pull_request_number", "head", "tree"}, "candidate_anchor")
    require(candidate == {"pull_request_number": expectations.candidate_pr_number, "head": expectations.candidate_head, "tree": expectations.candidate_tree}, "candidate anchor differs from the tested PR #100 head/tree")
    require(SHA1_RE.fullmatch(candidate["head"]) is not None and SHA1_RE.fullmatch(candidate["tree"]) is not None, "candidate Git identities are malformed")

    canonical = require_exact_keys(payload["canonical_aggregate"], {"squash_commit", "parent", "tree", "candidate_tree_identical"}, "canonical_aggregate")
    require(canonical == {"squash_commit": expectations.canonical_commit, "parent": expectations.canonical_parent, "tree": expectations.canonical_tree, "candidate_tree_identical": True}, "canonical aggregate anchor differs from the pinned squash commit/parent/tree")
    for key in ("squash_commit", "parent", "tree"):
        require(SHA1_RE.fullmatch(canonical[key]) is not None, f"canonical_aggregate.{key} is malformed")
    require(canonical["squash_commit"] != candidate["head"], "canonical squash commit must be distinct from the tested candidate commit")
    require(canonical["tree"] == candidate["tree"], "canonical aggregate tree is not byte-identical to the tested candidate tree")

    commit = canonical["squash_commit"]
    require(git_text(root, "rev-parse", f"{commit}^{{commit}}") == commit, "canonical aggregate commit does not resolve exactly")
    parent_line = git_text(root, "rev-list", "--parents", "-n", "1", commit).split()
    require(parent_line == [commit, canonical["parent"]], "canonical aggregate is not the pinned single-parent squash commit")
    require(git_text(root, "rev-parse", f"{commit}^{{tree}}") == canonical["tree"], "canonical aggregate Git tree differs from the seal")
    require(is_ancestor(root, commit, expectations.main_ref), f"canonical aggregate commit is not reachable from {expectations.main_ref}")

    sealed = require_exact_keys(payload["sealed_contract"], {"path", "git_blob", "byte_length", "raw_sha256", "canonical_json_sha256", "truth_boundary_canonical_sha256"}, "sealed_contract")
    expected_sealed = {
        "path": expectations.contract_path,
        "git_blob": expectations.contract_blob,
        "byte_length": expectations.contract_byte_length,
        "raw_sha256": expectations.contract_raw_sha256,
        "canonical_json_sha256": expectations.contract_canonical_sha256,
        "truth_boundary_canonical_sha256": expectations.contract_truth_boundary_sha256,
    }
    require(sealed == expected_sealed, "sealed contract identity differs from the pinned immutable contract")
    require(SHA1_RE.fullmatch(sealed["git_blob"]) is not None, "sealed contract Git blob is malformed")
    for key in ("raw_sha256", "canonical_json_sha256", "truth_boundary_canonical_sha256"):
        require(SHA256_RE.fullmatch(sealed[key]) is not None, f"sealed_contract.{key} is malformed")

    contract_file = safe_repository_file(root, sealed["path"], "sealed contract path")
    working_bytes = contract_file.read_bytes()
    require(len(working_bytes) == sealed["byte_length"], "sealed contract working-tree byte length differs")
    require(raw_sha256(working_bytes) == sealed["raw_sha256"], "sealed contract working-tree raw SHA-256 differs")
    contract = load_json_bytes(working_bytes, sealed["path"])
    require(canonical_sha256(contract) == sealed["canonical_json_sha256"], "sealed contract canonical JSON SHA-256 differs")
    require("truth_boundary" in contract, "sealed contract has no truth_boundary")
    require(canonical_sha256(contract["truth_boundary"]) == sealed["truth_boundary_canonical_sha256"], "sealed contract truth-boundary SHA-256 differs")
    require(contract["truth_boundary"].get("canonical_publication_root_complete") is False, "sealed base contract must retain canonical_publication_root_complete=false")
    require(contract.get("post_merge_aggregate_publication_seal_required") is True, "sealed base contract must retain post_merge_aggregate_publication_seal_required=true")

    line = git_text(root, "ls-tree", commit, "--", sealed["path"])
    require("\t" in line, "sealed contract is absent from the canonical aggregate tree")
    metadata, retained_path = line.split("\t", 1)
    fields = metadata.split()
    require(retained_path == sealed["path"] and len(fields) == 3, "canonical aggregate contract tree entry is malformed")
    mode, object_type, object_id = fields
    require(mode == "100644" and object_type == "blob", "canonical aggregate contract is not a regular Git blob")
    require(object_id == sealed["git_blob"], "canonical aggregate contract Git blob differs from the seal")
    canonical_bytes_value = git_output(root, "show", f"{commit}:{sealed['path']}")
    require(canonical_bytes_value == working_bytes, "working-tree contract differs from the canonical aggregate contract")


def verify_ci(ci: Any, expectations: Expectations) -> None:
    ci = require_exact_keys(
        ci,
        {
            "repository",
            "run_id",
            "run_attempt",
            "run_url",
            "workflow_name",
            "workflow_path",
            "event",
            "branch",
            "head_sha",
            "status",
            "conclusion",
            "job_window_started_at",
            "job_window_completed_at",
            "jobs",
            "summary",
            "dedicated_all_handlers_validation_step",
        },
        "canonical_main_push_ci",
    )
    require(ci["repository"] == EXPECTED_REPOSITORY, "canonical CI repository differs")
    require_int(ci["run_id"], "canonical CI run_id", positive=True)
    require(ci["run_id"] == expectations.main_push_run_id, "canonical CI run ID differs from the pinned run")
    require_int(ci["run_attempt"], "canonical CI run_attempt", positive=True)
    require(ci["run_url"] == f"https://github.com/{EXPECTED_REPOSITORY}/actions/runs/{ci['run_id']}", "canonical CI run URL differs")
    require(ci["workflow_name"] == EXPECTED_WORKFLOW_NAME, "canonical CI workflow name differs")
    require(ci["workflow_path"] == EXPECTED_WORKFLOW_PATH, "canonical CI workflow path differs")
    require(ci["event"] == "push", "canonical CI event must be push")
    require(ci["branch"] == "main", "canonical CI branch must be main")
    require(ci["head_sha"] == expectations.canonical_commit, "canonical CI head differs from the canonical aggregate commit")
    require(ci["status"] == "completed" and ci["conclusion"] == "success", "canonical CI run is not completed successfully")

    jobs = ci["jobs"]
    require(isinstance(jobs, list), "canonical CI jobs must be a list")
    require(len(jobs) == len(EXPECTED_JOB_NAMES), "canonical CI must bind all six jobs")
    normalized_jobs: list[dict[str, Any]] = []
    ids: set[int] = set()
    names: list[str] = []
    for index, raw_job in enumerate(jobs):
        job = require_exact_keys(raw_job, {"job_id", "name", "status", "conclusion", "started_at", "completed_at", "step_counts"}, f"canonical CI job[{index}]")
        job_id = require_int(job["job_id"], f"canonical CI job[{index}].job_id", positive=True)
        require(job_id not in ids, "canonical CI contains a duplicate job ID")
        ids.add(job_id)
        require(isinstance(job["name"], str) and job["name"], f"canonical CI job[{index}] has no name")
        names.append(job["name"])
        require(job["status"] == "completed" and job["conclusion"] == "success", f"canonical CI job {job['name']} is not completed successfully")
        started = parse_timestamp(job["started_at"], f"canonical CI job {job['name']} started_at")
        completed = parse_timestamp(job["completed_at"], f"canonical CI job {job['name']} completed_at")
        require(started <= completed, f"canonical CI job {job['name']} has an inverted window")
        counts = require_exact_keys(job["step_counts"], {"total", "successful", "failed", "skipped"}, f"canonical CI job {job['name']} step_counts")
        total = require_int(counts["total"], f"canonical CI job {job['name']} total steps", positive=True)
        successful = require_int(counts["successful"], f"canonical CI job {job['name']} successful steps")
        failed = require_int(counts["failed"], f"canonical CI job {job['name']} failed steps")
        skipped = require_int(counts["skipped"], f"canonical CI job {job['name']} skipped steps")
        require(total == successful + failed + skipped, f"canonical CI job {job['name']} step counts do not add up")
        require(successful == total and failed == 0 and skipped == 0, f"canonical CI job {job['name']} has failed or skipped steps")
        normalized_jobs.append({"job": job, "started": started, "completed": completed})
    require(names == sorted(names), "canonical CI jobs are not in deterministic name order")
    require(tuple(names) == EXPECTED_JOB_NAMES, "canonical CI job names differ from the six-job workflow")

    window_start = parse_timestamp(ci["job_window_started_at"], "canonical CI job window start")
    window_end = parse_timestamp(ci["job_window_completed_at"], "canonical CI job window completion")
    require(window_start == min(item["started"] for item in normalized_jobs), "canonical CI job window start is not the earliest job start")
    require(window_end == max(item["completed"] for item in normalized_jobs), "canonical CI job window completion is not the latest job completion")

    summary = require_exact_keys(ci["summary"], {"jobs_total", "jobs_successful", "jobs_failed", "jobs_skipped", "steps_total", "steps_successful", "steps_failed", "steps_skipped"}, "canonical CI summary")
    for key, value in summary.items():
        require_int(value, f"canonical CI summary {key}")
    expected_summary = {
        "jobs_total": len(jobs),
        "jobs_successful": len(jobs),
        "jobs_failed": 0,
        "jobs_skipped": 0,
        "steps_total": sum(item["job"]["step_counts"]["total"] for item in normalized_jobs),
        "steps_successful": sum(item["job"]["step_counts"]["successful"] for item in normalized_jobs),
        "steps_failed": 0,
        "steps_skipped": 0,
    }
    require(summary == expected_summary, "canonical CI summary differs from the exact per-job ledger")

    step = require_exact_keys(ci["dedicated_all_handlers_validation_step"], {"job_id", "job_name", "number", "name", "status", "conclusion", "started_at", "completed_at"}, "dedicated all-handlers validation step")
    require_int(step["job_id"], "dedicated step job_id", positive=True)
    require_int(step["number"], "dedicated step number", positive=True)
    require(step["job_name"] == "build" and step["name"] == EXPECTED_AGGREGATE_STEP_NAME, "dedicated all-handlers validation step identity differs")
    matching = [item for item in normalized_jobs if item["job"]["job_id"] == step["job_id"] and item["job"]["name"] == step["job_name"]]
    require(len(matching) == 1, "dedicated all-handlers validation step does not bind the unique build job")
    build = matching[0]
    require(step["number"] <= build["job"]["step_counts"]["total"], "dedicated all-handlers validation step number exceeds the build step count")
    require(step["status"] == "completed" and step["conclusion"] == "success", "dedicated all-handlers validation step did not succeed")
    step_start = parse_timestamp(step["started_at"], "dedicated all-handlers validation step started_at")
    step_end = parse_timestamp(step["completed_at"], "dedicated all-handlers validation step completed_at")
    require(step_start <= step_end, "dedicated all-handlers validation step has an inverted window")
    require(build["started"] <= step_start <= step_end <= build["completed"], "dedicated all-handlers validation step is outside the build job window")


def verify_publication_truth(value: Any) -> None:
    expected = expected_publication_truth()
    require(value == expected, "publication truth differs: only the effective canonical aggregate publication root may be promoted")
    require(value["semantic_promotions"] == [], "publication seal must not promote semantic gates")
    require(all(flag is False for flag in value["unchanged_false_gates"].values()), "publication seal promotes a false gate")
    require(all(issue["checkboxes_completed_by_this_seal"] == [] and issue["issue_closed"] is False for issue in value["issue_effect"].values()), "publication seal changes issue checkbox or closure state")


def verify_seal(root: Path, seal: dict[str, Any], expectations: Expectations) -> dict[str, Any]:
    root = root.resolve()
    seal = require_exact_keys(seal, {"format_version", "seal_version", "payload", "payload_canonical_sha256"}, "publication seal")
    require(seal["format_version"] == 1, "publication seal format_version differs")
    require(seal["seal_version"] == SEAL_VERSION, "publication seal version differs")
    require(isinstance(seal["payload_canonical_sha256"], str) and SHA256_RE.fullmatch(seal["payload_canonical_sha256"]) is not None, "payload canonical SHA-256 is malformed")
    payload = require_exact_keys(seal["payload"], {"candidate_anchor", "canonical_aggregate", "sealed_contract", "canonical_main_push_ci", "publication_truth"}, "publication seal payload")
    actual_payload_sha256 = canonical_sha256(payload)
    require(seal["payload_canonical_sha256"] == actual_payload_sha256, "publication seal payload digest does not match its payload")
    require(actual_payload_sha256 == expectations.payload_canonical_sha256, "publication seal payload digest differs from the verifier pin")
    verify_git_and_contract(root, payload, expectations)
    verify_ci(payload["canonical_main_push_ci"], expectations)
    verify_publication_truth(payload["publication_truth"])
    return seal


def verify(root: Path, seal_path: Path = SEAL_PATH, expectations: Expectations | None = None) -> dict[str, Any]:
    root = root.resolve()
    retained = safe_repository_file(root, seal_path, "publication seal path")
    seal = load_json_bytes(retained.read_bytes(), retained.relative_to(root).as_posix())
    effective_expectations = expectations or production_expectations()
    verified = verify_seal(root, seal, effective_expectations)
    verify_publication_docs(root, effective_expectations)
    require(retained.read_text(encoding="utf-8") == render(verified), "publication seal JSON is not deterministically rendered")
    return verified


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the canonical Uniswap V3 all-handlers v1 publication seal.")
    parser.add_argument("--root", type=Path, default=REPOSITORY)
    parser.add_argument("--seal", type=Path, default=SEAL_PATH)
    args = parser.parse_args()
    try:
        seal = verify(args.root, args.seal)
    except VerificationError as error:
        parser.error(str(error))
    ci = seal["payload"]["canonical_main_push_ci"]
    print(f"verified canonical Uniswap V3 all-handlers v1 publication seal at {ci['head_sha']} with main push run {ci['run_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
