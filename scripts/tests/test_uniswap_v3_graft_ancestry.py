from __future__ import annotations

import copy
import importlib.util
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[2]
VERIFIER = REPOSITORY / "scripts/verify-uniswap-v3-graft-ancestry.py"
SPEC = importlib.util.spec_from_file_location("uniswap_v3_graft_ancestry", VERIFIER)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
CONTRACT_PATH = REPOSITORY / MODULE.CONTRACT_PATH


def wasm_name(value: str) -> bytes:
    payload = value.encode("utf-8")
    return MODULE.encode_varint(len(payload)) + payload


def wasm_section(section_id: int, payload: bytes) -> bytes:
    return bytes([section_id]) + MODULE.encode_varint(len(payload)) + payload


def wasm_import(name: str, kind: int, descriptor: bytes) -> bytes:
    return wasm_name("env") + wasm_name(name) + bytes([kind]) + descriptor


def synthetic_wasm(
    *,
    function_imports: int = 0,
    defined_functions: int = 1,
    memory: bool = False,
    export_sections: list[list[tuple[str, int, int]]] | None = None,
) -> bytes:
    payload = bytearray(b"\0asm\x01\0\0\0")
    payload.extend(wasm_section(1, b"\x01\x60\x00\x00"))
    if function_imports:
        imports = bytearray(MODULE.encode_varint(function_imports))
        for index in range(function_imports):
            imports.extend(wasm_name("env"))
            imports.extend(wasm_name(f"import{index}"))
            imports.append(0)
            imports.extend(MODULE.encode_varint(0))
        payload.extend(wasm_section(2, bytes(imports)))
    functions = MODULE.encode_varint(defined_functions) + b"\x00" * defined_functions
    payload.extend(wasm_section(3, functions))
    if memory:
        payload.extend(wasm_section(5, b"\x01\x00\x01"))
    for exports in export_sections or []:
        section = bytearray(MODULE.encode_varint(len(exports)))
        for name, kind, index in exports:
            section.extend(wasm_name(name))
            section.append(kind)
            section.extend(MODULE.encode_varint(index))
        payload.extend(wasm_section(7, bytes(section)))
    code = bytearray(MODULE.encode_varint(defined_functions))
    for _ in range(defined_functions):
        code.extend(b"\x02\x00\x0b")
    payload.extend(wasm_section(10, bytes(code)))
    return bytes(payload)


class UniswapV3GraftAncestryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = MODULE.verify(REPOSITORY)

    def mutated_contract(self, mutate) -> tempfile.TemporaryDirectory[str]:
        temporary = tempfile.TemporaryDirectory()
        path = Path(temporary.name) / "contract.json"
        contract = copy.deepcopy(self.contract)
        mutate(contract)
        path.write_text(MODULE.render(contract), encoding="utf-8")
        temporary.contract_path = path  # type: ignore[attr-defined]
        return temporary

    def copied_root(self) -> tempfile.TemporaryDirectory[str]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        source = REPOSITORY / "uniswap-v3/graft-ancestry"
        target = root / "uniswap-v3/graft-ancestry"
        target.parent.mkdir(parents=True)
        shutil.copytree(source, target)
        temporary.root_path = root  # type: ignore[attr-defined]
        return temporary

    def test_exact_contract_is_deterministic_and_passes(self) -> None:
        self.assertEqual(
            CONTRACT_PATH.read_text(encoding="utf-8"),
            MODULE.render(MODULE.build_contract(REPOSITORY)),
        )
        self.assertEqual(len(self.contract["artifacts"]), 38)
        self.assertEqual(len(self.contract["networks"]["mainnet"]["segments"]), 6)
        self.assertEqual(len(self.contract["networks"]["base"]["segments"]), 2)
        self.assertEqual(self.contract["format_version"], 2)
        self.assertEqual(
            self.contract["contract_version"], "uniswap-v3-graft-ancestry/v2"
        )
        mappings = self.contract["mapping_writer_inventories"]
        self.assertEqual(len(mappings), 20)
        self.assertEqual(
            sum(
                len(mapping["registered_handler_export_function_indices"])
                for mapping in mappings
            ),
            70,
        )
        for mapping in mappings:
            self.assertEqual(
                mapping["observed_constant_store_set_target_count"],
                len(mapping["observed_constant_store_set_targets"]),
            )
            self.assertEqual(mapping["manual_wat_sha256"], MODULE.WAT_SHA256[mapping["cid"]])
            self.assertGreater(mapping["function_import_count"], 0)
            self.assertGreater(mapping["defined_function_count"], 0)
            for function_index in mapping[
                "registered_handler_export_function_indices"
            ].values():
                self.assertGreaterEqual(
                    function_index, mapping["function_import_count"]
                )
                self.assertLess(
                    function_index,
                    mapping["function_import_count"]
                    + mapping["defined_function_count"],
                )

    def test_valid_export_retarget_changes_the_numeric_function_index(self) -> None:
        first = synthetic_wasm(
            function_imports=1,
            defined_functions=2,
            export_sections=[[('handleEvent', 0, 1)]],
        )
        second = synthetic_wasm(
            function_imports=1,
            defined_functions=2,
            export_sections=[[('handleEvent', 0, 2)]],
        )
        first_exports, imported, defined = MODULE.wasm_function_exports(
            first, {"handleEvent"}
        )
        second_exports, _, _ = MODULE.wasm_function_exports(second, {"handleEvent"})
        self.assertEqual((imported, defined), (1, 2))
        self.assertEqual(first_exports["handleEvent"], 1)
        self.assertEqual(second_exports["handleEvent"], 2)

    def test_two_handler_target_swap_changes_both_numeric_bindings(self) -> None:
        original = synthetic_wasm(
            defined_functions=2,
            export_sections=[[('handleA', 0, 0), ('handleB', 0, 1)]],
        )
        swapped = synthetic_wasm(
            defined_functions=2,
            export_sections=[[('handleA', 0, 1), ('handleB', 0, 0)]],
        )
        handlers = {"handleA", "handleB"}
        original_exports, _, _ = MODULE.wasm_function_exports(original, handlers)
        swapped_exports, _, _ = MODULE.wasm_function_exports(swapped, handlers)
        self.assertEqual(original_exports, {"handleA": 0, "handleB": 1})
        self.assertEqual(swapped_exports, {"handleA": 1, "handleB": 0})

    def test_raw_wasm_export_structure_fails_closed(self) -> None:
        cases = {
            "duplicate .*section": synthetic_wasm(
                export_sections=[[("handleEvent", 0, 0)], [("other", 0, 0)]]
            ),
            "duplicate .*export name": synthetic_wasm(
                memory=True,
                export_sections=[[("handleEvent", 0, 0), ("handleEvent", 2, 0)]]
            ),
            "not a function": synthetic_wasm(
                memory=True,
                export_sections=[[("handleEvent", 2, 0)]]
            ),
            "out of range": synthetic_wasm(
                export_sections=[[("handleEvent", 0, 1)]]
            ),
            "targets imported": synthetic_wasm(
                function_imports=1,
                export_sections=[[("handleEvent", 0, 0)]],
            ),
        }
        for error, payload in cases.items():
            with self.subTest(error=error):
                with self.assertRaisesRegex(MODULE.VerificationError, error):
                    MODULE.wasm_function_exports(payload, {"handleEvent"})

    def test_raw_wasm_leb_failures_are_rejected(self) -> None:
        self.assertEqual(
            MODULE.read_leb(b"\xff\xff\xff\xff\x0f", 0),
            (2**32 - 1, 5),
        )
        malformed = {
            "truncated": b"\0asm\x01\0\0\0\x07\x80",
            "overflowing": b"\0asm\x01\0\0\0\x07\x80\x80\x80\x80\x10",
            "non-canonical": b"\0asm\x01\0\0\0\x07\x80\x00",
        }
        for error, payload in malformed.items():
            with self.subTest(error=error):
                with self.assertRaisesRegex(MODULE.VerificationError, error):
                    MODULE.wasm_function_exports(payload)

    def test_mixed_import_descriptors_count_only_function_imports(self) -> None:
        entries = [
            wasm_import("function0", 0, b"\x00"),
            wasm_import("table", 1, b"\x70\x01\x01\x02"),
            wasm_import("function1", 0, b"\x00"),
            wasm_import("memory", 2, b"\x00\x01"),
            wasm_import("global", 3, b"\x7f\x00"),
            wasm_import("tag", 4, b"\x00\x00"),
        ]
        imports = MODULE.encode_varint(len(entries)) + b"".join(entries)
        payload = b"".join(
            [
                b"\0asm\x01\0\0\0",
                wasm_section(1, b"\x01\x60\x00\x00"),
                wasm_section(2, imports),
                wasm_section(3, b"\x01\x00"),
                wasm_section(7, b"\x01\x0bhandleEvent\x00\x02"),
                wasm_section(10, b"\x01\x02\x00\x0b"),
            ]
        )
        exports, imported, defined = MODULE.wasm_function_exports(
            payload, {"handleEvent"}
        )
        self.assertEqual((imported, defined), (2, 1))
        self.assertEqual(exports["handleEvent"], 2)

    def test_malformed_import_descriptors_fail_closed(self) -> None:
        cases = {
            "import kind": wasm_import("invalid", 5, b""),
            "reference type": wasm_import("table", 1, b"\x71\x00\x01"),
            "minimum exceeds": wasm_import("memory", 2, b"\x01\x02\x01"),
            "global mutability": wasm_import("global", 3, b"\x7f\x02"),
            "tag attribute": wasm_import("tag", 4, b"\x01\x00"),
        }
        for error, entry in cases.items():
            imports = b"\x01" + entry
            payload = b"".join(
                [
                    b"\0asm\x01\0\0\0",
                    wasm_section(1, b"\x01\x60\x00\x00"),
                    wasm_section(2, imports),
                ]
            )
            with self.subTest(error=error):
                with self.assertRaisesRegex(MODULE.VerificationError, error):
                    MODULE.wasm_function_exports(payload)

    def test_function_code_and_section_envelopes_fail_closed(self) -> None:
        prefix = b"\0asm\x01\0\0\0" + wasm_section(1, b"\x01\x60\x00\x00")
        cases = {
            "function/code count mismatch": prefix
            + wasm_section(3, b"\x01\x00")
            + wasm_section(10, b"\x00"),
            "truncated .*function body": prefix
            + wasm_section(3, b"\x01\x00")
            + wasm_section(10, b"\x01\x03\x00\x0b"),
            "out-of-order": prefix
            + wasm_section(3, b"\x01\x00")
            + wasm_section(10, b"\x01\x02\x00\x0b")
            + wasm_section(7, b"\x00"),
            "unsupported .*section": prefix + wasm_section(14, b""),
            "export is missing": synthetic_wasm(
                export_sections=[[('other', 0, 0)]]
            ),
        }
        for error, payload in cases.items():
            with self.subTest(error=error):
                with self.assertRaisesRegex(MODULE.VerificationError, error):
                    MODULE.wasm_function_exports(payload, {"handleEvent"})

        valid = synthetic_wasm(export_sections=[[('handleEvent', 0, 0)]])
        custom = wasm_section(0, wasm_name("first")) + wasm_section(
            0, wasm_name("second")
        )
        with_custom = valid[:8] + custom + valid[8:]
        exports, _, _ = MODULE.wasm_function_exports(with_custom, {"handleEvent"})
        self.assertEqual(exports["handleEvent"], 0)

    def test_persisted_numeric_handler_index_mutation_is_rejected(self) -> None:
        def mutate(contract) -> None:
            mapping = contract["mapping_writer_inventories"][0]
            handler = next(iter(mapping["registered_handler_export_function_indices"]))
            mapping["registered_handler_export_function_indices"][handler] += 1

        with self.mutated_contract(mutate) as temporary:
            with self.assertRaisesRegex(MODULE.VerificationError, "numeric export binding"):
                MODULE.validate_internal_contract(
                    REPOSITORY,
                    MODULE.load_json(Path(temporary) / "contract.json"),
                )

    def test_v2_truth_boundary_requires_exact_keys_and_values(self) -> None:
        def missing(contract) -> None:
            del contract["truth_boundary"][MODULE.ANCESTRY_TRUE_FLAGS[0]]

        def legacy(contract) -> None:
            contract["truth_boundary"]["graft_ancestry_complete"] = True

        def extra(contract) -> None:
            contract["truth_boundary"]["fabricated_complete"] = True

        def boundary_promotion(contract) -> None:
            contract["truth_boundary"]["boundary_state_continuity_complete"] = True

        def blocker_drift(contract) -> None:
            contract["truth_boundary"]["remaining_blockers"].pop()

        for mutate in (missing, legacy, extra, boundary_promotion, blocker_drift):
            with self.subTest(mutate=mutate.__name__):
                contract = copy.deepcopy(self.contract)
                mutate(contract)
                with self.assertRaises(MODULE.VerificationError):
                    MODULE.validate_internal_contract(REPOSITORY, contract)

    def test_graft_block_belongs_to_base_and_next_block_to_child(self) -> None:
        for network in ("mainnet", "base"):
            chain = self.contract["networks"][network]
            for boundary in chain["boundary_probes"]:
                self.assertEqual(
                    MODULE.select_segment(self.contract, network, boundary["graft_block"])[
                        "deployment"
                    ],
                    boundary["base_deployment_at_graft_block"],
                )
                self.assertEqual(
                    MODULE.select_segment(
                        self.contract, network, boundary["graft_block"] + 1
                    )["deployment"],
                    boundary["child_deployment_at_next_block"],
                )

    def test_schema_declared_and_compiled_writer_sets_are_distinct(self) -> None:
        expected_absent = {"Collect", "Flash", "TickHourData"}
        expected_written = set(MODULE.ENTITIES) - expected_absent
        for network in ("mainnet", "base"):
            for segment in self.contract["networks"][network]["segments"]:
                matrix = {item["entity"]: item for item in segment["writer_matrix"]}
                actual_written = {
                    name
                    for name, item in matrix.items()
                    if item["observed_constant_store_set_target_present"]
                }
                self.assertEqual(actual_written, expected_written)
                for name in expected_absent:
                    self.assertEqual(
                        matrix[name]["required_absent_status"],
                        "not_certified",
                    )
                    self.assertEqual(matrix[name]["runtime_population_status"], "not_certified")

    def test_historical_writer_quirks_are_bound_to_specific_mappings(self) -> None:
        observations = {
            item["observation_id"]: item
            for item in self.contract["deployment_specific_static_observations"]
        }
        self.assertIn("npm-mainnet-root-qmywr", observations)
        self.assertIn("npm-mainnet-qmrv-qmebr", observations)
        self.assertIn("npm-mainnet-qmywx-epochs", observations)
        self.assertIn("mainnet-dead-current-guard", observations)
        self.assertIn("tick-hour-no-target-observed", observations)
        self.assertEqual(
            observations["npm-mainnet-qmrv-qmebr"]["mapping_cids"],
            ["Qmebr2EyxV7v1wLt9DSFKA7g8EhcVr9k1x7pwZr5eWEHT6"],
        )
        dead_guard = " ".join(observations["mainnet-dead-current-guard"]["observations"])
        self.assertIn("QmZe", dead_guard)
        self.assertIn("incorrectly skip mainnet block 14317993", dead_guard)
        pool_cids = observations["tick-hour-no-target-observed"]["mapping_cids"]
        self.assertEqual(len(pool_cids), 8)
        self.assertEqual(len(set(pool_cids)), 8)

    def test_wrong_artifact_digest_is_rejected(self) -> None:
        def mutate(contract) -> None:
            contract["artifacts"][0]["sha256"] = "0" * 64

        with self.mutated_contract(mutate) as temporary:
            path = Path(temporary) / "contract.json"
            with self.assertRaisesRegex(MODULE.VerificationError, "SHA-256 drift"):
                MODULE.verify(REPOSITORY, path)

    def test_missing_ancestor_is_rejected(self) -> None:
        def mutate(contract) -> None:
            del contract["networks"]["mainnet"]["segments"][2]

        with self.mutated_contract(mutate) as temporary:
            with self.assertRaises(MODULE.VerificationError):
                MODULE.verify(REPOSITORY, Path(temporary) / "contract.json")

    def test_cycle_or_wrong_parent_is_rejected(self) -> None:
        def mutate(contract) -> None:
            segments = contract["networks"]["mainnet"]["segments"]
            segments[1]["graft"]["base"] = segments[-1]["deployment"]

        with self.mutated_contract(mutate) as temporary:
            with self.assertRaisesRegex(MODULE.VerificationError, "graft base"):
                MODULE.verify(REPOSITORY, Path(temporary) / "contract.json")

    def test_gap_is_rejected(self) -> None:
        def mutate(contract) -> None:
            contract["networks"]["mainnet"]["segments"][1][
                "start_block_inclusive"
            ] += 1

        with self.mutated_contract(mutate) as temporary:
            with self.assertRaises(MODULE.VerificationError):
                MODULE.verify(REPOSITORY, Path(temporary) / "contract.json")

    def test_overlap_is_rejected(self) -> None:
        def mutate(contract) -> None:
            contract["networks"]["mainnet"]["segments"][1][
                "start_block_inclusive"
            ] -= 1

        with self.mutated_contract(mutate) as temporary:
            with self.assertRaises(MODULE.VerificationError):
                MODULE.verify(REPOSITORY, Path(temporary) / "contract.json")

    def test_child_writer_at_graft_block_is_rejected(self) -> None:
        def mutate(contract) -> None:
            segment = contract["networks"]["base"]["segments"][1]
            segment["start_block_inclusive"] = segment["graft"]["block"]

        with self.mutated_contract(mutate) as temporary:
            with self.assertRaisesRegex(
                MODULE.VerificationError, r"gap or overlap|graft block \+ 1"
            ):
                MODULE.verify(REPOSITORY, Path(temporary) / "contract.json")

    def test_segment_selector_fails_closed_on_overlap(self) -> None:
        contract = copy.deepcopy(self.contract)
        segments = contract["networks"]["base"]["segments"]
        segments[1]["start_block_inclusive"] = segments[0]["end_block_inclusive"]
        with self.assertRaisesRegex(MODULE.VerificationError, "matched 2 segments"):
            MODULE.select_segment(contract, "base", segments[0]["end_block_inclusive"])

    def test_unproven_graft_free_root_is_rejected(self) -> None:
        def mutate(contract) -> None:
            contract["networks"]["base"]["segments"][0]["graft_free_root"] = False

        with self.mutated_contract(mutate) as temporary:
            with self.assertRaisesRegex(MODULE.VerificationError, "graft-free claim is unproven"):
                MODULE.verify(REPOSITORY, Path(temporary) / "contract.json")

    def test_unclosed_manifest_artifact_reference_is_rejected(self) -> None:
        def mutate(contract) -> None:
            abi_cid = next(
                item["cid"]
                for item in contract["artifacts"]
                if item["media_type"] == "application/json"
            )
            contract["artifacts"] = [
                item for item in contract["artifacts"] if item["cid"] != abi_cid
            ]

        with self.mutated_contract(mutate) as temporary:
            with self.assertRaisesRegex(MODULE.VerificationError, "closure"):
                MODULE.verify(REPOSITORY, Path(temporary) / "contract.json")

    def test_handler_inventory_drift_is_rejected(self) -> None:
        def mutate(contract) -> None:
            contract["networks"]["mainnet"]["segments"][0]["manifest"][
                "components"
            ][0]["mapping"]["handlers"][0]["handler"] = "handleWrong"

        with self.mutated_contract(mutate) as temporary:
            with self.assertRaisesRegex(MODULE.VerificationError, "manifest inventory drift"):
                MODULE.verify(REPOSITORY, Path(temporary) / "contract.json")

    def test_missing_artifact_file_is_rejected(self) -> None:
        with self.copied_root() as temporary:
            root = Path(temporary)
            cid = self.contract["artifacts"][0]["cid"]
            (root / MODULE.ARTIFACT_DIRECTORY / cid).unlink()
            with self.assertRaisesRegex(MODULE.VerificationError, "missing artifact"):
                MODULE.verify(root)

    def test_artifact_byte_and_cid_drift_is_rejected(self) -> None:
        with self.copied_root() as temporary:
            root = Path(temporary)
            cid = next(
                item["cid"]
                for item in self.contract["artifacts"]
                if item["media_type"] == "application/graphql"
            )
            path = root / MODULE.ARTIFACT_DIRECTORY / cid
            path.write_bytes(path.read_bytes() + b"\n")
            with self.assertRaisesRegex(MODULE.VerificationError, "artifact CID drift"):
                MODULE.verify(root)

    def test_symlink_artifact_is_rejected(self) -> None:
        with self.copied_root() as temporary:
            root = Path(temporary)
            cid = next(
                item["cid"]
                for item in self.contract["artifacts"]
                if item["media_type"] == "application/json"
            )
            path = root / MODULE.ARTIFACT_DIRECTORY / cid
            backup = path.with_suffix(".backup")
            path.rename(backup)
            os.symlink(backup.name, path)
            with self.assertRaisesRegex(MODULE.VerificationError, "must not be a symlink"):
                MODULE.verify(root)

    def test_duplicate_json_key_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "contract.json"
            path.write_text('{"format_version":1,"format_version":1}', encoding="utf-8")
            with self.assertRaisesRegex(MODULE.VerificationError, "duplicate JSON key"):
                MODULE.verify(REPOSITORY, path)


if __name__ == "__main__":
    unittest.main()
