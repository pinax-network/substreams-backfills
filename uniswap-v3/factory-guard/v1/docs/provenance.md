# Provenance and reproduction

The immediate parent is PR #59 head
`2eb0cc6db9634f5cb19de30f959b33665b7e6f57`. The supplement pins the raw
field-semantics v2 contract before doing any new analysis:

```text
uniswap-v3/segment-field-semantics/v2/contract.json
sha256 0ca8708bd2ed60d4799559d52b3f7e0602abfd7c3edbd35f579476f00baba6ef
```

The two authoritative retained artifacts are:

| Profile | Mapping CID | WASM SHA-256 | WAT SHA-256 |
|---|---|---|---|
| modern Base | `QmXFDgK3qLnmsLFcPWobXbdnqV9gESL9BvYY29si4vpTjr` | `296eb1ad59dca0ef5000e7e48971cb4c39ce8a3d8cfeb7541f6e8b924d049694` | `ea8185d6d94ff68dbb041684f29d23d528c6784a3396542657f9708d73d70972` |
| modern mainnet | `QmbJGLb6sXkN11djxLvKGb2zDk3s7ddgEsULwzC7TVyrEb` | `9a33e52667ce538278f9ab88ac9818f5442021e8a2ddb22fd5994a9643148887` | `84064b99fa818216ac5090dcf2a8f6b16acfe5f93edcc9819d0cb88d84526449` |

WAT is reproduced with exactly:

```text
wasm2wat --generate-names <retained-modern-factory-wasm>
```

The required WABT version is 1.0.35. The verifier also pins each complete
handler body, the exact guard slice, and all ten helper bodies used by the
event extraction, string parser, ByteArray constructor, and equality loop.
Static strings are decoded from the retained WAT data segments rather than
accepted from source prose.

The proof does not reuse the withdrawn lexical/proximity analyzer. It first
matches every instruction in the bounded guard, then independently parses the
structured-control tree, versions every local assignment, and executes the two
finite loop models. The literal loop has exactly twenty iterations over string
indexes 0 through 38 in steps of two. Once length equality establishes twenty
event bytes, the comparison loop covers byte indexes 0 through 19 in steps of
one.

Mutation tests first assemble every changed module with WABT `wat2wasm`, so a
rejection cannot be credited to syntactically invalid WAT. The suite includes
the six reviewed counterexamples that defeated the withdrawn analyzer, plus
self-comparison, branch inversion, active-literal substitution, reachable
heap and local writes, call-target replacement, extra return, `select`, and
`call_indirect` cases. Contract self-promotion is also rejected by full
deterministic regeneration.
