# substreams-backfills

Per-subgraph Substreams modules that materialize graph-node deployments **at head**,
bypassing sync-from-genesis and graft-ancestry replay. This is how we enter markets that
are otherwise locked to incumbents with custom infra.

## Why this exists (2026-08-21)

6 of The Graph network's top-40 deployments by query volume (~17M q/day combined) cannot be
served by ordinary graph-node syncing in reasonable time:

| Deployment | Chain | q/day | Blocker |
|---|---|---|---|
| `QmTZ8ejX…` | mainnet | 11.3M | graft chain back to 2021 (base @19,470,000 → base @13,605,860) |
| `QmWSfh5q…` | base | 3.4M | ellipfra-monopoly; from-genesis sync ≈ months |
| `QmVjXU7y…` | bsc | 2.6M | ellipfra-monopoly |
| `Qmb4VUcA…` | base | 2.1M | grafts @19,852,000 + from-genesis base sync |
| `QmY67iZD…` | bsc | 1.9M | ellipfra near-monopoly |
| `QmWqwrVt…` | matic | 5.5M | our only copy died years behind (kan sgd3); catch-up ≈ months |

Only ellipfra (`graph-l2prod.ellipfra.com`) serves most of these — single-indexer pricing on
~10M q/day. A deployment-hash-faithful backfill breaks that moat.

Tracking: [k8s-subgraphs#779](https://github.com/pinax-network/k8s-subgraphs/issues/779).

## Architecture

- **Engine** (separate repo): [`substreams-graph-node-backfill`](https://github.com/pinax-network/substreams-graph-node-backfill)
  (v0.5.0+) — loads entity rows into graph-node Postgres schemas and finalizes deployment
  metadata. This repo NEVER duplicates engine logic.
- **`common/`** — shared Rust for the hard 20%: emitting entities that are byte-faithful
  to graph-node's storage semantics (`vid` ordering, `block_range` vs immutable `block$`,
  causality regions, PoI compatibility). One reviewed implementation.
- **`<family>/`** (root-level, one dir per subgraph family — same schema = same family;
  the mainnet + base "ERC20" targets share schema `Qma8a81T…` and are one family
  parameterized by chain/addresses/start-block).
- **`<family>/<Qm-hash>.yaml`** — the per-deployment binding living next to its module:
  schema hash, chain, graft ancestry, market data, sgd/shard placement per cluster.

## Deployment-hash fidelity — the one invariant

A backfilled deployment must be **indistinguishable at query time** from a natively-synced
copy of the same IPFS hash: same entities, same values at any queried block within retained
history. We serve the REAL hash — this is correctness, not imitation. Divergence = wrong
query results + slashing exposure. Every family therefore ships with a **differential
verifier**: sampled entity comparisons against a reference endpoint (the incumbent or the
subgraph author's) before any allocation is opened.

## Delivery milestones

1. **M1 — contract test**: `crates/common` encodes one hand-written entity set; engine loads
   it into a scratch schema; graph-node serves it and answers a GraphQL query correctly.
2. **M2 — first family** (`erc20-balances`, schema `Qma8a81T…`): base variant (`Qmb4VUcA…`,
   smallest data of the pair), verified differentially, landed paused on riv + kan via the
   engine, activated behind a 200-GRT allocation.
3. **M3 — mainnet variant** of the same family (`QmTZ8ejX…`, the 11.3M q/day prize).
4. **M4 — remaining families** in market-size order (`QmWSfh5q`, `QmVjXU7y`, `QmY67iZD`,
   then the matic revival `QmWqwrVt`).
5. **M5 — port `uniswap-v4`** from `substreams-v4-subgraph` once the active univ4base
   backfill completes a committed segment (owning agent's safety contract governs timing;
   the old repo stays frozen until the port reproduces a segment).
