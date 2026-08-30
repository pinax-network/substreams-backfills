# Provenance and reproduction

This certificate is based on the exact canonical PR #71 squash merge. Its tree
is byte-identical to the independently audited candidate tree:

```text
canonical merge commit:      cf4d096304c09f150a7ee2ea85de5d479d5ec7ef
canonical merge tree:        346c9ba3eb141ada18d4ee1589a725919b349351
canonical merge parent:      27dc439b150bbade46b6552d9e8611bc3c00da6f
canonical merge parent tree: 1345a42221c47c56783fbb0d5f3acbc6707a04ce
audited candidate commit:    4e173177089ae0781e389588d11dfe1a8d013391
audited candidate tree:      346c9ba3eb141ada18d4ee1589a725919b349351
```

The implementation branch was retargeted to that canonical merge, and
deterministic generation plus all gates below were rerun. This ancestry fact
does not promote any backfill, production, or readiness claim.

## Bound parent contracts and code

Before reconstructing the legacy WAT, the verifier requires exact bytes and
reruns each applicable parent:

| Input | SHA-256 |
|---|---|
| Factory effects contract | `f737d67550721ed418d8b5fb83424a55e429dceea7596643c69748458c5ac892` |
| Factory effects verifier | `547cd30d69cf8a149d50b7e35accda423dbec123e1b61bb73d7371bd16d45ee0` |
| modern Factory static contract | `c5a71b98fc28082aff3dea6b0b22916c86e7efb8ccbec24b2af228948091ed51` |
| modern Factory static verifier | `140d7e5649c03e3f59027ba2c3505196fd98b5a2211868e535e9cd4a32a60eb3` |
| Pool Swap fee-growth contract | `28e12268ebd6ddf78c4d6e59805967793630c6475ca6f0b332fefcf46c5b6b9b` |
| Pool Swap fee-growth verifier | `392fcebecd72abe912af34d256bbc01b42f1ddb4b9b04dab645d6c1669f42932` |
| shared WAT runtime | `bd555b5d44bed144777e35b361fcb63e275d7f21b774db3ffe0e08bef3bf4411` |
| writer compatibility | `259481724561d5aa725c17f90b5a19ea93ad6f7cd6074cf2cb8a8661c39f81c4` |
| field-semantics v2 contract | `0ca8708bd2ed60d4799559d52b3f7e0602abfd7c3edbd35f579476f00baba6ef` |
| segment writer matrix contract | `7f6d1a34a8c885fe5ddcd81895818ba7ae8a0d736d541b881c1cc7cd54275161` |

## Retained artifact authority

WAT is reproduced from the retained deployed WASM with checksum-pinned WABT
1.0.35 `wasm2wat --generate-names`.

| Profile | WASM SHA-256 | WAT SHA-256 | Factory handler SHA-256 |
|---|---|---|---|
| legacy Base root | `0855ce1d5260cd8395628dfac2e18db063909168c58e7d5de118612fee9f9a4e` | `c2e7425784b498481ee8a822be18b59edd7aa6dd27712d8d093696cf0b8b1684` | `8c2c0b729892664f7f57430de9a933ec594899ce14d17a70ad0eee8b28b1c006` |
| legacy mainnet QmRv | `c90c4b86b184d8ffed606f3264d6f3b921421ef7dce2cb35484dd7faaf452cd4` | `4263d51999d58769c06bef6da1aed4c24c1c846f4b0aaed9142bf3bd912ecf9b` | `e28b09377fd2e7fa10dfa0a7afaccd7f120b35d4b9be5f4be6a5c6c819a41f2c` |
| legacy mainnet root | `ab7c84297665ab608ce3c6b8cc71f1c584ae7f2a94ebe674993b069d6b8b5c98` | `1fbcd7b7305dd0e0eb2e9de2e64ecb023e9aa5abe29f7562be4dad72bf561f4d` | `266f6faad4b727316ecdb49a8fd0994fb9f33a0d007dad32c6308a6305529417` |
| legacy mainnet stable | `1bde476d96fd4ba7720246a351c4de0f129693d838f9a39a660097c85d1edead` | `d44ed8c0bbd1bdf62635871b475fbe1a22c8d3a4b88e5d77e6827e3e61b70f81` | `cfaa881acf0c9a45f3f71af203c0587f86bad622083db6c15c2c4f77a8274a09` |

Every legacy handler has 443 instructions, 182 calls, 15 local writes, one
direct heap store, and returns at relative lines 8, 137, and 211. The four
origin slices normalize to
`c8091502d50ab53483cac7a778ffce1c9c05b1280bf7f4c29c59c35aae38cdae`.
The selected setter slices normalize to
`92d6e327b1e98bb4a0889af7f18c4b55d24e1afc6872950df9f52cc91b420605`,
and the setter-through-save slices normalize to
`1e50d552ad313df092f2c6c271ff49eb81ccf17fc14de542d3c64547c8f14b79`.

Normalization strips each instruction, maps `generated/schema/` to
`src/types/schema/`, decodes every static AssemblyScript string pointer, and
replaces only that numeric pointer with `STATIC_STRING_` plus the SHA-256 of
the decoded UTF-8 string. It then joins the normalized lines with one final
newline. Non-decodable constants and all other operands remain unchanged.

The complete legacy global-writer inventory has canonical SHA-256
`2d6aeacb9c69e6e4d68a641f6abe75359df13f1003db16e6ae6bd2910d45b9bf`.
Its parser admits the terminal WAT form `global.set $gN)`; this retains the
native-start `$g10` write, `memory.reset` `$g1` write, and terminal constant
writers that a strict line-equality matcher would omit.

## Deterministic and adversarial checks

`--write-contract` recomputes the JSON from the retained artifacts and bound
parents; normal verification demands byte-for-byte canonical equality and a
strict duplicate-key-free JSON parse. The focused suite contains 53 tests.
Its valid WAT fixtures round-trip through `wat2wasm --debug-names` before they
must fail in their intended layer.

Mutation coverage includes artifact and parent drift; receiver origin; decoded
keys; `$g2`, zero, wrapper kind, and payload; native start and second/reset
writers; inserted return/control/reassignment/overwrite; Pool save receiver,
target, ID and traps; outer TypedMap update-store/constructor/push-call
operands; early returns; static
array and `totalSupply` residuals; reachable body/effect inventories; segment,
field and diff omissions; truth-gate promotion; stale canonical JSON; and
duplicate JSON keys. Inner TypedMap search/entry/push/backing semantics and
fresh Value allocation are explicit false boundaries, not mutation-proof
claims.

Reproduce locally with:

```bash
python3 scripts/verify-uniswap-v3-factory-fee-growth-init.py \
  --wasm2wat /opt/homebrew/bin/wasm2wat --write-contract
python3 scripts/verify-uniswap-v3-factory-fee-growth-init.py \
  --wasm2wat /opt/homebrew/bin/wasm2wat
python3 -m unittest scripts.tests.test_uniswap_v3_factory_fee_growth_init
```
