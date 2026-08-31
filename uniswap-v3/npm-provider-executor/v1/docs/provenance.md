# Provenance

This executor is based on canonical Factory Pool price-initialization PR #75
merge `f6efe64263ada4b9ca288fe595b644bd87538ad5`, whose tree is
`fa1ea4b89418768d9e95c6afb5430b4cb9ae839a` and whose exact parent is the
canonical PR #74 merge `324e088c1877120585adbf834451d1ede074d14b`.

Only these direct dependencies are cross-bound by raw SHA-256:

- NPM observation-plan runtime: `8cd45b0c31994332e75bd25ccd515d961fe0de9d93ac30874f5a17c0f35b6c10`
- NPM observation-plan semantics: `2d305149664b4c1e83d31a21a4131e585e44f8f25636d311ff741b9c437eaa3f`
- selected NPM/Flash field-semantics v1: `4daa777ce2d14edd8a665a6a1239db8fb78957aa091174fd31f81b2c25136d4e`

At the requested base, observation-plan provenance incorrectly named
`1468dd…` instead of its then-current `6e80d215…` semantic digest. The
canonical PR #74 merge corrected that mismatch, fixed the transposed Base
Factory literal exposed by full executor testing, and deterministically
re-pinned the current semantic digest to
`2d305149664b4c1e83d31a21a4131e585e44f8f25636d311ff741b9c437eaa3f`.
The verifier asserts the current documentation binding and rejects both stale
digests.

Field-semantics v2 and every Factory supplement are deliberately not direct
dependencies. Transitive planner/reducer/writer bindings remain owned and
verified by the observation-plan contract. No live endpoint, database,
provider response, package, or output artifact is provenance for this host
executor.
