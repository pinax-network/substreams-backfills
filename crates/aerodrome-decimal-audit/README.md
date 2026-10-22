# Aerodrome Q-N2 decimal diagnostics

This offline tool identifies the remaining R-7/Q-N2 numeric boundary without
changing the common validator, mapping host, reducer or engine. It has no network
client, database connection, or production mutation path.

For a token recorded with zero decimals, `convertTokenToDecimal` returns raw
`BigInt.toBigDecimal()`. Saving `Swap.amount0/1` crosses Graph Node's decimal
boundary once, `n(raw)`. Some negative values are not fixed points of `n` and
remain deliberately refused by BlockChanges v1. The smallest raw negative
magnitude that can reach this case is `2^116 * 1000`:
`83076749736557242056487941267521536000`. A magnitude test alone is insufficient:
many larger values, such as negative powers of ten, are fixed points.

`extractor` uses the reducer's existing canonical ExtractorBlock validator and
locked event decoder, then classifies each negative Swap amount with the actual
`graph-numerics` single-crossing constructor and strict wire encoder. It requires
the inclusive requested observed range, every parent/hash link, actual EOF, and
the externally supplied full input byte count and SHA-256. A malformed suffix,
synthetic fill, short range, unknown protobuf fields or pin mismatch refuses the
entire report. It never emits a successful partial report.

Each potential refusal remains explicitly conditional on **the mapping's stored
token decimals being zero**. Extractor candidates do not establish committed
host admission, handler success, or historical Token metadata. Neither current
ERC20 RPC answers nor caller-supplied decimals are silently treated as that
evidence. Witnesses therefore say `unresolved_mapping_token_decimals` and
`extractor_candidate_only`. A later investigation can resolve them against the
actual seed/entity history and handler outcome. An empty candidate set rules out
this raw Swap mechanism only for the supplied, structurally validated input;
package origin and producer exit are still independent evidence.

`saved` parses exact PostgreSQL numeric text without `from_db_text` or another
Graph Node normalization. It strips only decimal trailing zeroes and checks the
resulting exact coefficient/scale tuple. Thus a persisted value such as
`-85070591730234615865843651857942052000.000` is reported with coefficient
`-85070591730234615865843651857942052`, scale `-3`, and strict-v1 refusal. Applying
Graph Node normalization before this check would erase the finding.

## CLI and bounds

Build with `cargo build --locked --release -p aerodrome-decimal-audit`. Each mode
takes a request file and its independently computed lowercase SHA-256:

```sh
target/release/aerodrome-decimal-audit extractor request.json REQUEST_SHA256
target/release/aerodrome-decimal-audit saved saved-request.json REQUEST_SHA256
target/release/aerodrome-decimal-audit sql page.json REQUEST_SHA256
```

The two scan modes print their JSON report only after all checks succeed. The
`sql` mode prints a read-only query plan; it does not execute it. Request files
are at most 64 KiB. Unix file admission rejects symlinks and nonregular files
without blocking on FIFOs. Input paths in scan requests must be absolute.

Extractor requests use these exact fields:

```json
{
  "format": "pinax.aerodrome.qn2-extractor-request/v1",
  "input": "/evidence/extractor.bcf1",
  "input_sha256": "<exact input SHA-256>",
  "input_bytes": 18286956,
  "from_block": 13843704,
  "to_block": 13919662,
  "parent_hash": "<observed predecessor hash>",
  "head_hash": "<observed final hash>"
}
```

The range is inclusive and capped at 100,000 blocks, the file at 2 GiB and each
payload at 16 MiB. At most 64 witnesses are retained in the report; every witness
(including omitted ones) contributes to the ordered JSON-lines inventory hash.
Counts and the inventory commitment therefore cover the whole successful scan.

## Bounded read-only SQL pages

A page request has exactly:

```json
{
  "format": "pinax.aerodrome.qn2-sql-page/v1",
  "schema": "sgd2",
  "min_vid": -1,
  "max_vid": 9999,
  "from_block": 13843704,
  "to_block": 13919662,
  "max_rows": 10000
}
```

Only `sgd` plus decimal digits is accepted as the schema identifier. The VID
interval spans at most 1,000,001 possible IDs; the block interval is bounded as
above. The generated query uses `BEGIN READ ONLY`, a five-second statement
timeout, one-second lock timeout, both intervals, ordered VIDs, `LIMIT max_rows+1`
and `ROLLBACK`. `max_rows` is at most 10,000. These bounds include the work/output
failure paths; a large or slow page must be narrowed rather than retried without
limits. Source identity, history retention and the approved seed boundary must
be checked independently before using any real source.

The query uses Graph Node's physical `amount_0` and `amount_1` columns and emits
the logical `amount0` and `amount1` JSON fields. The retained Graph Node-produced
Swap DDL and field mapping in `fixtures/` independently bind this distinction.
The query selects **all saved Swap versions whose lower block boundary lies in
the requested interval**, including closed history. It does not normalize or
prefilter the amounts. Execute an approved plan with psql's no-rc, quiet,
tuples-only, unaligned mode and `ON_ERROR_STOP=1` to retain one JSON object per
line. Do not concatenate command-status output or retry over an existing proof.
No database password, DSN or routing value belongs in the report.

A saved scan request contains `format: pinax.aerodrome.qn2-saved-request/v1`,
`page` (the complete page object), and `input`, `input_sha256`, `input_bytes`.
The exact exported JSONL is capped at 64 MiB and each row at 64 KiB. Rows must have
the unique ascending `vid`, `id`, `block_start`, `amount0`, `amount1` fields and
lie within the page. A `max_rows+1` result refuses as saturated. Negative VIDs
are supported. Numeric cells are bounded at 16 KiB; NaN, infinity, exponent-form
and malformed text refuse. Missing or pruned history is never inferred absent.

Both reports unconditionally retain `full_range_qn2_closed: false`. Saved reports
also retain `query_execution_verified: false` and
`source_database_identity_verified: false`: pinned local bytes alone cannot
establish those facts. Full Q-N2 closure requires externally verified complete
history through the seed, complete extractor coverage over the intended
backfill range, and resolution of every potential zero-decimal witness. An
early-history scan cannot close that gate. Any numeric contract carve-out remains
a separate coordinated change after reachable evidence is established.

## Validation

Portable tests exercise the exact threshold and neighbors, larger fixed points,
shared Swap ABI decoding, bounded witness commitments, malformed/short/extra
frames, pins, SQL identifier/range guards, exact saved non-fixed points, saturated
pages and actual CLI FIFO/symlink refusal.

The explicit PostgreSQL 16 test creates its own new Unix-socket cluster with
ambient routing/credentials cleared, executes the retained Graph Node-generated
Swap table DDL, runs the generated read-only query over synthetic history, and
checks the preserved numeric tuple:

```sh
PG16_BIN=/path/to/postgresql16/bin cargo test --locked \
  -p aerodrome-decimal-audit --test saved_postgres -- --ignored --test-threads=1
```

This fixture is a codec/query test, not a live deployment observation.
