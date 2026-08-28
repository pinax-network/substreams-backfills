#!/usr/bin/env bash
set -euo pipefail

readonly range_start=12369621
readonly range_stop=12370674
readonly range_blocks=$((range_stop - range_start))
readonly live_ack_expected="run-fixed-mainnet-range-${range_start}-${range_stop}"
readonly substreams_version_expected="substreams version 1.20.3 (Commit cc555bd, Commit Date 2026-07-31T14:30:54Z)"
readonly go_version_pattern='^go version go1\.26\.5 (darwin|linux)/(amd64|arm64)$'

fail() {
    echo "Uniswap V3 mainnet ChainConfig parity run refused: $*" >&2
    exit 1
}

(( $# == 1 )) || fail "usage: SOURCE_REVISION=<40-hex> SUBSTREAMS_ENDPOINT=<host:port> ETHEREUM_RPC_URL=<secret-url> ETHEREUM_RPC_LABEL=<public-label> $0 <new-artifact-directory>"

source_revision=${SOURCE_REVISION:-}
[[ "$source_revision" =~ ^[0-9a-f]{40}$ ]] || fail "SOURCE_REVISION must be an exact lowercase commit"
[[ ${UNISWAP_V3_MAINNET_PARITY_LIVE_ACK:-} == "$live_ack_expected" ]] \
    || fail "set UNISWAP_V3_MAINNET_PARITY_LIVE_ACK=$live_ack_expected"

substreams_endpoint=${SUBSTREAMS_ENDPOINT:-}
[[ "$substreams_endpoint" =~ ^[A-Za-z0-9.-]+:[0-9]+$ ]] || fail "SUBSTREAMS_ENDPOINT must be a credential-free DNS host:numeric-port"
substreams_port=${substreams_endpoint##*:}
(( 10#$substreams_port >= 1 && 10#$substreams_port <= 65535 )) || fail "SUBSTREAMS_ENDPOINT port is invalid"
python3 - "$substreams_endpoint" <<'PY' || fail "SUBSTREAMS_ENDPOINT DNS target is malformed"
import ipaddress
import re
import sys
host = sys.argv[1].rsplit(":", 1)[0]
try:
    ipaddress.ip_address(host)
except ValueError:
    pass
else:
    raise SystemExit(1)
label = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
if len(host) > 253 or not all(label.fullmatch(part) for part in host.split(".")):
    raise SystemExit(1)
PY
substreams_api_token=${SUBSTREAMS_API_TOKEN:-}
substreams_api_key=${SUBSTREAMS_API_KEY:-}
if [[ -n $substreams_api_token && -n $substreams_api_key ]] || [[ -z $substreams_api_token && -z $substreams_api_key ]]; then
    fail "set exactly one of SUBSTREAMS_API_TOKEN or SUBSTREAMS_API_KEY"
fi
credential_value=${substreams_api_token:-$substreams_api_key}
(( ${#credential_value} >= 16 )) || fail "Substreams credential is too short for reliable redaction scanning"

ethereum_rpc_url=${ETHEREUM_RPC_URL:-}
[[ "$ethereum_rpc_url" == https://* && ${#ethereum_rpc_url} -ge 16 ]] || fail "ETHEREUM_RPC_URL must be a nonempty HTTPS secret URL"
[[ "$ethereum_rpc_url" != *$'\n'* && "$ethereum_rpc_url" != *$'\r'* ]] || fail "ETHEREUM_RPC_URL contains control characters"
ethereum_rpc_label=${ETHEREUM_RPC_LABEL:-}
[[ "$ethereum_rpc_label" =~ ^[A-Za-z][A-Za-z0-9._-]{0,63}$ ]] || fail "ETHEREUM_RPC_LABEL must be an explicit short public label"
unset SUBSTREAMS_API_TOKEN SUBSTREAMS_API_KEY ETHEREUM_RPC_URL

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
artifact_arg=$1
artifact_dir=$(python3 - "$artifact_arg" "$PWD" <<'PY'
import sys
from pathlib import Path
value = Path(sys.argv[1])
if not value.is_absolute():
    value = Path(sys.argv[2]) / value
print(value.resolve(strict=False))
PY
)
[[ ! -e "$artifact_dir" ]] || fail "artifact directory already exists"
[[ -d "$(dirname "$artifact_dir")" ]] || fail "artifact parent directory does not exist"
case "$artifact_dir/" in
    "$repo_dir/"*) fail "artifact directory must be outside the repository checkout" ;;
esac

for tool in cargo git go python3 rustc substreams; do
    command -v "$tool" >/dev/null || fail "required tool is unavailable: $tool"
done
[[ $(go version) =~ $go_version_pattern ]] || fail "exact Go 1.26.5 is required"
[[ $(substreams --version) == "$substreams_version_expected" ]] || fail "exact official Substreams v1.20.3 identity is required"

if [[ ${UNISWAP_V3_PARITY_EXACT_CHECKOUT:-} != "$source_revision" ]]; then
    git -C "$repo_dir" cat-file -e "${source_revision}^{commit}" 2>/dev/null || fail "SOURCE_REVISION is unavailable"
    temporary_root=$(mktemp -d "${TMPDIR:-/tmp}/uniswap-v3-mainnet-parity.XXXXXXXX")
    exact_checkout=$temporary_root/repository
    outer_succeeded=0
    cleanup_parent_best_effort() {
        if (( outer_succeeded == 0 )); then
            rm -rf -- "$artifact_dir" >/dev/null 2>&1 || true
        fi
        if [[ -d "$exact_checkout" ]]; then
            git -C "$repo_dir" worktree remove --force "$exact_checkout" >/dev/null 2>&1 || true
        fi
        rmdir "$temporary_root" >/dev/null 2>&1 || true
    }
    trap cleanup_parent_best_effort EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    git -C "$repo_dir" worktree add --detach "$exact_checkout" "$source_revision" >/dev/null
    child_status=0
    SOURCE_REVISION="$source_revision" \
        SUBSTREAMS_ENDPOINT="$substreams_endpoint" \
        SUBSTREAMS_API_TOKEN="$substreams_api_token" \
        SUBSTREAMS_API_KEY="$substreams_api_key" \
        ETHEREUM_RPC_URL="$ethereum_rpc_url" \
        ETHEREUM_RPC_LABEL="$ethereum_rpc_label" \
        UNISWAP_V3_MAINNET_PARITY_LIVE_ACK="$live_ack_expected" \
        UNISWAP_V3_PARITY_EXACT_CHECKOUT="$source_revision" \
        bash "$exact_checkout/scripts/run-uniswap-v3-mainnet-chain-config-parity.sh" "$artifact_dir" || child_status=$?
    git -C "$repo_dir" worktree remove --force "$exact_checkout" >/dev/null || fail "could not remove exact-revision worktree"
    rmdir "$temporary_root" || fail "could not remove exact-revision worktree parent"
    (( child_status == 0 )) || exit "$child_status"
    outer_succeeded=1
    trap - EXIT INT TERM
    exit 0
fi

[[ $(git -C "$repo_dir" rev-parse --verify 'HEAD^{commit}') == "$source_revision" ]] || fail "exact checkout HEAD differs from SOURCE_REVISION"
git -C "$repo_dir" symbolic-ref -q HEAD >/dev/null && fail "execution checkout must be detached"
[[ -z $(git -C "$repo_dir" status --porcelain --untracked-files=all) ]] || fail "exact execution checkout is dirty"

umask 077
mkdir "$artifact_dir"
runtime_dir=$artifact_dir/.runtime
capture_dir=$artifact_dir/.capture
mkdir "$runtime_dir" "$capture_dir"
run_succeeded=0
cleanup_inner_best_effort() {
    if (( run_succeeded == 0 )); then
        rm -rf -- "$artifact_dir"
    else
        rm -rf -- "$runtime_dir" "$capture_dir"
    fi
}
trap cleanup_inner_best_effort EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

profile=$repo_dir/uniswap-v3/fixtures/mainnet-chain-config-parity-v1.json
baseline_spkg=$runtime_dir/uniswap-v3-mainnet-baseline.spkg
mainnet_spkg=$runtime_dir/uniswap-v3-mainnet-configured.spkg
base_spkg=$runtime_dir/uniswap-v3-base-configured.spkg
build_manifest=$runtime_dir/controlled-build-candidate.json
rpc_before=$capture_dir/ethereum-rpc-before.json
rpc_after=$capture_dir/ethereum-rpc-after.json
capture_client_build=$runtime_dir/uniswap-v3-parity-client.build
capture_client=$runtime_dir/uniswap-v3-parity-client
session_id=$(python3 -c 'import secrets; print(secrets.token_hex(32))')

(
    cd "$repo_dir/scripts/parity-client"
    GOTOOLCHAIN=local go mod verify
    GOTOOLCHAIN=local go test -mod=readonly ./...
    GOTOOLCHAIN=local go vet -mod=readonly ./...
    if GOTOOLCHAIN=local go list -mod=readonly -deps ./... | grep -F 'services-control-plane'; then
        fail "private services-control-plane replacement entered the capture-client dependency graph"
    fi
    CGO_ENABLED=0 GOTOOLCHAIN=local go build -mod=readonly -trimpath -buildvcs=false -ldflags=-buildid= -o "$capture_client_build" .
)
mv "$capture_client_build" "$capture_client"
chmod 0500 "$capture_client"
[[ $($capture_client --version) == "uniswap-v3-mainnet-parity-client-v1 (protocol v3; upstream v1.20.3 cc555bd4e325b65ac3f95dfde4655076f88d4a0a)" ]] \
    || fail "capture-client version identity drift"

"$repo_dir/scripts/verify-uniswap-v3-import.sh"
python3 "$repo_dir/scripts/build-uniswap-v3-chain-manifests.py" --root "$repo_dir" --check
python3 "$repo_dir/scripts/verify-uniswap-v3-chain-config.py" --root "$repo_dir"
(
    cd "$repo_dir/uniswap-v3/source"
    cargo build --locked --target wasm32-unknown-unknown --release
)
git -C "$repo_dir" diff --quiet -- uniswap-v3/source || fail "baseline build changed the frozen import"
substreams pack -o "$baseline_spkg" "$repo_dir/uniswap-v3/source/substreams.yaml"
python3 "$repo_dir/scripts/verify-uniswap-v3-diagnostic-package.py" "$baseline_spkg"

"$repo_dir/scripts/materialize-uniswap-v3-chain-config.sh" "$runtime_dir/configured"
(
    cd "$runtime_dir/configured"
    cargo build --locked --target wasm32-unknown-unknown --release
    substreams pack -o "$mainnet_spkg" substreams.mainnet.yaml
    substreams pack -o "$base_spkg" substreams.base.yaml
)
python3 "$repo_dir/scripts/verify-uniswap-v3-chain-config.py" \
    --root "$repo_dir" --runtime "$runtime_dir/configured" \
    --mainnet-spkg "$mainnet_spkg" --base-spkg "$base_spkg" \
    --evidence-out "$runtime_dir/configured-package-evidence.json"
python3 "$repo_dir/scripts/build-uniswap-v3-mainnet-parity-candidate.py" \
    --root "$repo_dir" --source-revision "$source_revision" --profile "$profile" \
    --baseline-spkg "$baseline_spkg" --mainnet-spkg "$mainnet_spkg" --base-spkg "$base_spkg" \
    --capture-client "$capture_client" --output "$build_manifest"

capture_rpc_snapshot() {
    local phase=$1
    local output=$2
    ETHEREUM_RPC_URL="$ethereum_rpc_url" ETHEREUM_RPC_LABEL="$ethereum_rpc_label" \
        python3 - "$phase" "$output" "$session_id" <<'PY'
from __future__ import annotations
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

START = 12369621
STOP = 12370674
BATCH = 50
phase, output, session_id = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
url = os.environ["ETHEREUM_RPC_URL"]
label = os.environ["ETHEREUM_RPC_LABEL"]

def reject_pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value

def reject_number(value):
    raise ValueError(f"forbidden JSON number: {value}")

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "redirect forbidden", headers, fp)

opener = urllib.request.build_opener(NoRedirect())

def rpc(payload):
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, separators=(",", ":")).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with opener.open(request, timeout=30) as response:
        if response.status != 200 or response.headers.get_content_type() != "application/json":
            raise ValueError("unexpected RPC HTTP response")
        raw = response.read(64 * 1024 * 1024 + 1)
    if len(raw) > 64 * 1024 * 1024:
        raise ValueError("RPC response too large")
    return json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=reject_pairs, parse_float=reject_number, parse_constant=reject_number)

started = time.time_ns()
chain = rpc({"jsonrpc": "2.0", "id": "chain", "method": "eth_chainId", "params": []})
if not isinstance(chain, dict) or set(chain) != {"jsonrpc", "id", "result"} or chain != {"jsonrpc": "2.0", "id": "chain", "result": "0x1"}:
    raise ValueError("RPC is not Ethereum mainnet")
blocks = {}
request_count = 0
previous_timestamp = None
for first in range(START, STOP, BATCH):
    numbers = list(range(first, min(first + BATCH, STOP)))
    requests = [
        {"jsonrpc": "2.0", "id": str(number), "method": "eth_getBlockByNumber", "params": [hex(number), False]}
        for number in numbers
    ]
    response = rpc(requests)
    request_count += 1
    if not isinstance(response, list) or len(response) != len(numbers):
        raise ValueError("RPC batch cardinality drift")
    by_id = {}
    for item in response:
        if not isinstance(item, dict) or set(item) != {"jsonrpc", "id", "result"} or item["jsonrpc"] != "2.0":
            raise ValueError("malformed RPC response")
        if item["id"] in by_id:
            raise ValueError("duplicate RPC response ID")
        by_id[item["id"]] = item["result"]
    if set(by_id) != {str(number) for number in numbers}:
        raise ValueError("RPC response IDs drift")
    for number in numbers:
        block = by_id[str(number)]
        if not isinstance(block, dict) or block.get("number") != hex(number):
            raise ValueError("RPC block number drift")
        digest, timestamp_hex = block.get("hash"), block.get("timestamp")
        if not isinstance(digest, str) or re.fullmatch(r"0x[0-9a-f]{64}", digest) is None:
            raise ValueError("RPC block hash malformed")
        if not isinstance(timestamp_hex, str) or re.fullmatch(r"0x[0-9a-f]+", timestamp_hex) is None:
            raise ValueError("RPC timestamp malformed")
        timestamp = int(timestamp_hex, 16)
        if timestamp <= 0 or (previous_timestamp is not None and timestamp <= previous_timestamp):
            raise ValueError("RPC timestamps are not strictly increasing")
        previous_timestamp = timestamp
        blocks[str(number)] = {"number": number, "hash": digest, "timestamp_seconds": timestamp}
completed = time.time_ns()
canonical = json.dumps(blocks, sort_keys=True, separators=(",", ":")).encode()
document = {
    "format_version": 1,
    "kind": "uniswap-v3-mainnet-parity-ethereum-rpc-snapshot",
    "session_id": session_id,
    "phase": phase,
    "rpc_label": label,
    "network": "mainnet",
    "chain_id": "0x1",
    "range": {"start_block": START, "end_block_exclusive": STOP, "block_count": STOP - START},
    "batches": {"maximum_batch_size": BATCH, "request_count": request_count},
    "clock": {"started_at_unix_nanos": started, "completed_at_unix_nanos": completed, "ordered": True},
    "blocks": blocks,
    "blocks_sha256": hashlib.sha256(canonical).hexdigest(),
    "completed": True,
    "trust_boundary": {
        "promotion_eligible": False, "authoritative_graph_reference": False,
        "physical_or_poi_parity": False, "production_pin": False, "approved_runtime_contract": None,
    },
}
with output.open("x", encoding="utf-8") as handle:
    os.chmod(output, 0o600)
    json.dump(document, handle, sort_keys=True, separators=(",", ":"))
    handle.write("\n")
    handle.flush()
    os.fsync(handle.fileno())
PY
}

capture_invocation() {
    local role=$1
    local package=$2
    SUBSTREAMS_API_TOKEN="$substreams_api_token" SUBSTREAMS_API_KEY="$substreams_api_key" \
        python3 "$repo_dir/scripts/capture-uniswap-v3-mainnet-parity-invocation.py" \
        --session-id "$session_id" --source-revision "$source_revision" --role "$role" \
        --endpoint "$substreams_endpoint" --capture-client "$capture_client" --package "$package" \
        --stdout "$capture_dir/$role.protocol-v3.stdout.jsonl" \
        --stderr "$capture_dir/$role.protocol-v3.stderr" \
        --completion "$capture_dir/$role.protocol-v3.completion.json"
}

capture_rpc_snapshot before "$rpc_before"
capture_invocation baseline "$baseline_spkg"
capture_invocation candidate "$mainnet_spkg"
capture_rpc_snapshot after "$rpc_after"

SUBSTREAMS_API_TOKEN="$substreams_api_token" SUBSTREAMS_API_KEY="$substreams_api_key" ETHEREUM_RPC_URL="$ethereum_rpc_url" \
    python3 - "$runtime_dir" "$capture_dir" <<'PY'
import os
import sys
from pathlib import Path
roots = [Path(value) for value in sys.argv[1:]]
secrets = [os.environ[name].encode() for name in ("SUBSTREAMS_API_TOKEN", "SUBSTREAMS_API_KEY", "ETHEREUM_RPC_URL") if os.environ.get(name)]
for root in roots:
    for path in root.rglob("*"):
        if path.is_file() and not path.is_symlink():
            raw = path.read_bytes()
            if any(secret in raw for secret in secrets):
                raise SystemExit("supplied secret detected in staged artifact")
PY

python3 - \
    "$capture_client" "$artifact_dir/uniswap-v3-parity-client" 0500 \
    "$baseline_spkg" "$artifact_dir/uniswap-v3-mainnet-baseline.spkg" 0444 \
    "$mainnet_spkg" "$artifact_dir/uniswap-v3-mainnet-configured.spkg" 0444 \
    "$base_spkg" "$artifact_dir/uniswap-v3-base-configured.spkg" 0444 \
    "$build_manifest" "$artifact_dir/controlled-build-candidate.json" 0444 \
    "$rpc_before" "$artifact_dir/ethereum-rpc-before.json" 0444 \
    "$rpc_after" "$artifact_dir/ethereum-rpc-after.json" 0444 <<'PY'
import os
import sys
from pathlib import Path

arguments = sys.argv[1:]
if len(arguments) % 3:
    raise SystemExit("invalid staged-artifact publication contract")
published = []
try:
    for offset in range(0, len(arguments), 3):
        source = Path(arguments[offset])
        destination = Path(arguments[offset + 1])
        mode = int(arguments[offset + 2], 8)
        if not source.is_file() or source.is_symlink() or os.path.lexists(destination):
            raise RuntimeError("staged-artifact exclusive publication refused")
        os.link(source, destination, follow_symlinks=False)
        published.append(destination)
        os.chmod(destination, mode, follow_symlinks=False)
    directory = os.open(Path(arguments[1]).parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
except BaseException:
    for destination in reversed(published):
        try:
            destination.unlink()
        except FileNotFoundError:
            pass
    raise
PY

SUBSTREAMS_API_TOKEN="$substreams_api_token" SUBSTREAMS_API_KEY="$substreams_api_key" ETHEREUM_RPC_URL="$ethereum_rpc_url" \
    python3 "$repo_dir/scripts/verify-uniswap-v3-mainnet-chain-config-parity.py" \
    --root "$repo_dir" --profile "$profile" --session-id "$session_id" \
    --substreams-endpoint "$substreams_endpoint" --ethereum-rpc-label "$ethereum_rpc_label" \
    --baseline-stdout "$capture_dir/baseline.protocol-v3.stdout.jsonl" \
    --baseline-stderr "$capture_dir/baseline.protocol-v3.stderr" \
    --baseline-completion "$capture_dir/baseline.protocol-v3.completion.json" \
    --candidate-stdout "$capture_dir/candidate.protocol-v3.stdout.jsonl" \
    --candidate-stderr "$capture_dir/candidate.protocol-v3.stderr" \
    --candidate-completion "$capture_dir/candidate.protocol-v3.completion.json" \
    --build-manifest "$build_manifest" --rpc-before "$rpc_before" --rpc-after "$rpc_after" \
    --artifact-dir "$artifact_dir"

rm -rf -- "$runtime_dir" "$capture_dir"
SUBSTREAMS_API_TOKEN="$substreams_api_token" SUBSTREAMS_API_KEY="$substreams_api_key" ETHEREUM_RPC_URL="$ethereum_rpc_url" \
    python3 - "$artifact_dir" <<'PY'
import os
import sys
from pathlib import Path
secrets = [os.environ[name].encode() for name in ("SUBSTREAMS_API_TOKEN", "SUBSTREAMS_API_KEY", "ETHEREUM_RPC_URL") if os.environ.get(name)]
for path in Path(sys.argv[1]).rglob("*"):
    if path.is_file() and not path.is_symlink():
        raw = path.read_bytes()
        if any(secret in raw for secret in secrets):
            raise SystemExit("supplied secret detected in final retained artifact")
PY

run_succeeded=1
trap - EXIT INT TERM
echo "Completed nonpromotable repository-only parity evidence; live output is not a production pin or Graph Node oracle."
