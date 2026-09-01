# Uniswap V2 Base source and target provenance

The deployment contract is
[`uniswap-v2-base-target.json`](uniswap-v2-base-target.json). It is authoritative for the
IPFS closure, target address/start block, source search, generic-extractor gap, and false
readiness gates. The human-readable summary below does not replace that lock.

## Exact deployed target

- Deployment: `QmQmz5kh1f83Re1Zaj9UYrzKmcWqpKf1tNs9K6M9WrvPC8`.
- Network: Base; Factory: `0x8909Dc15e40173Ff4699343b6eB8132c65e18eC6`;
  start block: `6,601,915`.
- Components: one Factory data source and one dynamic Pair template.
- Factory handler: PairCreated. Pair handlers, in manifest order: Mint, Burn, Swap,
  Transfer, Sync.
- Schema: 15 entities and 157 fields. `PairTokenLookup` is the sole immutable entity.

The manifest, schema, five ABI objects, and two mapping WASMs are all vendored for a complete
offline target closure. Every child remains locked by its IPFS CID, source and vendored byte
counts, normalization rule, and SHA-256. Vendoring the deployed bytes does not turn the
non-reproducible upstream candidate into source authority.

## Bounded source search

The manifest's repository URL redirects to `Uniswap/v2-subgraph`. The earliest source with
the deployed Factory's `uint256` decimals decode and `<=255` guard is commit
`6fba1a6f7304df83c08c3555bc90a38028f1435c`, tree
`c80a1d0ddfb378a1fd7e9177e59a94420b01bd5e`. Every file consumed by the static behavior
profile is Git-blob and SHA-256 locked.

This is not an exact deployment source:

1. None of seven historical schema revisions matches the deployed schema.
2. The closest revision makes `Swap` immutable; the deployed schema keeps it mutable.
3. The deployed manifest omits `ERC20BigDecimals`, while the candidate template and
   generated Factory code require it.
4. The repository has no dependency lockfile and does not retain the generated schema or
   contract-binding workspace used for deployment.
5. With the deployed schema injected, the candidate Pair WASM reproduces exactly, but the
   Factory output is 26 bytes shorter and has a different digest.

The verifier therefore freezes the negative result and refuses
`source_revision_pinned=true` or `source_reproducible=true`. The pinned behavioral
candidate is evidence only; it is not the exact deployed source revision.

## Static behavior and implementation gap

The layout profile summarizes the candidate source's Factory and Pair effect ordering,
including the Factory partial-effect return, Transfer-driven pending Mint/Burn records,
Sync reserve/price updates, and transaction/interval writes. These are static source facts,
not a Graph Node runtime or proof-of-indexing certification.

The generic `substreams-evm/dex/uniswap-v2` module at commit `970a665…` lacks Pair Transfer
and has no target Factory, dynamic-Pair-membership, or start-block filter. A target runtime
must replace those gaps and implement ordered Graph entity effects before parity work can
begin.

M8 orders #87, then #89, then #93, but M0 remains indeterminate. Eligibility requires the
fastest healthy path in both required clusters to exceed 28 days or be non-converging in
both fresh 24-hour and 72-hour windows. Any fastest-healthy window at or below 28 days stops
implementation, compute, and load. The issue #83 market snapshot measured at
`2026-08-31T17:20:00Z` records `780953` queries and exactly `954.416540` GRT in 24-hour
Gateway query fees; it ranks market value and does not establish eligibility. All exact
source-revision, implementation, runtime, history, parity, physical, PoI, backfill,
production, readiness, and issue-completion gates remain false.
