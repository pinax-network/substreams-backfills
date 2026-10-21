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

Fresh R0 `[13843704,13899663)` and R1 `[13899663,13919663)` replay is **pending**.
The run uses copied binaries, recording disabled, the existing hash-locked
cassette, and the authorized Base Firehose endpoint. R1 must start from the
closed R0 checkpoint only after complete R0 verification. Acceptance requires
every frame's exact v1 projection, every semantic report field including PoI,
closing materialized checkpoint rows, and ordered runtime source inventory to
match retained v1 evidence. A follow-up receipt must record actual completed
ranges and artifact pins; this code commit does not claim that gate passed.
No pre-existing Aerodrome source-v2 chunk artifact was located. The verifier
computes the existing source-v2 order commitment from in-band creations and
checks the retained runtime inventory, without claiming a chunk comparison.

No candidate OCI image was built: the local Docker daemon's `/info` request
returned HTTP 500. No release, indexer parity or production run is implied.
