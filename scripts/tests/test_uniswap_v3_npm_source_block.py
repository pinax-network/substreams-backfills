#!/usr/bin/env python3
"""Hermetic tests for the provider-free Uniswap V3 NPM source package."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VERIFIER_PATH = ROOT / "scripts/verify-uniswap-v3-npm-source-block.py"
SPEC = importlib.util.spec_from_file_location("npm_source_block_verifier", VERIFIER_PATH)
assert SPEC and SPEC.loader
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)
WRITER = VERIFIER.load_writer_verifier(ROOT)


def tree_digest(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(directory.rglob("*")):
        relative = path.relative_to(directory)
        if not path.is_file() or "target" in relative.parts:
            continue
        digest.update(relative.as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
        digest.update(b"x" if path.stat().st_mode & 0o111 else b"-")
    return digest.hexdigest()


class NpmSourceBlockContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source_before = tree_digest(ROOT / "uniswap-v3/source")
        cls.contract = VERIFIER.load_contract(ROOT)
        cls.semantics = VERIFIER.load_semantics(ROOT)
        VERIFIER.verify_upstream(ROOT)
        VERIFIER.verify_proto(ROOT)
        cls.manifests = VERIFIER.load_manifests(ROOT)
        VERIFIER.verify_static_source(ROOT)
        cls.temporary = tempfile.TemporaryDirectory(prefix="npm-source-block-tests-")
        cls.runtime = Path(cls.temporary.name) / "runtime"
        subprocess.run(
            [
                "bash",
                str(ROOT / "scripts/materialize-uniswap-v3-npm-source-block.sh"),
                str(cls.runtime),
            ],
            env={**os.environ, "PYTHON": sys.executable},
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def test_exact_six_authorities_and_conservative_truth_boundary(self) -> None:
        self.assertEqual(
            self.contract["source_authorities"],
            {
                "writer_runtime_sha256": VERIFIER.WRITER_RUNTIME_SHA256,
                "writer_profiles_sha256": VERIFIER.WRITER_PROFILES_SHA256,
                "writer_contract_sha256": VERIFIER.WRITER_CONTRACT_SHA256,
                "writer_proto_sha256": VERIFIER.WRITER_PROTO_SHA256,
                "segment_matrix_sha256": VERIFIER.SEGMENT_MATRIX_SHA256,
                "execution_order_sha256": VERIFIER.EXECUTION_ORDER_SHA256,
            },
        )
        truth = self.contract["truth_boundary"]
        self.assertTrue(truth["source_module_implemented"])
        self.assertTrue(truth["diagnostic_only"])
        self.assertTrue(all(value is False for key, value in truth.items() if key not in {"source_module_implemented", "diagnostic_only"}))

    def test_semantics_never_promote_projection_to_checkpoint_or_graph_success(self) -> None:
        self.assertEqual(self.semantics["mode"], "provider-free-source-only")
        self.assertFalse(self.semantics["provider_observations_serialized"])
        self.assertFalse(self.semantics["unresolved_errors_serialized"])
        self.assertFalse(self.semantics["checkpoint_authority"])
        self.assertFalse(self.semantics["graph_block_success_authority"])
        self.assertFalse(self.semantics["backfill_ready"])
        self.assertFalse(self.semantics["production_ready"])
        self.assertFalse(self.contract["module_contract"]["source_package_inherits_complete_writer_descriptor_set"])
        self.assertTrue(
            self.contract["module_contract"]["original_writer_package_descriptor_set_must_match_baseline"]
        )

    def test_proto_and_manifests_are_exactly_two_module_two_wasm_source_only(self) -> None:
        proto = (ROOT / VERIFIER.OVERLAY / "proto/uniswap/npm/source/v1/npm_source_block.proto").read_text()
        self.assertIn("uniswap.writer.v1.WriterEvents writer_events = 1;", proto)
        self.assertIn("repeated TransactionRef transactions = 3;", proto)
        unstable_sentinel = "Provider" + "Unavailable"
        for forbidden in (unstable_sentinel, "PossibleReorg", "PositionCall", "TokenRead", "checkpoint"):
            self.assertNotIn(forbidden, proto)
        for network, manifest in self.manifests.items():
            self.assertEqual(list(manifest["binaries"]), ["writer", "npm_source"], network)
            self.assertEqual(
                [module["name"] for module in manifest["modules"]],
                ["map_writer_events", "map_npm_source_block"],
                network,
            )
            self.assertEqual(
                manifest["modules"][1]["inputs"],
                [{"source": "sf.ethereum.type.v2.Block"}, {"map": "map_writer_events"}],
                network,
            )
            self.assertNotIn("doc", manifest["package"], network)
            self.assertEqual(manifest["protobuf"]["importPaths"], ["../proto"], network)
            self.assertNotIn("stores", manifest)
            self.assertTrue(all(module["kind"] == "map" for module in manifest["modules"]))
            self.assertNotIn("graph_out", [module["name"] for module in manifest["modules"]])

    def test_source_uses_successful_transaction_gas_limit_not_usage(self) -> None:
        source = (ROOT / VERIFIER.OVERLAY / "runtime/src/npm_source_block.rs").read_text()
        production = source.split("#[cfg(test)]", 1)[0]
        self.assertIn("TransactionTraceStatus::Succeeded", production)
        self.assertIn("gas_limit: trace.gas_limit", production)
        self.assertIn(".gas_price", production)
        self.assertIn(".as_ref()", production)
        self.assertNotIn("gas_used", production)
        self.assertIn("transactions.sort_by", production)
        self.assertIn("output.encode_to_vec() != bytes", production)
        for required in (
            "all_eight_segment_boundaries_emit_deterministic_empty_source_frames",
            "referenced_transactions_are_successful_unique_sorted_and_use_transaction_gas",
            "missing_failed_duplicate_and_malformed_transaction_metadata_fail_closed",
            "block_identity_header_parent_and_timestamp_corruption_fail_closed",
            "writer_network_segment_contract_address_and_order_corruption_fail_closed",
            "canonical_decoder_rejects_unknown_fields_and_source_table_corruption",
        ):
            self.assertIn(required, source)

    def test_dedicated_lock_is_pinned_valid_and_not_the_writer_lock(self) -> None:
        source_lock = ROOT / VERIFIER.OVERLAY / "runtime/Cargo.lock"
        self.assertEqual(hashlib.sha256(source_lock.read_bytes()).hexdigest(), VERIFIER.SOURCE_CARGO_LOCK_SHA256)
        lock = tomllib.loads(source_lock.read_text())
        versions = {item["name"]: item["version"] for item in lock["package"]}
        self.assertEqual(versions["home"], "0.5.9")
        self.assertEqual(versions["indexmap"], "2.2.5")
        self.assertEqual(versions["tempfile"], "3.10.1")
        self.assertNotEqual(
            (self.runtime / "npm-source-block-runtime/Cargo.lock").read_bytes(),
            (self.runtime / "Cargo.lock").read_bytes(),
        )

    def test_materialization_is_exact_and_preserves_writer_and_import(self) -> None:
        VERIFIER.verify_runtime(ROOT, self.runtime, self.contract)
        self.assertEqual(tree_digest(ROOT / "uniswap-v3/source"), self.source_before)
        with tempfile.TemporaryDirectory(prefix="npm-source-writer-baseline-") as temporary:
            baseline = Path(temporary) / "writer"
            WRITER.materialize_expected(ROOT, baseline)
            for relative, path in VERIFIER.non_build_files(baseline).items():
                self.assertEqual((self.runtime / relative).read_bytes(), path.read_bytes(), relative)

    def test_runtime_verifier_rejects_source_lock_and_writer_manifest_drift(self) -> None:
        for mutation in ("source-lock", "writer-manifest", "extra"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory(
                prefix="npm-source-runtime-drift-"
            ) as temporary:
                runtime = Path(temporary) / "runtime"
                shutil.copytree(self.runtime, runtime)
                if mutation == "source-lock":
                    target = runtime / "npm-source-block-runtime/Cargo.lock"
                    target.write_bytes(target.read_bytes() + b"\n")
                elif mutation == "writer-manifest":
                    target = runtime / "substreams.mainnet.yaml"
                    target.write_bytes(target.read_bytes() + b"\n")
                else:
                    (runtime / "unexpected.txt").write_text("drift\n")
                with self.assertRaises(VERIFIER.VerificationError):
                    VERIFIER.verify_runtime(ROOT, runtime, self.contract)

    def test_materializer_refuses_nonempty_and_repository_destinations(self) -> None:
        script = ROOT / "scripts/materialize-uniswap-v3-npm-source-block.sh"
        with tempfile.TemporaryDirectory(prefix="npm-source-nonempty-") as temporary:
            destination = Path(temporary)
            sentinel = destination / "keep.txt"
            sentinel.write_text("preserve\n")
            result = subprocess.run(
                ["bash", str(script), str(destination)],
                env={**os.environ, "PYTHON": sys.executable},
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("destination must be empty", result.stdout)
            self.assertEqual(sentinel.read_text(), "preserve\n")
        forbidden = ROOT / "npm-source-block-forbidden"
        self.assertFalse(forbidden.exists())
        result = subprocess.run(
            ["bash", str(script), str(forbidden)],
            env={**os.environ, "PYTHON": sys.executable},
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("destination must be outside the repository", result.stdout)
        self.assertFalse(forbidden.exists())

    def test_fixed_semantic_digest_rejects_rehashed_promotion(self) -> None:
        with tempfile.TemporaryDirectory(prefix="npm-source-semantics-drift-") as temporary:
            root = Path(temporary)
            target = root / VERIFIER.OVERLAY / "npm-source-block-v1.json"
            target.parent.mkdir(parents=True)
            mutated = copy.deepcopy(self.semantics)
            mutated["checkpoint_authority"] = True
            mutated["graph_block_success_authority"] = True
            target.write_text(json.dumps(mutated, indent=2) + "\n")
            with self.assertRaisesRegex(VERIFIER.VerificationError, "digest drift"):
                VERIFIER.load_semantics(root)

    def test_writer_package_arguments_cannot_be_silently_ignored(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(VERIFIER_PATH),
                "--runtime",
                str(self.runtime),
                "--writer-mainnet-spkg",
                str(self.runtime / "writer-mainnet.spkg"),
                "--writer-base-spkg",
                str(self.runtime / "writer-base.spkg"),
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("writer package checks require --mainnet-spkg and --base-spkg", result.stdout)

    def test_docs_and_ci_keep_the_source_boundary_explicit(self) -> None:
        self.assertTrue((ROOT / VERIFIER.OVERLAY / "docs/eligibility.md").is_file())
        self.assertTrue((ROOT / VERIFIER.OVERLAY / "docs/provenance.md").is_file())
        self.assertFalse((ROOT / VERIFIER.OVERLAY / "evidence").exists())
        self.assertFalse((ROOT / VERIFIER.OVERLAY / "provenance").exists())
        workflow = (ROOT / ".github/workflows/ci.yaml").read_text()
        self.assertIn("Verify provider-free NPM source-block contract and refusals", workflow)
        self.assertIn("Pack provider-free NPM source packages twice", workflow)
        self.assertIn("npm-source-package/substreams.npm-source.mainnet.yaml", workflow)
        self.assertIn("cmp \"$RUNNER_TEMP/uniswap-v3-mainnet-npm-source.spkg\"", workflow)
        self.assertIn("verify-uniswap-v3-npm-source-block.py", workflow)
        self.assertIn("Release only the NPM source Cargo targets", workflow)
        self.assertIn('cargo +1.79.0 clean --manifest-path "$source_root/Cargo.toml"', workflow)
        self.assertIn('cargo +1.79.0 clean --manifest-path "$source_root/npm-source-block-runtime/Cargo.toml"', workflow)
        self.assertIn('test ! -e "$source_root/target"', workflow)
        self.assertIn('test ! -e "$source_root/npm-source-block-runtime/target"', workflow)


if __name__ == "__main__":
    unittest.main()
