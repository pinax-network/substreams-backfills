# Uniswap V3 modern Factory guard v1

This supplement closes only the excluded-pool guard proof for the two retained
modern Factory mappings. It is stacked on the immutable
[`segment-field-semantics/v2`](../../segment-field-semantics/v2/README.md)
contract and pins those exact bytes before inspecting either artifact.

The deployed mapping WASM is authoritative. For each modern mapping, the
verifier reconstructs the checksum-pinned WABT 1.0.35 WAT and accounts for the
complete 149-line guard region, including the function header, local
declarations, result block, final equality `if`, and return.

The proof is intentionally bounded:

- structured control is parsed into all ten exact `block`, `loop`, and `if`
  nodes, including every `else`, end, parent, result arity, and branch target;
- all eight mutable-local assignments become explicit SSA versions;
- the event parameter flow is bound from handler parameter `$p0` through
  parameters index 4 and `toAddress` into both length and byte comparisons;
- the exact excluded literal is parsed through 20 two-character iterations
  into the 20-byte address;
- the equality loop is evaluated as one length-mismatch path, twenty possible
  first-byte-mismatch paths, and one all-equal early-return path; and
- any extra instruction, call, local or heap write, control edge, operand,
  loop transition, return, `select`, or `call_indirect` fails closed.

The result moves cumulative Factory proof closure from four to six of the 18
upstream paths. The remaining twelve paths stay unresolved. In particular,
this does not prove Factory effect order or arguments, dynamic template
identity, rollback, `totalSupply` result dataflow, complete static handler
semantics, or every initialized field value.

It adds no runtime code or Substreams module and is not consumed by the writer.
Runtime population, combined scheduling, continuity, oracle/parity,
proof-of-indexing, backfill, and production gates remain false.

See [eligibility.md](docs/eligibility.md) for the exact decision boundary and
[provenance.md](docs/provenance.md) for immutable inputs and reproduction.

Verify with:

```bash
python3 scripts/verify-uniswap-v3-modern-factory-guard.py
python3 -m unittest scripts.tests.test_uniswap_v3_modern_factory_guard
```
