# Uniswap V3 execution model

Status: selected 2026-09-02 for issues #115, #38, #37, #116, and #10.

## Decision

| Exact target | Graft-free replay root | Segments | Replay origin | Authenticated 9274F seed | Selected model |
|---|---|---:|---:|---|---|
| Mainnet `QmTZ8ejXJxRo7vDBS4uwqBeGoxLSWbhaA7oXa1RvxunLy7` | `Qme66ZNMxSdCQKzaDuvS381whCVYCQjf637sGZCqJHAWHB` | 6 | 12,369,621 | unavailable | full ancestry replay |
| Base `Qmb4VUcAY9LsVgeCuCCMs7X1XrkbRcaiuAbSK8SqhmsAfP` | `QmPWDTWRfS8XewMJhxXoQiZX6RkrUMYH7BFnnB846v6wzR` | 2 | 1,371,679 | unavailable | full ancestry replay |

“Unavailable” is the fail-closed operational conclusion: no retained,
authenticated artifact was found. It does not claim that an undisclosed
off-repository archive is impossible.

## Evidence

- The current Kan [mainnet worker](https://github.com/pinax-network/k8s-subgraphs/blob/573880f3a2bbcd30860c42852fbac9979cf4838e/core/kan/graph-node-univ3mainnet.yaml#L6-L8) and [Base worker](https://github.com/pinax-network/k8s-subgraphs/blob/573880f3a2bbcd30860c42852fbac9979cf4838e/core/kan/graph-node-univ3base.yaml#L6-L10) describe population “later” from the 9274F appliance. They prove intent, not creation, transfer, or restore.
- [k8s-subgraphs issue #420](https://github.com/pinax-network/k8s-subgraphs/issues/420) records the two ancestry syncs as running and calls the dense mainnet lineage giant-class; it does not record a completed V3 dump or Kan restore.
- [k8s-subgraphs PR #419](https://github.com/pinax-network/k8s-subgraphs/pull/419) created the dedicated landing zones. It contains no immutable V3 dump location, digest, head hash, or restore receipt.
- The [2026-08-18 teardown ledger](https://github.com/pinax-network/k8s-subgraphs/issues/583#issuecomment-5332265293) states that the appliance held no subgraph data and identifies its only 38 GB `pgdumps` content as an unrelated `sgd2856` dump that had already been restored. The [completion record](https://github.com/pinax-network/k8s-subgraphs/issues/583#issuecomment-5333170600) says Docker ended with zero containers, images, volumes, and build cache; only the unrelated legacy agent database dump was retained.
- Searches of the backfills, engine, and k8s repositories, GitHub issues and pull requests using both exact target CIDs plus `pg_dump`, and all three repositories' release assets found no V3 archive path, byte digest, block/hash identity, runtime identity, landing record, or restore receipt.

The evidence bar is intentionally artifact-based. A filename, recollection,
landing-zone comment, database name, or statement that a copy once ran is not a
seed.

## Cost and surviving scope

The retained oracle capture at 2026-08-28T11:59:31Z observed mainnet head
25,853,596 and Base head 50,564,511. Inclusive replay from the origins above is
therefore:

- mainnet: 13,483,976 blocks across six mapping segments;
- Base: 49,192,833 blocks across two mapping segments;
- total: 62,676,809 chain blocks across eight segment executions.

These counts are a dated scope proxy, not a duration forecast. A wall-clock or
monetary estimate needs a pinned SPKG/runtime, endpoint, token, machine shape,
and measured throughput. The head must be refreshed when compute is actually
authorized.

Full ancestry replay leaves issue #38's remaining writer-provenance, segment
diff, segment-specific execution, representative-sample, graft-boundary
continuity, and #37/#9 consumption work intact. The model-selection wording can
be resolved, but it is not complete until all eight segment-specific writers
are implemented and versioned. The BlockChanges producer must dispatch those
same eight segment profiles rather than only the two current mappings.

## Reopening seed mode

Seed mode may replace full ancestry replay before compute only when operations
provides, for each exact target:

1. an immutable archive location and byte digest;
2. deployment CID, PostgreSQL schema identity, and Graph Node/runtime identity;
3. captured head block and block hash plus capture time;
4. a successful isolated restore receipt with catalog and deployment checks;
5. a certified replay boundary showing which mapping becomes authoritative at
   the next block.

Until all five are present, implementations and plans must treat the seed as
absent. This decision authorizes no stream, compute, Kubernetes action,
database write, load, deployment, allocation, or activation.
