# Pool Flash provenance

Semantic authority is the eight retained deployed Pool mapping WASM artifacts
converted with checksum-pinned WABT 1.0.35
`wasm2wat --generate-names`. Source text is corroboration only.

The deterministic verifier directly pins and recursively recomputes:

| authority | SHA-256 |
| --- | --- |
| Pool Swap verifier | `097047f6aac55b169c364cc0b4f51a1b4d655f103b77ed6dcc623a5daa3c77f8` |
| Pool Swap contract | `5437e87329ae98eaf26e273903e53078a05c068c8be52f19a9673ed41cf4dd8b` |
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

The Flash verifier SHA-256 is
`1ffc7b8d9b6e96b320c7e8323693ce92da5d7f3dc7a0f871b02d2b7855abc81e`.
The deterministically rendered contract SHA-256 is
`e90a292497f0771128a3e4859c8950b3496cbee9dcfd431334d19fe44926f696`.

The contract serializes the complete handler tuples, decoded call and setter
flows, call-helper trap proofs, same-WAT runtime capsules, exact mutation and
store inventories, required-absence records, eight segment surfaces, and all
28 pairwise scoped diffs. It also publishes every compile-valid mutation
fixture category and expected rejection layer.

The exact branch base is canonical Pool Swap squash merge
`71d554fa9676d8c77437c0366a9859e13834e235`. Its merge tree was verified
identical to the audited candidate before the Flash-local digests were
recomputed.
