# Pool Flash v2 provenance

## Implementation base

- commit: `42c6d01f2e719993e41fca9db51be55d33da734c`
- tree: `ba8531df0e102ba71fd30b4df2af2977355dabf3`

## Direct authority roots

| Input | Version | Raw SHA-256 | Canonical SHA-256 |
| --- | --- | --- | --- |
| `scripts/verify-uniswap-v3-pool-flash.py` | verifier | `1ffc7b8d9b6e96b320c7e8323693ce92da5d7f3dc7a0f871b02d2b7855abc81e` | n/a |
| `uniswap-v3/pool-flash/v1/contract.json` | `uniswap-v3-pool-flash-semantics/v1` | `e90a292497f0771128a3e4859c8950b3496cbee9dcfd431334d19fe44926f696` | `272caec6c59ff6adcf645a99dad5ac9e950079f88b6bdff4047f4e1f0da6af8f` |
| `scripts/verify-uniswap-v3-segment-field-semantics-v2.py` | verifier | `e14a7ad95f9124861c36f72b60927f02200cfc02ad06eddf31eb36d7cc54e5ec` | n/a |
| `uniswap-v3/segment-field-semantics/v2/contract.json` | `uniswap-v3-segment-field-semantics/v2` | `0ca8708bd2ed60d4799559d52b3f7e0602abfd7c3edbd35f579476f00baba6ef` | `28b9ed0d665cccb47ef6288ba7ae6247368036753bcbbfe0527e184b3c04eed3` |

The verifier recomputes Pool Flash v1 from all eight retained mapping binaries
and its pinned transitive verifier chain. It then loads the field-semantics v2
contract directly, requires byte and canonical digests, and requires that the
direct contract equals the catalog reproduced through the Pool Flash v1
dependency chain. Factory static v2 is not an input.

The field catalog is recounted from source on every run: 299 unique
entity/field pairs across 20 entities, including Pool's 29 stored plus seven
derived fields and Flash's 12 required-absent stored fields. The eight mapping
proofs are regenerated from retained WASM through WABT 1.0.35 WAT before the
2,392 outcomes and all 28 pairwise diffs are built.

## Reproduction

```bash
python3 scripts/verify-uniswap-v3-pool-flash-v2.py \
  --wasm2wat /path/to/wabt-1.0.35/bin/wasm2wat
python3 -m unittest scripts.tests.test_uniswap_v3_pool_flash_v2
python3 scripts/verify-uniswap-v3-pool-flash-v2.py \
  --wasm2wat /path/to/wabt-1.0.35/bin/wasm2wat \
  --write-contract
```

Byte-identical regeneration from a detached checkout is the final artifact
check. It does not widen the semantic or operational eligibility boundary.
