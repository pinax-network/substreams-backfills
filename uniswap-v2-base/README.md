# Uniswap V2 Base — `QmQmz5kh…`

This directory is the immutable, non-executable baseline for the deployed Uniswap V2
Base subgraph. It binds Factory `0x8909Dc15e40173Ff4699343b6eB8132c65e18eC6`
from block `6,601,915`, its dynamically created Pair templates, all six handlers, and
the exact 15-entity/157-field deployed layout.

## Immutable target closure

`reference/deployment.yaml` is byte-identical to the deployment CID. The vendored schema
adds one repository trailing newline; the lock records both the 7,422-byte IPFS object and
the 7,423-byte vendored object. All five ABI and both mapping WASM children are also
vendored, producing a complete offline target closure; the lock pins each by CID, source
and vendored byte counts, SHA-256 digests, normalization, and exported handler set. Run:

```console
python3 scripts/verify-uniswap-v2-base-target.py
```

The verifier rejects duplicate keys, target address/start-block drift, component or handler
reordering, schema type/nullability/mutability drift, derived-field drift, untracked files,
source overclaims, generic-extractor overclaims, and any readiness promotion.

## Source boundary

The deployed bytes do not come from a clean reproducible upstream revision. All seven
upstream schema revisions (six unique blobs) were checked; none matches the deployed schema.
The nearest later schema marks `Swap` immutable while this deployment keeps it mutable.
The deployed Factory WASM contains the malformed-decimals guard introduced at
`6fba1a6f7304df83c08c3555bc90a38028f1435c`, but the deployed manifest omits the
`ERC20BigDecimals` ABI required by that clean source template and generated Factory binding.
The upstream repository also has no dependency lockfile and does not version generated
schema/binding inputs.

For that reason the lock calls `6fba1a6…` an earliest behavioral source candidate, not an
exact source pin. A bounded build using Graph CLI 0.64.1, Graph TS 0.32.0,
AssemblyScript 0.19.10, and the target schema reproduced the Pair WASM exactly but produced
a 46,951-byte Factory WASM instead of the deployed 46,977-byte object. This negative result
is retained as evidence; it does not authorize substituting the candidate output.

The optional source verifier rechecks both upstream repositories and every pinned Git blob:

```console
./scripts/verify-uniswap-v2-base-source.sh
```

## Generic extractor gap

`pinax-network/substreams-evm` commit `970a665…`, package `dex/uniswap-v2@v0.6.0`,
is a decoder seed only. It decodes Swap, Sync, Mint, Burn, and PairCreated signatures from
all logs. It does **not** decode Pair Transfer, filter PairCreated to the target Factory,
track dynamically created target Pairs, or bind the Base start block. It therefore cannot
preserve the Transfer-driven Mint/Burn correlation or target scope and is not a source-parity
or implementation base.

## Readiness boundary

M8 orders [#87](https://github.com/pinax-network/substreams-backfills/issues/87), then
[#89](https://github.com/pinax-network/substreams-backfills/issues/89), then
[#93](https://github.com/pinax-network/substreams-backfills/issues/93); it does not satisfy
M0. The binding retains the issue #83 Gateway snapshot measured at
`2026-08-31T17:20:00Z`: `780953` queries over 24 hours and exactly `954.416540` GRT in
24-hour query fees. Market value does not establish backfill eligibility.

This baseline is deliberately non-executable. M0 requires both `riv-subgraphs-a` and
`kan-subgraphs-a` to be fully accounted for by inventorying every current copy or supplying
fresh structural absence proof. When viable healthy copies exist, the independently selected
minimum stable same-pod 24-hour ETA and minimum stable same-pod 72-hour ETA across all
viable copies may belong to different copies; both must exceed 28 days or be
non-converging. If either minimum is at or below 28 days, implementation, compute, and load
stop while native Graph Node syncing continues. With no viable copy, fresh structural
absence proof is required from both clusters. Eligibility, exact source revision, source
reproducibility, implementation,
runtime, history, logical/physical/VID/PoI parity, backfill, production, readiness, and all
three issue-completion gates remain false. No package was built, no backfill was run or
loaded, and no Kubernetes resource was changed. Issues #87, #89, and #93 remain open.
