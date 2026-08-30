# Uniswap V3 Pool Swap core-state semantics v1

This additive supplement binds retained-WAT `Pool.handleSwap`
call-flow evidence for exactly three Pool assignments across all eight retained
Uniswap V3 Pool mappings:

- `Pool.liquidity <- Swap` parameter 5 (`uint128 liquidity`);
- `Pool.tick <- Swap` parameter 6 (`int24 tick`); and
- `Pool.sqrtPrice <- Swap` parameter 4 (`uint160 sqrtPriceX96`).

It is based on exact Pool Mint squash merge
`fa1c8d842712e53d363615062ecf1374e52bb854`. The verifier digest-pins the
landed Mint verifier and contract and directly digest-pins the canonical Pool
runtime and Pool Initialize verifiers and contracts. The branch was retargeted
to that merge and the focused and full validation gates were rerun.

For the two modern mappings, the verifier proves closed missing-entity traps for
the required Bundle, Factory, and trigger-address Pool loads; successful
continuation therefore has nonzero entities. It also proves the excluded-Pool
early return and the exact no-`else` two-Token guard. The three selected updates
and both observed Pool saves are dominated by that guard, so a missing Token
skips the entire selected body on a normal return.

The modern assignments decode EventParam indices 5, 6, and 4, then use
`Value#toBigInt`, `Value#toI32 -> BigInt.fromI32`, and `Value#toBigInt`
respectively. The verifier binds the exact inline kind-7 Value construction for
liquidity and sqrt price, the generated nullable tick setter, decoded keys, and
the selected Pool receiver copied from the loaded Pool.

The six legacy mappings expose misleading deduplicated symbols. The verifier
does not infer semantics from those names. It proves instead that:

- `Mint__Params#get:amount0` decodes parameter 5 and its result reaches decoded
  key `liquidity` through the function named `PoolDayData#set:liquidity`, with
  the loaded Pool as receiver;
- `Swap__Params#get:tick` decodes parameter 6, flows through
  `ByteArray.fromI32`, and reaches decoded key `tick`; and
- `Mint__Params#get:amount` decodes parameter 4 and reaches decoded key
  `sqrtPrice`.

All three selected setters precede the first direct `Pool.save`. A second direct
`Pool.save` is also reachable and is inventoried. In modern WAT, the selected
Pool scratch local is reassigned before that second save only inside a closed
abort-and-`unreachable` branch; successful-path identity remains intact through
both saves. This is call-flow and ordering evidence, not persisted-state proof.

Every reachable function body, direct linear-memory write, TypedMap set, Graph
store site, store target, and indirect target is digest-bound. The current exact
inventories are:

| generation/profile | reachable functions | direct writes | TypedMap sets |
| --- | ---: | ---: | ---: |
| modern Base | 111 | 630 | 197 |
| modern mainnet | 111 | 628 | 197 |
| each legacy profile | 197 | 185 | 60 |

Only the three selected receiver/key/value flows are classified. The remaining
194 modern or 57 legacy TypedMap-set sites and every direct write retain their
alias residual. All profiles reach exactly 13 Graph store targets: Bundle,
Factory, Pool, PoolDayData, PoolHourData, Swap, Tick, TickDayData, Token,
TokenDayData, TokenHourData, Transaction, and UniswapDayData.

The verifier and 40-test suite include compile-valid WAT counterexamples for
parameter indices, decoded keys, misleading legacy aliases, receiver identity,
Value kind/payload, signed integer conversion, modern traps and guard, excluded
Pool control, both Pool saves, hidden memory effects, runtime-helper drift, and
Graph store targeting. Contract count, proof, truth, source-digest, diff, and
duplicate-key mutations also fail closed.

```console
python3 scripts/verify-uniswap-v3-pool-swap-core.py
python3 -m unittest scripts.tests.test_uniswap_v3_pool_swap_core
```

Intentional deterministic regeneration uses:

```console
python3 scripts/verify-uniswap-v3-pool-swap-core.py --write-contract
```

See [eligibility.md](docs/eligibility.md) for the claim boundary and
[provenance.md](docs/provenance.md) for the exact retained authority chain.
