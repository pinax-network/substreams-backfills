# Uniswap V3 parity contract

This file separates what the imported parity source proves from the work still
required before either deployment can be loaded or served.

## Proven by the import

The exact source tree at commit
`42c7b15345e6df80561b694e52a0eb622b374b96` contains 20 GraphQL entity types.
After entity directives are excluded, its complete entity/field/type contract
has SHA-256
`6c801fc4c141c0ae12dbb937652f0dd49c9be5bd3b1b3c8e38bdb92fe6efec5d`,
which matches the schema stored at IPFS CID
`Qma8a81T9XoX5Pbkrk8J3kxMhWdXJzFSYZge1wGi3QZBru`.

The source changes relative to its upstream base are:

- output field renames for `tvlUSD` and `untrackedVolumeUSD` while retaining
  the original Store key names;
- removal of `Pool.totalValueLockedETHUntracked`, which is absent from the
  target schema;
- `TickDayData` and `TickHourData` output wiring using
  `0x{pool}#{tick}-{time_id}` identities and initialized aggregate fields.

The import CI executes those exact `db.rs` functions from an external Rust 1.79
contract-test crate. Deterministic day/hour create fixtures pin entity IDs,
timestamps, zero defaults, and field sets; update fixtures pin gross/net values
and deletion filtering. This exercises the imported implementation while
leaving its source tree byte-identical to the reviewed commit.

The 20-type schema is not a claim that all 20 entity rows are currently
emitted. In this frozen source, `Collect` events update positions but do not
create `Collect` rows, and the `Flash` extraction/emission path is commented
out. The fixed-range certificate therefore reports only the nonempty observed
entity subset and keeps `Collect` and `Flash` as explicit follow-up work. It
must not be described as authoritative 20-entity coverage or a final package.

The target declares `Transaction`, `Swap`, `Mint`, and `Burn` as mutable. The
imported logical schema declares those four entities immutable. That is a real
physical-layout difference which the future schema profile and loader must
handle; it is not erased by the logical contract match.

## Evidence not yet sufficient for certification

The previously reported 50-block Firehose run is useful smoke evidence, but no
block-hash-bound output, query response, or evidence digest was retained in this
repository. It cannot certify every handler or entity, tick identity parity,
zero-value behavior, temporal rows, or proof of indexing.

The frozen source remains Ethereum-mainnet-specific, but the versioned
`chain-config/` overlay now externalizes the complete audited factory, position
manager, start-boundary, pricing, whitelist, filter, and metadata contract.
Every consuming handler validates an exact digest-bound selector before output.
CI builds one materialized WASM and parses both diagnostic packages to prove
that their embedded WASM bytes match, while recording the expected distinct
per-chain execution hashes.

The configuration architecture is therefore no longer the certification
blocker. A versioned mainnet logical-parity profile and fail-closed offline
verifier now make the first remaining comparison reproducible, but this
repository change does not execute that live comparison. Representative Base
Firehose/reference parity and a controlled production package freeze also
remain outstanding.

## Mainnet ChainConfig logical-parity gate

[`fixtures/mainnet-chain-config-parity-v1.json`](fixtures/mainnet-chain-config-parity-v1.json)
locks the continuous half-open range `[12,369,621, 12,370,674)`. Its boundaries
come from repository-held evidence:

- `12,369,621` is the imported module/factory start;
- `12,369,651` is the versioned mainnet position-manager start; and
- historical commit `d3e5384b3ef47c78e8a1404b3c33de1ae8a78e3a`
  records a first-mints smoke slice beginning at `12,370,624`, so the profile
  retains that 50-block slice through exclusive stop `12,370,674`.

The old smoke run did not retain canonical block hashes or an output digest. It
selects a useful range; it is not imported into the new certificate as parity
evidence.

The official Substreams v1.20.3 CLI renderer cannot prove this range complete:
its JSONL mode omits zero-byte map outputs and its sink treats an early EOF as
success. The harness therefore does not use `substreams run` for parity. A
repository-owned Go 1.26.5 client calls only
`/sf.substreams.rpc.v3.Stream/Blocks`, using the v1.20.3 package closure pinned
to commit `cc555bd4e325b65ac3f95dfde4655076f88d4a0a` and tree
`38ea588549e5e41698da00ee149278aa2d855c64`. The official checksum-pinned CLI
remains limited to `pack` and `info` during the controlled build.

The client sends one exact development-mode, final-only protocol-v3 request per
package. It disables production, noop, partial-block, snapshot, parameter, and
retry behavior; requests only `graph_out`; caps processed blocks at 1,053; and
accepts completion only after a real EOF following exactly one session and all
1,053 sequential block responses. Progress messages are ignored for counting.
Undo, fatal, partial, snapshot, nil, unknown, debug-output, type, module,
finality, cursor, range, or extra-response drift fails closed. Every response,
including a zero-byte map output, retains the block number, lowercase hash,
UTC protobuf timestamp seconds/nanoseconds, exact map bytes in canonical
base64, byte length, map digest, and cursor digest. No absent record is ever
reconstructed. The opaque cursor must carry either the irreversible-only or
new-plus-irreversible step, with both its block and LIB bound to the same clock
number and hash.

The capture client is built with `CGO_ENABLED=0`, `-mod=readonly`, `-trimpath`,
and no build ID. Its source, tests, `go.mod`, `go.sum`, Go toolchain, complete
package dependency inventory, binary module build information and sums, binary
hash/size, and v1.20.3 upstream commit/tree are retained. The v3 package has a
broader v1.20.3 closure than generated protobuf alone. A package-less local
replacement permits public module resolution, while both `go list -deps` and
binary build information must prove that the private
`services-control-plane` module never enters runtime code.
The exact `go.mod` plus package-less replacement pair is also retained as one
public module-graph patch digest.

Each stream completion binds a common 256-bit session, unique invocation ID,
role, exact source revision, credential-free Substreams endpoint, auth kind,
sanitized arguments, request digest, package hash/size, capture-client
hash/size, wrapper/client clock bounds, all record bytes, and clean EOF. The
exclusive wrapper hashes raw stdout/stderr, scans them and its sidecar for the
supplied credential, and atomically publishes only a fully validated capture.
This is local provenance, not a signed service attestation.

Before and after both streams, the runner requests all 1,053 canonical Ethereum
mainnet block headers in batches of at most 50. It requires chain ID `0x1`, the
exact number/hash/timestamp for every block, unchanged before/after maps, and
clock bounds that surround both captures. Only a separately supplied, explicit
nonsecret RPC label is retained; no origin or identifier is derived from the
secret RPC URL.

`scripts/verify-uniswap-v3-mainnet-chain-config-parity.py` rejects duplicate
JSON keys, invalid UTF-8, floats, non-finite numbers, trailing data, malformed
protobuf/base64, missing/duplicate/extra blocks, early EOF, completion replay,
fork drift, timestamp drift, package/client/source drift, or stronger trust
claims. It compares the exact ordered `EntityChanges` protobuf bytes and
requires at least one nonempty output and equal nonempty observed entity
coverage. It does not claim all 20 schema entities were exercised.

The certificate binds the exact repository/source commit and tree,
import/config/overlay/target-schema identities, all three package and WASM
digests, every module execution hash, toolchain/platform identity, exact
checksum-approved CLI binary and version, credential-free Substreams endpoint
and public RPC label, exact source-built capture-client identity, two invocation
sidecars, raw stdout/stderr hashes, before/after full-range RPC evidence,
complete canonical streams, counts, timestamps, and observed entity coverage.
Every candidate byte payload—including the client, packages, build manifest,
RPC snapshots, raw streams, sidecars, and certificate—is scanned for supplied
secrets before publication, and the final retained set is scanned again.
Outputs are installed by exclusive atomic links and made read-only or
owner-executable as appropriate.

The live runner contract is deliberately separate from CI and must execute from
an exact detached revision. It requires credentials only through environment
variables, removes them from the build environment, rejects credential-bearing
Substreams endpoints, never derives retained data from the secret RPC URL,
captures every Ethereum mainnet block hash and timestamp before and after both
calls, and gives both packages the same endpoint, range, final-only setting,
and processed-block limit. It also builds the
configured Base package so the one-WASM/two-package invariant remains attached
to the candidate. Temporary materialization and raw-capture paths are removed
on success. Any nonzero exit or interruption makes a best-effort removal of the
prevalidated, newly created evidence directory, including failures that occur
while cleaning the outer exact-revision worktree. Exit status zero is required
for evidence validity; any path surviving an operating-system cleanup failure
is invalid and must not be treated as a parity certificate.

An operator with separately approved endpoint access can invoke it from the
repository root as follows; the artifact directory must be new and outside the
repository checkout:

```bash
export SOURCE_REVISION=<exact-40-character-repository-commit>
export SUBSTREAMS_ENDPOINT=<credential-free-host:port>
export SUBSTREAMS_API_TOKEN=<read-from-a-secret-store>
export ETHEREUM_RPC_URL=<read-from-a-secret-store>
export ETHEREUM_RPC_LABEL=<explicit-public-provider-label>
export UNISWAP_V3_MAINNET_PARITY_LIVE_ACK=run-fixed-mainnet-range-12369621-12370674
./scripts/run-uniswap-v3-mainnet-chain-config-parity.sh /new/private/evidence-directory
```

Ordinary CI performs no Substreams `run` or Ethereum RPC calls. It reuses the
three diagnostic packages already built by the V3 job and emits a
`controlled-build-candidate.json` bound to the actual pull-request head (or
push) commit. The candidate rejects a version-prefix collision and records the
platform-specific archive and binary checksums for the exact official v1.20.3
CLI used to inspect the packages. That candidate is useful build provenance,
but the CI job also builds and tests the pinned Go client, proves the private
replacement is absent from its dependency graph, and checks all three real
packages against the client package contract. The mutable hosted runner is not
the approved release environment and the manifest is explicitly
`candidate-not-a-production-pin`.

Every resulting certificate hard-codes these boundaries:

- `promotion_eligible: false`;
- `authoritative_graph_reference: false`;
- `physical_or_poi_parity: false`;
- `production_pin: false`; and
- `approved_runtime_contract: null`.

A successful retained live certificate can satisfy only issue #12's fixed-range
logical protobuf equality criterion. It cannot establish Collect/Flash row
implementation, complete 20-entity coverage, authoritative Graph reference
parity, Graph Node temporal/physical history, proof of indexing, the ordered
engine protocol, a production package pin, or permission to deploy or promote.

Finally, `graph_out` emits standard coalesced `EntityChanges`. That format does
not by itself preserve every intermediate save, empty-but-triggered handler, or
causality detail needed for exact Graph Node proof of indexing. Physical and PoI
certification therefore waits for the V4-derived ordered protocol, schema
profiles, and generic verifier.

The CI-built SPKG is likewise diagnostic: CI checks the package name/version,
mainnet network, exact 22-module set, initial block, and `graph_out` output type,
but does not freeze environment-dependent package or WASM bytes. The immutable
dual-chain production package remains a later controlled-release output; CI
packages are diagnostic and are not frozen here.

## Required order

1. Preserve this exact source import and hermetic logical checks.
2. Use the pinned mainnet/Base `ChainConfig` and retain a successful fixed-range
   mainnet logical-parity certificate from the exact-revision runner.
3. Capture canonical Base Firehose fixtures and authoritative historical
   GraphQL or read-only database evidence for every handler and aggregate
   boundary.
4. Certify mainnet through the generic ordered runtime against an exact stopped
   oracle and disposable scratch target.
5. Land mainnet only in named, revalidated targets, paused.
6. Repeat exact certification for Base with the same WASM and its pinned config;
   land paused and request activation separately.
