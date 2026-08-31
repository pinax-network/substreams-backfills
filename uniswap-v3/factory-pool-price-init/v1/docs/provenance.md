# Provenance and reproduction

This certificate is based on the exact canonical PR #73 merge. Its tree is
byte-identical to the independently audited candidate tree:

```text
canonical merge commit:      19bbc277006cccaf960647dc0bb3c7344688a07f
canonical merge tree:        0afaf69b8446c84b5542453addb0810852387090
canonical merge parent:      982dd6f049af265cfed4c7b8edce1a90c936f319
audited candidate commit:    0b29c6e53ef42ed98e3413a49ad79a9dcefdbb97
audited candidate tree:      0afaf69b8446c84b5542453addb0810852387090
exact-head CI run:            33342202456 (6 jobs, 163 successful steps)
```

The implementation branch starts from that canonical merge. This ancestry
fact does not promote any backfill, deployment, production, or readiness
claim.

## Bound parent

The verifier requires the exact canonical Factory Pool BigInt initialization
parent bytes and reruns that parent, including all transitive retained artifact,
WABT, Factory fee-growth/effects, modern-static, Pool-fee-growth, field-catalog,
and segment-matrix gates.

| Input | SHA-256 |
|---|---|
| Factory Pool BigInt initialization contract, raw bytes | `75ee8f9891e7f7835108d634d1fca2a74aedecd7e2a2ed1581c63fd8805bea25` |
| Factory Pool BigInt initialization contract, canonical JSON | `2b916bf3df7212604507cc5075f03950fc66b0d75b62924ad32a1923521e5dc6` |
| Factory Pool BigInt initialization verifier | `0dca669d82194aedd29254fe7b8d2d79d88bb5d10d43ec93c9953b7bbc3bb9ee` |

The parent must reproduce the 36 selected / 230 residual field ledger, 14/18
Factory closure, 6/44 direct static sites, 7/78 expanded invocations, and the
residual shared `txCount` site before this certificate is evaluated.

## Retained legacy WAT slices

WAT is reproduced from four retained deployed WASM artifacts with
checksum-pinned WABT 1.0.35 `wasm2wat --generate-names`.

The selected direct groups are at relative handler lines 351–355 and 356–360.
The selected same-receiver region ends at `Pool.save` on line 420.

| Profile | Price keys | Direct concat SHA-256 | Through-save SHA-256 |
|---|---|---|---|
| legacy Base root | `4080`, `4112` | `6dbe6e414441fa6df4a02cd8137f068485556ad23aba29ca3ae574441707e8ca` | `73efa76ca1f108771e060723b144c1af15f0b0cc5f343238e2543bdfeb93ed8f` |
| legacy mainnet QmRv | `6472`, `6504` | `1d2b6bfe9129010ca7f17fe18ed0b9e435271a8c5a2028296b97f18bb290727c` | `c8e9d98707c9eb79a50ae2722afc0783b480859c4aece956917998ca31c2b8d8` |
| legacy mainnet root | `6384`, `6416` | `447779da95797e5cf903d7ebb2602da754c328a84e76921d3954795f3b490ade` | `e3adfcd5063ec2026464904c74050dd3a07013a09bb3109dfb13ababeb309ac8` |
| legacy mainnet stable | `6512`, `6544` | `ea0ba12575f7acaaf60dfc0381a563fd003b53e9b3ad0ffe8872f7b8e5aa2681` | `65ba47a1886cf207794dc86a23797b1ef1c081f4760779fe98adacba2ab54a80` |

After decoding AssemblyScript static strings, all profiles share these
normalized digests:

- two-field direct concat:
  `3f22dabad50f6fa72e41d3e4711e6c1610aec087b4b47feeadf5efb4ed8cb102`;
- first price group through `Pool.save`:
  `6a42100ae5ccc46d0a656b19743ed0b4f9b5cfad599fb29eea0207d1c166e898`;
- constants lines 11–13, decoded-string normalized:
  `d58f98aeb90ccdb2975b0d747dfbe9953e74b97f847cdd812d49ee9143ca9ad0`.

The raw constants-line digest is
`031932bfc1fa2e80e619f4c0ef405027f0588a82335ab209e2b9972d0204694a`.
Those lines decode the pointer operand to the string `"0"`, call imported
`bigDecimal.fromString`, and store the returned pointer in `$g4`. The complete
global-writer inventory has exactly one `$g4` writer at constants relative line
13. This proves pointer provenance only, not the import's numeric behavior.

`Value.fromBigDecimal` starts at WAT line 2791, has 11 lines, and retains body
digest
`c22dc4c0902b6c3aa5b53bf549c79ccb3b8b5175add4de32117b556c19e54741`.
It binds kind tag 2 and input-pointer payload identity; constructor allocation
and freshness semantics remain false.

The cumulative direct relative sites are
`[327,335,340,345,350,355,360,365]`. The cumulative selected expanded
invocations are `[327,330,335,340,345,350,355,360,365]`, with canonical digest
`57d91787e8feb728d7f2e59bdbb366233d649bea59a055a8c7a27c0dd6acb1cf`.
The two newly selected invocations have digest
`142249e361d4dd5f0506ac6c81132e7f8afcc645ed18a8a3b62a2b260440104b`.
The full 78-invocation inventory retains digest
`e1786369ca1dccbf1328ec9f0534c5f2059851dbc65bc8a2c2a940f85be6b3a9`.

Normalization strips instruction whitespace, maps `generated/schema/` to
`src/types/schema/`, decodes each static AssemblyScript string pointer, and
replaces only that pointer with the SHA-256 of the decoded UTF-8 string.
Non-decodable constants and every other operand remain unchanged.

## Deterministic and adversarial checks

`--write-contract` recomputes the JSON from retained artifacts and bound
parents. Normal verification requires byte-for-byte canonical rendering and a
strict duplicate-key-free JSON parse.

Every WAT mutation fixture is first compiled with checksum-pinned
`wat2wasm --debug-names`, regenerated with `wasm2wat --generate-names`, and
then rejected by the intended semantic layer. The focused suite covers the
`$g4` source string, import-call target, and destination global;
`Value.fromBigDecimal` kind and payload; direct key, receiver, global, wrapper,
group order, and set target; inserted return/control and receiver writes;
Pool-save receiver/target drift; later key aliases; site/invocation accounting;
projections; strict false gates; raw and canonical parent drift; canonical base
drift; and duplicate JSON keys.

Reproduce locally with:

```bash
python3 scripts/verify-uniswap-v3-factory-pool-price-init.py \
  --wasm2wat /opt/homebrew/bin/wasm2wat --write-contract
python3 scripts/verify-uniswap-v3-factory-pool-price-init.py \
  --wasm2wat /opt/homebrew/bin/wasm2wat
python3 -m unittest scripts.tests.test_uniswap_v3_factory_pool_price_init
```
