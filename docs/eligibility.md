# Graph Node catch-up eligibility

Backfill engineering starts only when the fastest healthy native Graph Node
path is projected to take **more than 28 days** to reach chain head. This gate
is independent of query fees and market priority: QoS decides which eligible
target is most valuable, never whether a backfill is necessary.

## Market-priority metadata

When a binding retains Gateway QoS, `market_snapshot` is the only accepted
machine-readable shape. It records the exact payload time, integer 24-hour
query count, precision-preserving string value for 24-hour Gateway query fees,
and the repository issue that retains the source evidence:

```yaml
market_snapshot:
  measured_at: "2026-08-31T17:20:00Z"
  queries_24h: 386433
  query_fees_grt_24h: "471.970"
  authority: https://github.com/pinax-network/substreams-backfills/issues/83
```

If the payload timestamp, aggregation window, or authority was not retained,
the binding omits `market_snapshot`; an old estimate must not be relabeled as a
current measurement. The validator rejects the ambiguous legacy fields
`market_qpd`, `qos_snapshot_at`, and `signal_grt`. Gateway query fees are not
on-chain signal; separately sourced signal metadata needs its own explicit
contract and must never be inferred from QoS.

The versioned policy is
[`eligibility/policy-v1.yaml`](../eligibility/policy-v1.yaml). Target and
evidence shapes are documented by the JSON Schemas under [`schemas/`](../schemas/)
and enforced by `scripts/validate-targets.py`.

## Calculation

For both 24-hour and 72-hour windows, using the same requested start and end
times for the deployment and chain:

```text
deployment_delta = deployment_end - deployment_start
chain_delta      = chain_end - chain_start
net_delta        = deployment_delta - chain_delta
lag              = max(chain_end - deployment_end, 0)

net_rate_blocks_per_day = net_delta * 86400 / duration_seconds

if net_delta <= 0:
    ETA = infinite
else:
    ETA_days = lag / net_rate_blocks_per_day
```

The validator compares the threshold without floating-point arithmetic:

```text
ETA > 28 days
iff
lag * duration_seconds > 28 * net_delta * 86400
```

Exactly 28 days does not qualify. A head regression invalidates the evidence;
it is not a non-positive rate.

## Fastest healthy copy rule

Every target covers both `riv-subgraphs-a` and `kan-subgraphs-a`. Evidence must account
for each cluster by recording either:

- every current copy of the deployment; or
- read-only proof that no attached version or required graft base exists.

A viable copy is active, attached, healthy, not failed, and currently indexing.
Failed and stopped duplicates never make a target eligible. The target decision
uses the lowest 24-hour ETA and lowest 72-hour ETA across all viable copies;
those minima may belong to different copies.

The canonical Riv identity is the production and VictoriaMetrics label
`riv-subgraphs-a`. Do not substitute the legacy `riv-dev1` name or the
`riv-dev1-sa` kubeconfig context: the latter currently reaches a different
cluster with no subgraph namespaces.

When at least one viable copy exists, fully inventoried failed or stopped copies
in another required cluster are accounted but excluded from the calculation.
They do not require a false missing-version/graft claim and cannot override the
fastest healthy copy. If no viable copy exists anywhere, fresh structural proof
is still required from every cluster before the target can be eligible.

Decision precedence is:

1. Missing-cluster or contradictory identity evidence is `indeterminate`.
2. A fresh, healthy `synced=true` copy is `complete`, even if another duplicate
   has stale or regressed samples.
3. For unsynced copies, stale or regressed required evidence is `indeterminate`.
4. If either fastest window is at or below 28 days, the target is `monitor` and
   native syncing continues.
5. If every viable copy exceeds 28 days in both windows, the target is
   `eligible`. A non-positive rate is an infinite ETA.
6. With no viable copy, `eligible` requires explicit structural proof from
   every cluster. A failed-only inventory is `indeterminate`.

Graph Node's `synced` value is sticky: it proves the deployment reached head at
least once. A later freshness incident belongs to operations and does not
re-open the historical backfill gate automatically.

## Authoritative inputs

Capture current health from Graph Node's read-only `indexingStatuses` API and
historical heads from central VictoriaMetrics. Relevant metrics are:

```promql
deployment_head{
  deployment="Qm...",
  cluster="kan-subgraphs-a",
  namespace=~"subgraphs-.+"
}

ethereum_chain_head_number{
  cluster="kan-subgraphs-a",
  network="base"
}

deployment_synced{deployment="Qm...",cluster="kan-subgraphs-a"}
deployment_status{deployment="Qm...",cluster="kan-subgraphs-a"}
```

Evaluate the head queries at one common UTC `measured_at`, then at exactly
`measured_at - 24h` and `measured_at - 72h`. Retain the returned sample
timestamps and reject a sample more than ten minutes from its requested time.
Query raw per-copy series with stable `cluster`, `namespace`, and `pod` labels.
Do not use `max by(deployment)` across endpoints: a pod or database change can
splice two copies into a fictitious rate.

Use the status API plus read-only `deployment_schemas` and graft-base inventory
to prove `missing_attached_version` or `missing_graft_base`. A missing metric is
not absence proof.

The evidence `sources` object records the exact queries, returned series
identity, evaluation timestamps, status endpoints, and inventory commands or
query digests. It must never contain credentials.

## Capture workflow

Prepare a reviewed JSON measurement with these top-level fields:

```json
{
  "measured_at": "2026-08-27T12:00:00Z",
  "collector": {"version": 1, "repository_commit": "<commit>"},
  "sources": {
    "status_api": [],
    "victoriametrics": {"queries": []},
    "postgres_inventory": []
  },
  "clusters": []
}
```

Each cluster has `cluster`, `accounted`, `copies`, and `structural_blockers`.
Each copy records one stable selector, its current state, and raw `start`/`end`
points for `24h` and `72h`. See
[`schemas/eligibility-evidence-v1.schema.json`](../schemas/eligibility-evidence-v1.schema.json)
for the exact stored shape; the capture command calculates all derived fields
and the summary.

Run from the repository root:

```bash
python3 scripts/capture-eligibility.py \
  --binding morpho-blue-base/QmWSfh5qnidd1tBd6FY6eDvbSQUPTNhNG7o8CUGenvbaht.yaml \
  --measurements /path/to/reviewed-measurements.json \
  --output evidence/eligibility/QmWSfh5qnidd1tBd6FY6eDvbSQUPTNhNG7o8CUGenvbaht/20260827T120000Z.json
```

The command refuses to overwrite evidence and prints the exact
`eligibility.latest` block, including the file SHA-256, for review. It never
edits a binding or opens the gate itself.

Commit evidence append-only. Never replace an older file or promote an ETA
copied from an issue comment.

### Evidence storage

Eligibility evidence is an immutable, append-only JSON snapshot generated by
`scripts/capture-eligibility.py` and stored under:

```text
evidence/eligibility/<deployment>/<YYYYmmddTHHMMSSZ>.json
```

The corresponding target binding records the relative path and SHA-256 of the
exact file bytes. Capture a new snapshot and update the binding in a reviewed
commit; never replace an older snapshot.

No evidence is committed initially because this repository does not yet contain
a fresh, source-complete 24-hour and 72-hour measurement for every required
cluster. Until that evidence is captured, all target gates remain
`indeterminate` and closed.

## Validation and action checks

Offline repository validation is deterministic and does not use wall-clock
time:

```bash
python3 scripts/validate-targets.py
python3 -m unittest discover -s scripts/tests -p 'test_*.py'
```

Immediately before starting work, check freshness separately:

```bash
python3 scripts/check-eligibility.py <binding> --purpose implementation-start
python3 scripts/check-eligibility.py <binding> --purpose compute-or-load-start
```

Implementation evidence is valid for 24 hours. Compute/load evidence is valid
for one hour. Both commands fail closed unless the binding points at matching,
digest-verified, `eligible` evidence.

This split deliberately avoids stale automation. Historical evidence continues
to validate in CI, while an old pointer cannot authorize a new action. There is
no scheduled process that edits bindings or silently opens a gate.

## V4 consolidation

The Uniswap V4 repository consolidation ports an already approved and proven
pipeline. It does not authorize a new backfill, workflow submission, database
write, allocation, or activation, so it has no target binding under this gate.
