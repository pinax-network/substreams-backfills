# All-handlers v1 provenance

## Provisional repository anchor

- implementation base commit:
  `0b66c2403e9440ecce9f7f48d70e9eec85d6b382`
- implementation base tree:
  `6e76693a346efa8a75bd49728866673391fd8b3e`

The base is the sealed local Liquidity candidate and contains every selected
component in one linear ancestry with matching predecessor edges. Factory,
Initialize, Flash, Burn, Mint, and Swap are canonical; corrected Transfer,
Collect, and Liquidity remain provisional, so the final certificate must be
regenerated on the canonical ancestry.

## Component roots

| Component | Commit | Tree | Contract raw SHA-256 | Contract canonical SHA-256 | Status at input |
|---|---|---|---|---|---|
| Factory | `afaf3af9c25db029091d7699befe557276a442c7` | `5c2e8f38721448039f09e06b195e019d11332d3f` | `7437a95b9b1cff1c248b0685f59ec098a77fffe0ea4166b8f930a32ba6288118` | `adcd236a56b7a5627f956b23ba44daaeb6c58630b853ddf232516fec964373ef` | canonical |
| Initialize | `42c6d01f2e719993e41fca9db51be55d33da734c` | `ba8531df0e102ba71fd30b4df2af2977355dabf3` | `6d9c36526ce4e041e18811ff5545efd5b5da96b4b2280c345b1f11379f202b84` | `c213d22dd95973f128059ca6fecfef2900ede9510dfdb344d4ceb3532bc9d224` | canonical |
| Flash | `796aa3ebd50a56a7b36a588a70fb0aa7fa092818` | `638f8ee61b71111eebeb4a6d7901311e5c9e4018` | `8ca53bf7ca19bdc52a81abda624181030e07d42c30b6771aee1802723e1f1b9b` | `073f9c01ae8066122013d3c43f4f75133fa300ee9f0a1ee325144be08c9ec9f3` | canonical; ancestor of implementation base; exact post-merge push CI run 33371981478 passed |
| Burn | `54bfab587a55a7c81204a166990c03cb659ae113` | `29616314b951850d0a8f5003c819e7e29baf216c` | `eab3d3e9555c6a2cae4c61de30da41d7af206eb66da76e42a7c34dd53ff5eb6d` | `1081e9d0061a17df58c83a5735f736c432aade2a286959f318bb5e623293790e` | canonical; exact post-merge validation passed |
| Mint | `7fdcdc915ab683c1081df307ef867cfde1f1bebd` | `976d7c858a3f111bd8ca2380ccf12bfdfa6e1ee7` | `0500fe9d45406e055298389dd3d1e6d44463f73c430469d4112be5ac09e4e013` | `cf1e1b990d0c400146c5615057ce705f8c49caf0d054cca96712bc15c41349f1` | canonical; exact post-merge push CI run 33382459957 passed |
| Swap | `8ac009d06ef05d077430aadac5782c6391a0ca0c` | `2ddc9d94172eb8f61306280320d63a9029efcce3` | `17cf23150f3cf097c65b2008533ebd61bea28e8b31ff79861c2450a03ae492ae` | `d002ae277913afc79e386911a7bb1a39eff73511a9f95e950f9d6f961ad79fdb` | canonical; exact post-merge push CI run 33406602088 passed |
| Transfer | `86c21e35f65f21f78917fa4e3f16228ec2124931` | `ca82557bd179527369f527c1c114a2d3d5ae252e` | `0fcadd7e68ca373ff1b1d202991818c1b36c5ba25ac8ede1515d1b8b1f041d7c` | `c208e1470767054553f8fcef68a2375f300cca90b8b5c1ba495639e7f0b75f12` | corrected provisional local candidate; canonical post-merge validation unavailable |
| Collect | `648443fec0d10bffd68b5e40f71e594822342968` | `c3500dc8bac4367520f6a512de4af3e7c10b1e86` | `bbcfa10a83abf5d80514ba2a629567796555070275c8c052cf9edcc2bd619a29` | `c0e9382baae5a585efbac5616321384dc9946b126c0c1ec99ce39f59806e965e` | corrected provisional local candidate; canonical post-merge validation unavailable |
| Liquidity | `0b66c2403e9440ecce9f7f48d70e9eec85d6b382` | `6e76693a346efa8a75bd49728866673391fd8b3e` | `6e4bff6a67baddf06aed51a957e9ba35f510e1bd64a02c7eeb46a66e99b86d71` | `811f9b7c5cba87d27bb954ce2d59f5a229e49df3815f8e112cf1d851880ce04e` | corrected provisional local candidate; focused 39, inherited 145, full discovery 1,001, direct verifier, Rust, and detached regeneration passed |

Flash ancestry correction: replace `canonical, not in base ancestry` with
`canonical; ancestor of implementation base; exact post-merge push CI run
33371981478 passed`.

The component manifest additionally pins every verifier/test digest, parent,
source-contract set, scope, truth boundary and segment-diff surface. Its digest
is generated into `contract.json`; it must change when any provisional root is
resealed.

## Direct shared roots

- segment-field semantics v2 commit
  `86ba5eaf978b4751011cdcbc8d764814105c5d02`, tree
  `69f4d49b02dd65af0bdb8c575fa961f9d09bbd99`, raw contract
  `0ca8708bd2ed60d4799559d52b3f7e0602abfd7c3edbd35f579476f00baba6ef`,
  canonical contract
  `28b9ed0d665cccb47ef6288ba7ae6247368036753bcbbfe0527e184b3c04eed3`;
- execution-order v1 commit
  `8c625578bcf2e2131bc8c954f99378509b19c751`, tree
  `733a03f38b0061f62c92b41c7d49c415939fe221`, raw contract
  `241e970cfcec4d76610b29a10141d3bff2512d80454a6308594f3db23621cde2`,
  canonical contract
  `3e58943f80e97688e05fffd73e3680de44570195383e78b02d1caab7bdc65d7b`;
- Graph Node reference commit
  `77823b5a7adc4eac4abf03202c8dd7cb00dea31d`.

The upstream field-catalog digest is
`b866d0241355fb378d891dd31193de30bc61771b2fc3b27f3793b0445d391424`.
The direct parser also pins ordered and sorted projections plus the ordered
entity/field-pair digest
`7b467a440decf968491d8eacdcf7857bf7998e4015ad54867d573579acb11fc2`.

## Retained schemas

- `QmSGd2GREu8QzGgqXA626cyYbF65TGXj3gmk96CDBNQ9zG`: 18,381 bytes,
  `35d07db24c66668ffd15f4d415cacdeaf0432c8c6149937cbc9644ae81e47964`
- `QmU2VngSqWUtEo8XpPiPmXBfwLHZGrKnXqmifcj7GDH1b4`: 18,381 bytes,
  `a623302914a925519745508fbb268100f58eaa65c4b01e84f9db5cf91ab0abcc`
- `Qma8a81T9XoX5Pbkrk8J3kxMhWdXJzFSYZge1wGi3QZBru`: 19,034 bytes,
  `ae03d0c6d3c6c03f87ae8e699b1e71804266c1d4adb7acbf4f4de5d48727c39c`

All three parse independently to the same ordered 299-field projection.

## Raw manifest roots

| Deployment | Bytes | Raw SHA-256 |
|---|---:|---|
| `Qme66ZNMxSdCQKzaDuvS381whCVYCQjf637sGZCqJHAWHB` | 4,146 | `8c4e9c93d1aa9ecb9549ffb547e0174272fef716fca94435c58148ee0aa3d137` |
| `QmRvEgUpbjVV326W2zPvxWimzQwcDREfjejUdFn2L92qry` | 4,226 | `5d39dce087a8e76d564972718cd95136a523cc8c06ea7fc58f8fa603afe18198` |
| `QmS13421u6qsbVdBCrZhdRaZw2wH67drwF3urmueJvvJ5P` | 4,226 | `aef82097c2c69afadb448a331c21b85afca5a4d0853e860e9f8e74431fc8fe32` |
| `QmSLHXCZBNKVtJRrWiEAF1yRQNPqAFptBsAcLdXQPsubSX` | 4,226 | `5811b920f213e6baed3b11fe549015a49e543508f01c284be0dd289c59d7ae53` |
| `QmZeCuoZeadgHkGwLwMeguyqUKz1WPWQYKcKyMCeQqGhsF` | 4,226 | `e85fcc1e89eb3553d0e76068a35733940df3579657c12b2099b3b06e401234ec` |
| `QmTZ8ejXJxRo7vDBS4uwqBeGoxLSWbhaA7oXa1RvxunLy7` | 4,268 | `691ea53201c6e3c65de3959b76be1a8fd1d9c119e1aaf55ab4a521f8e8a06e16` |
| `QmPWDTWRfS8XewMJhxXoQiZX6RkrUMYH7BFnnB846v6wzR` | 4,164 | `ab8cd8401649ae4ff439c2ab95f54f4cfdd31d259f20e21bcbee7b1436c9b78b` |
| `Qmb4VUcAY9LsVgeCuCCMs7X1XrkbRcaiuAbSK8SqhmsAfP` | 4,257 | `b4516b3e083985529c801b5071f804ab103ff307264bf82d18cda61b0ccc1085` |

The verifier reads each raw manifest directly, checks byte length and digest,
and extracts the ten handler declarations in datasource/template order.

## Regeneration authority

The default all-handler verifier archives each exact component commit into an
isolated temporary directory and runs its pinned verifier. It then independently
reconstructs the direct schema catalog, Factory projection, normalized cells,
overlays, setter/direct-write authority, manifest order and diffs.

Regenerate with:

```bash
python3 scripts/verify-uniswap-v3-all-handlers-v1.py \
  --wasm2wat /path/to/wasm2wat \
  --write-contract
```

In-place and detached regeneration must be byte-identical. Missing Git objects,
stale parents, digest drift, category/overlay/setter-authority/order/diff
mutations or any false-gate promotion fail closed. The candidate must be
regenerated again when the canonical component ancestry becomes available.
