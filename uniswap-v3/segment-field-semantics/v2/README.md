# Uniswap V3 segment field-semantics v2

Version 2 is the complete offline inventory and proof-status ledger for all
retained Uniswap V3 mainnet and Base ancestry segments. It extends, but does
not replace, the immutable v1 selected-handler contract.

The generated contract binds:

- all 20 schema entities and all 299 stored fields in every segment, for 2,392
  segment-field records;
- all ten manifest handlers in each of the eight segments, for 80 exact
  handler/export/body bindings;
- all six unique Factory mappings and eight unique Pool mappings to their
  retained deployed WASM, WAT digest, writer profile, machine-proved paths,
  and explicitly unresolved control/dataflow paths;
- Factory `handlePoolCreated` and Pool `Initialize`, `Mint`, `Burn`, and `Swap`
  evidence for calls, failures, rollback policy, exclusions, dynamic data
  source creation, effect order, metadata generations, pricing profiles,
  fee-spacing profiles, TickDay relation modes, and deployed quirks;
- bounded retained-WAT CFG/dataflow proofs for the excluded-pool guard in the
  four legacy Factory mappings, including exact active literal parsing,
  distinct equality operands, and the non-inverted early-return branch;
- v1's exact 34-field selected NPM/Flash projection and 33-field
  required-absence closure without changing v1 bytes; and
- recursive semantic and provenance diffs for all 28 segment pairs.

The retained mapping WASM is semantic authority. Checksum-pinned source
anchors are corroboration only. A reviewed description, lexical callsite, or
literal is never promoted to exact behavior when same-path reachability,
dominance, argument dataflow, or Graph serialization remains unproved.

## Truth boundary

This tranche completes the inventory and makes every known proof gap
machine-visible. It does **not** complete Factory or non-Flash Pool field
semantics. In particular, 232 conditional fields remain fail-closed, including
six Position relation fields and the shared `Transaction` and `Pool` histories.
The Factory and Pool profiles retain their complete upstream records while
listing every explicitly false proof-status path.

The bounded Factory analyzer closes exactly four of the 18 upstream Factory
proof gaps: the excluded-pool guard for the four legacy mappings. Fourteen
paths remain false: both modern guard paths, all six effect-order/argument
paths, and all six `complete_static_handler_contract` paths. The reviewed
effect order and upstream legacy/modern `totalSupply` models remain
digest-bound provenance only; v2 does not promote their dominance, argument,
template, rollback, or success/failure value-dataflow semantics. Closing those
paths requires a more general structured-control, mutable-local,
interprocedural typed-stack, and global-initializer analysis.

The 28 diffs therefore compare the complete available evidence surfaces, not
complete writer semantics. The contract keeps full Factory/Pool completeness,
contract-call completeness, combined scheduling, dynamic-stage execution,
post-fatal execution, runtime/oracle/parity, package consumption, backfill, and
production gates false.

See [eligibility.md](docs/eligibility.md) for the promotion boundary and
[provenance.md](docs/provenance.md) for the immutable inputs.

## Verification

The verifier recursively runs the retained-WASM segment matrix and v1
verifiers with checksum-pinned WABT 1.0.35 evidence before regenerating v2:

```console
python3 scripts/verify-uniswap-v3-segment-field-semantics-v2.py
python3 -m unittest scripts.tests.test_uniswap_v3_segment_field_semantics_v2
```

Regeneration is intentional and deterministic:

```console
python3 scripts/verify-uniswap-v3-segment-field-semantics-v2.py --write-contract
```
