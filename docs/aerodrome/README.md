# Aerodrome implementation

The lane targets the existing Aerodrome Slipstream Base deployment
`QmasYjypV6nTLp4iNH4Vjf7fksRNxAkAskqDdKf2DCsQkV`. The extractor and sequential
native reducer belong in this repository; the reducer emits canonical
BlockChanges for the family-neutral backfill engine. A dedicated Graph Node
worker provides a parallel baseline/continuation path. The mapping host remains
the deployed-WASM oracle. Pool/NPM call answers come from storage changes;
ERC20 metadata uses RPC.

These are the operator's October 20 architecture decisions, reaffirmed by the
October 21 instruction to continue implementation. They authorize development
of this lane; they do not certify a package or authorize a production writer.

## Recovered design

The [integrated plan](design/INTEGRATED-PLAN.md) reconciles the five component
designs. Its interface resolutions take precedence over conflicting proposals
in the component documents. The [survey synthesis](survey/SYNTHESIS.md) records
the earlier investigation. These fifteen documents were recovered with trailing whitespace removed
from the October 20 stopped session on October 21. They are design/evidence
snapshots, not declarations of implemented behavior. Local scratch paths,
measurements, branch states, estimates and approval notes inside them are dated
references and must be rechecked before use. Some referenced raw probe outputs
remain outside this repository.

## Delivery state at restart (October 21)

| Piece | Evidence | Remaining work |
|---|---|---|
| Negative BigDecimal contract | source [PR #150](https://github.com/pinax-network/substreams-backfills/pull/150), passing candidate CI | Merge and engine adoption |
| Engine EOF/cancel protections | engine [PR #86](https://github.com/pinax-network/substreams-graph-node-backfill/pull/86), passing candidate CI | Canonical publication/adoption; early upstream OK is still unproven |
| Generic noop warmup | k8s [PR #1143](https://github.com/pinax-network/k8s-subgraphs/pull/1143), passing candidate CI | Merge and bounded live smoke |
| Generic development procedure | skills [PR #177](https://github.com/pinax-network/pinax-skills/pull/177), passing candidate CI | Merge |
| Mapping-host oracle | local `feat/aerodrome-mapping-host-oracle`, `a64a146e` | Release fixtures/evidence, review and PR; Flash and deployed-indexer parity still open |
| Dedicated worker | local `claude/aerodrome-worker-dom153`, `26761da` | Review/publication and separately approved operational transition |
| Worker-held failure alerts | local `claude/worker-only-failure-alerts` plus uncommitted edits | Finish review fixes; preserve unpublished edits |
| Extractor, native numerics, generic workflow library | prior agent runs stopped before new implementation | Resume from the integrated plan |

Implementation and publication are tracked separately from proof of complete
logical/physical parity, exact PoI, restart/rewind/no-op continuation, and paused
landing. The first integrated checkpoint is the root-window extractor/reducer
differential against the mapping-host oracle (M2 in the integrated plan). It
does not itself complete the production support goal.
