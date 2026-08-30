# Provenance and reproduction

The recorded implementation base is the reviewed local Factory-effects
commit. This is review provenance; the artifact verifier pins the parent
contract bytes below but does not inspect Git ancestry:

```text
699c9feeea3b1ed89c7f62dc86a46cf8ff1e7f03
```

Before reconstructing either WAT, the verifier requires the exact parent
contract bytes:

| Contract | SHA-256 |
|---|---|
| `uniswap-v3/factory-effects/v1/contract.json` | `f737d67550721ed418d8b5fb83424a55e429dceea7596643c69748458c5ac892` |

It then reruns that verifier and requires its 12-of-18 closure boundary. This
binds the complete handler authority, CFG/SSA analysis, constructor and save
helpers, persistent-effect closure, argument identity, and exact five-effect
suffix before the new static semantics are considered.

## Authoritative retained artifacts

| Profile | Mapping CID | WASM SHA-256 | WAT SHA-256 | Handler body SHA-256 |
|---|---|---|---|---|
| modern Base | `QmXFDgK3qLnmsLFcPWobXbdnqV9gESL9BvYY29si4vpTjr` | `296eb1ad59dca0ef5000e7e48971cb4c39ce8a3d8cfeb7541f6e8b924d049694` | `ea8185d6d94ff68dbb041684f29d23d528c6784a3396542657f9708d73d70972` | `485b7aab032b388184d0fe5535d40cd80176f0bc5cfd2682676824eff3f98dc8` |
| modern mainnet | `QmbJGLb6sXkN11djxLvKGb2zDk3s7ddgEsULwzC7TVyrEb` | `9a33e52667ce538278f9ab88ac9818f5442021e8a2ddb22fd5994a9643148887` | `84064b99fa818216ac5090dcf2a8f6b16acfe5f93edcc9819d0cb88d84526449` | `245ffe7ad61554106f9a5c748bb2cd629287a4fb0ecffa72c956d94915272dd5` |

Both authoritative handlers are
`src/mappings/factory/handlePoolCreated`, with 2,022 instructions, 37
structured controls, 312 direct calls, 183 heap writes, 206 local writes,
three normal returns, and 11 explicit traps. The Base handler starts at WAT
line 4,482; the mainnet handler starts at WAT line 4,617.

## Retained function bindings

| Function | modern Base body SHA-256 | modern mainnet body SHA-256 |
|---|---|---|
| `~start` | `03a9880de5c636da605722c9de980a9d8b831bd818f1ee932150410aceb58f04` | `82f696b281a1321a3b9fb5a98645ede19e925b0f3a10525624a093509885fd76` |
| `fetchTokenSymbol` | `96e3c6a30f1a578ee73fb0728502be0d664c45ae00ae81950a4205efebd63005` | `4f09a6bf9196de9bb7574e45b49e04e6998b40e02df2603ca33a7732a4714ed9` |
| `fetchTokenName` | `9c9d2d6f5b2f57cf6dea0c883b94c10ee85cbdea1936a3217b5f5e273103ee86` | `f760179a543ed09dc1a37c9bb0909376ec26c812b8917f55775e2fcd3bb607bd` |
| `fetchTokenTotalSupply` | `f81e091e27097d63c781cbe34253e50b5bdaca99120aad68fbbccd3b51934036` | `3feccb548d20c8961a76b9da3ca4e441ffdb90df4034d08b38814864371fb405` |
| `fetchTokenDecimals` | `a7d58596c9cb914b93bf95ce0a4737475dab9d152e13d5ea1ef61d34c08dd394` | `6b4849eab563bdf783203bf2541fd1687e652f51f2fd4c9b5cf0b3362d8653f5` |
| `StaticTokenDefinition.fromAddress` | `92bc949a17ab31a22ee3f81a5ff1bc20878df57af3af314ee542ad1c103aa8ef` | `9b4a566cea79a2ce18a1bdbe6d6add7fc42b13e3b2ecfb3ef4cbeeac669451bf` |
| whitelist membership | `fd7533a73510430897d69bce95502409898dccffd1eb01592089dbec82bfdc86` | `c2fcbe1f72c5178a09100ce46a209a2a47e7c9d7780f7c7eafa5fed6f054ba2e` |
| `Token#get:whitelistPools` | `346159ad6af19879530e3cd0b2eb2d2deb6bd6b1beb6166da50c2abd24dd8ebd` | `74ffe9096e8964cffc2f1dc62cd89e1f126681936d0e71a245d64eb917afabd1` |
| `Pool#get:id` | `082572dceb0673ebc1ba252ecc46e579316e6b34afeba9f7d9861849e5e26493` | `c3bf64291589c98b778f00f5c611241724cf1a66b65077d067f06b4e7e37ad31` |
| `Token#get:id` | `fa5baf7f95cc0c79730a34e04262e54730f53798b851866f2135f7976d18c9ba` | `929754fb22ba5daae26dfe0fb012b63cea986e258a470a3c75beed6202849731` |
| `Value.fromStringArray` | `a5bcd2f19ae7d650900aa231b50aee26423f702f3f1f21aa069080c8fa3a3662` | `b458f9ce24317d5c56af74ecc8eedc179bc0a9c2816953c2d8e87f24f31d3b43` |

The parent proof also binds the common modern `Token#constructor` body
`b0d614ab062922a181e44d3649ba6b9555b3871473c3374207ee6ce596993e83`.
That certificate proves the same input ID is encoded as a String Value under
the `id` key on the same fresh Token receiver that is returned.

The mainnet static profile is exactly:

| Address | Symbol | Name | Decimals |
|---|---|---|---:|
| `0xe0b7927c4af23765cb51314a0e0521a9645f0e2a` | DGD | DGD | 9 |
| `0x7fc66500c84a76ad7e9c93437bfc5ac33e2ddae9` | AAVE | Aave Token | 18 |
| `0xeb9951021698b42e4399f9cbb6267aa35f82d59d` | LIF | Lif | 18 |
| `0xbdeb4b83251fb146687fa19d1c660f99411eefe3` | SVD | savedroid | 18 |
| `0xbb9bc244d798123fde783fcc1c72d3bb8c189413` | TheDAO | TheDAO | 16 |
| `0x38c6a68304cdefb9bec48bbfaaba5c5b47818bb2` | HPB | HPBCoin | 18 |

The Base array is exactly empty. Reviewed mainnet source at commit
`69b50154b344e821d2ac71c24f260a5f54094808` corroborates the current mapping,
but source is not promoted to authority and no exact Base source match is
claimed.

The inlined `Pool.feeTier` conversion is also closed over the exact normalized
handler instruction slice from event-parameter selection through
`BigInt.fromI32`: Base
`2a63a66ed9dc95965e56fa204c683233a00045532c5d8cef09675bce8c3d2882`
and mainnet
`b624329a49f47c04f6b8203072ff91a8a04d5de32c54a32ed4808ae694cebcf7`.
Those digests are retained-artifact closure only. Independent structural checks
bind the exact event index, accepted Value kinds, payload pointer, sign
extension, byte copy, byte order, final `BigInt.fromI32`, Value wrapper, and
setter operands.

## Structural helper and setter closure

The retained helper digests above are authority seals, not the semantic proof
layer. The verifier independently binds:

- `Value.fromStringArray` allocation, backing buffer, capacity and offset-12
  length, same-index ordered String-to-Value conversion, final kind-4 payload,
  and same wrapper return;
- the profile-specialized whitelist backing pointer, length, every decoded
  member, input needle, equality loop, and Boolean result;
- `Token#get:whitelistPools`, `Pool#get:id`, and `Token#get:id` through exact
  receiver, key, kind/null gate, Value payload decoder, same-index conversion,
  and return;
- the Base zero-entry and mainnet six-entry static arrays, every tuple field and
  insertion slot, exact input-address lookup loop, matched object return, and
  null miss, including the mainnet fresh zeroed tuple constructor;
- all four token helpers from the original address through exact SmartContract
  construction, receiver, selector, signature, empty argument array, retained
  try-call/CallResult wrapper, and result decoder; and
- every operand, local definition, branch and byte comparison in the decimals
  `< 255` dataflow, while preserving the original input address on the failure
  fallback path.

The shared retained runtime certificates cover SmartContract construction and
try-call wrapping, `__newArray`, ByteArray/`BigInt.fromI32`, typed-array and
type-erased array get/set, `TypedMap#get`, CallResult wrappers, and common/entity
Value payload decoders. The pure `String.__eq` implementation is an explicit
irreducible retained-library body boundary with SHA-256
`f7967b738553ba98aba24f869e968d73e8013f99e83d02e106cad52306aa3c3f`.
Its authority is independent of the top-level whitelist-helper digest.

The mutation path from an Entity field assignment to its backing array is also
closed explicitly: both `TypedMap#set` branches preserve the same key/value,
new entries flow into `Array<TypedMapEntry>#push`, the push writes that entry at
the old length and commits the new length, and the Entity constructor owns a
fresh map array on the same returned receiver. Stub `__alloc` and `__new`
return identity are proved structurally. `ensureCapacity`'s committed backing
and capacity are checked structurally, while its complete complex growth body
is pinned as an exact retained-body boundary. The lower-level `memory.fill`,
`memory.copy`, and `memcpy` bodies are likewise exact retained-body boundaries.

For module initialization, the verifier binds the `_start -> ~start` export,
requires that no native WebAssembly start section exists, checks the zero
initial values of all critical mutable globals, and inventories every writer
of `~started`, the allocator offset, ZERO_BI, ONE_BI, and ZERO_BD. It decodes
and binds every whitelist object, backing range, member range, and the
allocator floor. The direct `~start` linear-memory-write/call inventory proves
only that initializer-local writes cannot reach those protected regions. Other
reachable helper bodies are pinned by the aggregate exact-body authority; the
verifier does not rederive a general absence of protected-memory writes inside
them. Imported host functions similarly remain an explicit trust boundary and
are assumed not to write arbitrary linear memory.

The complete direct and conservative-indirect closure from the handler contains
56 functions for Base and 57 for mainnet. Each profile has exactly 77 reachable
`TypedMap#set` sites: the 76 exact handler sites plus
`src/types/schema/Token#constructor` relative line 23. The canonical complete
setter inventory SHA-256 is
`193f2206f4a7b73ae2e743697cf62a7a837f29ee5cbe778fe3b7e0e121ad62f6`;
no other reachable setter is allowed. The handler event `$p0` and the initial
zero fee-copy index `$l2` are separately closed over their complete write
inventories and reaching definitions.

## Reproduction and adversarial validation

WAT is reconstructed with checksum-pinned WABT 1.0.35:

```text
wasm2wat --generate-names <retained-modern-factory-wasm>
```

The verifier deterministically recomputes the contract and rejects duplicate
JSON keys, parent-contract drift, artifact or helper drift, incomplete field
inventories, wrong receivers or decoded keys, wrong Value kinds, payload
producers, or final operands, wrong event/block inputs,
incorrect static tuples, changed early returns, changed effect sites, and any
appearance of `Pool.tick`.

The WAT mutation suite compiles every fixture with WABT `wat2wasm` before
semantic rejection. It covers field-key, constant, receiver, event/block source, Value
kind, payload, final operand, and exact wrapper-local substitutions; the
handler-entry event overwrite; early returns, whitelist direction and Bundle
effects; handler-inline and helper-injected `Pool.tick`; string/name/static and
`totalSupply` outcome drift; StringArray offset/kind changes; captured
whitelist backing, whitelist-getter length, Pool/Token ID keys, every requested
Base/mainnet static lookup or tuple placement change; all four token-helper
address-source substitutions; fee-tier byte assembly; and the decimals byte
comparator direction. It also mutates initializer dispatch and global state,
module-start protected memory,
`TypedMap#set` key/value operands, the appended array operand, Entity map
construction, capacity/backing commits, allocator return identity, and each
fixed low-level memory primitive. Transitive fixtures mutate the common Value
string decoder, exact retained `String.__eq`, and static tuple constructor
without changing their top-level caller bodies.

The affected top-level helper/body authority is refreshed in the relevant
fixtures, so each rejection occurs in the named structural dataflow layer.
The `feeTier` mutation similarly refreshes its exact slice digest. The
helper-injected setter fixture refreshes the modified Pool ID getter authority
and is still rejected by the independent reachable-setter closure. A separate
self-consistent contract-mutation suite proves that no residual gate or scope
boundary can be promoted by rewriting JSON.
