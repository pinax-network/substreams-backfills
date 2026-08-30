# Provenance and reproduction

The recorded reviewed base is:

```text
112fd27745b3cdc252a9df9665481b6fa8257705
```

This is review provenance only; the verifier does not use Git ancestry as
semantic authority. Authority is the exact retained WASM plus the
checksum-pinned WABT 1.0.35 `--generate-names` WAT projection.

## Exact artifact selection

| Profile | CID | Bytes | WASM SHA-256 | WAT SHA-256 |
|---|---|---:|---|---|
| `modern-base` | `QmPZCHE1URf4oviX7Tbrkw3aMENo1qAeEGa1AS2gMumG7P` | 76,545 | `e0050819429ca279916027512234119308ab26f4ff115939e6409aab676a501c` | `bd42b64aeaaf677018c11fe779179ecb81d7c4125fa0b846134bb0e0a6059ad1` |
| `modern-mainnet` | `QmSaGgPnyhStviGQSGTokQYRgVqLFNvnGWfnv8tSfuvpWD` | 78,047 | `f9a25426839d83f84679cd0d272582f2631c57117093ffd342351bc04aff8970` | `8454917398ef7a3b8f965a7e40e5b7a1d8cf7879e898490aeabe15726c3d4281` |

Both modules contain 123 defined functions.

## Shared and profile runtime authority

The reusable, contract-I/O-free algorithms live in
`scripts/uniswap_v3_wat_runtime.py`. The standalone verifier captures and
executes those exact source bytes, then requires a `--root` candidate to carry
identical bytes before verification or `--write`. The current raw SHA-256 is
recorded in `contract.json`; regenerate the contract whenever those bytes
change.

Common Pool bodies:

| Function | Lines | SHA-256 |
|---|---:|---|
| Pool `TypedMap#set` | 77 | `1e32ff9bb00d137e45c1023931fe103bbe71d7011e2955044d0fb772b88f008b` |
| Pool `TypedMap#get` | 32 | `672fd714a063fdaf09f51b8e3a25c5b01a2124f68f3e8f7fcb587cddeb5999cb` |
| Entity constructor, type IDs 25/27/29 | 58 | `df453669386fdd214d23b561c134fdc0b1fe4e8c9bb46a3b6bec63e22e51d032` |
| `stub/__alloc` | 73 | `a03922d8f65cdc65e9d23c65bae22238c3783fed3294ec8847c2951f45a49c68` |
| `stub/__new` | 35 | `dc15ae7bfd1ff6f9f27d365946a2de6d849b46ed9e08818b80d59c05f97918fa` |
| `String.__eq` | exact body | `f7967b738553ba98aba24f869e968d73e8013f99e83d02e106cad52306aa3c3f` |
| `memory.fill` | exact body | `3eb4dece783813845638f30ebde64f0ce5c2d10784a724c6b5bcd346e7771390` |
| `memory.copy` | exact body | `0128a0af41ee62c13df7a14de4648d2e7ac19f230786e447a8736179e36d74a6` |
| `memcpy` | exact body | `a201b34d93d9bb7e4813134f668fb9436014260ba637d2db39cf7af3dc84a97c` |

Profile-specialized bodies and allocator data floor:

| Profile | `~start` lines / SHA-256 | `ensureCapacity` SHA-256 | EventParam get SHA-256 | Data end / floor |
|---|---|---|---|---:|
| `modern-base` | 50 / `52a99f58e7904d3ed759bf0a0272101e9e998bdfdb0e2fe93a21aedd6c12d589` | `09e6f7222a5ada41dc343ffb5eb297342dd3ff167cd6532bcaeec772f9705578` | `dd7f14070e5643932f0dc9ba5d3e7f9966aa900dc9e171eb213b9aaf4cf6d0c8` | 20,902 / 20,940 |
| `modern-mainnet` | 49 / `785ca5348b08a12a9a90b79760beefb3ab8b71130bfc01ee9e48ddefa36c79d3` | `90f7a34c6ef281823ee2062d67f72c339ee27b748d82b578348b02c3300a7579` | `d7838efd2a3cd438b05d6d627df4c1ea8ef0a291c02921096b89198d8643de68` | 22,662 / 22,700 |

Base has 528 initialized data segments; mainnet has 558. The canonical segment
inventory hashes and complete global-writer inventories are emitted in
`contract.json`, including the profile-specific Q192 writer line.

## Reproduction

```text
wasm2wat --generate-names <retained-modern-pool-wasm>
```

Run:

```bash
python3 scripts/verify-uniswap-v3-pool-runtime.py
python3 -m unittest scripts.tests.test_uniswap_v3_pool_runtime
```

Every adversarial WAT fixture is first compiled with checksum-pinned WABT
`wat2wasm`. The test then refreshes only the named top-level authority where
needed, so rejection occurs at the independent structural, module-state, or
allocator-floor boundary. Candidate-root divergence is tested in both verify
and `--write` modes. The six legacy mappings remain the next runtime work; no
legacy hash is promoted by this certificate.
