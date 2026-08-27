from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[2]
VERIFIER = REPOSITORY / "scripts/verify-uniswap-v3-diagnostic-package.py"
SPEC = importlib.util.spec_from_file_location("uniswap_v3_package_contract", VERIFIER)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def valid_package() -> dict[str, object]:
    modules = [
        {
            "name": name,
            "kind": "map" if name == "graph_out" else "store",
            "initial_block": MODULE.EXPECTED_INITIAL_BLOCK,
            **(
                {"output_type": "proto:sf.substreams.entity.v1.EntityChanges"}
                if name == "graph_out"
                else {}
            ),
        }
        for name in sorted(MODULE.EXPECTED_MODULES)
    ]
    return {
        "name": "uniswap_v3",
        "version": "v0.2.11",
        "network": "mainnet",
        "modules": modules,
    }


class UniswapV3PackageContractTest(unittest.TestCase):
    def test_exact_structure_passes(self) -> None:
        MODULE.verify(valid_package())

    def test_identity_drift_is_rejected(self) -> None:
        package = valid_package()
        package["version"] = "v0.2.12"
        with self.assertRaises(ValueError):
            MODULE.verify(package)

    def test_module_drift_is_rejected(self) -> None:
        package = valid_package()
        package["modules"] = copy.deepcopy(package["modules"][:-1])
        with self.assertRaises(ValueError):
            MODULE.verify(package)

    def test_duplicate_module_is_rejected(self) -> None:
        package = valid_package()
        package["modules"].append(copy.deepcopy(package["modules"][0]))
        with self.assertRaises(ValueError):
            MODULE.verify(package)

    def test_initial_block_drift_is_rejected(self) -> None:
        package = valid_package()
        package["modules"][0]["initial_block"] += 1
        with self.assertRaises(ValueError):
            MODULE.verify(package)

    def test_graph_out_contract_drift_is_rejected(self) -> None:
        package = valid_package()
        graph_out = next(
            module for module in package["modules"] if module["name"] == "graph_out"
        )
        graph_out["output_type"] = "proto:example.Drift"
        with self.assertRaises(ValueError):
            MODULE.verify(package)


if __name__ == "__main__":
    unittest.main()
