# Provenance and reproduction

The immediate parent is the squash-merged V4 release-assets commit on `main`;
the Factory proof still independently pins and reruns the earlier modern-guard
contract:

```text
3d99ce161bfc4703d17c4bb7ccbd6ab7451b567d
```

The supplement pins both immutable semantic inputs before doing new analysis:

| Contract | SHA-256 |
|---|---|
| `uniswap-v3/segment-field-semantics/v2/contract.json` | `0ca8708bd2ed60d4799559d52b3f7e0602abfd7c3edbd35f579476f00baba6ef` |
| `uniswap-v3/factory-guard/v1/contract.json` | `8b9637519a4debc9d875245ca3318ad8269bc7a440837e716750dd007ffd3216` |

The six authoritative retained mappings are:

| Profile | Mapping CID | WASM SHA-256 | WAT SHA-256 |
|---|---|---|---|
| legacy mainnet QmRv | `QmT8CKmLDFFCgwYnubFhKXUsuer5rfJKPT4PrCsv9tTwjV` | `c90c4b86b184d8ffed606f3264d6f3b921421ef7dce2cb35484dd7faaf452cd4` | `4263d51999d58769c06bef6da1aed4c24c1c846f4b0aaed9142bf3bd912ecf9b` |
| legacy Base root | `QmUN4pxwjMTfNem7rf1sKNFNHDsfzpbcTP93RxPAczgkvj` | `0855ce1d5260cd8395628dfac2e18db063909168c58e7d5de118612fee9f9a4e` | `c2e7425784b498481ee8a822be18b59edd7aa6dd27712d8d093696cf0b8b1684` |
| legacy mainnet root | `QmUu9rnGvUiBbF9pLnuJQab1wHXqjooo3bY5cZDVTyQQgr` | `ab7c84297665ab608ce3c6b8cc71f1c584ae7f2a94ebe674993b069d6b8b5c98` | `1fbcd7b7305dd0e0eb2e9de2e64ecb023e9aa5abe29f7562be4dad72bf561f4d` |
| modern Base | `QmXFDgK3qLnmsLFcPWobXbdnqV9gESL9BvYY29si4vpTjr` | `296eb1ad59dca0ef5000e7e48971cb4c39ce8a3d8cfeb7541f6e8b924d049694` | `ea8185d6d94ff68dbb041684f29d23d528c6784a3396542657f9708d73d70972` |
| modern mainnet | `QmbJGLb6sXkN11djxLvKGb2zDk3s7ddgEsULwzC7TVyrEb` | `9a33e52667ce538278f9ab88ac9818f5442021e8a2ddb22fd5994a9643148887` | `84064b99fa818216ac5090dcf2a8f6b16acfe5f93edcc9819d0cb88d84526449` |
| legacy mainnet stable | `QmcsaU3DrUqZHZLzrrWT9aW4EVQuS54wxNHynq8g1PvESL` | `1bde476d96fd4ba7720246a351c4de0f129693d838f9a39a660097c85d1edead` | `d44ed8c0bbd1bdf62635871b475fbe1a22c8d3a4b88e5d77e6827e3e61b70f81` |

WAT is reproduced with checksum-pinned WABT 1.0.35:

```text
wasm2wat --generate-names <retained-factory-wasm>
```

The verifier binds each complete handler, all local/control/call/heap-write
inventories, legacy Pool/Token/Factory save helpers, modern Token save helpers,
the shared legacy entity constructor, the modern Token constructor, the two
inlined modern required-ID store regions, and the conservative modern
`call_indirect` table closure. Constructor certificates prove the fresh entity,
same input ID, decoded `id` key, exact Value encoding and map-set operands, and
return of the same receiver. The verifier scans all reachable `store.set` and
`dataSource.create` sites, including the earlier Bundle path. The effect trace
itself is deliberately handler-local; only explicit handler traps and the
reviewed save helpers' pre-store trap boundaries are projected.

Mutation fixtures are assembled with WABT `wat2wasm` before rejection. They
cover the eight counterexamples that defeated the withdrawn analyzer, plus
receiver/ID swaps, active/dead literal substitution, event-index drift,
branch inversion, partial normal return, helper call-target replacement,
hidden and duplicate effects, `select`, `call_indirect`, indirect-target
effects, every load/constructor receiver-definition alternative, and local or
aliased heap mutation. Each fixture first refreshes its exact mutated
WAT/WASM, handler authority, and complete handler-local syntax inventory, then
asserts rejection at the intended semantic stage rather than at a digest pin.
