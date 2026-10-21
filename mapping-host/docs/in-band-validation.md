# In-band oracle validation status

The C2 implementation adds the separate v2 envelope, capability-gated source
creations, mapping-host producer identity, shared operation builder/BCF1 adapter,
and an oracle comparison tool. Frozen v1 schema and binding bytes are unchanged.

Local checks on 2026-10-21:

- `cargo test --workspace --locked --offline`: 689 passed.
- `cargo test --manifest-path mapping-host/Cargo.toml --locked --offline`:
  219 passed, one pre-existing real-corpus test ignored.
- Strict clippy passed for the workspace and all mapping-host targets.
- `cargo xtask verify-all`: 16/16 checks passed after locked evidence hydration.
- `python3 -m unittest discover -s mapping-host/runtime -p 'test_*.py'`:
  25 passed. The committed context includes the new build script and verifies
  complete optional in-band descriptor pairs.
- Seven in-band host regressions cover real first-pool oracle equality,
  compiled-source and output-type refusal, stale-source generation refusal,
  failed creator groups, fatal host rollback, and duplicate requests across
  hosts/waves. Synthetic error cases are scheduling regressions, not deployed
  observations. Common tests additionally cover noncanonical wire data,
  capability/ordinal/template/context/error-policy refusal and exact v1 bytes.

The generated Aerodrome descriptor is
`2567c0bb63a8b09df4b8943ab4eae3fd6ae2e9592caa64faa722a37decd74357`.
Its compiled source closure is
`f3edab9536ae8cd3e75e66c786cfc3d7f7935a38e3b1bf50e17ca05574f1ff32`;
its deployed bundle lock is
`d6f3dfe7f84145a5140d9c8f3e106f1ffbe74f05d02b29847917eeb2fa51725e`.

Fresh R0 `[13843704,13899663)` and R1 `[13899663,13919663)` replay
completed: **75,959 observed blocks**, using the copied dev-profile binary from
source commit `251f63c4e7d1e30b22a4e341462621dac77b3675`. Recording was disabled;
the cassette bytes are unchanged. R1 resumed from the exact closed R0 checkpoint
`e10ddb633ba47add9d888b6b6ca07d485b0f4f9089559a1a1a908d6cd73de0fc`.
The independently exported committed build context regenerated the identical
descriptor. Later workflow, verifier and documentation commits are outside the
compiled producer closure.

Every frame's exact v1 projection and every semantic report field, including
PoI, matched the retained v1 evidence. Closing rows match in entity identity,
causality region, VID and fields; cached-absence entries and the ordered runtime
source inventory also match. The complete final store is byte-identical:
35,906,547 bytes, SHA-256
`8318a8342dcc2f8bd48fc7793b304085b15216b60a3d74b687819a6a77f3d8b0`.
It contains 10,213 entities and one PoI row. The final public PoI at block
13,919,660 is
`f1d57922f8f46f89257f4f73d052c2e18387cf8ad185202b4a8b3bdfb62c0245`.
The 13 accepted creations match the retained runtime inventory and produce
source-order commitment
`4cbe5492b944cf3b9e56484fe56abbd99e3af3bee846f171c03559fc011af03c`.
No pre-existing Aerodrome source-v2 chunk artifact was located; this comparison
does not claim to compare such a chunk.

The original verifier failed on whole checkpoint-row equality: **779 cache
residency flags differ**, with 387 keys cached only in the legacy checkpoint and
392 only in the in-band checkpoint. This failure is preserved in the receipt
and continuation archive. The corrected verifier compares all materialized row
fields exactly and reports residency separately. Two focused tests prove that
identity, VID, value, row-count and explicit-Null-versus-absent mutations are
still refused; its release build and strict clippy passed.

The statement in `src/checkpoint.rs` that this host never calls LFU eviction is
incorrect. Pinned Graph Node `EntityCache::as_modifications` calls
`evict_and_stats` after applying updates. Updates iterate a randomized `HashMap`,
and equal LFU priorities have no entity-key tie-breaker. At the default 10 MB
limit, separate processes can retain different equally-used rows. Restore
rebuilds every cache entry from the identical materialized store, preserving
Null fields. Every Aerodrome entity type is mutable, so cache misses reload the
store before modifications. Immutable schemas could expose different
Insert/Overwrite behavior; full continuation-checkpoint equality is not claimed.
The source comment remains unchanged in this frozen producer; this paragraph
corrects its claim without silently changing the recorded source closure.

A separate bounded continuation resumed both closing checkpoints through
`[13919663,13919683)`: **20 blocks and 11 handler groups**. The original locked
cassette attempts both refused the same missing call at block 13,919,667.
Separate cassette copies then recorded 18 new calls using the previously
configured Base archive RPC, pinned by block hash. Both processes exited zero,
the resulting cassettes are byte-identical, and canonical frames, semantic
reports, PoI and materialized rows match. Both final stores have SHA-256
`d461ac80445763e03c18dc2e0b35a0707a492d308d431fe47fbf3faf0c8e7611`.
The same 779 residency differences persist. This establishes that observed
continuation, not arbitrary future equivalence.

The [receipt](../evidence/aerodrome-in-band-oracle-v1.json) records exact binary,
source, verifier and input pins. Separate [R0](../evidence/aerodrome-in-band-r0-comparison.json),
[R1](../evidence/aerodrome-in-band-r1-comparison.json) and
[continuation](../evidence/aerodrome-in-band-continuation-comparison.json)
comparisons retain the source order and checkpoint bindings. The
[evidence lock](../evidence/aerodrome-in-band-oracle-v1.lock.json) contains seven
main replay assets and one deterministic continuation archive containing raw
frames, reports, checkpoints, stores, the extended cassette, descriptors and a
per-file manifest. All eight assets are published in the immutable
[`aerodrome-in-band-oracle-v1` release](https://github.com/pinax-network/substreams-backfills/releases/tag/aerodrome-in-band-oracle-v1),
which targets frozen producer `251f63c`. A fresh-cache download verified all
301,844,726 bytes against the lock; the committed round-trip receipt retains
every asset hash. The existing v1 releases are unchanged.

For offline verification after hydrating the old and new evidence locks, run
`cargo run --release --manifest-path mapping-host/Cargo.toml --locked --offline
--example verify_in_band_oracle --` followed by the two descriptor paths,
legacy/new BCF1 paths, legacy/new report paths and new/legacy closing checkpoint
paths, in that order. For continuation, extract the archive and append the main
R1 in-band checkpoint as the ninth argument. The verifier then checks inherited
sources, the first parent hash and the closing checkpoint's predecessor hash.

No candidate OCI image was built: the local Docker daemon's `/info` request
returned HTTP 500. No deployed indexer parity or production run is implied.
