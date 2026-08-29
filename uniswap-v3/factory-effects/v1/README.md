# Uniswap V3 Factory effects v1

This additive supplement closes only the normal-return effect-order and exact-
argument path for each of the six retained Factory mappings. It pins the
immutable [`segment-field-semantics/v2`](../../segment-field-semantics/v2/README.md)
and [`factory-guard/v1`](../../factory-guard/v1/README.md) contracts before
reconstructing any WAT.

The retained deployed WASM is authoritative. One shared proof engine parses
complete handler-local structured control, versions every mutable local,
carries required-ID path predicates, inventories every direct heap write, and
scans all reachable direct and indirect calls for persistent effects. It
projects every handler-local normal and explicit trap exit onto the reviewed
suffix:

```text
Pool.save
Pool template create
Token[token0].save
Token[token1].save
Factory.save
```

Every normal fallthrough must execute that sequence exactly once. The three
reviewed explicit early returns in each generation occur before the first
effect and therefore have an empty projection. Handler-local explicit traps
and the reviewed save helpers' pre-store trap boundaries may stop only at an
ordered prefix. The verifier does not project traps from every reachable
helper or imported host call. Separate legacy and modern frontends prove every
alternative receiver definition, its event or immutable Factory ID, and the
constructor body that places that same ID on the returned entity. They also
prove save-helper behavior, active template name `Pool`, and the one template
argument derived from `event.pool`.

The earlier optional Bundle write is inventoried but is outside this five-
effect projection. The proof reaches Graph host-effect invocation; retained
WAT cannot establish Graph Node rollback if a later call or type check traps.

This moves cumulative Factory closure from six to twelve of 18 upstream paths.
The six complete-static-handler paths remain unresolved. `totalSupply`, all
initialized fields, full Factory history, runtime consumption, scheduling,
continuity, oracle/parity, proof of indexing, backfill, and production gates
remain false.

See [eligibility.md](docs/eligibility.md) for the exact truth boundary and
[provenance.md](docs/provenance.md) for immutable inputs and reproduction.

Verify with:

```bash
python3 scripts/verify-uniswap-v3-factory-effects.py
python3 -m unittest scripts.tests.test_uniswap_v3_factory_effects
```
