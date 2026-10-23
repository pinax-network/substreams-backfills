# Q-N2 early-history diagnostic evidence

The optimized diagnostic at source commit
`93fae41c8aaac5549af567390878f42a52bc340e` scanned the retained M2 canonical
ExtractorBlock input over **13,843,704 through 13,919,662 inclusive**. All 75,959
observed blocks and the actual input EOF matched the externally pinned range,
parent/head hashes, 18,286,956 bytes and SHA-256. It decoded 3,014 Swaps containing
3,014 negative amounts and found **zero potential zero-decimal strict-v1
refusals**. The debug and optimized reports are byte-identical.

This result covers the retained early-history input only. It does not establish
full-range Q-N2 closure, live database history or retention, package origin,
producer completion, stored Token decimals, or committed handler provenance.
The report deliberately keeps `full_range_qn2_closed: false`. No production SQL
was executed and no numeric admission contract changed.

## Retained artifacts

`request.json` and `report.json` preserve the exact invocation and report bytes.
`summary.json` binds those files, the source commit/tree, the actual Darwin arm64
optimized executable and exit status, local origin receipts, validation logs,
and the first attempts. The binary SHA-256 is
`e8a3343e3445cbc0d2ca3c5f323a0f089dc8cfdf154255b8a61fc02ea29137cc`;
the report SHA-256 is
`c8d00efe0c7a69eda0b04daa82fdca89922a913f6117abe8992feb9df44096ca`.
Local `/private/tmp` and `/tmp` paths are evidence pointers, not portable
downloads or a release archive. This is host execution evidence, not OCI or
production qualification.

To reproduce, build `aerodrome-decimal-audit` from the pinned source and obtain
the exact retained input identified by the request. With the original absolute
input path intact:

```sh
target/release/aerodrome-decimal-audit extractor \
  fixtures/aerodrome-qn2-early-history-v1/request.json \
  b4309d7be82835aa5d13add1c497a5ff99b89eb1cd7c898d9bca463c6066ac66
```

If the input moves, create and independently pin a new request; do not claim its
request/report bytes match this invocation.

## Validation and retained correction

The final source passed formatting, 816 workspace tests (one default ignored),
strict workspace Clippy, all 16 `xtask verify-all` checks, the optimized build,
seven focused portable diagnostic groups, and the explicit owned PostgreSQL 16
test. Independent review closed after the SQL correction below. The full gates
are tied to the source commit above; this evidence-only follow-up was checked
for JSON validity, exact hashes and unchanged source bytes.

The first synthetic PostgreSQL fixture used logical `amount0`/`amount1` as SQL
column names and mirrored the same mistake in the query. Its green result
proved only that synthetic shape. Independent review found that actual Graph
Node columns are `amount_0`/`amount_1`. The final query uses those physical names,
and the fixture executes an exact retained Graph Node-produced Swap DDL slice
with a separately pinned complete logical-to-physical field mapping. Independent
comparison against engine commit
`e4580444c56d6fcc778cb50394a9a693823457eb` and the corrected PostgreSQL test both
passed. The earlier log remains identified in `summary.json`.

The first broad workspace attempt also lacked ignored archived baseline
fixtures. Only local bytes matching the committed evidence locks were hydrated
before the final successful run. No failed attempt was overwritten.
