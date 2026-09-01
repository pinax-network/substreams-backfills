# Messari V3 BSC + Base source provenance

The exact deployed IPFS bytes under `messari-v3/reference/` are authoritative.
The source anchors below explain the nearest retained public workspaces; they
do not replace the deployed artifacts or prove a source-to-WASM build.

## PancakeSwap V3 BSC

- repository: `https://github.com/messari/subgraphs`
- source anchor: `0c4618d6343b5011742a59ec308dd7ce07b9908b`
- tree: `1a309dcd6e8827db41a00634eaab6d1e1ed70da6`
- parent: `6af451686c1dc783f823e51b28686ef95d219c16`
- committed: `2023-05-30T20:55:00Z`
- exact result: `subgraphs/uniswap-v3-forks/schema.graphql` is byte-identical
  to deployed schema `QmSY3DA…` (47,054 bytes, SHA-256
  `efdc8cc4dd6838a065ec573e28cc9218d73e9ad8858694eb836acae0f977c64a`)
- ABI result: Pancake Factory, NPM, Pool, and TickLens JSON values are
  semantically identical; deployed formatting is separately locked

## Uniswap V3 Base

- repository: `https://github.com/messari/subgraphs`
- source anchor: `2c60bd10b5e1a090f6e3b55f0634f2a15ec91dbe`
- tree: `3a2ff3eec89f6ab6f1f61d3c10a546c231c3f06b`
- parent: `b16e506a84247a178a9eae09e799bc75787f4275`
- committed: `2023-08-14T15:07:15Z`
- exact result: `subgraphs/uniswap-v3-forks/schema.graphql` is byte-identical
  to deployed schema `QmVrng7…` (47,061 bytes, SHA-256
  `e93bf39c118446d0695291d03cd1cbe959010d0b00e18d610e5739711fb3411c`)
- ABI result: Factory, NPM, and Pool files match deployed bytes after removing
  one trailing LF; the deployed TickLens object remains independently locked

## Manifest metadata continuity

The source templates at both pinned anchors carry the same `mapping.entities`
metadata as the deployed manifests. Factory lists nonexistent `_PricesUSD`
and `_TokenTracker`; the primary Pool lists nonexistent `LiqudityPool`,
`PoolDailySnapshot`, `_PricesUSD`, `_Account`, `_DailyActiveAccount`, and
`_TokenTracker`; and the fee-only template lists nonexistent `LiqudityPool`.
The primary Pool lists `Token` exactly twice. `Protocol` is excluded from the
missing-name inventory because it is a declared interface in both exact
schemas. The deployed manifest order and duplicate multiplicity are preserved;
normalization is not allowed.

## Reproduction refusal

At both anchors, the protocol templates declare spec `0.0.2` while the exact
deployed manifests declare `0.0.4`. The committed Yarn and npm locks also pin
`https://github.com/edgeandnode/gluegun` commit
`b34b9003d7bf556836da41b57ef36eb21570620a`; that repository is unavailable.
On 2026-08-31, both frozen Yarn and npm installs failed at that exact missing
dependency. Substituting a newer package would no longer reproduce the pinned
workspace.

Accordingly, `source_revision_pinned`, `source_reproducible`, and every
runtime/parity/readiness gate remain false until an exact build closure is
recovered or a complete independently reviewed retained-WASM semantic contract
replaces it.
