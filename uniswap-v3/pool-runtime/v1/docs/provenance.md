# Provenance and reproduction

The recorded reviewed base is:

```text
1df0c471c354fc3718dac88a973a34f5b149d9c3
```

This is review provenance only; the verifier does not use Git ancestry as
semantic authority. Authority is the exact retained WASM plus the
checksum-pinned WABT 1.0.35 `--generate-names` WAT projection.

## Exact artifact selection

| Profile | CID | Bytes | WAT lines | WASM SHA-256 | WAT SHA-256 |
|---|---|---:|---:|---|---|
| `modern-base` | `QmPZCHE1URf4oviX7Tbrkw3aMENo1qAeEGa1AS2gMumG7P` | 76,545 | 16,748 | `e0050819429ca279916027512234119308ab26f4ff115939e6409aab676a501c` | `bd42b64aeaaf677018c11fe779179ecb81d7c4125fa0b846134bb0e0a6059ad1` |
| `modern-mainnet` | `QmSaGgPnyhStviGQSGTokQYRgVqLFNvnGWfnv8tSfuvpWD` | 78,047 | 16,605 | `f9a25426839d83f84679cd0d272582f2631c57117093ffd342351bc04aff8970` | `8454917398ef7a3b8f965a7e40e5b7a1d8cf7879e898490aeabe15726c3d4281` |
| `legacy-mainnet-root` | `QmWuomVAQCdEXdCRavcsmRz4BNqPx2nppqe8S6AXid66xw` | 40,813 | 8,842 | `f2238dc4f98e2ab6e7caf1ebe2bf2574c0f47f50df17c466b492542f3e06e4e7` | `5e8f6e0c96992afee37669c053b8940355e09e18741e53089838fb1c11924666` |
| `legacy-mainnet-qmrv` | `QmYQRHstsSS7mntgKNSot74qN2dpuyFEtd1DddPmnqWC65` | 40,954 | 8,865 | `ee35ffc861d04313370845e12d27de3a16d4f1f2d7137b81407c797d189fe94f` | `84dc181907baec30b5770fe5f8cdc61062b002989eb09f218963fd1995209aae` |
| `legacy-base-root` | `QmZPiDeH1j95mozzb5AjKCHn6zgpnhMu77kNAitPbi4Vt3` | 39,128 | 8,859 | `daaf355098f0d962fe772cdf858a5135cf229c03224380a83ea1e5248b746a0c` | `7444416b1ac3e7a3c98f4a2d5d3f24d343b2a1af8238f159b4839a0b2adc0a02` |
| `legacy-mainnet-stable` | `QmeNbEMUnaaPpmpLaUVBJfFWRCN5SxG8xPG5eDNoXEGdbW` | 40,971 | 8,862 | `0cb47b9bc9352ff26fda2267967374dee8bd54b9627120c97e442de1692979c5` | `6fac410afa86a411137e3bfabf46550261785b79fbfc53a39b8ec59492061d36` |
| `legacy-mainnet-stable-fee-tier-1` | `Qmaydei2ScE7JptBTPgSfkf6PFxEZpLn39gEXYqrBZhsv8` | 40,987 | 8,871 | `5130b364eb6e67767f0f6890011095a40f603af96e3dab9b3207e474af7d9e3b` | `3e68ada1f22ed2a2b72f74ecbdebe2f084ad42e11068fdc6991947963f145cb5` |
| `legacy-mainnet-stable-fee-tier-100` | `QmadCQv7VPgNXhQTNkcDyzmiWZpWexynUH4XuuaMrsAbJY` | 40,988 | 8,871 | `6f795b4a38a805ff8fbff2b0c33f8c5e52da2cd342a5efea9cffe637ec8ff42b` | `3868d954fe13117081173408b79d72fb88c4b88bfeabfb7a6e93b5482b87e4ff` |

## Modern authority retained

Both modern modules contain 123 defined functions. Their existing public
collection and exported-initializer proofs are retained without weakening.
The exact modern common bodies, profile `~start`, `ensureCapacity`, EventParam,
data-segment, and global-writer inventories remain recorded in
`contract.json`.

## Legacy module and collection authority

All six legacy modules contain 225 defined functions and have the same native
module shape: `(start $start)`, no `_start` export, 17 imports, 11 exports,
`(table $table 1 funcref)`, sole element `$null`, and no `call_indirect`.
The export inventory SHA-256 is
`ec559f76cf848547649dc9d0306b7830b37536366c6eef5542002056125b0bf4`.
Import inventory, global-definition inventory, complete global-writer
inventory, no-writer static globals, and all handler reachability inventories
are profile-bound in `contract.json`.

The four profile digest groups are:

| Group | Profiles | `start` SHA-256 | Entry-array ctor SHA-256 | Entry-array push SHA-256 | String allocate SHA-256 |
|---|---|---|---|---|---|
| `legacy-wuom` | mainnet root | `287ad43620693a8d7b56e4e279c70c20ddf418deee872113bea040240b6d6c37` | `49c2ef950af1df2183e8d9a554594508f9b0bf86ed4831a39a211468f3023428` | `3ac2d877fec3008d9f13c8e95a1e20bc78c8a9bbe429630cc5e0a077604c3d5d` | `857aa72088e9ec6101a1c984f483b2321172f093d8acfb857acbf79b7f2432f1` |
| `legacy-yqr` | mainnet qmrv | `7b4e87d1aac1cdab8bbf97f74860739b39d24e70561c5f5b658318720852e9c1` | `f70f06c137d5b20c51b88de9ef8ff2eda6f713b92a8ab2fe0515238823e9fa8d` | `383337d49695eb70e6f113a5b5ee2bac214824350c788a996594a8d3104515d7` | `bac733ad2a46c0975cfeb8f37fd25464803ec78d52cb5b6262aad4386ea71e1b` |
| `legacy-zpi` | Base root | `dfedcb96be9317aad4d57a7bb53c8df3bbc2cd661a90f94b30ec299b7045424a` | `3ceaf38d13058325c0d8929a6ecf48010e801860d9d11cb34b9f321f73eef486` | `741170d740eafb130b2ca5ec98930f6e4d648ab781de35b8f0e193c4023ab4af` | `3775376af9346f6a9e5ab38c9721e024a9e481481189b1cc3cb2035fcf07f608` |
| `legacy-stable` | stable trio | `e97cc12f2129907015f400de8d01332698f783916ea1eaaaaca46272ccd79b53` | `174c75441ee0095f6f7e05633ee7f7352c47019ed0140970d3f28560d5ea4d63` | `830deee879384740601f635f04a329aa2a0e3688c5dc2bc8178e399308625665` | `098a5876f9394c48b20268aaecb58e3967f063baced1bfc0b5a42aafa036962b` |

Shared six-profile exact bodies include the constants initializer,
ByteArray/Factory/NativeMath dependencies, arena allocator, ArrayBuffer
compute/allocate/reallocate, EventParam get, Value constructor/fromBigDecimal,
TypedMap get/getEntry/set, the misleading 8-byte entry constructor,
String equality/compare, and memory allocate/reset. The full names, line counts,
hashes, structural facts, and exact low-level primitive boundaries are emitted
in each legacy proof projection.

Initialized data remains strictly below the exact `align8(max_data_end)` floor:

| Profile group | Segments | Maximum end | Allocator floor |
|---|---:|---:|---:|
| `legacy-wuom` | 194 | 10,981 | 10,984 |
| `legacy-yqr` | 195 | 11,069 | 11,072 |
| `legacy-zpi` | 177 | 9,301 | 9,304 |
| `legacy-stable` | 197 | 11,109 | 11,112 |

## Reproduction

```text
wasm2wat --generate-names <retained-pool-wasm>
```

Run:

```bash
python3 scripts/verify-uniswap-v3-pool-runtime.py
python3 -m unittest scripts.tests.test_uniswap_v3_pool_runtime
```

Every adversarial WAT fixture is first compiled with checksum-pinned WABT
`wat2wasm`. The legacy registry contains 55 compile-valid mutations spanning
every promoted layer and all four digest groups. A deeper invariant test
refreshes only the deliberately changed top-level body authority so rejection
occurs at the independent structural boundary. Candidate-root divergence is
tested in both verify and `--write` modes.

The reusable contract-I/O-free algorithms live in
`scripts/uniswap_v3_wat_runtime.py`. The standalone verifier captures and
executes those exact source bytes, then requires a `--root` candidate to carry
identical bytes before verification or `--write`. The current raw SHA-256 is
recorded in `contract.json`; regenerate both Pool runtime and Factory static
contracts whenever those bytes change.
