# Uniswap V3 Pool runtime v1

This additive certificate closes a structural runtime capsule for all eight
retained Uniswap V3 Pool mappings. It treats the two modern and six legacy
AssemblyScript runtime generations separately. It does not certify a Pool
event handler, an entity history, or a backfill.

The selection key is the complete `(profile_id, mapping CID, WASM SHA-256, WAT
SHA-256)` tuple:

| Profile | Mapping CID | WASM SHA-256 | WAT SHA-256 |
|---|---|---|---|
| `modern-base` | `QmPZCHE1URf4oviX7Tbrkw3aMENo1qAeEGa1AS2gMumG7P` | `e0050819429ca279916027512234119308ab26f4ff115939e6409aab676a501c` | `bd42b64aeaaf677018c11fe779179ecb81d7c4125fa0b846134bb0e0a6059ad1` |
| `modern-mainnet` | `QmSaGgPnyhStviGQSGTokQYRgVqLFNvnGWfnv8tSfuvpWD` | `f9a25426839d83f84679cd0d272582f2631c57117093ffd342351bc04aff8970` | `8454917398ef7a3b8f965a7e40e5b7a1d8cf7879e898490aeabe15726c3d4281` |
| `legacy-mainnet-root` | `QmWuomVAQCdEXdCRavcsmRz4BNqPx2nppqe8S6AXid66xw` | `f2238dc4f98e2ab6e7caf1ebe2bf2574c0f47f50df17c466b492542f3e06e4e7` | `5e8f6e0c96992afee37669c053b8940355e09e18741e53089838fb1c11924666` |
| `legacy-mainnet-qmrv` | `QmYQRHstsSS7mntgKNSot74qN2dpuyFEtd1DddPmnqWC65` | `ee35ffc861d04313370845e12d27de3a16d4f1f2d7137b81407c797d189fe94f` | `84dc181907baec30b5770fe5f8cdc61062b002989eb09f218963fd1995209aae` |
| `legacy-base-root` | `QmZPiDeH1j95mozzb5AjKCHn6zgpnhMu77kNAitPbi4Vt3` | `daaf355098f0d962fe772cdf858a5135cf229c03224380a83ea1e5248b746a0c` | `7444416b1ac3e7a3c98f4a2d5d3f24d343b2a1af8238f159b4839a0b2adc0a02` |
| `legacy-mainnet-stable` | `QmeNbEMUnaaPpmpLaUVBJfFWRCN5SxG8xPG5eDNoXEGdbW` | `0cb47b9bc9352ff26fda2267967374dee8bd54b9627120c97e442de1692979c5` | `6fac410afa86a411137e3bfabf46550261785b79fbfc53a39b8ec59492061d36` |
| `legacy-mainnet-stable-fee-tier-1` | `Qmaydei2ScE7JptBTPgSfkf6PFxEZpLn39gEXYqrBZhsv8` | `5130b364eb6e67767f0f6890011095a40f603af96e3dab9b3207e474af7d9e3b` | `3e68ada1f22ed2a2b72f74ecbdebe2f084ad42e11068fdc6991947963f145cb5` |
| `legacy-mainnet-stable-fee-tier-100` | `QmadCQv7VPgNXhQTNkcDyzmiWZpWexynUH4XuuaMrsAbJY` | `6f795b4a38a805ff8fbff2b0c33f8c5e52da2cd342a5efea9cffe637ec8ff42b` | `3868d954fe13117081173408b79d72fb88c4b88bfeabfb7a6e93b5482b87e4ff` |

## Generation-specific proofs

The modern semantic proof is retained and its declaration boundary is
strengthened. Its public shared collection capsule binds the
77-line inline `TypedMap#set`, both update and append branches, exact old/new
length commit, `TypedMap#get`, EventParam indexed access, the Entity
constructor with type IDs 25/27/29, stub allocator and object-return
identities, `String.__eq`, and profile-specific `ensureCapacity`. Its module
proof binds `_start -> ~start`, absence of a native start section, all eight
critical mutable globals and all their writers, direct-memory-write absence in
the initializer, and the initialized-data floor.

The legacy proof binds a separate native `(start $start)` module shape for all
six artifacts. It checks the exact 17-import and 11-export inventories, sole
one-entry `$null` table, absence of `call_indirect`, complete global definition
and writer inventories, static no-writer globals, all initialized data, and the
exact aligned allocator floor. The six artifacts reduce to four explicit
digest groups for native start, entry-array constructor/push, and string
allocation bodies.

The public legacy collection capsule closes the arena allocator and
ArrayBuffer allocate/reallocate paths; EventParam indexing; Value construction
and `fromBigDecimal`; `String.__eq` and `compareUnsafe`; TypedMap
get/getEntry/set; and entry-array construction/push. The retained symbol
`ethereum.SmartContract#constructor` is bound by its call sites and exact
layout as the 8-byte TypedMap entry constructor: receiver zero, key at offset
0, value at offset 4, and the same entry returned.

Before either generation-specific capsule can close, the verifier binds an
independent exact declaration inventory for every named helper used by the
proof. Each entry includes the full function header and every leading local
declaration, fixing parameter/local names, order, types, results, and type-use
identity. A refreshed body checksum therefore cannot reinterpret `$p1` as
`$p2` or exchange named locals behind otherwise unchanged instructions.

`memcpy`, `memmove`, and `memset` remain exact retained-body authorities. The
capsule proves the relevant operand call sites but does not claim a new general
semantic proof of those low-level routines. Imported host behavior is also an
explicit false boundary.

Legacy `memory.reset` is exported to the host. It has no internal call site and
is unreachable from each of the five handler closures, but it is not
host-unreachable. Allocator freshness is therefore claimed only within one
handler invocation under the explicit assumption that imported hosts do not
reenter `memory.reset`; no cross-handler freshness claim is made.

This closes eight of eight Pool runtime profiles and leaves zero runtime
profiles residual. Burn, Mint, Initialize, Swap, and Flash handler semantics,
complete entity histories, actual historic event population, continuity,
oracle/parity, checkpoint, backfill, production, and readiness all remain
strict `false` values.

See [eligibility.md](docs/eligibility.md) for the exact truth boundary and
[provenance.md](docs/provenance.md) for retained hashes and reproduction.

Verify with:

```bash
python3 scripts/verify-uniswap-v3-pool-runtime.py
python3 -m unittest scripts.tests.test_uniswap_v3_pool_runtime
```
