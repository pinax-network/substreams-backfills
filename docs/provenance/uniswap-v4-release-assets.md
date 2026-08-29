# Uniswap V4 historical release-asset mirror

The v0.1.0 event package and v0.4.1 NUL-metadata audit package were published as
GitHub release assets but were not tracked in the v0.4.1 source tree. This repository
retains exact byte copies so a future source-repository archive cannot remove the inputs
needed to inspect or reproduce the active backfill.

The machine-readable lock is
[`uniswap-v4-release-assets-v1.json`](uniswap-v4-release-assets-v1.json). CI rejects a
changed path, source release identity, size, checksum, missing asset, or unlisted package.
Run:

```sh
python3 scripts/verify-uniswap-v4-release-assets.py
```

## Preserved packages

| Source release | Package | Bytes | SHA-256 |
|---|---|---:|---|
| `v0.1.0` | `uniswap-v4-base-backfill-v0.1.0.spkg` | 442,378 | `75b810d18ec1dc78ca5535b2cc56828334c873b93d39500f93ca036499048453` |
| `v0.4.1` | `uniswap-v4-base-nul-metadata-audit-v0.1.0.spkg` | 1,534,793 | `c2470ab845cebc929aa20489a21114cb9db891aef9ad99559c97757b1938e81a` |

This mirror completes only the historical-package preservation gate. The source releases
remain canonical historical URLs, active consumers may still depend on the source
repository, no new release has been proven from this repository, and future-release
authority has not transferred.
