#!/usr/bin/env python3
"""Hermetic tests for the diagnostic Uniswap V3 writer-runtime overlay."""

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
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
VERIFIER_PATH = ROOT / "scripts/verify-uniswap-v3-writer-runtime.py"
SPEC = importlib.util.spec_from_file_location("writer_runtime_verifier", VERIFIER_PATH)
assert SPEC and SPEC.loader
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)

INVENTORY_PATH = ROOT / "scripts/build-uniswap-v3-import-inventory.py"
INVENTORY_SPEC = importlib.util.spec_from_file_location("v3_import_inventory", INVENTORY_PATH)
assert INVENTORY_SPEC and INVENTORY_SPEC.loader
INVENTORY = importlib.util.module_from_spec(INVENTORY_SPEC)
INVENTORY_SPEC.loader.exec_module(INVENTORY)

RESOLVER_PATH = ROOT / "scripts/resolve-materialization-destination.py"
RESOLVER_SPEC = importlib.util.spec_from_file_location("materialization_destination", RESOLVER_PATH)
assert RESOLVER_SPEC and RESOLVER_SPEC.loader
RESOLVER = importlib.util.module_from_spec(RESOLVER_SPEC)
RESOLVER_SPEC.loader.exec_module(RESOLVER)

CLIPPY_PATH = ROOT / "scripts/verify-uniswap-v3-writer-clippy.py"
CLIPPY_SPEC = importlib.util.spec_from_file_location("writer_clippy", CLIPPY_PATH)
assert CLIPPY_SPEC and CLIPPY_SPEC.loader
CLIPPY = importlib.util.module_from_spec(CLIPPY_SPEC)
CLIPPY_SPEC.loader.exec_module(CLIPPY)


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


def encode_varint(value: int) -> bytes:
    output = bytearray()
    while value >= 0x80:
        output.append((value & 0x7F) | 0x80)
        value >>= 7
    output.append(value)
    return bytes(output)


def length_field(number: int, value: bytes) -> bytes:
    return encode_varint(number << 3 | 2) + encode_varint(len(value)) + value


def varint_field(number: int, value: int) -> bytes:
    return encode_varint(number << 3) + encode_varint(value)


class WriterRuntimeContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = VERIFIER.load_runtime_contract(ROOT)
        cls.profiles = VERIFIER.load_profiles(ROOT)
        cls.configs = VERIFIER.load_configs(ROOT)
        cls.manifests = VERIFIER.load_manifests(ROOT, cls.configs)

    def test_exact_eight_ordered_digest_bound_profiles(self) -> None:
        self.assertEqual(len(self.profiles["profiles"]), 8)
        actual = tuple(
            (
                profile["network"],
                profile["start_block_inclusive"],
                profile["end_block_inclusive"],
                profile["deployment"],
            )
            for profile in self.profiles["profiles"]
        )
        self.assertEqual(actual, VERIFIER.EXPECTED_RANGES)

    def test_profiles_are_exact_source_projection(self) -> None:
        source_path = ROOT / VERIFIER.SOURCE_WRITER_CONTRACT
        source = json.loads(source_path.read_text())
        self.assertEqual(
            self.profiles,
            VERIFIER.derive_profile_document(source_path, source),
        )

    def test_missing_extra_reordered_gap_and_overlap_fail_closed(self) -> None:
        mutations = []
        missing = copy.deepcopy(self.profiles)
        missing["profiles"].pop()
        mutations.append(missing)
        extra = copy.deepcopy(self.profiles)
        extra["profiles"].append(copy.deepcopy(extra["profiles"][0]))
        mutations.append(extra)
        reordered = copy.deepcopy(self.profiles)
        reordered["profiles"][0], reordered["profiles"][1] = (
            reordered["profiles"][1],
            reordered["profiles"][0],
        )
        mutations.append(reordered)
        gap = copy.deepcopy(self.profiles)
        gap["profiles"][1]["start_block_inclusive"] += 1
        mutations.append(gap)
        overlap = copy.deepcopy(self.profiles)
        overlap["profiles"][1]["start_block_inclusive"] -= 1
        mutations.append(overlap)
        for mutation in mutations:
            with self.subTest(mutation=len(mutation["profiles"])):
                with self.assertRaises(VERIFIER.VerificationError):
                    VERIFIER.validate_profile_document(mutation)

    def test_self_consistently_rehashed_source_still_fails_pinned_digest(self) -> None:
        with tempfile.TemporaryDirectory(prefix="writer-source-drift-") as temporary:
            root = Path(temporary)
            source_path = root / VERIFIER.SOURCE_WRITER_CONTRACT
            source_path.parent.mkdir(parents=True)
            source = json.loads((ROOT / VERIFIER.SOURCE_WRITER_CONTRACT).read_text())
            source["unapproved_self_consistent_rewrite"] = True
            source_path.write_text(json.dumps(source, indent=2) + "\n")
            derived = VERIFIER.derive_profile_document(source_path, source)
            profile_path = root / "uniswap-v3/writer-runtime/segment-profiles-v1.json"
            profile_path.parent.mkdir(parents=True)
            profile_path.write_text(json.dumps(derived, indent=2) + "\n")
            with self.assertRaisesRegex(VERIFIER.VerificationError, "source writer contract raw digest drift"):
                VERIFIER.load_profiles(root)

    def test_every_segment_boundary_and_preorigin_gap(self) -> None:
        for network, start, end, deployment in VERIFIER.EXPECTED_RANGES:
            with self.subTest(network=network, block=start):
                self.assertEqual(VERIFIER.select_profile(self.profiles, network, start)["deployment"], deployment)
            if end is not None:
                with self.subTest(network=network, block=end):
                    self.assertEqual(VERIFIER.select_profile(self.profiles, network, end)["deployment"], deployment)
        for network, block in (("mainnet", 12_369_620), ("base", 1_371_678)):
            with self.assertRaises(VERIFIER.VerificationError):
                VERIFIER.select_profile(self.profiles, network, block)

    def test_block_14317993_profile_divergence_is_explicit(self) -> None:
        mainnet = VERIFIER.select_profile(self.profiles, "mainnet", 14_317_993)
        base = VERIFIER.select_profile(self.profiles, "base", 14_317_993)
        self.assertEqual(mainnet["npm_profile_id"], "mainnet-no-collect-amounts")
        self.assertFalse(mainnet["historical_guard"]["effective_in_segment"])
        self.assertEqual(base["npm_profile_id"], "base-root-amount0-to-both")
        self.assertTrue(base["historical_guard"]["effective_in_segment"])

    def test_base_runtime_and_npm_gate_boundaries_are_distinct(self) -> None:
        initial = self.configs["base"]["initial_blocks"]
        self.assertEqual(
            initial,
            {
                "module": 1_371_679,
                "factory": 1_371_679,
                "factory_creation": 1_371_679,
                "nonfungible_position_manager": 1_371_713,
            },
        )
        self.assertLess(1_371_678, initial["module"])
        self.assertEqual(1_371_679, initial["module"])
        self.assertLess(1_371_712, initial["nonfungible_position_manager"])
        self.assertEqual(1_371_713, initial["nonfungible_position_manager"])
        writer = next(
            module
            for module in self.manifests["base"]["modules"]
            if module["name"] == "map_writer_events"
        )
        self.assertEqual(writer["initialBlock"], 1_371_713)

    def test_graph_out_is_exact_legacy_shape_and_has_no_diagnostic_path(self) -> None:
        for network, manifest in self.manifests.items():
            legacy = yaml.safe_load(
                (ROOT / f"uniswap-v3/chain-config/manifests/substreams.{network}.yaml").read_text()
            )
            expected_graph = next(module for module in legacy["modules"] if module["name"] == "graph_out")
            actual_graph = next(module for module in manifest["modules"] if module["name"] == "graph_out")
            if network == "base":
                expected_graph = copy.deepcopy(expected_graph)
                expected_graph["initialBlock"] = 1_371_679
            self.assertEqual(actual_graph, expected_graph)
            self.assertFalse(
                any(
                    item.get("map") == "map_writer_events" or item.get("store") == "map_writer_events"
                    for module in manifest["modules"]
                    for item in module.get("inputs", [])
                )
            )

    def test_fixture_covers_raw_max_values_and_filters(self) -> None:
        fixture = json.loads((ROOT / "uniswap-v3/writer-runtime/fixtures/events-v1.json").read_text())
        all_case = fixture["cases"][1]
        self.assertEqual(all_case["expected_ordinals"], [10, 20, 30, 40, 50])
        self.assertEqual(all_case["expected_types"], ["transfer", "decrease", "collect", "increase", "increase"])
        raw = json.dumps(fixture)
        self.assertIn(str(2**256 - 1), raw)
        self.assertIn(fixture["addresses"]["foreign"], raw)
        self.assertTrue(any(transaction["status"] != 1 for transaction in all_case["transactions"]))
        self.assertIn(fixture["addresses"]["base_nonfungible_position_manager"], raw)

    def test_writer_patch_refuses_wrong_order_and_applies_after_chain_config(self) -> None:
        writer_patch = (ROOT / "uniswap-v3/writer-runtime/runtime.patch").read_text()
        with tempfile.TemporaryDirectory(prefix="writer-patch-order-") as temporary:
            runtime = Path(temporary) / "runtime"
            shutil.copytree(ROOT / "uniswap-v3/source", runtime)
            wrong = subprocess.run(
                ["patch", "--directory", str(runtime), "--strip", "1", "--forward", "--batch", "--dry-run"],
                input=writer_patch,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            self.assertNotEqual(wrong.returncode, 0)
            for patch in (
                ROOT / "uniswap-v3/chain-config/runtime.patch",
                ROOT / "uniswap-v3/writer-runtime/runtime.patch",
            ):
                subprocess.run(
                    ["patch", "--directory", str(runtime), "--strip", "1", "--forward", "--batch"],
                    input=patch.read_text(),
                    text=True,
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                )
            self.assertTrue((runtime / "src/writer_runtime.rs").is_file())

    def test_materializer_refuses_nonempty_destination_before_writing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="writer-nonempty-") as temporary:
            destination = Path(temporary)
            sentinel = destination / "keep.txt"
            sentinel.write_text("preserve\n")
            result = subprocess.run(
                ["bash", str(ROOT / "scripts/materialize-uniswap-v3-writer-runtime.sh"), str(destination)],
                env={**os.environ, "PYTHON": sys.executable},
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("destination must be empty", result.stdout)
            self.assertEqual(sentinel.read_text(), "preserve\n")

    def test_materializer_rejects_repository_and_source_aliases_before_writing(self) -> None:
        candidates = (
            ROOT / "uniswap-v3/source/writer-runtime-forbidden",
            ROOT / "writer-runtime-forbidden",
            ROOT / "uniswap-v3/source/../source/writer-runtime-forbidden",
        )
        for candidate in candidates:
            self.assertFalse(candidate.exists())
            with self.subTest(candidate=candidate):
                result = subprocess.run(
                    ["bash", str(ROOT / "scripts/materialize-uniswap-v3-writer-runtime.sh"), str(candidate)],
                    env={**os.environ, "PYTHON": sys.executable},
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("destination must be outside the repository", result.stdout)
                self.assertFalse(candidate.exists())
        with tempfile.TemporaryDirectory(prefix="writer-source-symlink-") as temporary:
            alias = Path(temporary) / "source-alias"
            alias.symlink_to(ROOT / "uniswap-v3/source", target_is_directory=True)
            result = subprocess.run(
                ["bash", str(ROOT / "scripts/materialize-uniswap-v3-writer-runtime.sh"), str(alias)],
                env={**os.environ, "PYTHON": sys.executable},
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("destination must be outside the repository", result.stdout)
            self.assertTrue(alias.is_symlink())

    def test_destination_guard_rejects_case_aliases_by_filesystem_identity(self) -> None:
        normal = ROOT / "writer-runtime-case-alias-forbidden"
        parts = list(normal.parts)
        alias = None
        for index, part in enumerate(parts):
            if part and any(character.isalpha() for character in part):
                swapped = part.swapcase()
                candidate = Path(*parts[:index], swapped, *parts[index + 1 :])
                if candidate.parent.exists() and os.path.samefile(candidate.parent, normal.parent):
                    alias = candidate
                    break
        if alias is None:
            self.skipTest("filesystem is case-sensitive")
        with self.assertRaisesRegex(ValueError, "outside the repository"):
            RESOLVER.resolve_destination(ROOT, alias)

    def test_live_source_preflight_rejects_extra_build_inputs_and_symlinks(self) -> None:
        inventory = INVENTORY.build_inventory()
        mutations = ("sentinel", "cargo-config", "outward-symlink")
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory(
                prefix="writer-live-source-"
            ) as temporary:
                temporary_path = Path(temporary)
                source = temporary_path / "source"
                shutil.copytree(
                    ROOT / "uniswap-v3/source",
                    source,
                    ignore=shutil.ignore_patterns("target"),
                )
                external = temporary_path / "external"
                external.mkdir()
                sentinel = external / "keep.txt"
                sentinel.write_text("preserve\n")
                if mutation == "sentinel":
                    (source / "untracked.txt").write_text("not pinned\n")
                elif mutation == "cargo-config":
                    (source / ".cargo/config").write_text(
                        '[build]\nrustflags=["--cfg","untracked_source_injection"]\n'
                    )
                else:
                    (source / "configs").symlink_to(external, target_is_directory=True)
                with self.assertRaisesRegex(RuntimeError, "live source"):
                    INVENTORY.verify_live_source_tree(source, inventory)
                self.assertEqual(sentinel.read_text(), "preserve\n")
                self.assertEqual(list(external.iterdir()), [sentinel])

    def test_materialization_is_exact_and_frozen_source_is_immutable(self) -> None:
        before = tree_digest(ROOT / "uniswap-v3/source")
        with tempfile.TemporaryDirectory(prefix="writer-materializer-parent-") as temporary:
            destination = Path(temporary) / "runtime"
            subprocess.run(
                ["bash", str(ROOT / "scripts/materialize-uniswap-v3-writer-runtime.sh"), str(destination)],
                env={**os.environ, "PYTHON": sys.executable},
                text=True,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            VERIFIER.verify_runtime(ROOT, destination, self.contract)
        self.assertEqual(tree_digest(ROOT / "uniswap-v3/source"), before)

    def test_toolchain_proto_and_generated_bindings_are_bound(self) -> None:
        with tempfile.TemporaryDirectory(prefix="writer-toolchain-") as temporary:
            runtime = Path(temporary) / "runtime"
            VERIFIER.materialize_expected(ROOT, runtime)
            VERIFIER.verify_toolchain(runtime)
            VERIFIER.verify_protobuf(runtime)

    def test_spkg_parser_extracts_exact_single_embedded_wasm(self) -> None:
        wasm = b"\0asm\x01\0\0\0diagnostic-writer"
        binary = length_field(2, wasm)
        modules = length_field(2, binary)
        package = length_field(6, modules)
        with tempfile.NamedTemporaryFile(suffix=".spkg") as handle:
            handle.write(package)
            handle.flush()
            self.assertEqual(VERIFIER.embedded_wasm_binaries(Path(handle.name)), [wasm])

    def test_spkg_binary_index_type_and_entrypoint_are_bound(self) -> None:
        wasm = b"\0asm\x01\0\0\0diagnostic-writer"
        binary = length_field(1, b"wasm/rust-v1") + length_field(2, wasm)
        writer = length_field(1, b"map_writer_events") + length_field(5, b"map_writer_events")
        graph_out = length_field(1, b"graph_out") + length_field(5, b"graph_out")

        def package(modules: list[bytes], binaries: list[bytes]) -> bytes:
            envelope = b"".join(length_field(1, module) for module in modules)
            envelope += b"".join(length_field(2, item) for item in binaries)
            return length_field(6, envelope)

        def verify(payload: bytes) -> bytes:
            with tempfile.NamedTemporaryFile(suffix=".spkg") as handle:
                handle.write(payload)
                handle.flush()
                return VERIFIER.verify_package_binary_bindings(
                    Path(handle.name), ["map_writer_events", "graph_out"]
                )

        self.assertEqual(verify(package([writer, graph_out], [binary])), wasm)

        mutations = [
            package(
                [
                    writer + varint_field(4, 1),
                    graph_out,
                ],
                [binary],
            ),
            package(
                [writer, graph_out],
                [length_field(1, b"wasm/unknown") + length_field(2, wasm)],
            ),
            package([writer, graph_out], [binary, binary]),
            package(
                [
                    writer + length_field(5, b"map_writer_events"),
                    graph_out,
                ],
                [binary],
            ),
            package(
                [
                    length_field(1, b"map_writer_events"),
                    graph_out,
                ],
                [binary],
            ),
            package([graph_out, writer], [binary]),
            package([writer], [binary]),
            package(
                [
                    writer + length_field(9, length_field(1, b"store_filter")),
                    graph_out,
                ],
                [binary],
            ),
            package(
                [
                    length_field(1, b"map_writer_events")
                    + length_field(5, b"graph_out"),
                    graph_out,
                ],
                [binary],
            ),
        ]
        for mutation in mutations:
            with self.subTest(mutation=hashlib.sha256(mutation).hexdigest()):
                with self.assertRaises(VERIFIER.VerificationError):
                    verify(mutation)

    def test_descriptor_order_multiplicity_path_and_digest_are_bound(self) -> None:
        writer = length_field(1, b"uniswap/v1/writer.proto") + length_field(
            2, b"uniswap.writer.v1"
        )
        other = length_field(1, b"fixture.proto") + length_field(2, b"fixture.v1")

        def set_digest(descriptors: list[bytes]) -> str:
            framed = b"".join(
                len(descriptor).to_bytes(8, "big") + descriptor
                for descriptor in descriptors
            )
            return hashlib.sha256(framed).hexdigest()

        descriptors = [other, writer]
        VERIFIER.verify_descriptor_payloads(
            descriptors,
            2,
            set_digest(descriptors),
            hashlib.sha256(writer).hexdigest(),
            "fixture",
        )
        with self.assertRaisesRegex(VERIFIER.VerificationError, "set drift"):
            VERIFIER.verify_descriptor_payloads(
                list(reversed(descriptors)),
                2,
                set_digest(descriptors),
                hashlib.sha256(writer).hexdigest(),
                "fixture",
            )
        duplicated = [writer, writer]
        with self.assertRaisesRegex(VERIFIER.VerificationError, "multiplicity"):
            VERIFIER.verify_descriptor_payloads(
                duplicated,
                2,
                set_digest(duplicated),
                hashlib.sha256(writer).hexdigest(),
                "fixture",
            )
        moved = length_field(1, b"writer.proto") + length_field(
            2, b"uniswap.writer.v1"
        )
        moved_descriptors = [other, moved]
        with self.assertRaisesRegex(VERIFIER.VerificationError, "path drift"):
            VERIFIER.verify_descriptor_payloads(
                moved_descriptors,
                2,
                set_digest(moved_descriptors),
                hashlib.sha256(moved).hexdigest(),
                "fixture",
            )
        with self.assertRaisesRegex(VERIFIER.VerificationError, "count drift"):
            VERIFIER.verify_descriptor_payloads(
                [writer],
                2,
                set_digest([writer]),
                hashlib.sha256(writer).hexdigest(),
                "fixture",
            )

    def test_stable_module_structure_and_independent_hash_vectors(self) -> None:
        wasm = b"diagnostic-test-wasm\n"
        fixture = {
            "binaries": {"default": {"type": "wasm/rust-v1", "file": "fixture.bin"}},
            "modules": [
                {
                    "name": "map_a",
                    "kind": "map",
                    "initialBlock": 10,
                    "inputs": [
                        {"params": "string"},
                        {"source": "sf.test.Block"},
                    ],
                    "output": {"type": "proto:test.A"},
                },
                {
                    "name": "store_b",
                    "kind": "store",
                    "updatePolicy": "set",
                    "valueType": "string",
                    "inputs": [{"map": "map_a"}],
                },
                {
                    "name": "map_c",
                    "kind": "map",
                    "inputs": [
                        {"store": "store_b", "mode": "deltas"},
                        {"map": "map_a"},
                    ],
                    "output": {"type": "proto:test.C"},
                },
            ],
            "params": {"map_a": "fixture=params"},
        }
        official_v1_20_3_vector = [
            "4790fe64663f6e893f8f2768d59e2c2a4b3063b4",
            "468e87a5621b8d342afbbbe5f2d46b124a221b53",
            "673048141000f573191128c235caecee98528e08",
        ]
        self.assertEqual(
            VERIFIER.expected_package_module_hashes(fixture, wasm),
            official_v1_20_3_vector,
        )

        for mutator in (
            lambda value: value["params"].__setitem__("map_a", "fixture=changed"),
            lambda value: value["modules"][0].__setitem__("initialBlock", 11),
            lambda value: value["modules"][2]["inputs"].pop(),
        ):
            changed = copy.deepcopy(fixture)
            mutator(changed)
            self.assertNotEqual(
                VERIFIER.expected_package_module_hashes(changed, wasm),
                official_v1_20_3_vector,
            )
        self.assertNotEqual(
            VERIFIER.expected_package_module_hashes(fixture, wasm + b"drift"),
            official_v1_20_3_vector,
        )

        non_hash_semantics = copy.deepcopy(fixture)
        non_hash_semantics["modules"][0]["output"]["type"] = "proto:test.Changed"
        non_hash_semantics["modules"][1]["updatePolicy"] = "add"
        non_hash_semantics["modules"][1]["valueType"] = "bigint"
        non_hash_semantics["modules"][2]["inputs"][0]["mode"] = "get"
        self.assertEqual(
            VERIFIER.expected_package_module_hashes(non_hash_semantics, wasm),
            official_v1_20_3_vector,
        )

        for network, manifest in self.manifests.items():
            structure = VERIFIER.expected_package_module_structure(manifest)
            self.assertEqual(
                VERIFIER.canonical_sha256(structure),
                VERIFIER.PACKAGE_MODULE_STRUCTURE_SHA256[network],
            )
            hashes = VERIFIER.expected_package_module_hashes(manifest, wasm)
            modules = [dict(module, hash=module_hash) for module, module_hash in zip(structure, hashes)]
            VERIFIER.verify_package_module_hashes(modules, manifest, wasm, network)
            modules[0]["hash"] = "0" * 40
            with self.assertRaisesRegex(VERIFIER.VerificationError, "hash/binary"):
                VERIFIER.verify_package_module_hashes(modules, manifest, wasm, network)

    def test_package_module_structure_rejects_graph_policy_mode_and_start_drift(self) -> None:
        for network, manifest in self.manifests.items():
            expected = VERIFIER.expected_package_module_structure(manifest)
            actual = [dict(module, hash="0" * 40) for module in expected]
            VERIFIER.verify_package_module_structure(actual, manifest, network)

            mutations = []
            missing_graph_input = copy.deepcopy(actual)
            graph_out = next(module for module in missing_graph_input if module["name"] == "graph_out")
            graph_out["inputs"] = [
                item
                for item in graph_out["inputs"]
                if not (item["type"] == "map" and item["name"] == "map_pools_created")
            ]
            mutations.append(missing_graph_input)

            shifted_start = copy.deepcopy(actual)
            next(module for module in shifted_start if module["name"] == "graph_out")["initial_block"] += 1
            mutations.append(shifted_start)

            changed_mode = copy.deepcopy(actual)
            graph_out = next(module for module in changed_mode if module["name"] == "graph_out")
            store_input = next(
                item
                for item in graph_out["inputs"]
                if item["type"] == "store" and item["name"] == "store_positions"
            )
            store_input["mode"] = "deltas" if store_input["mode"] == "get" else "get"
            mutations.append(changed_mode)

            changed_policy = copy.deepcopy(actual)
            next(module for module in changed_policy if module["name"] == "store_pool_count")[
                "update_policy"
            ] = "set"
            mutations.append(changed_policy)

            changed_output = copy.deepcopy(actual)
            next(module for module in changed_output if module["name"] == "map_pools_created")[
                "output_type"
            ] = "proto:uniswap.types.v1.ERC20Tokens"
            mutations.append(changed_output)

            changed_value_type = copy.deepcopy(actual)
            next(module for module in changed_value_type if module["name"] == "store_pool_count")[
                "value_type"
            ] = "string"
            mutations.append(changed_value_type)

            injected_block_filter = copy.deepcopy(actual)
            injected_block_filter[0]["block_filter"] = {
                "module": "store_pools_created",
                "query": "evt_addr:00",
            }
            mutations.append(injected_block_filter)

            for mutation in mutations:
                with self.assertRaisesRegex(VERIFIER.VerificationError, "module graph"):
                    VERIFIER.verify_package_module_structure(mutation, manifest, network)

    def test_clippy_inventory_rejects_code_less_and_build_script_warnings(self) -> None:
        message = {
            "reason": "compiler-message",
            "package_id": "path+file:///tmp/runtime#substreams-uniswap-v3@0.1.0",
            "message": {
                "level": "warning",
                "message": "unclassified build warning",
                "code": None,
                "spans": [],
            },
        }
        self.assertIsNotNone(CLIPPY.unclassified_root_warning(message))
        line = "warning: substreams-uniswap-v3@0.1.0: injected build warning"
        self.assertEqual(CLIPPY.cargo_root_warnings(line + "\n"), [line])


if __name__ == "__main__":
    unittest.main()
