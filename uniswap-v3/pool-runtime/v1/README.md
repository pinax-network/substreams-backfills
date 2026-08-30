# Uniswap V3 modern Pool runtime v1

This additive certificate closes a structural runtime capsule for exactly the
retained modern Base and modern mainnet Pool mappings. It does not certify a
Pool event handler, an entity history, or a backfill.

The selection key is the complete `(profile_id, mapping CID, WASM SHA-256, WAT
SHA-256)` tuple:

| Profile | Mapping CID | WASM SHA-256 | WAT SHA-256 |
|---|---|---|---|
| `modern-base` | `QmPZCHE1URf4oviX7Tbrkw3aMENo1qAeEGa1AS2gMumG7P` | `e0050819429ca279916027512234119308ab26f4ff115939e6409aab676a501c` | `bd42b64aeaaf677018c11fe779179ecb81d7c4125fa0b846134bb0e0a6059ad1` |
| `modern-mainnet` | `QmSaGgPnyhStviGQSGTokQYRgVqLFNvnGWfnv8tSfuvpWD` | `f9a25426839d83f84679cd0d272582f2631c57117093ffd342351bc04aff8970` | `8454917398ef7a3b8f965a7e40e5b7a1d8cf7879e898490aeabe15726c3d4281` |

For each tuple, the standalone verifier invokes the one public shared
collection capsule. The Pool-specific specification binds the 77-line inline
`TypedMap#set`, both update and append branches, exact old/new length commit,
`TypedMap#get`, EventParam indexed access, the Entity constructor with type IDs
25/27/29, stub allocator and object-return identities, `String.__eq`, and the
profile-specific `ensureCapacity` body. The complete bodies of
`ensureCapacity`, `memory.fill`, `memory.copy`, and `memcpy` remain explicit
aggregate authority boundaries; the verifier adds structural checks for the
capacity/backing commits but does not rederive their general memory semantics.

The module-state proof independently binds `_start -> ~start`, rejects a native
WebAssembly start section, requires all eight critical mutable globals to start
at zero, and inventories every writer of those globals across all defined
functions. The exact Pool initializer body installs the profile allocator
floor and has no direct linear-memory write. Every initialized data segment is
decoded, inventoried, and required to end below that floor; both profiles
retain a 38-byte gap.

Imported host functions are assumed not to write arbitrary linear memory.
General reachable-helper memory safety is not rederived beyond the public
aggregate capsule and exact retained bodies. Those are explicit boundaries,
not implicit promotion claims.

This closes two of eight Pool runtime profiles. The six legacy Pool runtime
capsules remain unproved. Burn, Mint, Initialize, Swap, and Flash handler
semantics, complete entity histories, actual historic event population,
continuity, oracle/parity, checkpoint, backfill, production, and readiness all
remain strict `false` values.

See [eligibility.md](docs/eligibility.md) for the exact truth boundary and
[provenance.md](docs/provenance.md) for retained hashes and reproduction.

Verify with:

```bash
python3 scripts/verify-uniswap-v3-pool-runtime.py
python3 -m unittest scripts.tests.test_uniswap_v3_pool_runtime
```
