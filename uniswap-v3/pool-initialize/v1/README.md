# Uniswap V3 Pool Initialize semantics v1

This additive supplement proves the exact persisted `Pool.handleInitialize`
projection for every retained Uniswap V3 mainnet and Base ancestry segment.
It consumes, but does not modify, the immutable segment field-semantics v2
ledger.

The retained deployed mapping WASM is semantic authority. For each of the
eight unique Pool mappings, the verifier regenerates WAT with checksum-pinned
WABT 1.0.35 and proves that `handleInitialize`:

1. loads the `Pool` whose ID is the trigger address;
2. routes ABI parameter 0, `sqrtPriceX96: uint160`, to
   `Pool.sqrtPrice: BigInt!`;
3. routes ABI parameter 1, `tick: int24`, through the signed four-byte BigInt
   conversion to `Pool.tick: BigInt`;
4. uses that same loaded Pool as both setter receivers; and
5. either saves that same Pool after both setters as the sole reachable
   `Pool.save`/Pool write, or has no Pool mutation anywhere in the complete
   transitive Initialize call closure.

## Segment result

Three profiles persist both selected fields:

- current mainnet (`modern-mainnet`);
- Base root (`legacy-base-root`); and
- current Base (`modern-base`).

The five historical mainnet profiles mutate the loaded entity in mapping
memory but never store `Pool`, directly or through any reachable helper. Their
exact persisted selected-handler projection therefore preserves both fields.
For each of the three saving profiles, the direct handler save and its generated
`store.set` are the only reachable Pool persistence path, so a later helper
cannot overwrite the selected projection.

This raises the cumulative exact selected-handler field count from 34 to 36
and reduces the unresolved conditional field count from 232 to 230. It does
not complete the history of either field: Factory creation and Pool Mint,
Burn, Swap, and Flash contributions remain outside this proof.

## Fail-closed verification

The adversarial suite round-trips every WAT mutation through
`wat2wasm --debug-names` before asking the semantic verifier to reject it. It
covers wrong ABI indices, wrong receivers and conversions, wrong or dead field
keys, original-event and loaded-Pool local overwrites, legacy parameter-wrapper
corruption, intermediate BigInt/payload loss, conditional setter/save bypasses,
wrong exact collection-call targets, fatal effects outside closed trap guards,
wrong save targets or save entities, later reachable Pool re-saves, and direct,
transitive, or delete-style Pool mutations in historical no-save mappings.

```console
python3 scripts/verify-uniswap-v3-pool-initialize.py
python3 -m unittest scripts.tests.test_uniswap_v3_pool_initialize
```

Intentional deterministic regeneration uses:

```console
python3 scripts/verify-uniswap-v3-pool-initialize.py --write-contract
```

See [eligibility.md](docs/eligibility.md) for the promotion boundary and
[provenance.md](docs/provenance.md) for the retained artifact chain.
