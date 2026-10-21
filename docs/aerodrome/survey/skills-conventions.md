# Survey: where and how to document "make any subgraph Substreams-backfillable" as agent skills

Survey date: 2026-10-20. Strictly read-only. No clone was checked out, fetched, committed or pushed.

## Sources and identities

| Label | Path read | Revision |
|---|---|---|
| `pinax-skills` | `~/Github/pinax-skills` (branch `main`, clean) | `d456ab2` = `origin/main` = GitHub `main` (2026-10-19) |
| `k8s-subgraphs` | `scratchpad/ro/k8s-subgraphs` | `4da0b37` = GitHub `main` (2026-10-20 00:23Z) |
| `engine` (`substreams-graph-node-backfill`) | `scratchpad/ro/engine` | GitHub `main` = `5c98b57` (2026-09-07, PR #84). The snapshot's `.git` points at a pruned worktree, so `git log` fails there; files were read directly. Engine `main` has had no merge since 2026-09-07 (`gh pr list`). |
| `substreams-backfills` | `~/Github/substreams-backfills` (`main`, `bbe3783`) | current per task statement |
| `v4-subgraph` | `scratchpad/ro/v4-subgraph` | `6ebfaea` |
| `k8s-token-api-workflows` | `scratchpad/ro/k8s-token-api-workflows` | `3f06707` |
| `substreams-skills` (StreamingFast) | `~/Github/substreams-skills` | branch `develop` `5d9f04a` (read only for overlap) |

`scratchpad/ro/` = `/private/tmp/claude-501/-Users-denis-Github-substreams-backfills/6974ca53-b59e-4778-97ac-3643f910b626/scratchpad/ro/`.

**Evidence labels.** **VERIFIED** means I read the code, or ran the audit or a probe. **DOC-CLAIM** means a document states it and I did not execute it.

---

## TL;DR

1. **The pinax-skills contract is small and mechanical** (VERIFIED: I ran `scripts/audit-skills.py` and probed its parser):
   - **Directory and name:** a kebab-case directory name of at most 64 characters, `SKILL.md` inside it, and frontmatter `name` equal to the directory name.
   - **Description:** must contain the literal `Use when`, and must be on **one line**. A folded `>-` description is parsed as the string `">-"` and fails the audit.
   - **Colons:** a `name` or `description` value with `: ` must be quoted.
   - **Indexes:** each skill needs a row in the `AGENTS.md` routing table and a `- \`<name>/\`` line in the `README.md` catalogue. Both are checked in both directions.
   - **Symlinks:** `CLAUDE.md -> AGENTS.md` and `.claude/skills -> ../.agents/skills` must exist.
   - **Portability:** no home paths, named personal service accounts, personal SSH logins or shell-startup sourcing; no `inc-NNN`-style evidence files under `references/`.
   - **Links:** local Markdown links must resolve.
   - **Not enforced:** banned words, description length, and line limits. All 65 current skills use only the `name` and `description` keys. Descriptions run from 222 to 814 characters (median 394).
   - **Not enforced but recommended:** the skill-creator validator used in the 2026-09-12 review also rejects `<` and `>` in descriptions and anything over 1024 characters. One live skill, `operate-token-api-sinks`, already breaks the angle-bracket rule.
2. **No existing skill covers making a subgraph Substreams-backfillable.**
   - **pinax-skills** has nothing on Substreams to Graph Node backfill. The nearest text is in `backfill-firehose-merged-blocks`: graph-node is "bound by single-threaded WASM work". `operate-token-api-sinks` holds the noop vocabulary.
   - **k8s-subgraphs** `backfill-subgraph` is a Uniswap V4 Base production-lane checklist, hard-wired to `sgd1246`, `univ4base_*` and the "20-table" contract. It predates the engine's family-neutral `block-changes-v1-framed` input.
3. **Proposed skills:**
   - **pinax-skills `develop-subgraph-backfill-substreams`** (new, generic, cross-repo). It covers the decision gates (eligibility, then target freeze, semantic inventory, producer design, engine contract, noop, backfill, parity and landing) and routes to the owning repositories. A frontmatter draft passes the audit (671 characters).
   - **k8s-subgraphs `operate-subgraph-backfill-workflows`** (new runbook skill plus a `docs/` runbook) for submitting, monitoring and cleaning up the generic noop and backfill Argo workflows.
   - **Rescope `backfill-subgraph`** to "Uniswap V4 Base production lane".
   - **Six pinax-skills cross-links and three hygiene fixes** in k8s-subgraphs.
4. **PR convention:**
   - **Title:** `🤖 [claude] <Imperative sentence>`.
   - **Branch:** `create-pull-request` says `<type>/<short-slug>`. Recent history also uses `pinax-skills/feat/<slug>` and `claude/<slug>`.
   - **Commits:** split into "Add …", "Index … in AGENTS.md and README.md" and "Add trigger rows …".
   - **Body:** `## Summary` plus `## Test plan`, with checked audit and unittest boxes and an unchecked "CI green" box, then the `🤖 Created by …` footer.

---

## 1. The pinax-skills skill-authoring contract

### 1.1 Layout and discovery

- **Canonical store and symlinks:** the canonical store is `.agents/skills/`. `CLAUDE.md -> AGENTS.md` and `.claude/skills -> ../.agents/skills` are symlinks (`pinax-skills/AGENTS.md:12-28`). The repo says: "**Do not 'simplify' the two symlinks away** … `scripts/audit-skills.py` fails if either is replaced by a copy or deleted" (`AGENTS.md:21-27`).
- **Plugin manifest:** `.claude-plugin/plugin.json` sets `"skills": "./.agents/skills"`. `marketplace.json` publishes one plugin named `pinax-skills` with category `operations`. Neither file lists individual skills, so **adding a skill needs no manifest change** (VERIFIED by reading both files).
- **Optional Codex metadata:** `agents/openai.yaml` (16 of 65 skills have it). The shape is `interface: {display_name, short_description, default_prompt: "Use $<skill-name> to …"}`, for example `file-pinax-github-issues/agents/openai.yaml`. Recent new-skill PRs #166 and #167 include it. The audit does not check it.

### 1.2 Frontmatter rules (audit-enforced, VERIFIED)

`scripts/audit-skills.py`:

| Rule | Code | Exact message |
|---|---|---|
| Frontmatter is `\A---\n(.*?)\n---\n`. Only top-level single-line `key: value` pairs are read; indented lines are skipped. Values are stripped of `"'` | `:42-54` | (a missing block leads to the name and description errors) |
| `name` and `description` must be quoted if the value contains `:` followed by whitespace or end of line | `:118-122` | `quote {key} containing a colon followed by whitespace` |
| Directory name `[a-z0-9]+(?:-[a-z0-9]+)*`, at most 64 characters | `:123-124` | `use a kebab-case name of at most 64 characters` |
| `name` == directory name | `:125-128` | `name must match directory {dir}` |
| `"Use when" in description` (literal, case-sensitive) | `:129-131` | `description needs a Use when trigger` |

**Probe results (VERIFIED by importing `frontmatter()`):**

- `description: >-` followed by an indented block is parsed as `'>-'`. **YAML folded or literal descriptions therefore fail the "Use when" check.** k8s-subgraphs skills use `>-` (for example `k8s-subgraphs/.agents/skills/backfill-subgraph/SKILL.md:3-8`), so **do not copy that style into pinax-skills**.
- An unquoted `description: … Use when a: b.` passes the parser, but the colon rule above flags it.

The test fixture `scripts/tests/test_catalogue_audit.py:32-35` shows a nested `metadata:` block is allowed and ignored.

**Catalogue practice (VERIFIED by scanning all 65 skills):**

- Every skill uses exactly the keys `name` and `description`.
- Descriptions are 222 to 814 characters, median 394.
- Style: "<What it does, as a concrete verb phrase>. Use when <the user phrases and symptoms that should trigger it>." For example, `subgraphs-onboard-deployment/SKILL.md:3` and `trace-substreams-request/SKILL.md:3`.

**Not in the audit, but enforced by the skill-creator validator that the 2026-09-12 review ran** ("Skill-creator YAML/frontmatter validation for all 41 entrypoints", `docs/reviews/2026-09-12-skill-catalogue.md:109`). From `skill-creator/scripts/quick_validate.py`:

- allowed keys: `{name, description, license, allowed-tools, metadata, compatibility}`;
- `"Description cannot contain angle brackets (< or >)"`;
- the description must be at most 1024 characters;
- the name must not start or end with a hyphen or contain `--`.

`operate-token-api-sinks/SKILL.md:3` currently contains `substreams-<asset>` and would fail that validator (VERIFIED by grep). **New descriptions must avoid `<…>` placeholders and `Qm…`/`<hash>` patterns.**

### 1.3 Index rules (VERIFIED)

- **Forward checks:** every skill directory must appear in `AGENTS.md` as the literal string `.agents/skills/<name>/SKILL.md` and in `README.md` as `<name>/` (`audit-skills.py:133-137`). In prose: "A new or renamed skill must be listed in **both** `AGENTS.md` … and `README.md` … or the audit fails" (`AGENTS.md:233-234`).
- **Reverse checks:**
  - `\.agents/skills/([a-z0-9-]+)/SKILL\.md` anywhere in AGENTS.md must name an existing directory.
  - `^- \`([a-z0-9-]+)/\`` lines in README.md must name an existing directory (`audit-skills.py:139-146`).
  - So README catalogue rows **must** use the form `- \`<name>/\` — <summary>`.
- **Routing-table row format** (`AGENTS.md:30-96`): `| "<user phrase> / <user phrase> / …" | \`.agents/skills/<name>/SKILL.md\` |`.
  - Phrases are quoted, lower-case, in the user's voice, and separated by ` / `.
  - Rows cluster by domain. Subgraph rows are at `:64-69`; Firehose and Substreams rows are at `:70-74`.
- **README catalogue:** a skill goes under a bold category heading. The relevant ones are **Subgraphs** (`README.md:63-69`) and **Firehose & Substreams** (`README.md:71-76`).

### 1.4 Portability rules (audit-enforced, VERIFIED, `audit-skills.py:14-39,165-185`)

These rules apply to **every file** under `.agents/skills/`, not only Markdown:

- `/(?:Users|home)/[A-Za-z0-9._-]+`: "absolute operator home path; use $HOME or ~"
- `kube-system:<x>-cli`: "named interactive service account; describe the role encoded in the kubeconfig"
- a line that starts with `source ~/.zshrc` and similar: "shell startup sourcing; require the invoking environment or approved MCP"
- `ssh|scp|sftp|rsync … <user>@<host>` with a user other than `admin`, `debian`, `root`, `ubuntu` or `user`: "literal SSH user {u}; use <user>@ or a variable"
- a file under `references/` named `inc-\d+.*\.md` or `(dom|ceph)\d+.*(case-study|example|lab).*\.md`: "move incident/test-host evidence to its owning record"

Matching prose rules in `AGENTS.md:110-117`:

- "Keep every skill team-portable … Do not encode a person's username, named personal service account, absolute home directory, kubeconfig, or token."
- "Keep reusable skills free of incident progress ledgers, dated test-host state, and one-off operator stop decisions."

Consequence for the new skill: **Aerodrome deployment IDs, sgd numbers, checkpoints and dated ETA readings belong in the owning repositories** (substreams-backfills family directories, k8s-subgraphs `docs/`), not in the generic skill. The k8s-subgraphs kubeconfig path `~/.kube/kan-subgraphs-a-sa.yaml` and the SA name `denis-cli` (`k8s-subgraphs/AGENTS.md:34-36`) must be described by role ("operator-owned Kan kubeconfig").

### 1.5 Link rules (VERIFIED)

- **Inline links:** inline Markdown file links are checked (`audit-skills.py:57-91`).
  - Skipped: fenced code, targets containing `${}<>*`, URLs, `~` paths, and paths resolving outside the repo.
  - A link that resolves inside the repo but is missing is reported as `broken local link`.
- **Linking convention:** "Link supporting files with Markdown paths relative to the document containing the link; label sibling-repository paths with their owning repo" (`AGENTS.md:235-237`).
- **Existing practice for sibling repos:** cross-repo paths appear as backticked prose with the repo named, for example "k8s-subgraphs skill **`transplant-subgraph`** (runbook: `docs/pinax2-cutover-runbook.md`)" (`subgraphs-onboard-deployment/SKILL.md:18-19`).

### 1.6 Content conventions (prose, not machine-checked)

From `AGENTS.md:218-243`:

- "**Macro here, micro with the infra.** If a procedure edits or queries a specific repo's resources, keep the detailed runbook there and reference it; this repo holds the cross-cutting workflow and the decision logic."
- "Verb-first kebab-case directory name … `description` **must** contain a 'Use when…' trigger."
- "Every skill states its **access prerequisites** (kubeconfig, SSH, API keys) up front."
- "New recurring procedure? Copy the shape of an existing skill rather than inventing a layout."
- "Put deterministic, reusable diagnostics in the skill's own `scripts/` directory. Keep them read-only by default; state-changing behavior needs an explicit flag and operator approval."
- Catalogue reviews go in dated `docs/reviews/` reports. The JS-skill PR #168 also added `docs/reviews/2026-10-16-js-supply-chain-skill.md` as its evidence; this is optional for a new skill.
- "Preserve distinct workflows when their owners or acceptance gates differ" (`AGENTS.md:242`). This is the rule that justifies keeping V4's production lane separate from a generic runbook.
- Long entrypoints: "can move conditional procedures into linked references when it reduces repeated context" (`docs/reviews/2026-09-12-skill-catalogue.md:92-93`).
- `SKILL.md` sizes: median 133 lines, maximum 614 (`operate-firehose-substreams`). There is no limit.

**Tension to resolve explicitly:**

- `README.md:20-22` says: "Skills are operator-focused; for developer Substreams workflows, defer to StreamingFast's own docs." `operate-firehose-substreams/SKILL.md:3,8-10` says the same ("as the operator, not a substreams developer").
- The new skill is a **Pinax-specific developer and operator procedure**, because the engine contract is Pinax's. It should defer generic module-authoring mechanics to StreamingFast's `substreams-dev`, `substreams-sink` and `substreams-testing` skills (`~/Github/substreams-skills/skills/*`; loaded in this session as `substreams:substreams-dev` and others). Those skills contain nothing about graph-node or BlockChanges (VERIFIED by grep).
- README `:20-22` should get a one-clause exception: "…except the Pinax backfill-engine contract (`develop-subgraph-backfill-substreams`)".

### 1.7 CI (VERIFIED, `.github/workflows/ci.yml:1-54`)

On every `push` and `pull_request`:

1. `python3 scripts/audit-skills.py`
2. install `jq` and `ripgrep`, then `python3 -m unittest discover -s scripts/tests -v`
3. JSON and TOML validation of `integrations/mcp/*` examples
4. `py_compile` of every `*/scripts/*.py`
5. `bash -n` of every `*.sh`

There is no Markdown lint, link-to-remote check, line limit or banned-word list. `AGENTS.md:245-269` adds that `rg` must be a real binary for the tests. A local run on `main` today prints `skill audit passed: 65 skills, indexes, symlinks and local links consistent` (VERIFIED).

**Validation for the PR** (copy from PR #166 and #169 test plans):

```bash
python3 scripts/audit-skills.py
python3 -m unittest discover -s scripts/tests -v
```

Any new helper script needs an offline test under `scripts/tests/`. PR #167 added `test_repo_audit_helpers.py`; PR #168 added `test_js_supply_chain.py`.

---

## 2. What existing skills say about Substreams backfills of subgraphs

### 2.1 pinax-skills: no dedicated coverage (VERIFIED by grep)

These terms match nothing in pinax-skills:

- `graph-node-backfill`, `substreams-backfills`, `backfill-subgraph`, `certify-backfill`;
- `EntityChanges`, `graph_out`, `BlockChanges`, `substreams-v4`, `verify-disposable`.

The adjacent text that does exist:

| Skill | Quote | Relevance |
|---|---|---|
| `backfill-firehose-merged-blocks/SKILL.md:46-48` | "Do not assume that placing merged blocks beside graph-node will accelerate a subgraph backfill. A local Firehose removes remote transport, but it does not parallelize graph-node's mapping execution. Dense subgraphs are commonly bound by single-threaded WASM work or database writes instead of Firehose delivery." | **This is exactly why Substreams backfills exist.** It ends with "optimize the mapping/CPU/database path instead" (`:78-79`) and never mentions the Substreams path. **Add a cross-link here.** |
| `operate-token-api-sinks/SKILL.md:64-67` | "Run a noop (`token-noop`, module `db_out`) over the range before a first backfill of a new package writes into ClickHouse." | The established "noop then backfill" pattern. The user's "noop" means this sense. |
| `operate-token-api-sinks/SKILL.md:320-327` | `substreams run <spkg_url> db_out -e <endpoint> -s <start> -t <stop> --limit-processed-blocks 0 --production-mode --noop-mode`, labelled "bounded tier2 warm-up" | The CLI form of noop. |
| `operate-token-api-sinks/SKILL.md:216-241` | Argo `token-noop-*` / `token-backfill-*` behaviour: a manual stop is recorded as `Failed` (exit 143); `token-noop` uses `podGC: OnPodSuccess` and `token-backfill` uses `OnPodCompletion` | Operational lessons to carry into the k8s-subgraphs runbook. |
| `architect-k8s-substreams/SKILL.md:105` | "If it feeds graph-node, continue through `subgraphs-onboard-deployment` for the indexer wiring." | About Substreams-*powered* subgraphs, not backfilling a WASM subgraph. **Needs a disambiguating line.** |
| `operate-firehose-substreams/SKILL.md:18,27-30,222-227` | tier2 is shared. "riv tier1 runs its tier2 work in kan … A kan tier2 problem hits **both** DCs" | A full-history noop over about 39M Base blocks loads shared Kan tier2. The new skill must route capacity questions here. |
| `subgraphs-onboard-deployment/SKILL.md:13-30` | The only paths are "transplant", "new chain" and "Fresh sync on an existing chain → `graphman create` + `graphman deploy`" | **Gap.** There is no "native sync is ineligible, backfill via Substreams" branch. |
| `subgraphs-fleet-health/SKILL.md:40-47` | The route table treats "lagging" only as an RPC or head problem | **Gap.** There is no "healthy but ETA > 28 days" route. |
| `trace-substreams-request/SKILL.md:3,211-232` | Trace a Substreams request and give an ETA; "It is a real production request" | Reuse for diagnosing long noop or backfill streams. No change needed. |
| `build-subgraph-grafana-dashboards/SKILL.md:23` | "`src/transplants.py`, `fullsyncs.py` and `backfills.py` cover migration/sync progress" | A dashboard for `backfill_*` metrics already exists. Reference it. |
| `AGENTS.md:187-192` registry | `k8s-subgraphs` "· 8 repo-local skills" | **Stale.** k8s-subgraphs has **13** skill directories (VERIFIED). `substreams-graph-node-backfill`, `substreams-backfills` and `substreams-v4-subgraph` are **absent** from the registry. |

### 2.2 k8s-subgraphs skills (VERIFIED by reading)

**`backfill-subgraph/SKILL.md` (64 lines).**

- Description (`:3-8`): "Run or review the Substreams-to-stopped-Graph-Node-PostgreSQL backfill prototype. Use when cloning a stopped deployment, capturing an exact target checkpoint, loading Store-state output with direct COPY, selecting the Parquet fallback, or certifying parity before a Graph Node replacement. Full runbook: docs/substreams-graph-node-backfill.md."
- Generic, still-valid safety rules worth lifting into the generic skill as principles:
  - `:18-20` "Require every source and target Graph Node writer to have zero replicas. Never let Graph Node and an external Parquet or direct-COPY writer advance the same deployment."
  - `:21-22` "A graft-derived deployment must not be replayed from an empty database."
  - `:23-24` immutable seed, with work done only in a reflink or hard-link copy.
  - `:29-31` "capture the first checkpoint from the exact stopped target after Graphman restore. Never reuse the source export because restored VIDs can differ."
  - `:34-36` preserve evidence before proposing cutover.
- V4-only or dated content, which is **stale as a generic instruction**:
  - `:27` and `:37-40`: `sgd1246`, `univ4base_a`, `univ4base_b`;
  - `:41-44`: `index_node_univ4base_copy_0`;
  - `:32`: "20-table/VID sequence checks". 20 tables is the V4 contract: "`src/sink.rs`: 20-table Graph Node contract" (`engine/AGENTS.md:96`);
  - `:50-56`: `sgd2` SQL replay;
  - `:62-64`: "The Kan prototype is pinned to paused `sgd1246` at block `32,374,154`".
- It never mentions the engine's family-neutral `block-changes-v1-framed` input (engine PRs #66 and #74, 2026-09-03) or profile-driven writers (#77).
- The runbook's production-lane identities (`sgd5303` parked at `32,374,183`; target `49,477,581`; `k8s-subgraphs/docs/substreams-graph-node-backfill.md:1355-1474`) are not in the skill at all.
- **Verdict:** current for the V4 lane, misleading as "the" backfill skill. Rescope the description to V4 Base and add a pointer to the generic skills.

**`verify-disposable-v3-root/SKILL.md` (68 lines).**

- Description: "Run or review the bounded ungrafted Uniswap V3 root oracle … Use for the opt-in v3-mainnet-oracle stack, not V4 production backfills or graft restoration."
- It has **no "Use when"** and is **not listed** in `k8s-subgraphs/AGENTS.md:111-130`.
- Generic lessons worth lifting:
  - `:16-18` "A fresh, ungrafted root may start empty; a grafted child may not."
  - `:29-33` "Graph Node may commit beyond the requested stop in its last batch … never loosen the comparison window."
  - `:34-40` a registrar bootstrap needs chain providers; the `general.query` selector must not match the node ID.
  - `:41-45` "A sealed stream without dynamic-source metadata cannot restore V3 faithfully."
  - `:47-57` narrow evidence interpretation: "Never label null as hash parity".

**`transplant-subgraph/SKILL.md` (119 lines).** This is the shape to copy for k8s-subgraphs skills (`k8s-subgraphs/AGENTS.md:132-134`): "copy `transplant-subgraph`'s shape". It is relevant only as the "Register / name mapping / serve and allocate" tail (`:60-89`) that a backfilled copy also needs, and for the attr-index check (`:95-97`).

**Repo hygiene (VERIFIED):**

- `relocate-graph-node-worker`, `specialize-offchain-portfolio` and `verify-disposable-v3-root` lack "Use when".
- `k8s-subgraphs/AGENTS.md:116-130` lists 12 of the 13 skill directories; only `verify-disposable-v3-root` is missing.
- No CI step audits skills in k8s-subgraphs.
- CI **does** lint backfill workflows (`k8s-subgraphs/.github/workflows/ci.yaml:67-75`): `kustomize build subgraphs-operations/backfill/kan`, then `argocli:v4.0.7 lint --offline --strict`, plus `test-contract.sh` and the exporter unittest. Any new noop or backfill template must be reachable from a linted kustomization.

### 2.3 substreams-backfills `.agents/skills/certify-backfill-successor` (VERIFIED)

- Description: "Verify, merge, and canonically publish a digest-pinned Substreams Graph Node backfill successor or evidence-only OCI overlay. Use when changing engine Docker targets, runtime identity allowlists, descriptor pins, release archives, or GHCR attachments."
- This is release certification for the engine runtime, not subgraph onboarding.
- **The repo itself breaks the estate agent contract:**
  - there is no `AGENTS.md` and no `CLAUDE.md` at the root (only `uniswap-v4/AGENTS.md`, imported);
  - `.claude/` is an empty untracked directory with **no `skills` symlink**;
  - `git ls-files` shows only `.agents/skills/certify-backfill-successor/SKILL.md`.
- So Claude Code cannot discover this skill. The contract is in `pinax-skills/AGENTS.md:149-152,215-216,278-281`: "give it the same four files and add a row here".

### 2.4 engine `AGENTS.md` (308 lines, VERIFIED)

Current and generic rules worth citing from the new skill:

- hard safety rules (`:25-68`), for example "Never let Graph Node and the external backfill writer advance the same deployment concurrently";
- "Never claim production compatibility from a selective fixture";
- "Never report a proposal, running job, draft PR, or selective fixture as a completed production backfill" (`:307-308`);
- the validation ladder (`:132-290`).

**Stale relative to the engine's own `src/`:**

- The Mission (`:8-19`) and code ownership map (`:89-116`) describe only the V4 reducer, Store-state and JSONL paths.
- `src/` now also holds `block_changes_input.rs`, `block_changes_descriptor.rs`, `generic_state.rs`, `generic_checkpoint{,_v2}.rs`, `physical_profile.rs`, `physical_writer.rs`, `source_chunk.rs` and `v3_root_load*` (VERIFIED by listing). None of these is in the map.
- The new generic skill must therefore point at the engine **docs** (`docs/block-changes-v1-input.md`, `docs/physical-schema-profiles.md`, `docs/data-sources-*.md`), not at its AGENTS.md mission text.

### 2.5 Current engine reality the skill must encode (generic producer contract)

**The input contract.**

- **VERIFIED (code):** `cmd/substreams-native` is `Use: "substreams-native <manifest> [<module>]"`, "Stream raw Substreams map outputs using the backfill protobuf frame format". It ignores the output type (`sink.IgnoreOutputModuleType`), forces `config.Mode = sink.SubstreamsModeProduction` (`main.go:124`), and supports `--output-format legacy-v1|clock-v1`, `--limit-processed-blocks` and `--include-empty-frames` (`main.go:72-140`).
  - **So any Substreams package is engine-compatible at the transport layer** if its output module emits exactly one canonical `pinax.graph.backfill.v1.BlockChanges` per block. The package is in `substreams-backfills/common/proto/block_changes.proto:3`.
- **DOC-CLAIM:**
  - `state-replay --input-format block-changes-v1-framed --native-frame-format clock-v1 --block-changes-descriptor adapters/<family>/block-changes-v1.json` replays "a non-Uniswap-v4 family … without a hand-written per-family reducer" (`engine/docs/block-changes-v1-input.md:7-12,19-44`).
  - "Parquet output remains Uniswap v4-only" (`:17`).
  - The descriptor needs a `.sha256` sidecar, and its digest is the frame `compatibility_id` (`:84-92`).
- **DOC-CLAIM:** "This contract is deliberately not `sf.substreams.sink.entity.v1.EntityChanges`. Table-oriented EntityChanges coalesces writes by entity. Graph Node hashes each Set and Remove in mapping execution order … so a coalesced or reordered stream cannot prove equivalent entity history or proof of indexing" (`substreams-backfills/docs/block-changes-v1.md:10-14`).
  - **A conventional `graph_out` / EntityChanges Substreams is not sufficient.** The producer must preserve per-save order, handler groups, PoI causality region and deterministic-error policy (`:16-60`).

**Engine production blockers today** (DOC-CLAIM, `engine/docs/block-changes-v1-input.md:473-497`, `engine/docs/physical-schema-profiles.md:540-565`):

1. `data_sources$` for templated manifests:
   - the v1 sidecar is root-only and capped at 10,000 blocks and 16 MiB (`data-sources-sidecar-v1.md:1-16`);
   - v2 chunks are "an offline generation capability, not production certification or a database loader" (`data-sources-chunks-v2.md:3-6`).
2. Committed `RemoveEntity` is refused.
3. Immutable tables cannot be resumed across.
4. No physical profile is `production_selectable`. That needs a `live_catalog` capture and resolved pins.
5. A certified range against an independent Graph Node is required first (`substreams-backfills#10`).

The generic skill must make "check these against engine `main`" an explicit gate, not a hard-coded list, because they change. For Aerodrome, blocker 1 applies: the manifest declares a Pool template. Blockers 2 and 3 depend on the inventory; the target profile says "all target entities are mutable" (`substreams-backfills/aerodrome-slipstream-base/README.md:47-50`).

**Producer and cache rules from the V4 reference** (DOC-CLAIM, `v4-subgraph/AGENTS.md:7-14,34-59`):

- **Ownership split:** the Substreams half (extraction, Stores, maps, protos, SPKG releases) lives in the Substreams repo. The engine owns reduction, PoI, COPY, lifecycle and parity. `k8s-subgraphs` owns workflows and image pins.
- **Store writers:** "Never change a released Store writer in place." "Keep each Store writer binary isolated from downstream map binaries."
- **Store size:** the server Store limit is 2 GiB. "The legacy single Store exceeds the server's 2 GiB Store limit on the full Base history", hence 16 Tick shards.
- **Module identity:** "Treat module hashes, SPKG SHA-256 values, package versions, module names, initial blocks, update policies, value types, and protobuf output types as a compatibility contract."
- **Release bytes:** "Never call a host-built SPKG production-identical."

**Eligibility gate** (DOC-CLAIM, `substreams-backfills/docs/eligibility.md:1-11,43-60`; `README.md:28-40`):

- The rule: the minimum stable same-pod 24-hour and 72-hour ETAs across all viable copies on both clusters must both be more than 28 days, or the copies must be non-converging.
- The formula is `ETA_days = lag / (net_delta*86400/duration)`.
- The rule is enforced by `cargo xtask verify-targets`.
- Applied to the live fact in the task (Aerodrome at 34,725,888 vs 52,867,396, about 140k blocks a day net): roughly 130 days, so likely eligible. Formal eligibility still needs same-pod 24-hour and 72-hour windows from **both** clusters, recorded through the repo's evidence contract.

**The word "noop" means two different things.**

- In token-api it means cache warm-up:
  - `substreams-sink-noop … --noop-mode` / `substreams sink noop …` with `-H "X-Substreams-Parallel-Workers: N"`;
  - images `ghcr.io/pinax-network/substreams-sink-noop:v1.5.2` and `ghcr.io/streamingfast/substreams:v1.18.2`;
  - source: `k8s-token-api-workflows/workflows/templates/cluster/substreams-sink-noop.yaml:56-79,128-151`.
- In k8s-subgraphs backfill it means the **no-op resume certification gate**: `direct-load-noop.json` (`subgraphs-operations/backfill/base/workflow-template.yaml:601-607,1030`).
- The skills must name them distinctly: "noop warm-up" and "no-op resume gate".

The motivation for warm-up is in the V4 runbook (DOC-CLAIM): "The Store-state package has its own hash-addressed caches; its first run may need to extend them from the module initial block, while later runs reuse only artifacts from that exact packaged module graph" (`k8s-subgraphs/docs/substreams-graph-node-backfill.md:41-45`).

### 2.6 Stale versus current matrix

| Item | Location | Status | Action |
|---|---|---|---|
| "the" Substreams backfill skill is V4-only | `k8s-subgraphs/.agents/skills/backfill-subgraph/SKILL.md:1-64` | current for the V4 lane, stale as a generic skill | rescope the description to "Uniswap V4 Base production lane", add "For any other deployment use `operate-subgraph-backfill-workflows` and pinax-skills `develop-subgraph-backfill-substreams`" |
| Dated pin "sgd1246 at 32,374,154" | same `:62-64` | dated state inside a skill | move to `docs/` or keep it but tag the date |
| 20-table checks | same `:32` | V4-specific | in the generic skill, say "every table in the deployment's physical profile plus `poi2$` and `data_sources$`" |
| Engine mission and ownership map | `engine/AGENTS.md:8-19,89-116` | stale vs `src/block_changes_*`, `generic_*`, `physical_*` | owner-repo follow-up (engine PR); the skill must cite engine docs instead |
| k8s-subgraphs skill count | `pinax-skills/AGENTS.md:191` "8 repo-local skills" | stale (13) | fix in the same pinax-skills PR |
| Missing registry rows | `pinax-skills/AGENTS.md:187-192` | gap | add `substreams-backfills`, `substreams-graph-node-backfill`, `substreams-v4-subgraph` |
| Developer-Substreams deferral | `pinax-skills/README.md:20-22` | conflicts with the new skill | add the exception clause |
| `verify-disposable-v3-root` index and trigger | `k8s-subgraphs/AGENTS.md:111-130`, the skill `:3` | gap | list it; add "Use when" |
| `relocate-graph-node-worker`, `specialize-offchain-portfolio` triggers | k8s-subgraphs skills `:3` | gap | add "Use when" |
| substreams-backfills agent contract | repo root | missing `AGENTS.md`, `CLAUDE.md`, `.claude/skills` | owner-repo follow-up |
| Angle brackets in a description | `pinax-skills/.agents/skills/operate-token-api-sinks/SKILL.md:3` | breaks the skill-creator validator | optional drive-by fix (`substreams-ASSET`) |

### 2.7 Cross-links to add (exact anchors)

**pinax-skills:**

1. `subgraphs-onboard-deployment/SKILL.md:13-30`: add path **4**. "No healthy synced source and native sync is ineligible (both 24-hour and 72-hour ETAs more than 28 days, or non-converging) → `develop-subgraph-backfill-substreams`. Land the backfilled copy paused, then return here for wiring and completion gates." Optionally extend the `:3` description with "or backfilling history through Substreams".
2. `subgraphs-fleet-health/SKILL.md:40-47`: add a route row. "lagging, healthy and advancing, but ETA more than 28 days (mapping- or DB-bound)" → measure the 24-hour and 72-hour same-pod ETA, then `develop-subgraph-backfill-substreams`. Detail: "not fixed by restart or RPC".
3. `backfill-firehose-merged-blocks/SKILL.md:76-79`, after "optimize the mapping/CPU/database path instead": add "…or, when the ETA stays above 28 days, replace historical indexing with a Substreams backfill (`develop-subgraph-backfill-substreams`)."
4. `architect-k8s-substreams/SKILL.md:105`: add "To backfill an existing WASM subgraph's history (not a Substreams-powered subgraph), use `develop-subgraph-backfill-substreams`."
5. `operate-firehose-substreams/SKILL.md`, symptom table near `:305-319` or Capacity: a one-line note that long subgraph-backfill noop warm-ups are tier2-heavy, with a link to the new skill. Optional.
6. `operate-token-api-sinks/SKILL.md:216-220`: add "Subgraph backfill noop and backfill workflows run in k8s-subgraphs namespace `subgraphs-backfill`, not here (`develop-subgraph-backfill-substreams`)". This prevents namespace and alert confusion. Optional.
7. `diagnose-with-pinax-grafana/references/dashboard-routing.md:53`: add the subgraph backfill dashboard (`backfill_*` metrics, `k8s-subgraphs/docs/substreams-backfill-metrics.md`). Optional.

**k8s-subgraphs:**

- `AGENTS.md:111-130`: add `operate-subgraph-backfill-workflows` and `verify-disposable-v3-root`.
- Rescope the `backfill-subgraph` description.

---

## 3. Proposed skill set

### 3.1 pinax-skills: `develop-subgraph-backfill-substreams` (new, generic procedure)

**Name rationale:**

- It is verb-first (`AGENTS.md:226`), 36 characters, and matches the user's phrasing ("develop a Substreams").
- It does not prefix-collide with k8s-subgraphs `backfill-subgraph`. With both repos' skills loaded, a near-identical name would mis-route.
- Rejected alternatives:
  - `backfill-subgraph-with-substreams`, too close to `backfill-subgraph`;
  - `make-subgraph-substreams-backfillable`, which is awkward;
  - the `subgraphs-*` prefix, a legacy non-verb-first pattern (`subgraphs-fleet-health`, `subgraphs-onboard-deployment`); newer subgraph skills are verb-first.

**Frontmatter** (VERIFIED: passes `audit()` in a temporary repo; 671 characters; no `<` or `>`; no `: `):

```yaml
---
name: develop-subgraph-backfill-substreams
description: Make any Graph Node subgraph deployment backfillable through Substreams and the substreams-graph-node-backfill engine instead of a months-long native sync — eligibility, target freeze, semantic inventory, a Substreams producer of ordered BlockChanges v1 frames, the engine descriptor and physical profile, noop cache warm-up, segmented backfill into a stopped inactive copy, parity and paused landing. Use when a deployment's native sync ETA exceeds 28 days or never converges, when asked to develop or review a Substreams for a subgraph backfill, to make a new subgraph family compatible with the backfill engine, or to plan noop and backfill workflows for a deployment.
---
```

**AGENTS.md routing row.** Insert after `:68` ("add this subgraph / onboard this chain …"):

```markdown
| "subgraph sync will take months / backfill a subgraph's history with Substreams / make a subgraph compatible with substreams-graph-node-backfill / develop a backfill Substreams for a deployment / noop + backfill a subgraph" | `.agents/skills/develop-subgraph-backfill-substreams/SKILL.md` |
```

**README row.** Under **Subgraphs** (`README.md:63-69`):

```markdown
- `develop-subgraph-backfill-substreams/` — make any subgraph's history Substreams-backfillable: eligibility, BlockChanges producer, engine contract, noop, backfill, parity
```

**AGENTS.md registry rows.** Under `### Subgraphs` (`:187-192`). Also change "8 repo-local skills" to the current count, or drop the number:

| Repo | Owns | Read it before |
|---|---|---|
| `substreams-backfills` | per-deployment family targets (immutable deployment closure, target binding, eligibility evidence), the BlockChanges v1 contract and validator, `mapping-host` · skill `certify-backfill-successor` | choosing or freezing a backfill target; Rust-only, tooling through `cargo xtask` |
| `substreams-graph-node-backfill` | the engine: replay, PoI, physical profiles, PostgreSQL COPY spools, checkpoints, parity and lifecycle gates | any producer or engine contract change; never claim production compatibility from a fixture |
| `substreams-v4-subgraph` | the reference Substreams half (Uniswap V4 Base Stores and maps, SPKG releases) | copying its cache and release discipline |

**Proposed `SKILL.md` outline.** About 180 to 250 lines; conditional detail goes in `references/`.

```
# Develop a Substreams backfill for a subgraph

Access prerequisites
  - Substreams API token (role-based; never print), read access to engine/families repos,
    Grafana MCP / VictoriaMetrics read for heads, operator-owned Kan/Riv kubeconfig
    (read-only until the k8s runbook's approval gates), read-only graph-node SQL.
  - Read the owning repos' AGENTS.md: substreams-backfills, substreams-graph-node-backfill,
    k8s-subgraphs; for module mechanics defer to StreamingFast substreams-dev/-testing skills.

Ownership map (macro here, micro with the infra)
  target + family source + eligibility evidence ......... substreams-backfills/<family>/
  engine runtime, descriptor/profile contracts .......... substreams-graph-node-backfill
  Argo noop/backfill workflows, image pins, runbook ...... k8s-subgraphs (operate-subgraph-backfill-workflows)
  tier1/tier2 serving and capacity ...................... k8s-substreams (operate-firehose-substreams)

Stage gates (each is a stop/go; record evidence in the owning repo, not here)
  0 Eligibility — 28-day rule over BOTH clusters, same-pod 24h+72h minima; formula +
    xtask verifier in substreams-backfills docs/eligibility.md. Ineligible → keep syncing.
  1 Freeze the target — deployment CID, schema, manifest, ABIs, mapping WASMs by CID+SHA-256;
    graft facts (graft → seed from an existing copy; never replay a graft child from empty);
    network, start blocks, specVersion/apiVersion. `cargo xtask verify-target <family>`.
  2 Semantic inventory — per handler: triggers (event/call/block), entities+fields written,
    save order, contract calls (eth_call inputs), templates (→ data_sources$), removes,
    immutable entities, id types (production = String ids only), deterministic errors,
    Bytes/BigDecimal semantics. Prior-art packages are decoders, not Graph-compatible writers.
  3 Producer design — choose and justify:
     a. Substreams map emitting pinax.graph.backfill.v1.BlockChanges per block (re-implements
        the mapping; must reproduce per-save order, handler groups, PoI region, error policy);
     b. mapping-host executing the deployed WASM over Firehose blocks + eth_call cassette
        (faithful by construction; not a Substreams; segment-parallel);
     c. family-specific reducer (only V4 exists in the engine).
     Never emit EntityChanges/graph_out as the engine input (ordering/PoI loss).
  4 Engine contract — descriptor JSON + .sha256 sidecar (= compatibility_id), clock-v1 BCF1
    via substreams-native, physical profile captured from the live target pg_catalog,
    data_sources$ companion when templates exist. Re-check engine main for current production
    blockers (data_sources$, removes, immutable resume, production_selectable, certified range)
    before promising a load.
  5 Package discipline — immutable released SPKG by SHA-256; module hashes/initial blocks/
    output types are the cache contract; Store writers isolated from maps; shard Stores that
    can exceed the 2 GiB server limit on full history; never call a host-built SPKG production.
  6 Noop warm-up (cache) vs no-op resume (certification) — define both; warm-up runs the
    producer module over [initial block, target) in production mode via the k8s workflow;
    coordinate shared tier2 capacity; trace long requests with trace-substreams-request.
  7 Backfill — blue/green only: inactive, paused Graphman copy on a second shard; every Graph
    Node writer for source and target at zero replicas; first checkpoint captured from the
    exact target schema; atomic segments; capacity + writer-exclusion rechecked each segment.
    Detailed steps: k8s-subgraphs operate-subgraph-backfill-workflows.
  8 Parity and certification — zero-difference entity/temporal/PoI parity over pinned ranges
    vs an independent native copy, sequence audit, historical GraphQL, no-op resume,
    continuation, rewind/replay; differential check vs a reference indexer before allocation.
  9 Landing — completion leaves a paused inactive copy; activation, rewind-to-head handoff and
    allocation need explicit approval → subgraphs-onboard-deployment completion gates.

What not to claim (fixture ≠ production; running job ≠ backfill; Ready pod ≠ safe to read)
```

**`references/` files:**

- `references/target-inventory.md`: the checklist for stage 2, with Graph Node v0.44 behaviours that break naive reimplementations: entity cache merge vs save order, PoI per handler group, `start_handler` regions, templates, removes, immutables and id types. Cite `substreams-backfills/docs/block-changes-v1.md`.
- `references/engine-producer-contract.md`: the stage 3 and 4 checklist (descriptor fields, `substreams-native` invocation, refusal list, how to check blockers on engine `main`). It quotes engine docs **with paths only, not copied values**.

**Optional `scripts/`:**

- `scripts/estimate-sync-eta.py`: read-only. It queries VictoriaMetrics for one deployment's head and the chain head over 24-hour and 72-hour windows and prints the diagnostic ETA. Label it "diagnostic, not M0 evidence". The authoritative verifier is `cargo xtask verify-targets` in substreams-backfills.
- Needs `scripts/tests/test_*.py` offline fixtures (pattern: `test_egress_helpers.py`, `test_data_rpc_helpers.py`).
- Uses the Grafana MCP or an env token; no shell sourcing.

**`agents/openai.yaml`:**

```yaml
interface:
  display_name: "Develop a Subgraph Backfill Substreams"
  short_description: "Make a subgraph's history Substreams-backfillable"
  default_prompt: "Use $develop-subgraph-backfill-substreams to assess eligibility and plan the Substreams producer, noop and backfill for this deployment."
```

**Keep out of the skill** (`AGENTS.md:116-117`):

- Aerodrome identities and ETAs. Use them only as a dated example in the PR body or `docs/reviews/`.
- `sgd`/shard numbers.
- Image digests and SPKG hashes. Those belong to target bindings and k8s overlays.

### 3.2 k8s-subgraphs: `operate-subgraph-backfill-workflows` (new runbook skill)

**Name.** Mirrors pinax-skills `operate-subgraph-transplant-queue` (Argo queue operations). It is verb-first and does not collide with `backfill-subgraph`.

**Description draft** (single line works in both repos; k8s-subgraphs has no audit, but a single line keeps it portable):

> Submit, monitor and clean up the generic Substreams subgraph-backfill Argo workflows in subgraphs-backfill — a noop warm-up of the producer package over the target range, then the segmented backfill into a stopped inactive Graphman copy with its preflight and approval gates. Use when running noop or backfill for a deployment other than the certified Uniswap V4 Base lane, when a backfill workflow is Pending, suspended or failed, or when reading backfill_* progress. Full runbook: docs/subgraph-substreams-backfill-workflows.md.

**What belongs here (micro, repository-specific):**

- WorkflowTemplate names and parameters: deployment, spkg URL and SHA-256, module, start and stop, segment size, parallel workers, endpoint (`<chain>.substreams.<cluster>.pinax.io:80 --plaintext` or authenticated), target schema, expected seed block and hash.
- The kubeconfig role.
- `argo submit --from workflowtemplate/…` examples.
- Approval suspend nodes and how to release exactly one.
- Mutexes and semaphores.
- PVC and storage placement rules (`docs/pre-wave-capacity-gate.md`; never dom157).
- `backfill_*` metrics and dashboard.
- Argo stop semantics (exit 143 means a manual stop; carry this from `operate-token-api-sinks/SKILL.md:222-227`).
- `podGC` choices (noop keeps failed pods for wasm panic logs).
- Cleanup.
- CI: the templates must be under a kustomization linted by `ci.yaml:67-75`.

**Required alongside the skill** (`k8s-subgraphs/AGENTS.md:92-93,132-134`):

- a `docs/subgraph-substreams-backfill-workflows.md` runbook;
- an entry in `AGENTS.md` `## Skills`;
- a README mention if the namespace or stack inventory changes.

**Avoiding duplication with `backfill-subgraph`:**

- Keep `backfill-subgraph` as the V4 lane. Change its description to "…Uniswap V4 Base production lane (sgd1246/univ4base_b)…", and add a first-line pointer to the generic skill.
- The generic runbook should **reference**, not restate, the shared safety rules: writer exclusion, seed capture and immutable seed. Ideally those rules move into one runbook section that both skills cite: `docs/substreams-graph-node-backfill.md` `## Isolation and data flow`, `:51-84`.

### 3.3 Owner-repo follow-ups (not pinax-skills; optional, separate PRs)

- **substreams-backfills.** Add root `AGENTS.md`, `CLAUDE.md -> AGENTS.md` and `.claude/skills -> ../.agents/skills`. Optionally add a repo-local `add-subgraph-backfill-family` skill:
  - family directory layout `<family>/<Qm>.yaml` (`README.md:281-287`);
  - `cargo xtask verify-target`;
  - the evidence-assets moratorium;
  - Rust-only tooling, so no Python or shell helpers.
  - This is where per-family "how we freeze a target" detail lives.
- **engine.** Refresh the `AGENTS.md` Mission and code map for the block-changes, generic-state and physical-profile modules.

### 3.4 What goes where

| Content | pinax-skills `develop-subgraph-backfill-substreams` | k8s-subgraphs `operate-subgraph-backfill-workflows` / runbook | substreams-backfills / engine docs |
|---|---|---|---|
| Eligibility rule and decision | rule and stop or go | — | formula, evidence schema, `xtask` |
| Target freeze and semantic inventory | checklist and why | — | per-family closure and profile |
| Producer architecture choice | decision criteria | — | implementation |
| BlockChanges, descriptor and profile contract | checklist plus "re-check blockers" | image and descriptor pins in overlays | normative spec |
| Noop warm-up | purpose, when, capacity routing | templates, parameters, submit and monitor | — |
| Backfill load | gates (blue/green, writer exclusion, seed) | exact commands, suspends, mutexes, storage | engine flags and refusals |
| Parity and certification | required evidence list | certification workflow template | verifiers |
| Landing and allocation | handoff to `subgraphs-onboard-deployment` | activation steps | — |
| Target-specific IDs, dates, digests | **never** | dated docs | bindings |

---

## 4. PR and commit conventions to mirror

**pinax-skills** (VERIFIED via `gh pr list`/`gh pr view` and `git log`):

- **Branch names on recent merges:**
  - `pinax-skills/feat/audit-pinax-github-repos` (#167), `pinax-skills/docs/<slug>` (#171, #165, #164, …);
  - `claude/<slug>` (#172, #168, #147 by Denis), `feat/<slug>` (#169, #166), `docs/<slug>`, `fix/<slug>`.
  - `create-pull-request/SKILL.md:41` prescribes `<type>/<short-slug>`. Both `pinax-skills/feat/develop-subgraph-backfill-substreams` (the orchestrator's suggestion) and `feat/develop-subgraph-backfill-substreams` are consistent with history.
- **Title:** `🤖 [claude] <Imperative sentence, sentence case, no trailing period>` (`create-pull-request/SKILL.md:94-104`). Example of the pattern: "🤖 [claude] Add the JavaScript supply-chain skill and repo checker" (#168). Suggested: "🤖 [claude] Add develop-subgraph-backfill-substreams for Substreams subgraph backfills".
- **Commits:** imperative sentence case, no conventional-commit prefix. New-skill PRs split into:
  - "Add <skill> skill";
  - "Index <skill> in the README catalogue";
  - "Route <requests> to <skill> in AGENTS.md" (#166),
  - or "Index the three new skills in AGENTS.md and README.md" plus "Add trigger rows for … to AGENTS.md" (#169).
  - Merges are either a merge commit (#167, #169) or a squash (`(#175)`).
- **Body:**
  - `## Summary` bullets: what and why, with indexing noted;
  - `## Test plan` with checked boxes for `python3 scripts/audit-skills.py` (with the skill count) and `python3 -m unittest discover -s scripts/tests`, plus an unchecked `CI green`;
  - then `---` and `🤖 Created by Claude <exact model> (effort: <level or "not exposed by this session">)`;
  - session footers from the harness (#169, #168).
- **Rules:** never push to `main`; use a feature branch, then a PR (`AGENTS.md:134-136`); work in an isolated worktree (`work-in-isolated-worktree`). Commit attribution for this session is the harness trailer (`Co-Authored-By: Claude Opus 5.5 …` plus `Claude-Session:`).

**k8s-subgraphs:**

- Branches: `claude/<slug>` (#1142, #1136, …), `codex/<slug>`.
- Titles: `🤖 [claude] <Imperative sentence>`.
- CI gates: `shard-config-drift`, `kustomize-build`, and the backfill workflow lint (`AGENTS.md:70-72`; `ci.yaml:67-75`).
- Branch protection: squash-merge.

**substreams-backfills:**

- Conventional-commit titles: `feat(mapping-host): …`, `fix(runtime): …`, `docs: …`.
- Branches: `codex/<slug>`, `feat/<issue>-<slug>`.

---

## 5. Decisions needed

1. Skill names: pinax-skills `develop-subgraph-backfill-substreams` and k8s-subgraphs `operate-subgraph-backfill-workflows` (or alternatives).
2. Whether to rescope k8s-subgraphs `backfill-subgraph` to V4-only, as proposed, or fold the generic runbook into it. Folding risks mixing distinct acceptance gates (`pinax-skills/AGENTS.md:242`).
3. Whether the generic skill names a **preferred producer architecture**: a Substreams module emitting BlockChanges, or mapping-host over Firehose plus an eth_call cassette. The user asked for "a Substreams"; the engine accepts either through BlockChanges v1.
4. Whether to add the diagnostic ETA helper script to pinax-skills. That needs offline tests and must not duplicate the Rust `xtask` verifier.
5. Whether this PR also fixes the hygiene items:
   - the registry skill count;
   - the README developer-deferral clause;
   - the angle brackets in the `operate-token-api-sinks` description;
   - in k8s-subgraphs, the three missing "Use when" triggers and the unlisted `verify-disposable-v3-root`.

## 6. Risks and blockers relevant to the skills

- **Engine production blockers (DOC-CLAIM).** The engine's generic path is not yet production-loadable:
  - `data_sources$` for templated manifests is offline-only (v2 chunks) or root and 10k-block bounded (v1);
  - committed removes are refused;
  - immutable tables cannot be resumed across;
  - no profile is production-selectable.
  - **Effect:** a skill that promises an end-to-end Aerodrome load today would overclaim. Aerodrome has a Pool template.
- **Engine `main` has been idle since 2026-09-07.** Meanwhile substreams-backfills `mapping-host` merged producer-side work (PRs #139–#147). The skill must say "re-check engine `main` and open PRs" rather than freeze today's blocker list.
- **Shared tier2.** A full-range noop over about 39M Base blocks is a large tier2 load that riv tier1 also depends on (`operate-firehose-substreams/SKILL.md:222-227`). The skills must require capacity coordination and parallel-worker caps.
- **Audit traps.**
  - Folded YAML descriptions silently fail the "Use when" check (VERIFIED).
  - `/home/…` or `/Users/…` anywhere in a skill file, scripts included, fails the audit.
  - Copying k8s-subgraphs text verbatim brings in `~/.kube/...` and `denis-cli` references that violate the portability prose rules.
- **Undiscoverable skill.** `certify-backfill-successor` lives in a repo with no `CLAUDE.md` or `.claude/skills`, so it is invisible to Claude Code until that repo adopts the four-file contract.
