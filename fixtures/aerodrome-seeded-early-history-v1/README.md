# Twenty seeded early-history windows

The development proof replays twenty 1,000-block windows through real
`substreams-native` and the frozen public producer, starting each process pair
from an actual E5 Oracle snapshot. All twenty pairs exited successfully. Each
window matched the independent mapping-host whole-frame reference (only
`compatibility_id` masked), every triggered Fast PoI, every producer cached
entity, the producer's exhaustive state digest, and the final SQL-visible
entity/source state.

The windows requested 20,000 blocks, covering 19,000 distinct blocks. They cover
13 pool creations, 3,316 Swap invocations, Mint/Burn/Collect and position events,
and a day boundary. Counts include the deliberately overlapping day-boundary
window. They contain no Flash events. This is **early-history hermetic
integration**, not the stratified M4 gate or production qualification.

The source database was reconstructed in a fresh Unix-only PostgreSQL16
cluster from the retained, independently matched root history. Its three SQL
query outputs exactly matched the earlier physical-encoding proof. Only after
that comparison, the harness inserted minimal **synthetic** Graph Node
registry/health metadata. Those rows are fixture setup, not captured evidence
about a deployed registry, stopped writer, current health, history policy or
creating Graph Node binary. The profile remains a non-production hermetic
profile; its unresolved image placeholders are not actual image identities.
No live source database was read or modified.

The twenty imports use public `producer seed --from`, actual typed capture
manifests, pinned capture bindings and snapshot-derived initial lineages.
Oracle purpose remains sticky/nonloadable. Every replay obtains fresh native
bytes and a real native exit before private upstream completion is sent. The
archived stream is used only as a comparison reference. There is no engine
spool READY, production receipt, image qualification, physical loader commit,
Graph Node restart or lifecycle claim.

The independent engine helper restores only bounded memory state from the
actual Oracle snapshot. It reopens the producer redb **read-only**, checks its
committed checkpoint, recomputes its full logical digest and compares every
cached field to independent replay. The separate SQL reload comparison omits
explicit Null fields because Graph Node SQL reads omit NULL columns; neither
frames nor PoI are normalized. No such projection was needed in these twenty
windows (`sql_null_projection_fields = 0`).

`summary.json` pins the local proof, exact executable/runtime identities,
per-window receipts and helper source. The full retained evidence is under
`/private/tmp/aerodrome-seeded-early-history-v2`. Inputs were pinned before
creating the owned database. Original files/database were untouched. The helper
source lives in the separately reviewed engine change
`examples/aerodrome-oracle-comparison.rs`, based on engine commit `e458044`.
The source-side harness is `scripts/aerodrome-seeded-oracle.py`.

Three failed attempts remain in the evidence:

- A harness descriptor sidecar filename mismatch stopped before connecting.
- The first populated E5 snapshot exposed noncanonical zero encoding. The
  original capture binary remains pinned; the reviewed successor changes only
  canonical BigInt/BigDecimal zero bytes, retaining strict raw numeric text
  validation. Actual populated capture was repeated with that successor.
- The first completion used JSON object order from the seed result wrapper.
  The native process exited 0 and producer refused exit 4. Reopening the
  public producer with `inspect` supplies the canonical typed checkpoint
  order. A fresh actual native attempt then succeeded without producer edits.

Six isolated Python guard tests and twelve actual helper refusal probes cover
the proof boundaries.
The latter cover wrong digest, truncated/trailing snapshot, truncated frame,
symlink input, existing-result refusal and descriptor retention/type/deployment
binding mutations, oversized plans/inputs and FIFO input. They verify the
producer redb bytes remain unchanged. Failed evidence is never promoted into a successful receipt.

Review strengthened the helper descriptor binding and bounded file reader, and
the harness rejects reused results with another plan/window, broader masks or
missing success/scope fields. The final reviewed comparison outputs and source
identities are retained separately from the initial successful runs and initial
input-manifest script pin. The native requests are not repeated for this
read-only review pass.
