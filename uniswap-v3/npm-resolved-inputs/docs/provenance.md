# Provenance

The adapter is bound to these immutable repository artifacts:

- NPM source runtime contract `701e83d3833356cff75ad4455553894e7695fb9f75f03e7c53eaa3da616b57d5`
- NPM source semantics `267dfc6b7240c36cdf345553e02a4f7b5332fa70548349bc6ef4b3075b4fcb4b`
- NPM source protobuf `bd394a11de37449710f0fd7dc10eac4e7f4ad299141a9fd54ec156980246fe1e`
- NPM source validator `5dac40f6f81223b0e373eb69e12a652754bc92879c0da28244ba80849b95c177`
- NPM source generated binding `0dba8501e790d4efd0cda3cf64c9eddbca01cb9ce90da3931568224b38c7be3d`
- joint NPM reducer runtime `6f46d5cca49506c3ee0622351324ccb62a459916f0e41f3772fe021e0e185dd6`
- joint NPM reducer semantics `86cf89d8ffe66ac9f4aeda468988306ccc9dca1dbfd2641f132f12529207b143`
- writer runtime `765806bf19fca7695ef4d97f557593e4f791759589fe55c20f18c6523a5d07ca`
- writer profiles `2b6635c061a7a0bfce39430c71c41dacc1567f095fe41134e890a697aa27f823`
- writer compatibility `259481724561d5aa725c17f90b5a19ea93ad6f7cd6074cf2cb8a8661c39f81c4`
- writer protobuf `f87b4bc718349bae2ff8fe799e4a4dadbb507240b7b6e9bc8d7a199299e33c59`
- segment matrix `7f6d1a34a8c885fe5ddcd81895818ba7ae8a0d736d541b881c1cc7cd54275161`
- execution order `241e970cfcec4d76610b29a10141d3bff2512d80454a6308594f3db23621cde2`

The checked-in verifier recomputes every binding from its source file and
rejects any materialized runtime or writer/package identity drift.

The adapter's static Base Factory is the deployed
`33128a8fc17869897dce68ed026d694621f6fdfd`. The prior transposed byte tail is
rejected by a source-level verifier mutation test, and the observation-plan
harness carries a Base new-position `Value` row through exact Pool/Token
preflight and joint reduction.
