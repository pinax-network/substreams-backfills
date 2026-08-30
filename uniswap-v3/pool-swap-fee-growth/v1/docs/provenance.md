# Pool Swap fee-growth provenance

Semantic authority is the eight retained deployed Pool mapping WASM artifacts
converted with checksum-pinned WABT 1.0.35 using
`wasm2wat --generate-names`. Source text is corroboration only.

The deterministic verifier directly pins and recursively recomputes:

| authority | SHA-256 |
| --- | --- |
| Pool Flash verifier | `1ffc7b8d9b6e96b320c7e8323693ce92da5d7f3dc7a0f871b02d2b7855abc81e` |
| Pool Flash contract | `e90a292497f0771128a3e4859c8950b3496cbee9dcfd431334d19fe44926f696` |
| Pool Swap core verifier | `097047f6aac55b169c364cc0b4f51a1b4d655f103b77ed6dcc623a5daa3c77f8` |
| Pool Swap core contract | `5437e87329ae98eaf26e273903e53078a05c068c8be52f19a9673ed41cf4dd8b` |
| Pool Mint verifier | `a84e24fbff7449ca3ebbe94ef93ee1c6ab2d81ab4b9085c441108f587604be9d` |
| Pool Mint contract | `1040c821093b4f5afff3e99df58aa0e4b8021c643226d42dabd1255587fbf14c` |
| Pool runtime verifier | `a595e07fbe2162e02807b0536a2a882804001eedff9fad91149029708ac69b67` |
| Pool runtime contract | `66daf481b5b3a8627110ff2dd736460611688887d3cbd6fdd41365fec9731b53` |
| Pool Initialize verifier | `5de73a42431c0d26dea48c6c570a58626532be14288cd16da20bcd1f2710d21d` |
| Pool Initialize contract | `63bbec1b3190f1ccd54f9c9cb9a29bbd5a7d730be0165a2277412ea0b3adea14` |
| field-semantics v2 verifier | `e14a7ad95f9124861c36f72b60927f02200cfc02ad06eddf31eb36d7cc54e5ec` |
| field-semantics v2 contract | `0ca8708bd2ed60d4799559d52b3f7e0602abfd7c3edbd35f579476f00baba6ef` |
| segment writer matrix verifier | `1e9055f66517c1dada37b6dadd4770fddf505f38d2578349c7a07b46e567fc2f` |
| segment writer matrix contract | `7f6d1a34a8c885fe5ddcd81895818ba7ae8a0d736d541b881c1cc7cd54275161` |
| shared Pool ABI | `df8064cbe381e7a929aa4e1a658ce3617daed0e871883bf29ced54112fdfdbfd` |

The retained artifact identities, complete handler bodies, normalized selected
slices, modern pointers, legacy helper ranges, non-try call and `Value#toBigInt`
trap bodies, Pool receiver flows, two Pool saves, mutation inventories,
transitive Graph store inventories, segment surfaces, and all 28 scoped diffs
are serialized in `contract.json`.

The exact branch base is canonical PR #70 squash merge
`27dc439b150bbade46b6552d9e8611bc3c00da6f`, tree
`1345a42221c47c56783fbb0d5f3acbc6707a04ce`. The merge tree is identical to
the independently audited Flash candidate tree. The fee-growth contract is
regenerated and validated only against this canonical base.
