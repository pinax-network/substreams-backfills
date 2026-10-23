# Bounded Aerodrome archive-call cassette preparation

This native development tool prepares the replay-only cassette required **before**
an expensive disk-backed mapping-host seed import. It reads a complete, pinned
ExtractorBlock BCF1 window and independently obtains every supplied call answer
from an archive RPC. It never substitutes extractor answer bytes for RPC results.
No live RPC capture is part of the checked-in test evidence.

The output uses `pinax.substreams-backfills.mapping-host.cassette/v1`, with exact
keys `(block_hash, address, calldata)`. Calls are sequential, with a minimum
interval, per-request deadline and total RPC-phase deadline. There are no retries.

## Invocation and request

Build with `cargo build --locked -p aerodrome-call-cassette --release`. Supply an
authorized HTTPS archive endpoint privately as `BASE_ARCHIVE_RPC_URL`. Its value
is never a command-line argument, receipt field or diagnostic. Run:

```text
target/release/aerodrome-call-cassette \
  --request /absolute/canonical/request.json \
  --request-sha256 EXACT_RAW_REQUEST_SHA256 \
  --output /absolute/canonical/NEW_ATTEMPT_DIRECTORY
```

The request is ordinary strict JSON (unknown and duplicate fields refuse), with
these fields:

```json
{
  "format": "pinax.aerodrome.call-cassette-request/v1",
  "input": {"path": "/absolute/input.bcf1", "bytes": 1, "sha256": "EXACT_SHA256"},
  "descriptor": {"path": "/absolute/descriptor.json", "bytes": 1, "sha256": "EXACT_SHA256"},
  "extractor": {
    "spkg_sha256": "EXACT_PACKAGE_SHA256",
    "module": "map_extractor_block",
    "module_hash": "EXACT_MODULE_SHA1",
    "output_type": "proto:pinax.aerodrome.slipstream.base.v1.ExtractorBlock",
    "initial_block": 13843704
  },
  "from_block": 13903663,
  "to_exclusive": 13904663,
  "parent_hash": "EXACT_PARENT_HASH_WITHOUT_0x",
  "head_hash": "EXACT_LAST_BLOCK_HASH_WITHOUT_0x",
  "rpc_timeout_seconds": 30,
  "total_timeout_seconds": 3600,
  "minimum_interval_ms": 100
}
```

The illustrative pins/byte counts above are deliberately unusable. Use the exact
current descriptor/extractor identity, actual input and observed boundaries. The
descriptor must match the reviewed reducer contract. All paths must be absolute,
with canonical parents; final symlinks, FIFOs and other nonregular files refuse.
Exit 0 means this attempt completed; refusal exits 4. Preserve failed attempt
directories and use a new directory for a retry.

## Validation and evidence

Before any RPC, the tool validates the entire input through true EOF: raw size
and SHA256, observed contiguous clocks, nonzero hashes, parent links, canonical
protobuf, extractor version/identity, candidate ABI and call-answer/anomaly
contracts. Duplicate actual keys refuse before network access. Locally derivable
mandatory calls are checked for PoolCreated token metadata, Swap/Flash fee
growth, Mint/Burn endpoint ticks, NPM positions, and successful-position getPool.

It checks `eth_chainId == 8453`, then obtains each block's canonical identity by
number before and after its calls (including empty blocks). Calls use the reused
audit request codec: EIP-1898 `blockHash` plus `requireCanonical: true`, and exact
50,000,000 gas. Every JSON-RPC response requires the matching version and ID and
exactly one nonnull result/error arm. Provider failures refuse; only the existing
conservative audit revert rules produce mapping-host Null. Full successful return
bytes remain in the cassette, including ABI words the extractor does not consume.
Exact call-response bytes, including explicit revert data, are hex-encoded in the
bounded observations. Treat those raw provider responses as potentially sensitive
evidence; they are not printed in diagnostics.

The fresh evidence directory is created mode 0700 and files mode 0600 (a stricter
caller umask may further restrict them). Output files:

- `request.json`: exact externally pinned request bytes.
- `inventory.json`: supplied keys and mapping contract/function labels.
- `observations.jsonl`: requests, exact raw RPC response bytes, decoded complete
  return/revert and consumed-field comparison outcome.
- `archive-blocks.json`: before/after canonical block/hash/parent proofs.
- `cassette.json`: sorted unique replay keys and independent complete results.
- `complete.json`: all artifact pins, range, boundaries, counts, executing binary
  digest and explicit scope flags; published last and directory-fsynced.
- `.partial` files and `failure.json`: retained attempt evidence. No cassette or
  completion is published after a partial/mismatching RPC audit. Late filesystem
  failures can retain already completed audit bytes; process success is still
  separately required by the caller.

## Bounds and authority

Limits are 1,000 blocks, 2 GiB input, 16 MiB/frame, 100,000 calls, 64 MiB retained
inventory budget and cassette, 4 MiB/RPC response, 128 MiB observations and one
concurrent RPC. Request JSON is at most 64 KiB, descriptor 4 MiB, generated RPC
request 4 KiB. Serialization and reads enforce bounds before unbounded allocation.
Each RPC deadline is 1–30 seconds; total RPC time is 1–86,400 seconds; minimum
interval is 1–1,000 ms. HTTPS redirects refuse. DNS resolution also has a deadline;
a DNS timeout aborts the CLI without retries, and a still-blocked OS resolver
thread lives only until that process exits.

`proves_completeness` remains **false**. Historical Swap tick walks and versioned
token probes depend on authenticated extractor carry/seed state. This tool neither
proves that supplied inventory is complete nor authenticates a native process exit or
SPKG origin; the caller must retain those independent execution artifacts and
match the same inclusive block/hash window to the raw Firehose oracle input.
The disk oracle must still fail closed on any cassette miss. Completing this
capture does not qualify a seed, image, canary, production load or full-range
numeric semantics. The receipt binds the actual executable hash; its source/build
provenance must be independently reviewed.

## Tests

`cargo test --locked -p aerodrome-call-cassette` uses a local deterministic
transport and retained independently captured first-pool raw returns. It covers
full unconsumed ABI words, explicit reverts/empty returns, stable key order,
canonical archive checks for empty blocks, malformed/truncated input, duplicate
keys/JSON arms, changed identities/parents, missing calls/results, RPC deadline and
size bounds, generic provider failures, FIFO/symlink refusal, output no-clobber and
actual CLI diagnostic sanitization. It makes no live network requests.
