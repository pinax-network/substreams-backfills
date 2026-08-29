# Uniswap V3 scoped segment field semantics

This versioned supplement closes the largest field-level subset supported by
the retained artifacts without inferring missing behavior. It binds all eight
mainnet/Base ancestry segments and all 28 pairwise comparisons.

The completed scope is deliberately narrow:

- the four NonfungiblePositionManager handlers' host-projected effects on 34
  stored fields across `Transaction`, `Position`, and `PositionSnapshot`, with
  link fields excluded where exact Graph serialization is not proved;
- `Pool.handleFlash`'s atomic effect on
  `feeGrowthGlobal0X128` and `feeGrowthGlobal1X128`;
- all 33 stored fields on `Collect`, `Flash`, and `TickHourData`, whose rows are
  statically required absent across every retained mapping artifact.

Each segment records the exact NPM and Pool mapping provenance, handler body
bindings, reachable store targets, NPM profile, API/gas behavior, deterministic
error policy, historical guard, excluded-pool behavior, call ordering, call
failure behavior, and fatal-projection boundary. The pairwise table compares
the complete scoped semantic and provenance surfaces, not selected labels.

This is evidence, not a runnable writer. Factory handlers, non-Flash Pool
handlers, full entity histories, cross-component scheduling, post-fatal Graph
execution, runtime population, boundary continuity, oracle comparison, parity,
package wiring, and execution-model selection remain outside the completed
scope and false.

Run the hermetic verifier and adversarial tests with:

```console
python3 scripts/verify-uniswap-v3-segment-field-semantics.py
python3 -m unittest scripts.tests.test_uniswap_v3_segment_field_semantics
```

The committed contract is generated deterministically. To intentionally
regenerate it after reviewing an upstream evidence change:

```console
python3 scripts/verify-uniswap-v3-segment-field-semantics.py --write-contract
```
