# NPM Liquidity v2 provenance

## Repository anchors

- implementation base commit:
  `5ad75eca9857176e9a9ecdfa6aeff6dd2a763312`
- implementation base tree:
  `78ae066e45d0175f9efd858969c1d8dd8c968ac3`
- retained semantic authority commit:
  `42c6d01f2e719993e41fca9db51be55d33da734c`
- retained semantic authority tree:
  `ba8531df0e102ba71fd30b4df2af2977355dabf3`

Transfer and Collect v2 are not semantic or generated-input dependencies.
They supplied only the additive nine-file layout and CI ordering pattern.

## Direct contract roots

| Input | Raw SHA-256 | Canonical SHA-256 |
|---|---|---|
| `graft-ancestry/v2/contract.json` | `ae8c3e0099fedf2879b3071c2bcf545050fa4d448d0154fa6b895618bb8e203e` | `81f38fb34c1a5397386c77d7bd324d0350483587de627f171341f538b93edd37` |
| `graft-ancestry/v2/writer-compatibility.json` | `259481724561d5aa725c17f90b5a19ea93ad6f7cd6074cf2cb8a8661c39f81c4` | `96f1bc00e1a0eda7eb2a516e91bf9065aba5e2b668856e1d41905ba6e297bd71` |
| `segment-writer-matrix/v1/contract.json` | `7f6d1a34a8c885fe5ddcd81895818ba7ae8a0d736d541b881c1cc7cd54275161` | `356274207567cbcecb452a198758e8bdfc4440ba34d6ea3e66be2850d1a90280` |
| `segment-field-semantics/v2/contract.json` | `0ca8708bd2ed60d4799559d52b3f7e0602abfd7c3edbd35f579476f00baba6ef` | `28b9ed0d665cccb47ef6288ba7ae6247368036753bcbbfe0527e184b3c04eed3` |
| `segment-field-semantics/v1/contract.json` | `4daa777ce2d14edd8a665a6a1239db8fb78957aa091174fd31f81b2c25136d4e` | `34e421f2b276c91cc5596906d3731d16dc3af9ae17c890092e4ddb990a3ecf86` |

The segment-field v2 verifier is pinned at
`e14a7ad95f9124861c36f72b60927f02200cfc02ad06eddf31eb36d7cc54e5ec`.
The writer verifier is pinned at
`8cc6e779c8757cc4f59be49665922383ede95c5d654c65ffd043ea781555514b`.
Neither NPM Transfer nor NPM Collect verifier is imported.

The recomputed catalog has 20 entities, 299 fields, 286 stored fields and 13
derived fields. Its field-catalog digest is
`b866d0241355fb378d891dd31193de30bc61771b2fc3b27f3793b0445d391424`;
the ordered entity/field-pair digest is
`7b467a440decf968491d8eacdcf7857bf7998e4015ad54867d573579acb11fc2`.

## Retained schemas

- `QmSGd2GREu8QzGgqXA626cyYbF65TGXj3gmk96CDBNQ9zG`: 18,381 bytes,
  `35d07db24c66668ffd15f4d415cacdeaf0432c8c6149937cbc9644ae81e47964`
- `QmU2VngSqWUtEo8XpPiPmXBfwLHZGrKnXqmifcj7GDH1b4`: 18,381 bytes,
  `a623302914a925519745508fbb268100f58eaa65c4b01e84f9db5cf91ab0abcc`
- `Qma8a81T9XoX5Pbkrk8J3kxMhWdXJzFSYZge1wGi3QZBru`: 19,034 bytes,
  `ae03d0c6d3c6c03f87ae8e699b1e71804266c1d4adb7acbf4f4de5d48727c39c`

Each schema independently projects to the same 299-field catalog.

## Retained NPM mappings

| Mapping CID | Bytes | Raw SHA-256 | Generated WAT SHA-256 |
|---|---:|---|---|
| `QmYWR79pUmVbQ42JkvB24D6AKCGtdo4UG78ZSewmFxwQdR` | 20,794 | `3ad2abc957362fa5fa62ef8bb762ab3b38676d1139d1ca85ee0db2b25ade9fca` | `93cf89c0ac5f8af930c4a4a1b273a6831dced3247104db4585b6d6284da789a2` |
| `Qmebr2EyxV7v1wLt9DSFKA7g8EhcVr9k1x7pwZr5eWEHT6` | 20,794 | `bdb35f971e9a03b4bdc92b140d42285e27fdff6efb4edf14fe0f3eaad0c80537` | `19d7511d0a1ba05caeb115d4d820c89c61210c373b9253682915bc40d0d38d5d` |
| `QmYwxHm2GNNcukX9oe4owucCLNoAk2rYrbMFuMFtWfKLn2` | 20,604 | `b09ba105e25bbca52949325f57c2006fa2e441139617380d5f81e3945dfbbe02` | `c68a6ea285b643a301f7931ec8bebc3acd88c047a7c84b5773ffd2aa8570f9c3` |
| `QmUk7jc3c8joQBrrcTz2ZEVDKcg1P12G2nFtuNqiikDQLJ` | 20,876 | `e25dad1c3b6f1892eee2a8f51da62bb57268286deb9a135d6a689bdca1ad0034` | `4370c99e82c40e311a7a3d9c23ff0a61ed0dfd04feb9d737727308400ce03d12` |
| `QmWxG1yzdQmp4pRDiqKvTZyRrrrZPRUTza6xznjR1wu1sD` | 48,593 | `34487685c81672436f34b79f3749f41e6b3c724b52dd8cb24b933e3cb5006124` | `6febde6b56e441b694f1708821a5e507f766ddfac3056a8efbce026826a9dced` |
| `QmPjhEuGqknJJ2LfJCi6XTLFLtiymYfZAtjTLfkmJJGMEj` | 48,657 | `6338f6b3b2071d0599b8381c948070ca138827bd61b6e5e05eb0d112177b0c91` | `2ca2b971161bb406b60ddf8d0d486ee02c3599dedb72c3c9c9dad9f6e63dd8ca` |

The contract binds each handler export to its exact body, normalized body,
instruction shape, raw and normalized call sequence and WAT location. It then
binds each handler closure and their set union through function-name and body
digests, all callsites, memory writes, schema/store sites, aborts, unreachable
instructions and the closed current-codegen indirect target. Liquidity also
derives the loadTransaction store-null branch independently from each retained
WAT: only id is guarded, while blockNumber, timestamp, gasUsed, gasPrice and the
Transaction save are outside that branch. No Collect verifier or contract is
used as semantic authority.

The three-copy Ywx mapping is counted once in unique-six inventories and three
times in eight-binding weighted inventories. No physical union total is
presented as an executable handler sequence.

## WABT authority and regeneration

WABT `wasm2wat` version 1.0.35 is required with `--generate-names`.

- CI Linux release archive SHA-256:
  `cb3d22440273b1e8ee641e622b7a32222d97b519ad46169b1f8fcc6ce9af0b9b`
- reviewed macOS arm64 binary SHA-256:
  `df365308ea4fb092fde16ad0786c7c378bfe82863e460074a9574323f28e17da`

Executable version and the six exact generated WAT digests are authoritative;
platform executable bytes are not asserted equal.

Regenerate with:

```bash
python3 scripts/verify-uniswap-v3-npm-liquidity-v2.py \
  --wasm2wat /path/to/wasm2wat \
  --write-contract
```

In-place regeneration must leave no diff. Detached regeneration from the
sealed commit must reproduce identical raw and canonical contract digests. Any
direct-root, schema, verifier, WAT, physical denominator, path ledger, outcome,
diff or generated-byte drift fails closed.
