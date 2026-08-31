# Provenance

The generated [contract.json](../contract.json) is based on commit
`8ac009d06ef05d077430aadac5782c6391a0ca0c`, tree
`2ddc9d94172eb8f61306280320d63a9029efcce3`.

## Direct roots

| Root | Raw SHA-256 | Canonical SHA-256 |
|---|---|---|
| `graft-ancestry/v2/contract.json` | `ae8c3e0099fedf2879b3071c2bcf545050fa4d448d0154fa6b895618bb8e203e` | `81f38fb34c1a5397386c77d7bd324d0350483587de627f171341f538b93edd37` |
| `graft-ancestry/v2/writer-compatibility.json` | `259481724561d5aa725c17f90b5a19ea93ad6f7cd6074cf2cb8a8661c39f81c4` | `96f1bc00e1a0eda7eb2a516e91bf9065aba5e2b668856e1d41905ba6e297bd71` |
| `segment-writer-matrix/v1/contract.json` | `7f6d1a34a8c885fe5ddcd81895818ba7ae8a0d736d541b881c1cc7cd54275161` | `356274207567cbcecb452a198758e8bdfc4440ba34d6ea3e66be2850d1a90280` |
| `segment-field-semantics/v2/contract.json` | `0ca8708bd2ed60d4799559d52b3f7e0602abfd7c3edbd35f579476f00baba6ef` | `28b9ed0d665cccb47ef6288ba7ae6247368036753bcbbfe0527e184b3c04eed3` |
| selected `segment-field-semantics/v1/contract.json` | `4daa777ce2d14edd8a665a6a1239db8fb78957aa091174fd31f81b2c25136d4e` | `34e421f2b276c91cc5596906d3731d16dc3af9ae17c890092e4ddb990a3ecf86` |
| `verify-uniswap-v3-segment-field-semantics-v2.py` | `e14a7ad95f9124861c36f72b60927f02200cfc02ad06eddf31eb36d7cc54e5ec` | n/a |
| `verify-uniswap-v3-writer-semantics.py` | `8cc6e779c8757cc4f59be49665922383ede95c5d654c65ffd043ea781555514b` | n/a |

All five JSON roots are rebound by both raw and canonical digest and rerun
through their retained-WASM authority chain. A raw match with a canonical
discrepancy fails closed.

## Direct schemas

| CID | Bytes | Raw SHA-256 |
|---|---:|---|
| `QmSGd2GREu8QzGgqXA626cyYbF65TGXj3gmk96CDBNQ9zG` | 18,381 | `35d07db24c66668ffd15f4d415cacdeaf0432c8c6149937cbc9644ae81e47964` |
| `QmU2VngSqWUtEo8XpPiPmXBfwLHZGrKnXqmifcj7GDH1b4` | 18,381 | `a623302914a925519745508fbb268100f58eaa65c4b01e84f9db5cf91ab0abcc` |
| `Qma8a81T9XoX5Pbkrk8J3kxMhWdXJzFSYZge1wGi3QZBru` | 19,034 | `ae03d0c6d3c6c03f87ae8e699b1e71804266c1d4adb7acbf4f4de5d48727c39c` |

Each retained GraphQL artifact is parsed independently and matches the same
299 entity/field/type/directive/storage catalog.

## Retained NPM mapping authority

| Mapping CID | Raw SHA-256 | WAT SHA-256 | Bodies | Calls | Writes |
|---|---|---|---:|---:|---:|
| `QmYWR79p…` | `3ad2abc957362fa5fa62ef8bb762ab3b38676d1139d1ca85ee0db2b25ade9fca` | `93cf89c0ac5f8af930c4a4a1b273a6831dced3247104db4585b6d6284da789a2` | 89 | 326 | 172 |
| `Qmebr2Ey…` | `bdb35f971e9a03b4bdc92b140d42285e27fdff6efb4edf14fe0f3eaad0c80537` | `19d7511d0a1ba05caeb115d4d820c89c61210c373b9253682915bc40d0d38d5d` | 89 | 326 | 172 |
| `QmYwxHm2…` | `b09ba105e25bbca52949325f57c2006fa2e441139617380d5f81e3945dfbbe02` | `c68a6ea285b643a301f7931ec8bebc3acd88c047a7c84b5773ffd2aa8570f9c3` | 87 | 324 | 172 |
| `QmWxG1yz…` | `34487685c81672436f34b79f3749f41e6b3c724b52dd8cb24b933e3cb5006124` | `6febde6b56e441b694f1708821a5e507f766ddfac3056a8efbce026826a9dced` | 50 | 352 | 291 |
| `QmUk7jc3…` | `e25dad1c3b6f1892eee2a8f51da62bb57268286deb9a135d6a689bdca1ad0034` | `4370c99e82c40e311a7a3d9c23ff0a61ed0dfd04feb9d737727308400ce03d12` | 89 | 326 | 172 |
| `QmPjhEuG…` | `6338f6b3b2071d0599b8381c948070ca138827bd61b6e5e05eb0d112177b0c91` | `2ca2b971161bb406b60ddf8d0d486ee02c3599dedb72c3c9c9dad9f6e63dd8ca` | 50 | 352 | 291 |

Every direct call and memory write is retained in the generated contract, not
only the summary counts. The current mappings each contain one reachable
`call_indirect` in `Value#displayData`, whose local table has exactly one target
and no import or mutation. Legacy Transfer closures contain no
`call_indirect`; their exported table initializer is recorded separately and
is not promoted to an executable Transfer target.

WABT version 1.0.35 and all six generated WAT digests are enforced. CI pins the
Linux release archive SHA-256
`cb3d22440273b1e8ee641e622b7a32222d97b519ad46169b1f8fcc6ce9af0b9b`;
the reviewed local macOS arm64 binary SHA-256 is
`df365308ea4fb092fde16ad0786c7c378bfe82863e460074a9574323f28e17da`.
Platform executable bytes are not asserted equal.

## Interpretation boundary

The contract binds lexical and expanded call paths, decoded schema keys,
receivers, constructor authority, store target and order. It does not infer
field values from physical symbols, describe no-setter fields as preserved, or
promote host calls, store contents, aliases, persistence, rollback, histories,
runtime identity, parity, backfill, or readiness.
