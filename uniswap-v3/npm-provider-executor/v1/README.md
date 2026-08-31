# Uniswap V3 host NPM provider executor v1

This immutable repository slice turns the closed NPM observation plan into a
host-only execution path. It accepts one validated `NpmSourceBlock`, an
immutable block-start `ReducerState`, a gated exact block scope, and a provider
trait. Only providers declaring `HermeticFixture` authority are admitted.

Execution is deliberately phased: every sorted Position request is evaluated,
the complete Pool and ordinal-scoped Token closure is derived, every Pool is
evaluated, then every Token is evaluated. Only after every conservative row is
resolved does exact-key preflight admit the certified joint reducer. This
forces evaluation of the full WriterEvents suffix even when the reducer later
projects an earlier fatal result.

The direct observation-plan prerequisite also corrects the Base Factory tail
to deployed `…21f6fdfd`; a Base new-position `Value` row now traverses derived
Pool/Token resolution and exact preflight instead of failing against the prior
transposed adapter literal.

The successful result contains the reduction and a deterministic **canonical
conservative request-evaluation trace**. The trace binds request keys, resolved
result classes, exact consumption maxima, source/state/scope identity, and the
reducer coverage audit. It is intentionally not described as an exact Graph
call trace. Provider error payloads are discarded; unstable results and errors
return only a sanitized error kind, phase, and optional canonical request
index.

This layer has no live RPC/database adapter, Flash executor, combined
Factory/Pool scheduler, dynamic data-source stage model, post-fatal Graph
execution, output, Store, `graph_out`, package consumer, checkpoint, or
continuity authority. It proves neither physical/PoI parity nor backfill or
production readiness. The selected NPM/Flash field-semantics v1 contract is a
direct evidence binding; v2 and Factory supplements are intentionally absent.

Run:

```bash
python3 scripts/verify-uniswap-v3-npm-provider-executor.py
python3 -m unittest scripts.tests.test_uniswap_v3_npm_provider_executor
./scripts/materialize-uniswap-v3-npm-provider-executor.sh /tmp/uniswap-v3-npm-provider-executor
```
