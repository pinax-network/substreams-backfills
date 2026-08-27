from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[2]
VERIFIER = REPOSITORY / "scripts/verify-uniswap-v3-chain-config.py"
SPEC = importlib.util.spec_from_file_location("uniswap_v3_chain_config", VERIFIER)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def varint(value: int) -> bytes:
    output = bytearray()
    while value >= 0x80:
        output.append((value & 0x7F) | 0x80)
        value >>= 7
    output.append(value)
    return bytes(output)


def field(number: int, value: bytes) -> bytes:
    return varint((number << 3) | 2) + varint(len(value)) + value


def package_with_wasm(wasm: bytes) -> bytes:
    binary = field(1, b"wasm/rust-v1") + field(2, wasm)
    modules = field(2, binary)
    return field(6, modules)


class UniswapV3ChainConfigTest(unittest.TestCase):
    def test_exact_configs_and_manifests_pass(self) -> None:
        configs = MODULE.load_configs(REPOSITORY)
        manifests = MODULE.load_manifests(REPOSITORY, configs)
        self.assertEqual(manifests["mainnet"]["network"], "mainnet")
        self.assertEqual(manifests["base"]["network"], "base")

    def test_unknown_config_field_is_rejected(self) -> None:
        config = json.loads(
            (REPOSITORY / "uniswap-v3/chain-config/configs/base-v1.json").read_text()
        )
        config["unexpected"] = True
        with self.assertRaises(MODULE.VerificationError):
            MODULE.validate_config(config, "base")

    def test_incomplete_and_inconsistent_configs_are_rejected(self) -> None:
        config = json.loads(
            (REPOSITORY / "uniswap-v3/chain-config/configs/base-v1.json").read_text()
        )
        incomplete = copy.deepcopy(config)
        del incomplete["pricing"]["wrapped_native_token"]
        with self.assertRaises(MODULE.VerificationError):
            MODULE.validate_config(incomplete, "base")

        inconsistent = copy.deepcopy(config)
        inconsistent["initial_blocks"]["factory_creation"] -= 1
        with self.assertRaises(MODULE.VerificationError):
            MODULE.validate_config(inconsistent, "base")

    def test_mainnet_constant_in_base_config_is_rejected(self) -> None:
        config = json.loads(
            (REPOSITORY / "uniswap-v3/chain-config/configs/base-v1.json").read_text()
        )
        config["contracts"]["factory"] = MODULE.EXPECTED_CRITICAL["mainnet"]["factory"]
        config["contracts"]["factory_entity_id"] = MODULE.EXPECTED_CRITICAL["mainnet"]["factory_entity_id"]
        with self.assertRaises(MODULE.VerificationError):
            MODULE.validate_config(config, "base")

    def test_base_deployed_oddities_are_pinned(self) -> None:
        base = MODULE.load_configs(REPOSITORY)["base"]
        self.assertEqual(base["pricing"]["stablecoins"], [MODULE.BASE_STABLE_ARTIFACT])
        self.assertEqual(base["filters"]["ignored_pools"], [MODULE.IGNORED_POOL])
        self.assertEqual(base["filters"]["swap_ignored_pools"], [MODULE.SWAP_IGNORED_POOL])

    def test_embedded_wasm_divergence_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            mainnet = directory / "mainnet.spkg"
            base = directory / "base.spkg"
            mainnet.write_bytes(package_with_wasm(b"\0asm-shared"))
            base.write_bytes(package_with_wasm(b"\0asm-diverged"))
            mainnet_wasm = MODULE.embedded_wasm_binaries(mainnet)
            base_wasm = MODULE.embedded_wasm_binaries(base)
            self.assertNotEqual(mainnet_wasm, base_wasm)
            with self.assertRaises(MODULE.VerificationError):
                MODULE.require_shared_embedded_wasm(
                    b"\0asm-shared",
                    {"mainnet": mainnet_wasm[0], "base": base_wasm[0]},
                )

    def test_embedded_wasm_parser_rejects_missing_binary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary) / "empty.spkg"
            package.write_bytes(field(6, b""))
            with self.assertRaises(MODULE.VerificationError):
                MODULE.embedded_wasm_binaries(package)


if __name__ == "__main__":
    unittest.main()
