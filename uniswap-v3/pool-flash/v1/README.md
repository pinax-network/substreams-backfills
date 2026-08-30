# Uniswap V3 Pool Flash semantics v1

This additive certificate binds the retained-WAT `Pool.handleFlash` path across
all eight mainnet and Base ancestry segments. It proves this exact ordered
projection:

1. load the trigger-address `Pool` entity and bind the same address as the Pool
   smart contract;
2. call `feeGrowthGlobal0X128():(uint256)`;
3. decode result element zero as a `BigInt`;
4. call `feeGrowthGlobal1X128():(uint256)` on the same contract;
5. decode result element zero as a `BigInt`;
6. set `feeGrowthGlobal0X128` on the loaded Pool from the first decoded value;
7. set `feeGrowthGlobal1X128` on that same Pool from the second decoded value;
   and
8. save that same Pool receiver.

The canonical ABI selectors are independently recomputed with the verifier's
self-tested Keccak-256 implementation:

| ABI signature | selector |
| --- | --- |
| `feeGrowthGlobal0X128()` | `f3058399` |
| `feeGrowthGlobal1X128()` | `46141319` |

The two modern mappings inline both calls and both TypedMap setters. Their
90-line handler bodies differ in raw data offsets, while sharing the same
instruction shape. The six legacy mappings share one exact 24-line handler
body. Legacy getter and setter symbols are deduplicated and misleading: the
verifier derives semantics only from decoded method/signature strings, result
indices, decoded keys, operand sequences, and receiver identities.

The shared generated `SmartContract#call` helper invokes non-try
`ethereum.call`. Its null result branch aborts and reaches `unreachable`; the
same nonzero result is returned on successful continuation. The certificate
proves that closed-trap structure and proves that no successful handler path
bypasses the second call, either setter, or the Pool save. It does not rederive
the imported host's call value, block-pointer, error-classification, rollback,
or post-fatal semantics.

Every reachable function body, direct linear-memory write, TypedMap set, Graph
store site, store target, and indirect target is digest-bound:

| profile group | reachable functions | direct writes | TypedMap sets | Graph store targets |
| --- | ---: | ---: | ---: | --- |
| modern Base | 28 | 144 | 2 | `Pool` |
| modern mainnet | 28 | 144 | 2 | `Pool` |
| each legacy profile | 34 | 117 | 2 | `Pool` |

Both TypedMap sites are the selected receiver/key/value setters. General heap
alias semantics remain open. The one reachable Graph store site targets only
`Pool`. Combined with the recomputed segment writer matrix, this retains
`Flash` as a required-absent entity with all 12 fields statically writer-absent;
the target mapping does not synthesize a Flash row.

The verifier directly digest-pins and recursively recomputes the canonical
Pool Swap certificate, Mint, Pool runtime, Initialize, field-semantics v2, and
segment writer matrix. The selected-field ledger remains exactly 36 selected
and 230 residual because both fee-growth fields were already selected upstream.

This component is based on exact canonical Pool Swap squash merge
`71d554fa9676d8c77437c0366a9859e13834e235`. Its merge tree was verified
identical to the audited candidate before the Flash contract was regenerated
and the focused and full validation matrices were rerun.

The candidate source still disables Flash extraction and has no consuming
`graph_out` path. This certificate therefore does not implement Flash output,
does not complete issue #37's Flash implementation criterion, and does not
claim persistence, complete Pool/Flash history, package identity, continuity,
parity, checkpoint authority, backfill, production, or readiness.

The verifier and 46-test suite include compile-valid WAT counterexamples for
method/signature/order, result decoding, receiver/local identity, decoded keys,
Value kind/payload, legacy aliasing, non-try null traps, save order, hidden
writes, and Pool-only store closure. Contract overpromotion, ledger changes,
required-absence drift, source-digest drift, pairwise-diff drift, and duplicate
JSON keys also fail closed.

```console
python3 scripts/verify-uniswap-v3-pool-flash.py
python3 -m unittest scripts.tests.test_uniswap_v3_pool_flash
```

Intentional deterministic regeneration uses:

```console
python3 scripts/verify-uniswap-v3-pool-flash.py --write-contract
```

See [eligibility.md](docs/eligibility.md) for the claim boundary and
[provenance.md](docs/provenance.md) for the exact authority chain.
