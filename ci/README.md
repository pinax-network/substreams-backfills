`github-ci.yaml` → move to `.github/workflows/ci.yaml`. The scaffolding token lacked the
`workflow` OAuth scope to push workflow files; first human push (or a workflow-scoped token)
should relocate it.
