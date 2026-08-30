# Uniswap V3 Pool Swap fee-growth semantics v1

This additive certificate binds one bounded `Pool.handleSwap` suffix across all
eight retained mainnet and Base ancestry profiles. On the selected normal path,
it proves this exact order:

1. use `event.address` to bind the Pool smart contract;
2. call `feeGrowthGlobal0X128():(uint256)` with an empty argument array;
3. decode result element zero through `Value#toBigInt`;
4. call `feeGrowthGlobal1X128():(uint256)` on the same contract with an empty
   argument array;
5. decode result element zero through `Value#toBigInt`;
6. set `feeGrowthGlobal0X128` on the selected Pool from the first decoded value;
7. set `feeGrowthGlobal1X128` on that same Pool from the second decoded value;
   and
8. reach the second save of that same Pool receiver.

The first Pool save precedes both reads. The verifier proves that the second
setter and second save have the same control depth, that no `return`, `br`,
`br_if`, or `br_table` lies between them, and that the selected Pool receiver
cannot be reassigned on a successful path.

The canonical selectors are independently inherited from the checksum-pinned
Pool ABI and the Flash verifier's self-tested Keccak-256 derivation:

| ABI signature | selector |
| --- | --- |
| `feeGrowthGlobal0X128()` | `f3058399` |
| `feeGrowthGlobal1X128()` | `46141319` |

The modern mappings inline the contract construction, calls, decodes, and
TypedMap setters in one 65-line selected slice. Their method, signature, empty
array, Value kind, and payload pointers are exact-profile authority. The six
legacy mappings share a normalized 15-line selected slice and use exact-pinned
getter and setter wrappers. Deduplicated legacy symbol names are not semantic
authority; decoded methods, signatures, result indices, keys, operands,
receiver identities, and helper bodies are.

Modern missing Bundle, Factory, or Pool paths remain closed
abort-and-`unreachable` traps. Missing either Token skips the complete selected
body on a normal return, and the calls, setters, and second save stay inside
that same guard. All eight mappings return before the fee reads for excluded
Pool `0x9663f2ca0454accad3e094448ea6f77443880454`. Legacy evidence is limited to
normal completion; missing Pool and Token behavior is not promoted.

The shared generated `SmartContract#call` helper uses non-try `ethereum.call`.
A null result aborts and reaches `unreachable`. `Value#toBigInt` accepts the
retained kinds 3 and 4 and traps for an invalid kind. These machine shapes do
not rederive the imported host's call values, block pointer, error classes,
numeric behavior, rollback, or post-fatal execution.

The verifier recomputes the complete Swap reachability envelope:

| profile | reachable functions | direct writes | TypedMap sets | unclassified sets |
| --- | ---: | ---: | ---: | ---: |
| modern Base | 111 | 630 | 197 | 192 |
| modern mainnet | 111 | 628 | 197 | 192 |
| each legacy profile | 197 | 185 | 60 | 55 |

Three TypedMap sites were classified by the Swap core certificate and this
slice classifies the two fee-growth setters, for five cumulative classified
sites. Every other direct write and TypedMap set remains within the pinned
inventory but outside this claim. The exact reachable Graph store target set
remains `Bundle`, `Factory`, `Pool`, `PoolDayData`, `PoolHourData`, `Swap`,
`Tick`, `TickDayData`, `Token`, `TokenDayData`, `TokenHourData`, `Transaction`,
and `UniswapDayData`.

The verifier directly pins and recursively recomputes the audited Pool Flash
candidate, Swap core, Mint, Pool runtime, Initialize, field-semantics v2, and
segment writer matrix. It emits 16 segment-field call-flow records and all 28
pairwise scoped diffs. Both fee-growth fields were already selected upstream,
so the cumulative ledger remains exactly 36 selected and 230 residual.

This component is based on exact canonical PR #70 squash merge
`27dc439b150bbade46b6552d9e8611bc3c00da6f`, tree
`1345a42221c47c56783fbb0d5f3acbc6707a04ce`. That merge tree is identical to
the independently audited Flash candidate tree.

This is call-flow evidence only. It does not prove persistence, no later dynamic
overwrite, complete Swap or Pool history, legacy Factory initialization,
complete stored fields, payload alias safety, runtime population, package
consumption or identity, continuity, Graph-oracle evidence, parity, checkpoint
authority, backfill, deployment, production, or readiness. It completes no
checkbox in issues #37 or #38.

The focused 51-test suite includes compile-valid WAT counterexamples for call
operands and order, array descriptors, result indices, `Value#toBigInt`, result
cross-wiring, receiver/key/Value payload flow, legacy helper aliasing, null
traps, control guards, second-save order, branches, hidden writes, store
targets, truth gates, ledger counts, source pins, segment diffs, and duplicate
JSON keys.

```console
python3 scripts/verify-uniswap-v3-pool-swap-fee-growth.py
python3 -m unittest scripts.tests.test_uniswap_v3_pool_swap_fee_growth
```

Intentional deterministic regeneration uses:

```console
python3 scripts/verify-uniswap-v3-pool-swap-fee-growth.py --write-contract
```

See [eligibility.md](docs/eligibility.md) for the claim boundary and
[provenance.md](docs/provenance.md) for the authority chain.
