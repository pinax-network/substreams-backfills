# Provenance

The generated contract at [`../contract.json`](../contract.json) accepts only
the following raw-byte-identical inputs. The verifier rejects a digest or
contract-version change before projecting any semantic value.

| Evidence | Contract version | Raw SHA-256 |
|---|---|---|
| graft ancestry | `uniswap-v3-graft-ancestry/v2` | `ae8c3e0099fedf2879b3071c2bcf545050fa4d448d0154fa6b895618bb8e203e` |
| writer compatibility | `uniswap-v3-writer-compatibility/v3` | `259481724561d5aa725c17f90b5a19ea93ad6f7cd6074cf2cb8a8661c39f81c4` |
| segment writer matrix | `uniswap-v3-segment-writer-matrix/v1` | `7f6d1a34a8c885fe5ddcd81895818ba7ae8a0d736d541b881c1cc7cd54275161` |
| Graph Node execution order | `uniswap-v3-execution-order/v1` | `241e970cfcec4d76610b29a10141d3bff2512d80454a6308594f3db23621cde2` |
| scoped field semantics | `uniswap-v3-segment-field-semantics/v1` | `4daa777ce2d14edd8a665a6a1239db8fb78957aa091174fd31f81b2c25136d4e` |

## Authority chain

The segment-matrix verifier recursively recomputes all 20 retained mapping
artifacts with WABT 1.0.35 using:

```text
wasm2wat --generate-names <mapping-wasm>
```

Its complete all-function store-set closure and exact numeric handler exports
are the base machine evidence. V2 then binds each unique Factory and Pool
mapping to the retained artifact path, raw WASM SHA-256, generated WAT
SHA-256, full writer-profile record, and canonical profile/analysis digests.

The writer profiles include independently reviewed source anchors. Every such
binding states `artifact_authority: retained_mapping_wasm`; v2 copies that
record but separately fixes `source_corroboration_authoritative: false`.
Source text may explain a deployed shape but cannot close a control/dataflow
gap in the retained binary.

## Bounded Factory CFG/dataflow proof

V2 reruns WABT for each of the six unique Factory artifacts and binds the exact
numeric `handlePoolCreated` export. Its promoted CFG/dataflow scope is limited
to the four legacy excluded-pool guards.

For those legacy mappings, the analyzer proves the operand stack flows from
`PoolCreated__Params#get:pool` and the no-argument excluded-address helper into
the retained `ByteArray#equals` implementation, whose length and byte mismatch
branches compare distinct left/right parameters, return false, and whose
all-equal path returns true. It also binds every active `fromHexString` parser
input and its returned byte-fill loop to the excluded-address literal; the
diagnostic `input ` string cannot replace an active input.

The two modern guards remain false after independent review exposed
mutable-local and structured-control counterexamples outside this bounded
proof. All six normal-return effect paths also remain false: v2 retains the
machine-checked lexical callsites and reviewed
`Pool.save` -> `PoolTemplate.create` -> Token0/Token1 saves -> `Factory.save`
order as provenance, but does not claim same-path dominance, exact arguments,
template identity, or rollback.

The upstream writer profiles also bind each `totalSupply` helper function,
body digest, and reviewed deployed model. V2 rechecks those provenance
bindings and the two lexical handler callsites, but withholds every
success/failure value-dataflow claim, including the modern decoded-success
profile. Symbol, name, decimals, global zero values, and the rest of the
initialized field graph remain outside the promoted proof.

## Deterministic projections and diffs

Each segment surface contains all 299 field records, all ten handlers, exact
mapping/profile bindings, conservative writer and call evidence, exclusions,
ordering, error policy, manifest features, and deployed quirks. The provenance
surface contains exact handler-body bindings and canonical digests of the
upstream handler and reachability records.

All 28 unordered segment pairs are generated, never handwritten. Recursive
JSON-path diffs cover the entire semantic and provenance surfaces. Local
digest rewriting cannot conceal a changed field, handler, profile, proof
status, or pair because verification reconstructs the whole contract from the
pinned sources. Adversarial tests exercise those refusals, including inverted
legacy guard branches, active-literal substitution, legacy self-comparison,
attempted promotion of withdrawn modern-guard/effect/`totalSupply` claims,
promoted broad gates, source-authority promotion, missing
fields/handlers/pairs, cleared CFG blockers, modified deployed quirks, and
false self-rehashed diffs.
