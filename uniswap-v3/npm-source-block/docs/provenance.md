# Provenance

The source mapper is bound to these existing repository authorities:

- `uniswap-v3/writer-runtime/contract-v1.json` for the exact writer runtime;
- `uniswap-v3/writer-runtime/segment-profiles-v1.json` for all eight ordered
  segment identities and semantic digests;
- `uniswap-v3/graft-ancestry/v2/writer-compatibility.json` for the source writer
  contract;
- `uniswap-v3/writer-runtime/manifests/substreams.mainnet.yaml` and
  `substreams.base.yaml` for the unchanged writer module inputs and parameters;
- `uniswap-v3/writer-runtime/runtime.patch` for the checked-in writer protobuf
  binding and `map_writer_events` implementation;
- `uniswap-v3/segment-writer-matrix/v1/contract.json` for the approved segment
  writer composition;
- `uniswap-v3/execution-order/v1/contract.json` for the boundary between source
  extraction and later integrated Graph Node execution.

The new mapper deliberately does not bind a joint reducer, input adapter, live
provider, Graph Node host implementation, or Graph database. Those layers are
outside this source-only contract and may evolve without changing the raw
Firehose-derived boundary.

The source package preserves the existing writer WASM instead of rebuilding its
logic in the new binary. Its second WASM validates the upstream writer message,
block identity, and referenced transaction metadata before emitting the source
protobuf.

The source package pins its own 16-descriptor dependency closure. That closure
contains the exact writer and new source descriptors required by its two
modules, but it is not the complete descriptor set of an original 23-module
writer package. Original writer packages are rebuilt separately and must remain
byte-identical to their baseline packages, including their independently
validated descriptor sets.

The source mapper validates a Firehose timestamp as a positive whole second in
the protobuf `Timestamp` range. The canonical decoder repeats the range check,
but cannot authenticate the value against a Firehose block that is no longer
present after projection.

Source manifests and the source README are materialized together under
`npm-source-package`. This makes the source README the package documentation
selected by Substreams v1.20.3 while preserving the original writer runtime
README and packages byte-for-byte.
