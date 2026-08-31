# Provenance

The generated [`contract.json`](../contract.json) is derived from the exact
repository tree at canonical Factory static v2 commit
`afaf3af9c25db029091d7699befe557276a442c7` (tree
`5c2e8f38721448039f09e06b195e019d11332d3f`).

## Direct roots

| Root | Raw SHA-256 | Canonical SHA-256 |
|---|---|---|
| `scripts/verify-uniswap-v3-factory-static-v2.py` | `f735dc4c90c8b58c68664d2ba5c3c761d9f143b54cd4af9db9e0d8f5e2c94122` | n/a |
| `uniswap-v3/factory-static/v2/contract.json` | `7437a95b9b1cff1c248b0685f59ec098a77fffe0ea4166b8f930a32ba6288118` | `adcd236a56b7a5627f956b23ba44daaeb6c58630b853ddf232516fec964373ef` |
| `scripts/verify-uniswap-v3-pool-initialize.py` | `5de73a42431c0d26dea48c6c570a58626532be14288cd16da20bcd1f2710d21d` | n/a |
| `uniswap-v3/pool-initialize/v1/contract.json` | `63bbec1b3190f1ccd54f9c9cb9a29bbd5a7d730be0165a2277412ea0b3adea14` | `37439929c810e594ab8977a4691e59fcd56ba63733db4ed90ed297505476d602` |
| `scripts/uniswap_v3_wat_runtime.py` | `bd555b5d44bed144777e35b361fcb63e275d7f21b774db3ffe0e08bef3bf4411` | n/a |

The recursive walk binds 44 unique transitive input files. Both raw and
canonical JSON digests are rechecked whenever a parent declares both; a raw
match with a canonical discrepancy fails closed. The canonical combined
manifest digest is
`ad33a8e381331b79a1e3946d15fe37b45e752c80cc9db14ae6911622fc31e30a`.

## Retained mapping authority

| Profile | Mapping CID | WAT SHA-256 | Reachable bodies | Store sites |
|---|---|---|---:|---:|
| `legacy-mainnet-root` | `QmWuomVAQCdEXdCRavcsmRz4BNqPx2nppqe8S6AXid66xw` | `5e8f6e0c96992afee37669c053b8940355e09e18741e53089838fb1c11924666` | 107 | 4 |
| `legacy-mainnet-qmrv` | `QmYQRHstsSS7mntgKNSot74qN2dpuyFEtd1DddPmnqWC65` | `84dc181907baec30b5770fe5f8cdc61062b002989eb09f218963fd1995209aae` | 108 | 4 |
| `legacy-mainnet-stable` | `QmeNbEMUnaaPpmpLaUVBJfFWRCN5SxG8xPG5eDNoXEGdbW` | `6fac410afa86a411137e3bfabf46550261785b79fbfc53a39b8ec59492061d36` | 111 | 4 |
| `legacy-mainnet-stable-fee-tier-1` | `Qmaydei2ScE7JptBTPgSfkf6PFxEZpLn39gEXYqrBZhsv8` | `3e68ada1f22ed2a2b72f74ecbdebe2f084ad42e11068fdc6991947963f145cb5` | 111 | 4 |
| `legacy-mainnet-stable-fee-tier-100` | `QmadCQv7VPgNXhQTNkcDyzmiWZpWexynUH4XuuaMrsAbJY` | `3868d954fe13117081173408b79d72fb88c4b88bfeabfb7a6e93b5482b87e4ff` | 111 | 4 |
| `legacy-base-root` | `QmZPiDeH1j95mozzb5AjKCHn6zgpnhMu77kNAitPbi4Vt3` | `7444416b1ac3e7a3c98f4a2d5d3f24d343b2a1af8238f159b4839a0b2adc0a02` | 112 | 5 |
| `modern-mainnet` | `QmSaGgPnyhStviGQSGTokQYRgVqLFNvnGWfnv8tSfuvpWD` | `8454917398ef7a3b8f965a7e40e5b7a1d8cf7879e898490aeabe15726c3d4281` | 64 | 5 |
| `modern-base` | `QmPZCHE1URf4oviX7Tbrkw3aMENo1qAeEGa1AS2gMumG7P` | `bd42b64aeaaf677018c11fe779179ecb81d7c4125fa0b846134bb0e0a6059ad1` | 64 | 5 |

The full contract stores every reachable body binding, setter and save ledger,
fixed store site, helper invocation, remove and Ethereum-call absence, direct
memory-write inventory digest, and the sole closed table target. Modern
closures have one reachable indirect call; legacy closures have none. No
retained Initialize closure contains `ethereum.call` or `store.remove`.

## Interpretation boundary

Field transitions are reviewed against the exact digest-bound handler and
helper bodies and qualified to normally completed paths. Generated symbol
names are not treated as receiver authority: compiler deduplication names many
hour setters as day setters, and interval `sqrtPrice`/`tick` setters as Pool
setters. The verifier instead binds helper context, decoded keys, expanded
invocation order, final fixed save targets, and the complete containing module.
The schema catalog's `storage` and `directives` fields are also bound per
outcome: `@derivedFrom` query fields are never described as values serialized
or preserved by an entity save. The 95/59 counts remain conservative
entity-writer associations; their direct stored-field counterparts are 87/58.
The two derived Pool interval collections separately record the conditional
query-visible effect of creating a child whose stored `pool` relation points
back to that Pool.

The interval ledgers also bind the exact structural boundaries that must not be
promoted into imported semantics. In the three Pool-saving profiles the
handler's `Pool.save` call precedes the day and hour helper calls; the other five
profiles contain no reachable Pool save. Every helper then reaches a Pool
`store.get`, directly in modern modules and through generated `Pool.load` in
legacy modules. The returned version or visibility is unproved. Missing-row
high and low setters occur before, and can be followed by, separate setters
controlled by the exact legacy comparator return or modern compare-result
equality shape. Comparator numeric meaning remains unproved. The final
`txCount` setter receives the exact `BigInt#plus(existing-or-zero txCount,
ONE_BI)` result without certifying imported arithmetic behavior. Finally, all
20 interval catalog fields are classified as 19 non-null fields plus nullable
`tick`; the bound generated tick setter uses a non-null write branch and either
legacy `Entity#unset` or a modern generated null-Value write branch.

Imported numeric behavior, store success or failure, Graph rollback, and
historic population are deliberately not inferred from these WAT roots.
