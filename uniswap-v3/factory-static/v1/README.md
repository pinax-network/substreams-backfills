# Uniswap V3 modern Factory static semantics v1

This additive supplement closes only the `complete_static_handler_contract`
path for the retained modern Base and modern mainnet Factory mappings. It pins
and reruns the complete [`factory-effects/v1`](../../factory-effects/v1/README.md)
proof before adding any field claim. The retained deployed WASM remains the
semantic authority.

For each modern mapping, the verifier accounts for all 60 stored-field
contracts across `Factory`, `Bundle`, `Token`, and `Pool`:

| Entity | Stored-field contracts | Written | Required absence |
|---|---:|---:|---:|
| Factory | 13 | 13 | 0 |
| Bundle | 2 | 2 | 0 |
| Token | 16 | 16 | 0 |
| Pool | 29 | 28 | 1 (`Pool.tick`) |
| **Total** | **60** | **59** | **1** |

The handler contains 76 `TypedMap#set` calls because it initializes both
tokens and can update each token's whitelist. `Token.id` is set by the exact
constructor already proved by the bound Factory-effects contract. Every other
written field is continuously tied to its exact entity receiver, decoded key,
Value kind, semantic payload producer, final Value operand, and exact
`TypedMap#set` call. This includes structural source-to-payload proofs for
Factory `poolCount`, Pool ID, token helper outcomes, block metadata, and the
inlined signed `feeTier` decode. String-array initialization and append paths
bind the exact kind-4 wrapper to the same ordered input array. The exact
`feeTier` conversion-slice digest is retained-artifact closure in addition to,
not instead of, the structural dataflow proof. The mainnet static-token profile
is the exact six-entry deployed array; the Base profile is the exact safe empty
array.

The verifier also computes the complete direct and conservative-indirect call
closure from `handlePoolCreated`: 56 reachable functions on Base and 57 on
mainnet. Its complete `TypedMap#set` inventory is exactly the 76 handler sites
plus the separately certified `Token#constructor` ID site, with no other
reachable setter. This closes helper-injected writes as well as inline writes.
The entry event local remains the reaching definition for every event and
block read; its only earlier assignment is confined to a path that must abort.
The fee-copy index remains its WebAssembly-defined initial zero until the
certified copy-loop update.

The token and collection support is structural rather than checksum-only. It
binds SmartContract construction and try-call inputs, CallResult wrappers,
Value kind gates and payload decoders, typed-map and array index/value flow,
ordered string-array conversion, whitelist backing storage and members, ID
getters, static tuple allocation/insertion/lookup, and the complete signed
decimals comparison. It also closes the collection mutation chain through
`TypedMap#set`, `Array<TypedMapEntry>#push`, the Entity map constructor, the
stub allocator, and the committed backing/capacity outputs of `ensureCapacity`.
`String.__eq`, the complete retained `ensureCapacity` body, and the three
low-level memory primitives used beneath that chain are explicit exact-body
boundaries; their independently pinned digests are not refreshed by
top-level helper authority.

The shared public capsule also binds an exact 13-function declaration
inventory before those structural claims can close. Function type uses,
ordered named parameters and types, results, and named locals are independent
authority, so refreshing reachable-body hashes cannot reinterpret parameter
or local identities.

The initializer proof binds the `_start -> ~start` export, absence of a native
WebAssembly start section, zero initial mutable globals, and the complete
writer inventory for `~started`, the allocator offset, and ZERO/ONE constants.
It also binds the decoded whitelist objects, backing storage, members,
allocator floor, and exact `~start` call/direct-memory-write inventory. The
linear-memory writes in `~start` cannot overwrite those protected regions.
Other reachable helper bodies remain pinned by the aggregate body-authority
hash rather than a general memory-write proof. Imported host functions are a
second explicit trust boundary: this certificate assumes they do not write
arbitrary linear memory.

The new handler-local normal-return projection includes the optional earlier
Bundle write as well as the previously certified five-effect suffix:

```text
[]
[Bundle.save]
[Pool.save, PoolTemplate.create, Token[token0].save,
 Token[token1].save, Factory.save]
[Bundle.save, Pool.save, PoolTemplate.create, Token[token0].save,
 Token[token1].save, Factory.save]
```

The empty trace covers the existing-Pool return and a null-decimals return
when Factory already exists. When Factory is created, `Bundle.save` occurs
before either null-decimals return. This is a handler-local invocation proof;
retained WAT does not prove Graph Node rollback after a later helper, import,
or host trap.

This moves cumulative Factory closure from 12 to 14 of 18 upstream paths. The
four legacy complete-static paths remain false. Historic token-call outcomes,
runtime population, complete entity histories, integrated execution order,
continuity, oracle/parity, proof of indexing, backfill, and production gates
also remain false. This supplement completes no tracking-issue checkbox.

See [eligibility.md](docs/eligibility.md) for the exact truth boundary and
[provenance.md](docs/provenance.md) for immutable inputs, retained functions,
and adversarial validation.

Verify with:

```bash
python3 scripts/verify-uniswap-v3-modern-factory-static.py
python3 -m unittest scripts.tests.test_uniswap_v3_modern_factory_static
```
