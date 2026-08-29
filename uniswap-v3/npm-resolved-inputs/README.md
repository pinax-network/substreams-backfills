# Uniswap V3 resolved NPM input adapter

This host-only diagnostic layer joins the provider-free `NpmSourceBlock` with
resolved Graph call and Token-entity observations, then delegates to the exact
joint NPM reducer. It consumes no raw Firehose block, separate `WriterEvents`,
or `ChainConfig`, and it does not recompute headers, transactions, or writer
events.

The canonical protobuf embeds the complete validated source frame. Its
block-scoped call pointer is either the exact EIP-1898 hash matching the source
block hash or an explicit block-number fallback matching the source block
number. Position results are value/None, pool results are a 20-byte address
(zero included)/None, and Token reads are Found(u8)/Missing.

Resolution status stays outside protobuf. A transient payload-free gate has
`Resolved`, `PossibleReorg`, and `Unknown` states; either unstable state aborts
before a frame can be encoded, reduced, or considered for a checkpoint. All
supplied resolved rows are validated before reducer invocation, so malformed
or unstable rows after a would-be first fatal projection still abort.

This tranche is deliberately disconnected from a live engine. Source frames,
resolved input frames, and both joint-reducer dispositions independently deny
Graph block and checkpoint authority. Continuity, physical parity, PoI,
post-fatal execution, full required-observation evaluation, backfill, and
production gates remain false.

Run:

```bash
python3 scripts/verify-uniswap-v3-npm-resolved-inputs.py
python3 -m unittest scripts.tests.test_uniswap_v3_npm_resolved_inputs
./scripts/materialize-uniswap-v3-npm-resolved-inputs.sh /tmp/uniswap-v3-npm-resolved-inputs
```

The materializer starts from the final joint reducer, removes only its
standalone harness, copies the pinned source validator/binding/semantic file,
and installs the adapter plus one combined harness. It does not change
`src/lib.rs`, manifests, runtime protobuf descriptors, writer WASM, or writer
packages.
