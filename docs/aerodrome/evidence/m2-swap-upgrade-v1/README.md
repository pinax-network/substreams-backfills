# Live Swap call-completeness correction

The fresh development package passed the complete historical range
`[13,843,704, 13,919,663)` on 2026-10-22. Its 75,959 live WASM outputs contain
all 9,394 independently recorded Graph Node calls. The strengthened native
reducer matches all 90,966 Graph Node operations and 13 source creations;
only `compatibility_id` is masked. This is bounded historical M2 evidence,
not production runtime, durable restart, seed capture, or landing qualification.

[proof.json](proof.json) pins the actual runtime sources, package/module,
descriptor, executables, inputs, outputs, counts and retained artifact inventory.
The inventory references local artifacts that have **not** been published as a
release. This compact committed record is not a substitute for those artifacts.
[audit.rs](audit.rs) preserves the exact read-only G4 harness used; its source hash
matches the record. The native archive comparator's existing consumed-field masks
are unchanged, every cassette key is required, and the harness does not inject
answers into live frames. It validates the full canonical input, parent chain,
requested range, digest and EOF independently of reducer success.

## Why the previous run failed

The deployed Swap handler upgrades a zero-version token by calling
`getPool(USDC, token, 100/500/3000/10000)`, excluding USDC itself. Its later array
pushes affect a discarded getter copy, but the four host calls still require
answers. The old package omitted them and the old native handler skipped their
lookups. That combination passed frame parity while failing G4 with 44 missing
calls across 11 blocks (9,350 matched, zero wrong). The failed attempt is retained
and identified in the record; it is not reclassified as a success.

Runtime source `5e65aa2226dbcb42ae25e8784af989327967e1e6` now derives a conservative
probe set for both registered pool tokens on each decoded Swap. It reads the
end-of-block registry, unions/deduplicates keys with NPM getPool queries, and uses
the existing zero-address/provenance rules. No cassette query determines live
probe selection. The shared pure helper preserves the mapping's literal third
arguments and argument order. The strengthened reducer at
`3ae00fe968a99339aa680eed5ef7d39d78c99638` performs the exact required lookups and
refuses each independently tested missing answer.

The source regression retains all 44 actual missing cassette calls and 13 actual
PoolCreated candidates in
[swap-upgrade-calls.json](../../../../aerodrome-slipstream-base/substreams/fixtures/swap-upgrade-calls.json).
It reconstructs registry state from those candidate logs, including the nonzero
pool result. Its synthetic Swap host setup checks answer selection and values;
the separate fresh live run supplies historical end-to-end evidence.

## Evidence sequence

1. All 46 family tests, strict Clippy and protobuf regeneration checks passed.
   Four WASMs matched across two independent source/target roots. The existing
   cache-boundary test verified all 34 modules and isolated RPC imports.
2. Package `7df52603a63b261ed27faf5f27a0b178b2004e156829c6c0edc1b3d605b4ff59`,
   output module `5b880ad140246ec1bc3eefdd64c287769deac4f8`, ran through the
   frozen native transport with final blocks, no retries, a bounded processed-block
   budget and explicit empty-frame inclusion. Actual process exit was zero.
3. Every output frame was Observed, nonempty and contiguous. The recorded output
   digest is `1444ef8a9ac545e7358d7b7b3396131783d221cf38936a407562828d55a98fde`.
   The G4 audit found 9,394 matched calls, zero missing and zero wrong.
4. The isolated, frozen strengthened reducer ran fail-closed and completed all
   6,089 handlers, including 3,014 actual Swaps. Whole-envelope comparison against
   the frozen Graph Node oracle passed all 75,959 blocks. Its output digest is
   `c02895a54189f979f5e136e1e5d450ba444600cb7f24ad3a6dfc26a408583ffd`.
   Capture, audit, replay and comparator each returned actual exit zero.

The separately retained M1 raw-Firehose/native-reference proof also passed the
complete range. Its reference path explicitly supplemented getPool query keys,
so M1 could not clear the former live WASM coverage gap. The two paths remain
separately identified in `proof.json`.

## Rechecking

Check every retained artifact against the inventory before reuse. Build extractor
runtime **5e65aa2**, not an evidence-only descendant whose package documentation
may differ, using the recorded `cargo xtask aerodrome-substreams build --twice`
and `cache-boundary` route. Build the replay/comparator from **3ae00fe** in an
isolated checkout. The retained `capture.py`, `check.py`, `commands.json`,
`extractor-identity.json` and descriptor contain the exact commands and binding;
none contains credentials. The G4 harness can be built as a temporary example of
the reducer package at **5e65aa2** with `reference-extractor` enabled. Its invocation
requires input SHA, cassette, descriptor, extractor identity and descriptor SHA.
A fresh rerun needs the existing private Substreams authentication in the process
environment. Never promote a partial capture, fill missing frames, inject missing
call answers, or broaden comparison masks to make the gate pass.
