# exchange-v3-bsc — `QmY67iZD…`

This is PancakeSwap V3 on BSC: two concrete data sources (`Factory` and
`NonfungiblePositionManager`) plus a dynamic `Pool` template. It is related to the
Uniswap V3 family, but it has PancakeSwap protocol-fee fields and handlers and uses the
oldest manifest contract in this candidate fleet (`specVersion: 0.0.2`, mapping
`apiVersion: 0.0.4`).

Factory `0x0bfbcf9fa4f9c56b0f40a671ad40e0805a091865` starts at block 26,956,207;
NonfungiblePositionManager `0x46a15b0b27311cedf172ab29e4f4766fbe7f4364` starts at
block 26,931,961.

## Immutable target and source baseline

`reference/` vendors the exact deployed IPFS manifest, schema, six ABI objects, and
three mapping binaries. `layout-profile-v1.json` records the target-specific handler,
entity, fee, position, aggregate, pricing, and metadata contract needed for a later
implementation gap.
`docs/provenance/exchange-v3-bsc-target.json` pins every CID, byte count, SHA-256 digest,
data-source/template address and handler, the 20-entity all-mutable schema profile, and
the static schema difference from the frozen imported Uniswap V3 reference. Run:

```console
python3 scripts/verify-exchange-v3-bsc-target.py
```

The earliest byte-exact source is
[`pancakeswap/pancake-subgraph`](https://github.com/pancakeswap/pancake-subgraph) commit
`1da7ba61abb26633ff819ce8cdfe945be8770a92`, tree
`a2a113c9eedd7ed0e6fdcaea275153233223c95d`, with sole parent
`e2019f716f4310f4ce28addc4439980804d9e413`. The commit changes the BSC minimum native
liquidity threshold from 60 to 10; that one configuration boundary changes the Factory
and Pool binaries to the deployed bytes while the PositionManager binary stays stable.

The verified reproduction uses Node 14.21.3, Yarn 1.22.22, Graph CLI 0.21.0, Graph TS
0.20.1, and AssemblyScript 0.6.0 at commit
`3ed76a97f05335504166fce1653da75f4face28f`. It produces all three deployed mapping
objects byte-for-byte:

- Factory: 22,442 bytes, SHA-256 `c4b019c3…e7f8`;
- NonfungiblePositionManager: 19,527 bytes, SHA-256 `72805576…849e`;
- Pool: 42,716 bytes, SHA-256 `d806f251…1847`.

The historical lock references one deleted GitHub fork tarball used by Graph CLI's IPFS
client. The reproduction script applies one exact, fail-closed install transport override
to the public `concat-stream@2.0.0` tarball, restores the original lock before validation,
pins every compiler package, and then requires all deployed build bytes to match. The
override is recorded in the machine-readable provenance rather than silently rewriting
the historical source.

Run the networked source proof with:

```console
./scripts/verify-exchange-v3-bsc-source.sh
```

## Scope and remaining gates

This baseline is Part of issue #20. Issue #20 remains open. The static schema profile is
not the final functional/loader gap proof and this change does not authorize loading,
deployment, allocation, or activation. M6 still requires:

1. fresh evidence fully accounting for both required clusters by inventorying every current
   copy or supplying fresh structural absence proof; when viable healthy copies exist, the
   independently selected minimum stable same-pod 24-hour ETA and minimum stable same-pod
   72-hour ETA, which may belong to different copies, must both exceed 28 days or be
   non-converging;
   either minimum at or below 28 days stops implementation, compute, and load; if no viable
   copy exists anywhere, eligibility requires fresh structural absence proof from both
   clusters;
2. legacy spec-0.0.2 physical-schema and metadata support in the certified generic loader;
3. the final functional gap against the certified V3 family after issues #5 and #9; and
4. a paused differential certificate plus separate operational approval before activation.
