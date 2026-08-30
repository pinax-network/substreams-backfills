# Provenance

The generated [`contract.json`](../contract.json) is an additive proof over
immutable retained artifacts. Its semantic authority is exact retained WASM
plus WABT 1.0.35 `wasm2wat --generate-names` output; source text is
corroboration only.

## Pinned inputs

| Evidence | Identity | Raw SHA-256 |
|---|---|---|
| segment field-semantics v2 | `uniswap-v3-segment-field-semantics/v2` | `0ca8708bd2ed60d4799559d52b3f7e0602abfd7c3edbd35f579476f00baba6ef` |
| Pool Initialize contract | `uniswap-v3-pool-initialize-semantics/v1` | `63bbec1b3190f1ccd54f9c9cb9a29bbd5a7d730be0165a2277412ea0b3adea14` |
| Pool Initialize verifier | `scripts/verify-uniswap-v3-pool-initialize.py` | `5de73a42431c0d26dea48c6c570a58626532be14288cd16da20bcd1f2710d21d` |
| Pool runtime contract | `uniswap-v3-pool-runtime/v1` | `66daf481b5b3a8627110ff2dd736460611688887d3cbd6fdd41365fec9731b53` |
| Pool runtime verifier | `scripts/verify-uniswap-v3-pool-runtime.py` | `a595e07fbe2162e02807b0536a2a882804001eedff9fad91149029708ac69b67` |
| shared WAT runtime, through Pool runtime | `scripts/uniswap_v3_wat_runtime.py` | `bd555b5d44bed144777e35b361fcb63e275d7f21b774db3ffe0e08bef3bf4411` |
| writer compatibility | `uniswap-v3-writer-compatibility/v3` | `259481724561d5aa725c17f90b5a19ea93ad6f7cd6074cf2cb8a8661c39f81c4` |
| segment writer matrix | `uniswap-v3-segment-writer-matrix/v1` | `7f6d1a34a8c885fe5ddcd81895818ba7ae8a0d736d541b881c1cc7cd54275161` |
| shared Pool ABI | `QmULRc8Ac1J6YFy11z7JRpyThb6f7nmL5mMTQvN7LKj2Vy` | `df8064cbe381e7a929aa4e1a658ce3617daed0e871883bf29ced54112fdfdbfd` |

The Pool ABI artifact is 19,634 bytes and fixes the Burn parameter indices.
The Pool runtime verifier is digest-pinned and executed, and every Burn WAT
context is then passed through the same public runtime proof accessor. A valid
committed runtime JSON alone is therefore insufficient for a mutated Burn
fixture.

## Retained Pool mappings

| Profile | Mapping CID | WASM SHA-256 | WAT SHA-256 |
|---|---|---|---|
| `modern-base` | `QmPZCHE1URf4oviX7Tbrkw3aMENo1qAeEGa1AS2gMumG7P` | `e0050819429ca279916027512234119308ab26f4ff115939e6409aab676a501c` | `bd42b64aeaaf677018c11fe779179ecb81d7c4125fa0b846134bb0e0a6059ad1` |
| `modern-mainnet` | `QmSaGgPnyhStviGQSGTokQYRgVqLFNvnGWfnv8tSfuvpWD` | `f9a25426839d83f84679cd0d272582f2631c57117093ffd342351bc04aff8970` | `8454917398ef7a3b8f965a7e40e5b7a1d8cf7879e898490aeabe15726c3d4281` |
| `legacy-mainnet-root` | `QmWuomVAQCdEXdCRavcsmRz4BNqPx2nppqe8S6AXid66xw` | `f2238dc4f98e2ab6e7caf1ebe2bf2574c0f47f50df17c466b492542f3e06e4e7` | `5e8f6e0c96992afee37669c053b8940355e09e18741e53089838fb1c11924666` |
| `legacy-mainnet-qmrv` | `QmYQRHstsSS7mntgKNSot74qN2dpuyFEtd1DddPmnqWC65` | `ee35ffc861d04313370845e12d27de3a16d4f1f2d7137b81407c797d189fe94f` | `84dc181907baec30b5770fe5f8cdc61062b002989eb09f218963fd1995209aae` |
| `legacy-base-root` | `QmZPiDeH1j95mozzb5AjKCHn6zgpnhMu77kNAitPbi4Vt3` | `daaf355098f0d962fe772cdf858a5135cf229c03224380a83ea1e5248b746a0c` | `7444416b1ac3e7a3c98f4a2d5d3f24d343b2a1af8238f159b4839a0b2adc0a02` |
| `legacy-mainnet-stable-fee-tier-100` | `QmadCQv7VPgNXhQTNkcDyzmiWZpWexynUH4XuuaMrsAbJY` | `6f795b4a38a805ff8fbff2b0c33f8c5e52da2cd342a5efea9cffe637ec8ff42b` | `3868d954fe13117081173408b79d72fb88c4b88bfeabfb7a6e93b5482b87e4ff` |
| `legacy-mainnet-stable-fee-tier-1` | `Qmaydei2ScE7JptBTPgSfkf6PFxEZpLn39gEXYqrBZhsv8` | `5130b364eb6e67767f0f6890011095a40f603af96e3dab9b3207e474af7d9e3b` | `3e68ada1f22ed2a2b72f74ecbdebe2f084ad42e11068fdc6991947963f145cb5` |
| `legacy-mainnet-stable` | `QmeNbEMUnaaPpmpLaUVBJfFWRCN5SxG8xPG5eDNoXEGdbW` | `0cb47b9bc9352ff26fda2267967374dee8bd54b9627120c97e442de1692979c5` | `6fac410afa86a411137e3bfabf46550261785b79fbfc53a39b8ec59492061d36` |

## Proof and test boundary

The Burn verifier binds the handler-specific Pool/Token identity, exact
`bytesToHex` import target, ABI indices 4/5, matching decimals inputs,
conversion and subtraction operand order, old TVL getters, selected keys and
BigDecimal values, setter receivers, save receiver, selected-update-path
ordering, and reachable Graph store closure. The shared capsule supplies
collection, allocator, start, and complete global-writer facts.

The Burn-only in-memory boundary is an exact digest inventory of every
reachable function body and every reachable direct memory-write and
TypedMap-set site. Tests include compile-valid modern-base and representative
legacy mutations for no-op TypedMap setters, EventParam index behavior,
allocator returns, exact `bytesToHex` imports, helper-hidden and dynamic-key map
writes, and direct selected-payload overwrites. These fixtures prove fail-closed
coverage of changes to the retained authority; they do not classify the
baseline sites by receiver, key, value, or alias and do not turn the inventory
into a general heap-alias or imported-host proof.

Imported `bytesToHex`, numeric, and Graph store behavior remains assumed at the
explicit contract boundary. Graph rollback, post-fatal execution, cross-handler
freshness, no-later-selected-field-overwrite, selected-TVL persistence,
backfill readiness, and production readiness remain false.
