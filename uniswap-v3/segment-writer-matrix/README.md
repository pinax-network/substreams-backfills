# Uniswap V3 segment writer matrix

`v1/contract.json` is a diagnostic, fail-closed writer-provenance matrix for
the eight retained Uniswap V3 mainnet and Base ancestry segments. It is derived
offline from the exact ancestry v2 contract and writer v3 contract:

- ancestry raw SHA-256
  `ae8c3e0099fedf2879b3071c2bcf545050fa4d448d0154fa6b895618bb8e203e`;
- writer raw SHA-256
  `259481724561d5aa725c17f90b5a19ea93ad6f7cd6074cf2cb8a8661c39f81c4`;
- checksum-pinned `WABT wasm2wat 1.0.35 --generate-names` over all 20 retained
  mapping WASMs.

The v1 verifier refuses to regenerate against different source-contract bytes.
A source-contract revision requires a separately reviewed matrix version.

## What is bound

Each segment record binds its inclusive block range and graft parent to the raw
manifest, schema, every referenced ABI, and the Factory, position-manager, and
Pool mapping WASMs. The mapping records retain raw byte and SHA-256 identities,
WAT SHA-256, the complete writer-analysis digest, numeric export index, exact
WAT export target, and every registered handler body/call-sequence digest.

The verifier recomputes conservative call-graph writer and `ethereum.call`
reachability for every manifest handler. The resulting matrix contains:

- 8 segment records;
- 80 segment-handler records (10 per segment);
- 160 segment-entity records (20 per segment);
- 2,392 segment-field records (299 per segment);
- all 28 unordered segment pairs, including the 6 adjacent graft relations.

The retained Base root manifest is represented without collapsing two distinct
starts: the segment and Factory datasource begin at block `1,371,679`, while
the NonfungiblePositionManager datasource begins at block `1,371,713`. These
are manifest/runtime gates, not independent contract-creation proofs.

Named schema setter targets are deliberately labeled conservative candidates.
They can over-approximate a handler because call-graph reachability does not
prove branch execution, and old generic `TypedMap#set` code can omit a named
setter. They are therefore not promoted to complete field outputs.

Reviewed Factory, position-manager, and Pool formulas, calls, exclusions,
ordering observations, and deployed quirks remain tied to their exact writer-v3
profile records. Artifact changes, writer-provenance changes, and reviewed
semantic changes are hashed and diffed as three distinct surfaces. WAT line or
body-digest drift does not by itself become a semantic claim. The semantic
projection is an explicit normalized claim allowlist: WAT coordinates,
callsite IDs, record digests, profile-binding IDs, and implementation
call/function spellings remain only in artifact or provenance evidence.

## Population and execution truth

`Collect`, `Flash`, and `TickHourData` are `required_absent`: the complete
fixed-target writer scan finds no writer in any retained mapping. This is a
static writer-absence statement, not proof that a live table is empty.

The other 17 entities are classified `conditional` because at least one
conservative handler-to-writer path exists. No entity is certified
`required_nonempty`; that requires authoritative runtime/oracle evidence.

The contract catalogs the two execution models that issue #38 still needs to
decide:

1. emulate each deployed segment writer and its quirks; or
2. begin from an independently certified boundary seed and run the applicable
   later writer.

Both models are ineligible in v1 and every segment remains `undecided` with
`backfill_allowed=false`. Full handler/field semantics, contract-call value
semantics, exclusion control flow, target Graph Node runtime identity, boundary
samples and state continuity, logical/physical/PoI parity, writer-runtime
consumption, backfill readiness, and production readiness all remain false.
The adjacent-pair records identify boundary block numbers only; they explicitly
set `boundary_state_compared=false` and `graph_oracle_compared=false`.

## Verify or regenerate

With the checksum-pinned CI dependencies installed:

```bash
wasm2wat --version # must print 1.0.35
python3 scripts/verify-uniswap-v3-segment-writer-matrix.py
python3 -m unittest scripts.tests.test_uniswap_v3_segment_writer_matrix
```

`--write-contract` performs deterministic regeneration only after the exact
source contracts and every fresh WAT/handler derivation pass.
