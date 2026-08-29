# Eligibility

## Implemented

- A deterministic `map_npm_source_block` Substreams map.
- Exact composition with the existing `map_writer_events` module.
- Block hash, parent hash, number, and validated positive whole-second timestamp
  transport.
- Referenced successful transaction index, gas-limit, and gas-price transport.
- Dedicated mainnet and Base two-module, two-WASM packages.
- Canonical protobuf, manifest, package-isolation, and artifact-drift gates.

## Not eligible

This tranche is not eligible to run a backfill or advance a Graph Node block.
It has no provider calls, Graph entity reads, integrated handler engine,
checkpoint lifecycle, continuity state, dynamic data-source stages, POI, SQL,
Parquet, restore, or production certification.

The output is source input only. Neither successful decoding nor a successful
source-module invocation authorizes a checkpoint or Graph block transaction.
