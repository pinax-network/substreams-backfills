# All-handlers v1 provenance

## Canonical component anchor

- implementation base commit:
  `09555b21c1a18767107b92ae7bef20dfb2da77c2`
- implementation base tree:
  `4adcdd646b04ca49631fe33f4b8330bff6d7f905`

The base is the canonical corrected Liquidity squash merge and contains every
selected component in one linear canonical ancestry with matching predecessor
edges. The component reseal queue is empty. That
`canonical_reseal_required=false` state means only that no component reseal
remains; it does not publish the aggregate.

Merging the aggregate to `main` is necessary but not sufficient. A separate
post-merge content-addressed publication seal is the only publication
authority.

The immutable aggregate contract remains the pre-publication boundary and is
not rewritten after merge. Effective canonical publication is represented only
by a companion `publication-seal.json` that passes
`scripts/verify-uniswap-v3-all-handlers-v1-publication.py`. The seal binds the
tested PR candidate tree, byte-identical canonical aggregate squash tree,
immutable contract path/blob/bytes/digests, and the exact successful `main`
push workflow at that canonical commit. A missing or invalid seal means the
aggregate is unpublished. The base contract therefore keeps
`post_merge_aggregate_publication_seal_required=true` and
`canonical_publication_root_complete=false`; only the seal's effective
publication root may be true. This publication seal completes no additional
#37/#38 checkbox and closes neither issue.

## Canonical aggregate publication record

The marker-delimited record is populated exclusively from the four named
production pins in
`scripts/verify-uniswap-v3-all-handlers-v1-publication.py`. Any unresolved
placeholder is a fail-closed staging state. Once the pins are configured, the
verifier requires the exact linked commit, parent, tree, run, and payload digest.

<!-- publication-seal-record:start -->
- tested PR #100 candidate commit: [`ebac0f4c72cf564aee21a34c54e90bc0b0777145`](https://github.com/pinax-network/substreams-backfills/commit/ebac0f4c72cf564aee21a34c54e90bc0b0777145)
- tested candidate tree: [`e96f0956e76d136664db58e0d210851af38c2c87`](https://github.com/pinax-network/substreams-backfills/tree/ebac0f4c72cf564aee21a34c54e90bc0b0777145)
- canonical aggregate squash commit: [`{{EXPECTED_CANONICAL_AGGREGATE_COMMIT}}`](https://github.com/pinax-network/substreams-backfills/commit/{{EXPECTED_CANONICAL_AGGREGATE_COMMIT}})
- canonical aggregate parent: [`{{EXPECTED_CANONICAL_AGGREGATE_PARENT}}`](https://github.com/pinax-network/substreams-backfills/commit/{{EXPECTED_CANONICAL_AGGREGATE_PARENT}})
- canonical aggregate tree: [`e96f0956e76d136664db58e0d210851af38c2c87`](https://github.com/pinax-network/substreams-backfills/tree/{{EXPECTED_CANONICAL_AGGREGATE_COMMIT}}) (byte-identical to the tested candidate tree)
- canonical exact-head `main` push run: [`{{EXPECTED_CANONICAL_MAIN_PUSH_RUN_ID}}`](https://github.com/pinax-network/substreams-backfills/actions/runs/{{EXPECTED_CANONICAL_MAIN_PUSH_RUN_ID}})
- seal payload canonical SHA-256: `{{EXPECTED_PAYLOAD_CANONICAL_SHA256}}`
<!-- publication-seal-record:end -->

## Component roots

| Component | Commit | Tree | Contract raw SHA-256 | Contract canonical SHA-256 | Canonical status |
|---|---|---|---|---|---|
| Factory | `afaf3af9c25db029091d7699befe557276a442c7` | `5c2e8f38721448039f09e06b195e019d11332d3f` | `7437a95b9b1cff1c248b0685f59ec098a77fffe0ea4166b8f930a32ba6288118` | `adcd236a56b7a5627f956b23ba44daaeb6c58630b853ddf232516fec964373ef` | canonical; ancestral |
| Initialize | `42c6d01f2e719993e41fca9db51be55d33da734c` | `ba8531df0e102ba71fd30b4df2af2977355dabf3` | `6d9c36526ce4e041e18811ff5545efd5b5da96b4b2280c345b1f11379f202b84` | `c213d22dd95973f128059ca6fecfef2900ede9510dfdb344d4ceb3532bc9d224` | canonical; ancestral |
| Flash | `796aa3ebd50a56a7b36a588a70fb0aa7fa092818` | `638f8ee61b71111eebeb4a6d7901311e5c9e4018` | `8ca53bf7ca19bdc52a81abda624181030e07d42c30b6771aee1802723e1f1b9b` | `073f9c01ae8066122013d3c43f4f75133fa300ee9f0a1ee325144be08c9ec9f3` | canonical; ancestral |
| Burn | `54bfab587a55a7c81204a166990c03cb659ae113` | `29616314b951850d0a8f5003c819e7e29baf216c` | `eab3d3e9555c6a2cae4c61de30da41d7af206eb66da76e42a7c34dd53ff5eb6d` | `1081e9d0061a17df58c83a5735f736c432aade2a286959f318bb5e623293790e` | canonical; ancestral |
| Mint | `7fdcdc915ab683c1081df307ef867cfde1f1bebd` | `976d7c858a3f111bd8ca2380ccf12bfdfa6e1ee7` | `0500fe9d45406e055298389dd3d1e6d44463f73c430469d4112be5ac09e4e013` | `cf1e1b990d0c400146c5615057ce705f8c49caf0d054cca96712bc15c41349f1` | canonical; ancestral |
| Swap | `8ac009d06ef05d077430aadac5782c6391a0ca0c` | `2ddc9d94172eb8f61306280320d63a9029efcce3` | `17cf23150f3cf097c65b2008533ebd61bea28e8b31ff79861c2450a03ae492ae` | `d002ae277913afc79e386911a7bb1a39eff73511a9f95e950f9d6f961ad79fdb` | canonical; ancestral |
| Transfer | `0398e6184dc07fe848fcfef4ecd04ac0b64e8ece` | `ca82557bd179527369f527c1c114a2d3d5ae252e` | `0fcadd7e68ca373ff1b1d202991818c1b36c5ba25ac8ede1515d1b8b1f041d7c` | `c208e1470767054553f8fcef68a2375f300cca90b8b5c1ba495639e7f0b75f12` | canonical; ancestral |
| Collect | `5ad75eca9857176e9a9ecdfa6aeff6dd2a763312` | `78ae066e45d0175f9efd858969c1d8dd8c968ac3` | `79bd851de40cf85f34d2a56b27f0aedf9792fa10bfa15f16728d857e0acfb139` | `cd82fcc5b0ae2ada53b5d2a21d8fbff6ebeee04cd078b3bae964598fa0f89ffe` | canonical; ancestral |
| Liquidity | `09555b21c1a18767107b92ae7bef20dfb2da77c2` | `4adcdd646b04ca49631fe33f4b8330bff6d7f905` | `f0749606edc2fd72695b781692e4f3577db5bb79898529e78ae01f7e620a93ba` | `2673abf1c84388cddb11c9cecb16044eb23e8a71249a4ef4ef4e722847046388` | canonical; ancestral |

## Canonical component CI ledger

Every row below is an exact `push` run on branch `main` at the component commit,
with `conclusion=success`. All times are on 2026-08-31 UTC. Every recorded
step succeeded; there were zero failed and zero skipped steps.

| Component | Main push run | Exact head | Jobs | Steps | Six-job window | Component validation step |
|---|---|---|---:|---:|---|---|
| Factory | [33359148975](https://github.com/pinax-network/substreams-backfills/actions/runs/33359148975) | `afaf3af9c25db029091d7699befe557276a442c7` | 6/6 | 171/171 | 05:03:12–06:03:46 | `Verify complete all-profile Uniswap V3 Factory static semantics v2` 05:09:45–05:10:21 |
| Initialize | [33362881880](https://github.com/pinax-network/substreams-backfills/actions/runs/33362881880) | `42c6d01f2e719993e41fca9db51be55d33da734c` | 6/6 | 172/172 | 06:06:37–07:04:00 | `Verify complete path-qualified Uniswap V3 Pool Initialize v2` 06:08:15–06:09:16 |
| Flash | [33371981478](https://github.com/pinax-network/substreams-backfills/actions/runs/33371981478) | `796aa3ebd50a56a7b36a588a70fb0aa7fa092818` | 6/6 | 173/173 | 08:14:40–09:13:12 | `Recompute complete path-qualified Uniswap V3 Pool Flash v2 matrix` 08:19:24–08:20:18 |
| Burn | [33377759861](https://github.com/pinax-network/substreams-backfills/actions/runs/33377759861) | `54bfab587a55a7c81204a166990c03cb659ae113` | 6/6 | 174/174 | 09:27:33–10:25:14 | `Verify complete Uniswap V3 Pool Burn schema-API matrix v2` 09:30:44–09:34:28 |
| Mint | [33382459957](https://github.com/pinax-network/substreams-backfills/actions/runs/33382459957) | `7fdcdc915ab683c1081df307ef867cfde1f1bebd` | 6/6 | 175/175 | 10:27:06–11:17:36 | `Verify complete Uniswap V3 Pool Mint schema-API matrix v2` 10:34:45–10:40:05 |
| Swap | [33406602088](https://github.com/pinax-network/substreams-backfills/actions/runs/33406602088) | `8ac009d06ef05d077430aadac5782c6391a0ca0c` | 6/6 | 176/176 | 15:07:18–15:48:19 | `Verify complete Uniswap V3 Pool Swap schema-API matrix v2` 15:22:45–15:25:43 |
| Transfer | [33418534257](https://github.com/pinax-network/substreams-backfills/actions/runs/33418534257) | `0398e6184dc07fe848fcfef4ecd04ac0b64e8ece` | 6/6 | 177/177 | 17:15:05–18:12:19 | `Verify complete path-qualified Uniswap V3 NPM Transfer v2` 17:17:11–17:17:43 |
| Collect | [33429253753](https://github.com/pinax-network/substreams-backfills/actions/runs/33429253753) | `5ad75eca9857176e9a9ecdfa6aeff6dd2a763312` | 6/6 | 178/178 | 19:12:14–20:08:11 | `Verify complete path-qualified Uniswap V3 NPM Collect v2` 19:15:48–19:17:11 |
| Liquidity | [33438242374](https://github.com/pinax-network/substreams-backfills/actions/runs/33438242374) | `09555b21c1a18767107b92ae7bef20dfb2da77c2` | 6/6 | 179/179 | 20:51:03–21:50:22 | `Verify paired complete path-qualified Uniswap V3 NPM Liquidity v2` 20:56:08–20:59:22 |

The component manifest additionally pins every verifier/test digest, parent,
source-contract set, scope, truth boundary and segment-diff surface. Its digest
is generated into `contract.json`; any future component identity change must
regenerate it.

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
mutations or any false-gate promotion fail closed. A byte-identical aggregate
squash merge does not alter the bound component roots or require a component
reseal. The separate post-merge seal must bind that exact canonical squash
commit/tree and successful exact-head main-push CI without modifying this
contract; any contract content change invalidates the seal and requires
regeneration.
