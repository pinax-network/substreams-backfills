# uniswap-v4 (port target — M5)

Ported from [`substreams-v4-subgraph`](https://github.com/pinax-network/substreams-v4-subgraph)
AFTER the active univ4base backfill completes a committed segment — the owning agent's safety
contract governs timing (restart only at a committed segment with the loader stopped, then
writer-exclusion checks). The old repo stays authoritative for the running pipeline and is
frozen/archived only once this port reproduces a committed segment byte-for-byte.

NOTE: `postgres-nul-truncate-v1` activation approval (substreams-v4-subgraph#22) belongs to
the running pipeline and does not transfer implicitly to this port.
