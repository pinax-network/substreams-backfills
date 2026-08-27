#!/usr/bin/env python3
"""Verify the structure of an evidence-only V3 package without pinning its bytes."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

EXPECTED_MODULES = {
    "graph_out",
    "map_extract_data_types",
    "map_pools_created",
    "map_tokens_whitelist_pools",
    "store_derived_factory_tvl",
    "store_derived_tvl",
    "store_eth_prices",
    "store_max_windows",
    "store_min_windows",
    "store_native_amounts",
    "store_pool_count",
    "store_pool_liquidities",
    "store_pool_sqrt_price",
    "store_pools_created",
    "store_positions",
    "store_prices",
    "store_swaps_volume",
    "store_ticks_liquidities",
    "store_token_tvl",
    "store_tokens",
    "store_tokens_whitelist_pools",
    "store_total_tx_counts",
}
EXPECTED_INITIAL_BLOCK = 12_369_621


def fail(message: str) -> None:
    raise ValueError(message)


def inspect(package: Path) -> dict[str, object]:
    result = subprocess.run(
        ["substreams", "info", "--json", str(package)],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    return json.loads(result.stdout)


def verify(package: dict[str, object]) -> None:
    if package.get("name") != "uniswap_v3":
        fail(f"unexpected package name {package.get('name')!r}")
    if package.get("version") != "v0.2.11":
        fail(f"unexpected package version {package.get('version')!r}")
    if package.get("network") != "mainnet":
        fail(f"unexpected package network {package.get('network')!r}")

    modules = package.get("modules")
    if not isinstance(modules, list):
        fail("package modules are missing")
    if not all(isinstance(module, dict) for module in modules):
        fail("package modules must be objects")
    names = [module.get("name") for module in modules]
    if not all(isinstance(name, str) for name in names):
        fail("every package module must have a string name")
    if len(names) != len(set(names)):
        fail("package contains duplicate module names")
    by_name = {module["name"]: module for module in modules}
    if set(by_name) != EXPECTED_MODULES:
        fail(
            "module set drift: "
            f"missing={sorted(EXPECTED_MODULES - set(by_name))}, "
            f"unexpected={sorted(set(by_name) - EXPECTED_MODULES)}"
        )

    wrong_starts = {
        name: module.get("initial_block")
        for name, module in by_name.items()
        if module.get("initial_block") != EXPECTED_INITIAL_BLOCK
    }
    if wrong_starts:
        fail(f"initial block drift: {wrong_starts}")

    graph_out = by_name["graph_out"]
    if graph_out.get("kind") != "map":
        fail(f"graph_out kind is {graph_out.get('kind')!r}")
    if graph_out.get("output_type") != "proto:sf.substreams.entity.v1.EntityChanges":
        fail(f"graph_out output is {graph_out.get('output_type')!r}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("package", type=Path)
    args = parser.parse_args()
    try:
        verify(inspect(args.package))
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, ValueError) as error:
        print(f"Uniswap V3 diagnostic package verification failed: {error}", file=sys.stderr)
        return 1

    print(
        "verified evidence-only Uniswap V3 package: uniswap_v3 v0.2.11, "
        "mainnet, 22 modules, graph_out EntityChanges, initial block 12369621"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
