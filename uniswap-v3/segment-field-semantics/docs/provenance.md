# Provenance

The contract at `../v1/contract.json` is generated only from checksum-pinned,
repository-retained inputs. The verifier rejects a raw-byte change before
reading any semantic value.

| Evidence | Raw SHA-256 |
|---|---|
| graft ancestry v2 | `ae8c3e0099fedf2879b3071c2bcf545050fa4d448d0154fa6b895618bb8e203e` |
| writer compatibility v3 | `259481724561d5aa725c17f90b5a19ea93ad6f7cd6074cf2cb8a8661c39f81c4` |
| segment writer matrix v1 | `7f6d1a34a8c885fe5ddcd81895818ba7ae8a0d736d541b881c1cc7cd54275161` |
| Graph Node execution-order supplement v1 | `241e970cfcec4d76610b29a10141d3bff2512d80454a6308594f3db23621cde2` |
| Position runtime / semantics | `3099c3f08208cf46ce68df3433dd5b757436a3a7e315daec3f0d96bf242185c1` / `f449c4612413f381486de25c8045ea9d46899942b5d78ab12e477a77b261dec0` |
| Transaction runtime / semantics | `c9f355d141720dfda4347b4ef6cb5350a96803db31cf4770f035b5efca9def7f` / `83268d10f0ef3008d6d30fc3b6fd304fd46a067866b4284344fe468397878246` |
| Flash runtime / semantics | `0b24a14dcf460f9eda75addf7ffd6ae4832cd9c611a56b6f2591972767966168` / `8951469c026898de69d1a76381539eda3ddfdf094051d2b4b7f4295c860dfa43` |
| joint NPM runtime / semantics | `6f46d5cca49506c3ee0622351324ccb62a459916f0e41f3772fe021e0e185dd6` / `86cf89d8ffe66ac9f4aeda468988306ccc9dca1dbfd2641f132f12529207b143` |
| segment profiles v1 | `2b6635c061a7a0bfce39430c71c41dacc1567f095fe41134e890a697aa27f823` |

Field schema types come from the eight identical retained schema inventories.
Required absence comes from the all-functions, all-20-mappings store-target
closure. NPM and Flash value rules come from the executable host reducers and
are cross-bound to the retained WAT handler bodies, exact exports, mapping
CIDs, conservative store-target closure, and segment profiles.

For every handler, the generated provenance surface stores the exact body
binding plus a canonical digest of the full source handler record. For every
segment pair, recursive JSON-path diffs are recomputed over both the complete
scoped semantic surface and the complete scoped provenance surface. Editing a
value and recomputing its local digest cannot pass verification because the
entire contract is regenerated from the pinned sources.
