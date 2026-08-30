# Pool Swap core-state provenance

Semantic authority is the eight retained deployed Pool mapping WASM artifacts
converted with checksum-pinned WABT 1.0.35 `wasm2wat --generate-names`. Source
text is corroboration only.

The deterministic verifier consumes and pins:

| authority | SHA-256 |
| --- | --- |
| Pool Mint verifier | `a84e24fbff7449ca3ebbe94ef93ee1c6ab2d81ab4b9085c441108f587604be9d` |
| Pool Mint contract | `1040c821093b4f5afff3e99df58aa0e4b8021c643226d42dabd1255587fbf14c` |
| Pool runtime verifier | `a595e07fbe2162e02807b0536a2a882804001eedff9fad91149029708ac69b67` |
| Pool runtime contract | `66daf481b5b3a8627110ff2dd736460611688887d3cbd6fdd41365fec9731b53` |
| Pool Initialize verifier | `5de73a42431c0d26dea48c6c570a58626532be14288cd16da20bcd1f2710d21d` |
| Pool Initialize contract | `63bbec1b3190f1ccd54f9c9cb9a29bbd5a7d730be0165a2277412ea0b3adea14` |
| shared Pool ABI | `df8064cbe381e7a929aa4e1a658ce3617daed0e871883bf29ced54112fdfdbfd` |

The retargeted verifier SHA-256 is
`097047f6aac55b169c364cc0b4f51a1b4d655f103b77ed6dcc623a5daa3c77f8`.
The deterministically rendered contract SHA-256 is
`5437e87329ae98eaf26e273903e53078a05c068c8be52f19a9673ed41cf4dd8b`.

The complete handler tuples, helper-body digests, same-WAT public runtime
capsules, mutation inventories, store closures, segment surfaces, and all 28
pairwise scoped diffs are serialized in `../contract.json`. The contract also
publishes every valid-WAT mutation-fixture category and its expected rejection
layer.

The exact branch base is Pool Mint squash merge
`fa1c8d842712e53d363615062ecf1374e52bb854`. PR #68 exact-head CI completed
successfully on candidate `f596d28850b3f4201f227bf64b7ce4198671a9e8`,
and the merge tree was verified identical before this branch was retargeted.
