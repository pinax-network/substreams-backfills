#!/usr/bin/env python3
"""Verify the exact logical V3 schema and source-level parity boundaries."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


EXPECTED_LOGICAL_SHA256 = (
    "6c801fc4c141c0ae12dbb937652f0dd49c9be5bd3b1b3c8e38bdb92fe6efec5d"
)
EXPECTED_ENTITIES = {
    "Bundle",
    "Burn",
    "Collect",
    "Factory",
    "Flash",
    "Mint",
    "Pool",
    "PoolDayData",
    "PoolHourData",
    "Position",
    "PositionSnapshot",
    "Swap",
    "Tick",
    "TickDayData",
    "TickHourData",
    "Token",
    "TokenDayData",
    "TokenHourData",
    "Transaction",
    "UniswapDayData",
}
EXPECTED_SOURCE_IMMUTABLE = {"Burn", "Mint", "Swap", "Transaction"}


def fail(message: str) -> None:
    raise ValueError(message)


def parse_schema(path: Path) -> tuple[dict[str, dict[str, str]], set[str]]:
    entities: dict[str, dict[str, str]] = {}
    immutable: set[str] = set()
    current: str | None = None

    for raw_line in path.read_text().splitlines():
        line = raw_line.split("#", 1)[0].strip()
        declaration = re.match(
            r"^type\s+([_A-Za-z][_0-9A-Za-z]*)\s+@entity\s*"
            r"(\([^)]*\))?\s*\{",
            line,
        )
        if declaration:
            current = declaration.group(1)
            entities[current] = {}
            if declaration.group(2) and "immutable" in declaration.group(2):
                immutable.add(current)
            continue

        if current and line == "}":
            current = None
            continue

        if current:
            field = re.match(
                r"^([_A-Za-z][_0-9A-Za-z]*)\s*:\s*([\[\]!_A-Za-z0-9]+)",
                line,
            )
            if field:
                entities[current][field.group(1)] = field.group(2)

    return entities, immutable


def logical_hash(entities: dict[str, dict[str, str]]) -> str:
    payload = json.dumps(entities, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def function_body(source: str, name: str) -> str:
    marker = re.search(rf"(?:pub\s+)?fn {re.escape(name)}\b", source)
    if not marker:
        fail(f"missing function {name}")
    next_function = re.search(r"\n(?:pub\s+)?fn \w+\b", source[marker.end() :])
    end = len(source) if not next_function else marker.end() + next_function.start()
    return source[marker.start() : end]


def verify_source_contract(source_root: Path) -> None:
    schema, immutable = parse_schema(source_root / "schema.graphql")
    if set(schema) != EXPECTED_ENTITIES:
        missing = sorted(EXPECTED_ENTITIES - set(schema))
        extra = sorted(set(schema) - EXPECTED_ENTITIES)
        fail(f"entity set drift: missing={missing}, extra={extra}")
    if logical_hash(schema) != EXPECTED_LOGICAL_SHA256:
        fail(f"logical schema drift: {logical_hash(schema)}")
    if immutable != EXPECTED_SOURCE_IMMUTABLE:
        fail(f"source immutable entities drift: {sorted(immutable)}")

    db_source = (source_root / "src/db.rs").read_text()
    lib_source = (source_root / "src/lib.rs").read_text()

    create_pool = function_body(db_source, "create_pool")
    pool_tvl = function_body(db_source, "total_value_locked_pool_entity_change")
    if any(
        '"totalValueLockedETHUntracked"' in body
        for body in (create_pool, pool_tvl)
    ):
        fail("Pool reintroduced target-absent totalValueLockedETHUntracked")

    pool_window_tvl = function_body(db_source, "total_value_locked_usd_pool_windows")
    for required in (
        '.key_last_segment_eq("totalValueLockedUSD")',
        '.set("tvlUSD",',
    ):
        if required not in pool_window_tvl:
            fail(f"Pool window output/store-key boundary missing {required}")

    token_window_volume = function_body(db_source, "swap_volume_token_windows")
    if '"untrackedUSD" => "untrackedVolumeUSD"' not in token_window_volume:
        fail("Token window untracked-volume output/store-key boundary drifted")

    create_pool_window = function_body(db_source, "create_pool_windows_entity")
    if '.set("tvlUSD",' not in create_pool_window:
        fail("Pool window create output field tvlUSD drifted")
    create_token_window = function_body(db_source, "create_token_windows_entity")
    if '.set("untrackedVolumeUSD",' not in create_token_window:
        fail("Token window create output field untrackedVolumeUSD drifted")

    tick_create = function_body(db_source, "tick_windows_create")
    tick_update = function_body(db_source, "liquidities_tick_windows")
    for required in (
        '"TickDayData"',
        '"TickHourData"',
        'format!("0x{pool_address}#{tick_idx}-{time_id}")',
        '.set("liquidityGross",',
        '.set("liquidityNet",',
        '.set("volumeToken0",',
        '.set("volumeToken1",',
        '.set("volumeUSD",',
        '.set("feesUSD",',
    ):
        if required not in tick_create:
            fail(f"tick-window create contract missing {required}")
    for required in ('"liquidityGross"', '"liquidityNet"'):
        if required not in tick_update:
            fail(f"tick-window update contract missing {required}")
    for required in (
        "db::tick_windows_create(&mut tables, &ticks_liquidities_deltas);",
        "db::liquidities_tick_windows(&mut tables, &ticks_liquidities_deltas);",
    ):
        if required not in lib_source:
            fail(f"graph_out wiring missing {required}")

    hard_coded_markers = {
        "src/utils.rs": "1f98431c8ad98523631ae4a59f267346ea31f984",
        "src/price.rs": "8ad599c3a0ff1de082011efddc58f1908eb6e6d8",
        "substreams.yaml": "initialBlock: 12369621",
    }
    for relative_path, marker in hard_coded_markers.items():
        if marker.lower() not in (source_root / relative_path).read_text().lower():
            fail(f"mainnet-only marker changed in {relative_path}; version the import contract")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source-root",
        type=Path,
        default=Path("uniswap-v3/source"),
    )
    args = parser.parse_args()
    try:
        verify_source_contract(args.source_root)
    except (OSError, ValueError) as error:
        print(f"Uniswap V3 logical contract verification failed: {error}", file=sys.stderr)
        return 1

    print(
        "verified 20 logical entities, target field/type hash, renamed output/Store boundaries, "
        "tick-window wiring, and the explicit mainnet-only configuration marker"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
