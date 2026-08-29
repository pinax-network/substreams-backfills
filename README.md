# substreams-backfills

Per-subgraph Substreams modules that materialize graph-node deployments **at head**,
bypassing sync-from-genesis and graft-ancestry replay. This is how we enter markets that
are otherwise locked to incumbents with custom infra.

## Why this exists (2026-08-21)

6 of The Graph network's top-40 deployments by query volume (~17M q/day combined) cannot be
served by ordinary graph-node syncing in reasonable time:

| Deployment | Chain | q/day | Blocker |
|---|---|---|---|
| `QmTZ8ejX…` **Uniswap V3 (mainnet)** | mainnet | 11.3M | graft chain back to 2021 (base @19,470,000 → base @13,605,860) |
| `QmWSfh5q…` morpho-blue-base | base | 3.4M | ellipfra-monopoly; from-genesis sync ≈ months |
| `QmVjXU7y…` pancakeswap-infinity-cl-bsc | bsc | 2.6M | ellipfra-monopoly |
| `Qmb4VUcA…` **Uniswap V3 Base** | base | 2.1M | grafts @19,852,000 + from-genesis base sync |
| `QmY67iZD…` exchange-v3-bsc | bsc | 1.9M | ellipfra near-monopoly |
| `QmWqwrVt…` uniswap-v3-matic | matic | 5.5M | our only copy died years behind (kan sgd3); catch-up ≈ months |

Only ellipfra (`graph-l2prod.ellipfra.com`) serves most of these — single-indexer pricing on
~10M q/day. A deployment-hash-faithful backfill breaks that moat.

Tracking: [k8s-subgraphs#779](https://github.com/pinax-network/k8s-subgraphs/issues/779).

## Backfill eligibility gate

Implementation and compute/load actions are fail-closed unless the target
binding points at fresh, immutable evidence that the fastest healthy Graph Node
path exceeds 28 days in both its 24-hour and 72-hour forecast. See
[`docs/eligibility.md`](docs/eligibility.md) for the exact formula, evidence
contract, capture workflow, and action checks. Market QoS prioritizes targets
only after this gate passes.

## Architecture

- **Engine** (separate repo): [`substreams-graph-node-backfill`](https://github.com/pinax-network/substreams-graph-node-backfill)
  — owns native entity reduction, proof of indexing, Graph Node-native temporal rows,
  PostgreSQL COPY/Parquet output, checkpoints, lifecycle controls, and physical parity.
  This repository never duplicates that safety-critical runtime.
- **`uniswap-v4/`** — the source-identical import of the proven Uniswap V4 Base
  Substreams pipeline. Its exact upstream history is retained on the isolated
  `upstream/uniswap-v4-v0.4.1` branch. It is the golden reference from which reusable
  family-to-engine contracts are derived; its frozen production SPKGs remain byte-identical.
- **`pancakeswap-infinity-cl-bsc/`** — the immutable deployed Graph artifact set,
  exact reproducible source pin, and machine-readable semantic gap profile for M5.
  This baseline is a target contract for the V4-derived implementation, not a claim
  that a Pancake runtime or Graph Node physical parity already exists.
- **`uniswap-v3/source/`** — the source-identical Rust 1.79 import of the reviewed
  mainnet parity fork. Its history is retained at
  `upstream/uniswap-v3-qma8a81t-parity`; the surrounding family directory owns target
  bindings and the explicit logical-versus-physical evidence boundary.
- **`uniswap-v3/chain-config/`** — a versioned, fail-closed mainnet/Base overlay
  materialized outside the frozen source tree. Both generated manifests use one
  compiled WASM; CI rejects any difference in the WASM embedded in their diagnostic
  packages and records distinct configuration-derived execution hashes.
- **`uniswap-v3/writer-runtime/`** — a second ordered, digest-bound overlay that
  exposes a raw diagnostic NPM event stream in both packages while preserving
  the legacy `graph_out`; it corrects the Base runtime/Factory origin to
  1,371,679, keeps the direct NPM gate at 1,371,713, and leaves every parity,
  backfill, and production gate false.
- **`uniswap-v3/graft-ancestry/`** — the complete content-addressed mainnet/Base
  manifest ancestry through graft-free roots, with exact boundary ownership,
  handler/schema inventories, static writer-target matrices, and deliberately
  false logical/physical/PoI promotion gates.
- **`uniswap-v3/pool-initialize/v1/`** — the retained-WAT proof for the exact
  `Pool.handleInitialize` projection of `sqrtPrice` and `tick` across all eight
  ancestry segments. It proves the three saving profiles and recomputes the
  five historical no-save closures while leaving complete Pool history,
  runtime, parity, backfill, and production gates false.
- **`common/`** — shared contracts extracted only after they reproduce the V4 reference.
  A family boundary must preserve ordered mapping operations and the inputs required for
  exact PoI; a coalesced `EntityChanges` stream is not assumed sufficient.
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

0. **M0 — eligibility gates**: build a new backfill only when the fastest healthy Graph
   Node copy has a net catch-up ETA greater than 28 days. Borderline deployments remain
   monitoring-only.
1. **M1 — Uniswap V4 reference port**: preserve the complete Substreams-owned source,
   isolated upstream history, immutable package bytes, module hashes, Store cache boundaries,
   fixtures, and audit packages; then reproduce a certified segment through the pinned engine
   without touching the active source or recovery databases.
2. **M2 — V4-derived family contract**: extract the ordered block-change protocol, target
   schema profiles, metadata finalization, and certification harness while retaining V4 as
   a golden regression.
3. **M3 — Uniswap V3** (`uniswap-v3`, schema `Qma8a81T…`): **mainnet variant first**
   (`QmTZ8ejX…`, 11.3M q/day — highest QV, per operator 2026-08-21) via the
   [pinax-network/substreams-uniswap-v3](https://github.com/pinax-network/substreams-uniswap-v3)
   fork; gap list in `uniswap-v3/PARITY.md`. Verified differentially, landed paused via the
   engine, activated behind a 200-GRT allocation.
   Base (`Qmb4VUcA…`) follows through a complete versioned chain configuration while using
   the same certified WASM bytes; a factory-only rebind is insufficient.
4. **M4 — Uniswap V3 Matic** (`QmWqwrVt…`).
5. **M5 — PancakeSwap Infinity CL BSC** (`QmVjXU7y…`).
6. **M6 — Exchange V3 BSC** (`QmY67iZD…`).

Morpho Blue Base remains outside implementation while either its 24-hour or 72-hour net
catch-up forecast is at or below 28 days. No milestone grants production activation: every
target lands paused and requires its own certified evidence and operational approval.

## Uniswap V4 import contract

The imported directory is pinned to source commit
`6812a4deaa5a520020e8d727e17f6d0b7113d0a9` (`v0.4.1`) and Git tree
`2d60d30242443adc2c021a5b609c27edcb75128a`. It remains an independent Cargo project so
its Rust/Substreams versions and lockfiles do not get silently unified with other families.
The exact upstream commit history is mirrored at
`refs/heads/upstream/uniswap-v4-v0.4.1`, outside the default-branch ancestry. This preserves
the history without allowing its old repository-local `Closes #…` commit messages to close
unrelated roadmap issues here. Run `./scripts/verify-uniswap-v4-import.sh` to prove the mirror,
imported tree, file modes, frozen package bytes, and release lock are unchanged.

The original repository and releases remain available until the active V4 backfill reaches
its terminal certificate, the imported package reproduces a certified 100,000-block segment,
and every engine/release consumer is deliberately transferred. Historical release URLs and
embedded package metadata are provenance and must not be rewritten in place.

## Uniswap V3 import contract

The exact source tree at commit
`42c7b15345e6df80561b694e52a0eb622b374b96` is imported under
`uniswap-v3/source/` and retains its independent Rust 1.79 toolchain and lockfile. The
offline verifier proves the imported tree plus the 20-entity logical field/type contract.
The frozen source remains mainnet-hard-coded; the reviewed `chain-config/` overlay
externalizes those chain-sensitive values without mutating the import. Coalesced
`EntityChanges` still cannot certify exact physical history or PoI, and no host-built
package from either the raw import or configured overlay is a production pin.
