# Provenance and reproduction

This certificate is based on the exact canonical PR #72 squash merge. Its tree
is byte-identical to the independently audited candidate tree:

```text
canonical merge commit:      982dd6f049af265cfed4c7b8edce1a90c936f319
canonical merge tree:        ffc1ef46913c94a6c7b5bc9738de2389dce38daf
canonical merge parent:      cf4d096304c09f150a7ee2ea85de5d479d5ec7ef
audited candidate commit:    1c6d90f0cbf7bf80a47555f9f6242d8f7440975e
audited candidate tree:      ffc1ef46913c94a6c7b5bc9738de2389dce38daf
exact-head CI run:            33337445498 (6 jobs, 162 successful steps)
```

The implementation branch starts from that canonical merge. This ancestry
fact does not promote any backfill, deployment, production, or readiness
claim.

## Bound parent

The verifier requires the exact canonical Factory fee-growth initialization
parent bytes and reruns that parent, including all of its transitive retained
artifact, WABT, Factory-effects, modern-static, Pool-fee-growth, field-catalog,
and segment-matrix gates.

| Input | SHA-256 |
|---|---|
| Factory fee-growth initialization contract | `38301b81ae36e346595847c62a0ffc4bf12ce67e0b437abda7790e379e1489d1` |
| Factory fee-growth initialization verifier | `1c0ead297e7980f472c11f43032405430b0dafdd63332a9be25c67c3a8267980` |

The parent must reproduce the 36 selected / 230 residual field ledger and the
14/18 Factory closure before this certificate is evaluated.

## Retained legacy WAT slices

WAT is reproduced from four retained deployed WASM artifacts with
checksum-pinned WABT 1.0.35 `wasm2wat --generate-names`.

The four direct field groups are at relative handler lines 323–327, 331–335,
336–340, and 361–365. The selected shared `txCount` invocation is at 328–330.
The selected same-receiver region ends at the `Pool.save` call on line 420.

| Profile | Direct keys | Shared `txCount` key | Direct concat SHA-256 | Through-save SHA-256 |
|---|---|---:|---|---|
| legacy Base root | `3888`, `3936`, `3960`, `4144` | `1632` | `064f1648d8311bd74a5950fcc3cfd24cfddf1069042f098907bf73313833b8bc` | `9ee3fd7478f6f84e8f567d60e1a86cf7628424b11468064824f989b71a0fc8ef` |
| legacy mainnet QmRv | `6280`, `6328`, `6352`, `6536` | `3400` | `7756f05a11cd6778fc58483121fc8328a2177c3b2966e7a327f389edd274e329` | `16a3e3c8803409efe0fd5e97f6eaa7c46bb47162bd80f2c2e046b34dc12e5edd` |
| legacy mainnet root | `6192`, `6240`, `6264`, `6448` | `3312` | `5a2c2c97b3b8c03c2eaef20dfdfa7f0124ae696933546a8b022fea4e34b51310` | `6dc9a67e2015df5dc57ef62cc2a27e8fa69e00f28ce0830af91e14438aca1302` |
| legacy mainnet stable | `6320`, `6368`, `6392`, `6576` | `3440` | `a77253839dcae8a2416ccb3ee725938168168db8175b2148ef1e14e0a6f2ef9e` | `8814b5f6b20dd3be01be7b6b122c2836c2875b5b9a8bcbf205981886180fa359` |

After decoding AssemblyScript static strings, all profiles share these
normalized digests:

- direct four-field concat:
  `9f21f5981eaf93e4c9bc148c02148695706c95e255d152aeabe78a968fd41475`;
- shared helper body:
  `c66a247d0789ccc5317bb647bb0471e03ee9c743bfbc3ec6a3af194b751678c9`;
- selected helper invocation:
  `766a1a59d075f69fce80edf4786e7c39284a482171cb748eaa28291bef6a6408`;
  and
- earliest selected group through `Pool.save`:
  `2aae1299579e35b2ef62df758ff5aadd2f620edb9394efe821d9656a132d6fbd`.

The shared helper is bound at WAT line 2826 with six lines. Its raw body
digests are:

| Profile | SHA-256 |
|---|---|
| legacy Base root | `5e022004bdca5593d0346f836076eb53c3e98df605e7fcce5f24eb638a29ebba` |
| legacy mainnet QmRv | `3c70518e7acc06a9b0c1e9d17eab9954fef7d735fdbc30e8b0255bb4746895b0` |
| legacy mainnet root | `f496b1ab3b05e40f4c4b84c9c4ffb4744db7cd5b945ebb5f52099a7534ade202` |
| legacy mainnet stable | `437e4bc7e21f2217f30ded6c1be2d3cdb2f1ba68c3994ccc2a648dd46550b6f4` |

The exact shared-helper invocation lines are `[60,168,242,330]`, with
canonical digest
`8b914a24207681421cdaa033b60647fe0ed4acb87fbe66a71154d14aaa0ffa7c`.
The cumulative selected expanded invocation lines are
`[327,330,335,340,345,350,365]`, with canonical digest
`4e20adceefbfb06cdd7c63f371d729fe90e424605ea6310995da9b5282252afb`.
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
then rejected by the intended semantic layer. The focused suite covers direct
key/receiver/global/wrapper/group mutations; shared-helper key/wrapper/operand
mutations; selected and residual helper invocations; inserted control and
receiver writes; Pool-save receiver/target drift; later key aliases; reachable
unselected helpers; site/invocation accounting; projections; strict false
gates; canonical parent drift; and duplicate JSON keys.

Reproduce locally with:

```bash
python3 scripts/verify-uniswap-v3-factory-pool-bigint-init.py \
  --wasm2wat /opt/homebrew/bin/wasm2wat --write-contract
python3 scripts/verify-uniswap-v3-factory-pool-bigint-init.py \
  --wasm2wat /opt/homebrew/bin/wasm2wat
python3 -m unittest scripts.tests.test_uniswap_v3_factory_pool_bigint_init
```
