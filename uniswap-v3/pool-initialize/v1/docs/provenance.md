# Provenance

The generated contract at [`../contract.json`](../contract.json) is a compact,
additive proof over immutable retained artifacts.

## Pinned inputs

| Evidence | Identity | Raw SHA-256 |
|---|---|---|
| segment field-semantics v2 | `uniswap-v3-segment-field-semantics/v2` | `0ca8708bd2ed60d4799559d52b3f7e0602abfd7c3edbd35f579476f00baba6ef` |
| writer compatibility | `uniswap-v3-writer-compatibility/v3` | `259481724561d5aa725c17f90b5a19ea93ad6f7cd6074cf2cb8a8661c39f81c4` |
| segment writer matrix | `uniswap-v3-segment-writer-matrix/v1` | `7f6d1a34a8c885fe5ddcd81895818ba7ae8a0d736d541b881c1cc7cd54275161` |
| shared Pool ABI | `QmULRc8Ac1J6YFy11z7JRpyThb6f7nmL5mMTQvN7LKj2Vy` | `df8064cbe381e7a929aa4e1a658ce3617daed0e871883bf29ced54112fdfdbfd` |

The v2 verifier itself is pinned at
`e14a7ad95f9124861c36f72b60927f02200cfc02ad06eddf31eb36d7cc54e5ec`
and recursively rechecks its full source and proof ledger before this
supplement is generated.

## Retained Pool mappings

| Profile | Mapping CID | WASM SHA-256 | WAT SHA-256 | Initialize persistence |
|---|---|---|---|---|
| `modern-base` | `QmPZCHE1URf4oviX7Tbrkw3aMENo1qAeEGa1AS2gMumG7P` | `e0050819429ca279916027512234119308ab26f4ff115939e6409aab676a501c` | `bd42b64aeaaf677018c11fe779179ecb81d7c4125fa0b846134bb0e0a6059ad1` | save |
| `modern-mainnet` | `QmSaGgPnyhStviGQSGTokQYRgVqLFNvnGWfnv8tSfuvpWD` | `f9a25426839d83f84679cd0d272582f2631c57117093ffd342351bc04aff8970` | `8454917398ef7a3b8f965a7e40e5b7a1d8cf7879e898490aeabe15726c3d4281` | save |
| `legacy-mainnet-root` | `QmWuomVAQCdEXdCRavcsmRz4BNqPx2nppqe8S6AXid66xw` | `f2238dc4f98e2ab6e7caf1ebe2bf2574c0f47f50df17c466b492542f3e06e4e7` | `5e8f6e0c96992afee37669c053b8940355e09e18741e53089838fb1c11924666` | no Pool store |
| `legacy-mainnet-qmrv` | `QmYQRHstsSS7mntgKNSot74qN2dpuyFEtd1DddPmnqWC65` | `ee35ffc861d04313370845e12d27de3a16d4f1f2d7137b81407c797d189fe94f` | `84dc181907baec30b5770fe5f8cdc61062b002989eb09f218963fd1995209aae` | no Pool store |
| `legacy-base-root` | `QmZPiDeH1j95mozzb5AjKCHn6zgpnhMu77kNAitPbi4Vt3` | `daaf355098f0d962fe772cdf858a5135cf229c03224380a83ea1e5248b746a0c` | `7444416b1ac3e7a3c98f4a2d5d3f24d343b2a1af8238f159b4839a0b2adc0a02` | save |
| `legacy-mainnet-stable-fee-tier-100` | `QmadCQv7VPgNXhQTNkcDyzmiWZpWexynUH4XuuaMrsAbJY` | `6f795b4a38a805ff8fbff2b0c33f8c5e52da2cd342a5efea9cffe637ec8ff42b` | `3868d954fe13117081173408b79d72fb88c4b88bfeabfb7a6e93b5482b87e4ff` | no Pool store |
| `legacy-mainnet-stable-fee-tier-1` | `Qmaydei2ScE7JptBTPgSfkf6PFxEZpLn39gEXYqrBZhsv8` | `5130b364eb6e67767f0f6890011095a40f603af96e3dab9b3207e474af7d9e3b` | `3e68ada1f22ed2a2b72f74ecbdebe2f084ad42e11068fdc6991947963f145cb5` | no Pool store |
| `legacy-mainnet-stable` | `QmeNbEMUnaaPpmpLaUVBJfFWRCN5SxG8xPG5eDNoXEGdbW` | `0cb47b9bc9352ff26fda2267967374dee8bd54b9627120c97e442de1692979c5` | `6fac410afa86a411137e3bfabf46550261785b79fbfc53a39b8ec59492061d36` | no Pool store |

## Proof boundary

The verifier follows data through the retained WAT rather than accepting
source descriptions, call names, or literals by themselves. It binds the
trigger-address Pool load, generated ABI parameter access, signed tick
conversion, generated schema setter bodies, modern inline BigInt value
construction, exact receiver locals without successful-path reassignment, and
generated `Pool.save` target/ID/entity arguments while preserving its original
entity parameter on every normal store path. The legacy Initialize parameter
wrapper is inspected through allocation, event binding, and return.
Generation-specific EventParam lookup, entity-map access, and signed-byte
writer targets are exact names rather than lexical generic matches. Fatal host
calls and `unreachable` instructions are accepted only inside closed guard
branches that trap before returning to the certified normal path.

For negative persistence, store callsites and transitive reachability are
recomputed from the current WAT function graph. The retained Graph store host
imports are pinned as a closed `store.get`/`store.set` surface, so a reachable
`store.remove` cannot escape the write inventory. This is also done for mutated
fixtures, so adding a dormant direct call, delete, or store hidden in an already
reachable helper cannot reuse stale upstream callsite evidence.
In saving profiles the handler call is also required to be the only reachable
`Pool.save`, and the generated write must be the only reachable Pool-targeted
`store.set`, excluding a later helper overwrite.

Every mutation fixture must compile with checksum-pinned WABT 1.0.35
`wat2wasm --debug-names` and is then regenerated with
`wasm2wat --generate-names` before semantic rejection. Source text remains
non-authoritative corroboration.
