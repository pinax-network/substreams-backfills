#!/usr/bin/env python3
"""Build deterministic mainnet/Base manifests for the configured V3 runtime."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path

import yaml

CONFIGURED_MODULES = (
    "map_pools_created",
    "map_tokens_whitelist_pools",
    "map_extract_data_types",
    "store_total_tx_counts",
    "store_swaps_volume",
    "store_eth_prices",
    "store_derived_tvl",
    "graph_out",
)
PACKAGE_VERSION = "v0.3.0"


def selector(config_path: Path, config: dict[str, object]) -> str:
    digest = hashlib.sha256(config_path.read_bytes()).hexdigest()
    return f"version=1;network={config['network']};sha256={digest}"


def build(source: dict[str, object], config_path: Path) -> dict[str, object]:
    config = json.loads(config_path.read_text())
    network = config["network"]
    module_start = config["initial_blocks"]["module"]
    result = copy.deepcopy(source)
    result["package"]["name"] = f"uniswap_v3_{network}_backfill"
    result["package"]["version"] = PACKAGE_VERSION
    result["network"] = network

    configured = set(CONFIGURED_MODULES)
    found: set[str] = set()
    for module in result["modules"]:
        name = module["name"]
        if module.get("initialBlock") == 12_369_621:
            module["initialBlock"] = module_start
        if name in configured:
            inputs = module.setdefault("inputs", [])
            if any("params" in item for item in inputs):
                raise ValueError(f"source module {name} already has a params input")
            inputs.insert(0, {"params": "string"})
            found.add(name)

    missing = configured - found
    if missing:
        raise ValueError(f"configured module(s) missing from source: {sorted(missing)}")

    value = selector(config_path, config)
    result["params"] = {name: value for name in CONFIGURED_MODULES}
    return result


def render(document: dict[str, object]) -> str:
    return yaml.safe_dump(
        document,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=False,
        width=1000,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    root = args.root.resolve()
    source_path = root / "uniswap-v3/source/substreams.yaml"
    output_dir = root / "uniswap-v3/chain-config/manifests"
    source = yaml.safe_load(source_path.read_text())
    failures: list[str] = []

    for network in ("mainnet", "base"):
        config_path = root / f"uniswap-v3/chain-config/configs/{network}-v1.json"
        output_path = output_dir / f"substreams.{network}.yaml"
        expected = render(build(source, config_path))
        if args.check:
            if not output_path.exists() or output_path.read_text() != expected:
                failures.append(output_path.relative_to(root).as_posix())
        else:
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path.write_text(expected)
            print(f"wrote {output_path.relative_to(root)}")

    if failures:
        print("generated V3 manifest drift: " + ", ".join(failures), file=sys.stderr)
        return 1
    if args.check:
        print("verified deterministic mainnet/Base V3 manifests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
