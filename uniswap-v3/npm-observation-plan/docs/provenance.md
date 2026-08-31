# Provenance

The observation plan is based on exact PR #55 head
`507631937e79b86c5665525af4f5d051e737868f`.
That exact head was subsequently squash-merged as
`a14dfc22d5e4beed3acb6cfa5ff14402eaec46c9`.

Its direct runtime inputs are pinned by raw SHA-256:

- resolved-input runtime: `5df1d6f5d6852ff8aea9ef6b054be786d0df78021e6ed271439f744a330cfc1f`
- resolved-input semantics: `01f7e87b22f52d84f8bb2fe806e963ecfb9dc196ab29804baee4c156eabbdbd9`
- NPM source runtime: `701e83d3833356cff75ad4455553894e7695fb9f75f03e7c53eaa3da616b57d5`
- joint reducer runtime: `6f46d5cca49506c3ee0622351324ccb62a459916f0e41f3772fe021e0e185dd6`
- joint reducer semantics: `86cf89d8ffe66ac9f4aeda468988306ccc9dca1dbfd2641f132f12529207b143`
- writer runtime: `765806bf19fca7695ef4d97f557593e4f791759589fe55c20f18c6523a5d07ca`
- writer segment profiles: `2b6635c061a7a0bfce39430c71c41dacc1567f095fe41134e890a697aa27f823`
- writer compatibility: `259481724561d5aa725c17f90b5a19ea93ad6f7cd6074cf2cb8a8661c39f81c4`
- eight-segment matrix: `7f6d1a34a8c885fe5ddcd81895818ba7ae8a0d736d541b881c1cc7cd54275161`
- execution-order supplement: `241e970cfcec4d76610b29a10141d3bff2512d80454a6308594f3db23621cde2`

The canonical plan semantic contract has raw SHA-256
`2d305149664b4c1e83d31a21a4131e585e44f8f25636d311ff741b9c437eaa3f`.
Provider failures, endpoint identity, retry metadata, and resolution status are
explicitly excluded from canonical plan and resolved-frame bytes.

The resolved-input runtime corrects the Base Factory literal to deployed
`33128a8fc17869897dce68ed026d694621f6fdfd`. A Base new-position `Value`
row is exercised through derived Pool/Token resolution, exact-key preflight,
and joint reduction; the former transposed tail is rejected by the verifier.
