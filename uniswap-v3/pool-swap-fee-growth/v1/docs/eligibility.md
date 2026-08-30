# Pool Swap fee-growth eligibility

## Proved

For all eight retained Pool mappings, this certificate proves the exact
generation-specific `handleSwap` flow from `event.address` contract binding
through ordered non-try `feeGrowthGlobal0X128` and
`feeGrowthGlobal1X128` calls, empty argument arrays, result-zero BigInt
decodes, uncrossed same-Pool setters, and the second same-receiver Pool save.

The first Pool save precedes the fee reads. No normal `return` or branch lies
between the second setter and second save, and the selected Pool receiver has
no successful-path reassignment. Modern required Bundle, Factory, and Pool
absence traps are retained, while both Token entities dominate the complete
selected path. The excluded-Pool early return is retained in all profiles.

The exact full-Swap function, direct-write, TypedMap, indirect-call, Graph store
site, and 13-target inventories are bound. The selected TypedMap classification
rises from three inherited Swap-core sites to five. The segment surfaces retain
16 call-flow records and 28 pairwise diffs. The cumulative field ledger remains
36 selected and 230 residual.

## Not eligible

This certificate does not prove imported bytes-to-hex, numeric, Ethereum call,
block-pointer, call-error, Graph store, rollback, or post-fatal host semantics.
It does not prove direct or dynamic alias safety, selected persistence, absence
of later dynamic overwrite, complete Swap semantics, complete Pool history,
legacy Factory initialization, or all stored fields.

It also does not implement combined handler or dynamic-data-source order,
runtime population, writer consumption, configured package identity, boundary
continuity, Graph-oracle evidence, logical/physical/PoI parity, checkpoint
authority, backfill, deployment, production, or readiness. Every segment keeps
`execution_model: undecided` and `backfill_allowed: false`. Issues #37 and #38
gain no completed checkbox.

## Canonical base gate

The component binds exact canonical PR #70 squash merge
`27dc439b150bbade46b6552d9e8611bc3c00da6f`, tree
`1345a42221c47c56783fbb0d5f3acbc6707a04ce`. The merge tree is identical to
the independently audited Flash candidate tree. This satisfies only the source
base gate; every execution and readiness refusal above remains in force.
